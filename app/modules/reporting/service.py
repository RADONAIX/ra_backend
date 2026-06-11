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
REPORTS: list[dict[str, Any]] = [
    {
        "key": "missing_record_sequence",
        "title": "Raw Record Sequence check Report",
        "group": "Files",
        "available": True,
        "source": "clickhouse",
        "count_sql": "SELECT sum(missing_count) AS n FROM air_raw_record_sequence_check",
        "detail_sql": "SELECT * FROM air_raw_record_sequence_check ORDER BY missing_count DESC",
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
    },
    {
        "key": "file_exception",
        "title": "File Exception Report",
        "group": "Files",
        "available": True,
        "source": "bi_pg",
        "count_sql": "SELECT count(*) AS n FROM {schema}.air_file_exception_report",
        "detail_sql": "SELECT * FROM {schema}.air_file_exception_report ORDER BY file_date DESC",
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
    },
]

_BY_KEY = {r["key"]: r for r in REPORTS}


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


async def _run(source: str, sql: str) -> list[dict[str, Any]]:
    if source == "bi_pg":
        return await bi_postgres.query(sql)
    if source == "clickhouse":
        return await clickhouse.query(sql)
    raise UpstreamUnavailableError(f"Unknown report source: {source}")


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
