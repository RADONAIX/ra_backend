"""Reporting business logic: a registry-driven RA report catalog.

Each report is a spec with a live count query and a drill-down query against a
pre-computed source (BI Postgres matviews in ``rafms.bi_reports`` or ClickHouse
matviews in ``rafms``). The catalog badge shows the true total count; the
drill-down returns at most 100 rows; export returns the full set as CSV.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger
from app.integrations import bi_postgres, clickhouse
from app.modules.reporting import schemas

log = get_logger("reporting")

DETAIL_LIMIT = 100
EXPORT_LIMIT = 1_000_000

# Report registry. `{schema}` is filled from settings.ra_bi_pg_schema (BI PG).
# detail_sql is the base SELECT (with ORDER BY, NO limit); the limit is applied
# per use (100 for drill-down, EXPORT_LIMIT for CSV).
# `date_column` (a column in detail_sql's output) enables bulk-export date-range
# filtering + KPIs (exports module). `kpi_agg` is the aggregate projection used
# for the KPI preview, evaluated over the (date-filtered) export rows.
REPORTS: list[dict[str, Any]] = [
    {
        "key": "missing_record_sequence",
        "title": "Raw Record Sequence check Report",
        "group": "Files",
        "available": True,
        "source": "clickhouse",
        "count_sql": "SELECT sum(missing_count) AS n FROM air_raw_record_sequence_check",
        "detail_sql": "SELECT * FROM air_raw_record_sequence_check ORDER BY missing_count DESC",
        "date_column": "date",
        "kpi_agg": "count(*) AS rows, sum(missing_count) AS missing_records",
    },
    {
        "key": "processed_record_sequence",
        "title": "Processed Record Sequence Check Report",
        "group": "Files",
        "available": True,
        "source": "clickhouse",
        "count_sql": "SELECT sum(missing_count) AS n FROM air_processed_record_sequence_check",
        "detail_sql": (
            "SELECT * FROM air_processed_record_sequence_check ORDER BY missing_count DESC"
        ),
        "date_column": "date",
        "kpi_agg": "count(*) AS rows, sum(missing_count) AS missing_records",
    },
    {
        "key": "file_sequence_check",
        "title": "File Sequence Check Report",
        "group": "Files",
        "available": True,
        "source": "bi_pg",
        # Full sequence-check table (all statuses). missing_file_sequence is the
        # Missing-only view of the same table.
        "count_sql": "SELECT count(*) AS n FROM {schema}.air_file_seq_check",
        "detail_sql": "SELECT * FROM {schema}.air_file_seq_check ORDER BY date DESC",
        "date_column": "date",
        "kpi_agg": "count(*) AS rows, count(*) FILTER (WHERE status <> 'Present') AS missing_files",
    },
    {
        "key": "file_exception",
        "title": "File Exception Report",
        "group": "Files",
        "available": True,
        "source": "bi_pg",
        "count_sql": "SELECT count(*) AS n FROM {schema}.air_file_exception_report",
        "detail_sql": "SELECT * FROM {schema}.air_file_exception_report ORDER BY file_date DESC",
        "date_column": "file_date",
        "kpi_agg": "count(*) AS rows",
    },
    {
        "key": "report_batch_log",
        "title": "Report Batch Log",
        "group": "Operations",
        "available": True,
        "source": "bi_pg",
        # Lives in rafms.air_schema (not bi_reports) — fully qualified, no {schema}.
        "count_sql": "SELECT count(*) AS n FROM air_schema.report_batch_log",
        "detail_sql": "SELECT * FROM air_schema.report_batch_log ORDER BY start_time DESC",
        "date_column": "start_time",
        "kpi_agg": "count(*) AS rows",
    },
    {
        "key": "air_reconciliation",
        "title": "AIR Reconciliation Report",
        "group": "Reconciliation",
        "available": True,
        "source": "clickhouse",
        # Findings = reconciliation discrepancies (everything not MATCHED):
        # AMOUNT_MISMATCH, RAW_ONLY, PROC_ONLY. (Plain MergeTree — no FINAL.)
        "count_sql": (
            "SELECT count() AS n FROM air_reconciliation "
            "WHERE reconciliation_status != 'MATCHED'"
        ),
        "detail_sql": (
            "SELECT reconciliation_status, record_type, "
            "coalesce(raw_txn_id, proc_txn_id) AS txn_id, "
            "coalesce(raw_node_id, proc_node_id) AS node_id, "
            "coalesce(raw_subscriber_num, proc_subscriber_num) AS subscriber_num, "
            "raw_tran_amt, proc_tran_amt, raw_acc_balance, proc_acc_balance, "
            "coalesce(raw_filename, proc_filename) AS filename, created_time "
            "FROM air_reconciliation WHERE reconciliation_status != 'MATCHED' "
            "ORDER BY created_time DESC"
        ),
        "date_column": "created_time",
        "kpi_agg": (
            "count(*) AS rows, "
            "countIf(reconciliation_status = 'AMOUNT_MISMATCH') AS amount_mismatch, "
            "countIf(reconciliation_status = 'RAW_ONLY') AS raw_only, "
            "countIf(reconciliation_status = 'PROC_ONLY') AS proc_only"
        ),
    },
]

_BY_KEY = {r["key"]: r for r in REPORTS}


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


async def _run(
    source: str, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    if source == "bi_pg":
        return await bi_postgres.query(sql, params)
    if source == "clickhouse":
        return await clickhouse.query(sql, params)
    raise UpstreamUnavailableError(f"Unknown report source: {source}")


# --- Bulk-export query builders (shared by the async API + the sync worker) --
# Pure string builders (no I/O), so both the async endpoints and the sync Celery
# worker can execute the returned (source, sql, params). date_to is EXCLUSIVE.
def get_report(key: str) -> dict[str, Any] | None:
    return _BY_KEY.get(key)


def _date_predicate(source: str, date_column: str) -> str:
    col = f"_e.{date_column}"
    if source == "clickhouse":
        return f"toDate({col}) >= {{date_from:Date}} AND toDate({col}) < {{date_to:Date}}"
    return f"{col}::date >= :date_from AND {col}::date < :date_to"


def export_query(
    key: str, *, date_from: Any = None, date_to: Any = None
) -> tuple[str, str, dict[str, Any]]:
    """(source, SELECT-without-LIMIT, params) for the full export, optionally
    filtered to [date_from, date_to)."""
    report = _BY_KEY[key]
    source = report["source"]
    sql = report["detail_sql"].format(schema=settings.ra_bi_pg_schema)
    params: dict[str, Any] = {}
    if date_from is not None and date_to is not None and report.get("date_column"):
        pred = _date_predicate(source, report["date_column"])
        sql = f"SELECT * FROM ({sql}) AS _e WHERE {pred}"
        params = {"date_from": date_from, "date_to": date_to}
    return source, sql, params


def count_query(
    key: str, *, date_from: Any = None, date_to: Any = None
) -> tuple[str, str, dict[str, Any]]:
    source, sub, params = export_query(key, date_from=date_from, date_to=date_to)
    return source, f"SELECT count(*) AS n FROM ({sub}) AS _c", params


def kpi_query(
    key: str, *, date_from: Any = None, date_to: Any = None
) -> tuple[str, str, dict[str, Any]]:
    report = _BY_KEY[key]
    source, sub, params = export_query(key, date_from=date_from, date_to=date_to)
    agg = report.get("kpi_agg") or "count(*) AS rows"
    return source, f"SELECT {agg} FROM ({sub}) AS _k", params


async def report_kpis(
    key: str, *, date_from: Any = None, date_to: Any = None
) -> dict[str, Any] | None:
    """Aggregate KPI preview over the selected data (no row dump). None if the
    report is unknown/unavailable or the source is unreachable."""
    report = _BY_KEY.get(key)
    if report is None or not report.get("available"):
        return None
    try:
        source, sql, params = kpi_query(key, date_from=date_from, date_to=date_to)
        rows = await _run(source, sql, params)
    except UpstreamUnavailableError:
        log.info("report_kpis_unavailable", key=key)
        return None
    return {k: _jsonable(v) for k, v in rows[0].items()} if rows else {}


async def _count(report: dict[str, Any]) -> int:
    sql = report["count_sql"].format(schema=settings.ra_bi_pg_schema)
    rows = await _run(report["source"], sql)
    n = rows[0].get("n") if rows else 0
    return int(n or 0)


async def _detail_rows(report: dict[str, Any], limit: int) -> tuple[list[str], list[list]]:
    sql = f"{report['detail_sql'].format(schema=settings.ra_bi_pg_schema)} LIMIT {int(limit)}"
    rows = await _run(report["source"], sql)
    if not rows:
        return [], []
    columns = list(rows[0].keys())
    data = [[_jsonable(row.get(c)) for c in columns] for row in rows]
    return columns, data


async def report_detail(key: str) -> schemas.ReportDetail:
    report = _BY_KEY.get(key)
    if report is None or not report.get("available"):
        title = report["title"] if report else key
        return schemas.ReportDetail(key=key, title=title, count=None, columns=[], rows=[])
    try:
        count = await _count(report)
        columns, rows = await _detail_rows(report, DETAIL_LIMIT)
    except UpstreamUnavailableError:
        log.info("report_detail_unavailable", key=key)
        return schemas.ReportDetail(key=key, title=report["title"], count=None, columns=[], rows=[])
    return schemas.ReportDetail(
        key=key, title=report["title"], count=count, columns=columns, rows=rows
    )


async def report_export_csv(key: str) -> tuple[str, str]:
    """Return (filename, csv_text) for the full (uncapped) report set."""
    report = _BY_KEY.get(key)
    if report is None or not report.get("available"):
        raise UpstreamUnavailableError("Report is not available for export.")
    columns, rows = await _detail_rows(report, EXPORT_LIMIT)
    buf = io.StringIO()
    writer = csv.writer(buf)
    if columns:
        writer.writerow(columns)
        writer.writerows(rows)
    return f"{key}.csv", buf.getvalue()
