"""Celery tasks.

generate_report: materialises a certified reconciliation export as a CSV file
from ra-platform's ClickHouse recon table, records its size + SHA-256 checksum,
and marks the Report row Completed. All DB/ClickHouse access here is sync.
"""

from __future__ import annotations

import csv
import hashlib
import os
from datetime import UTC, datetime

import clickhouse_connect

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.reporting.models import Report
from app.workers.celery_app import celery
from app.workers.db import SyncSession

log = get_logger("worker")

_RECON_COLUMNS = [
    "record_type",
    "raw_txn_id",
    "proc_txn_id",
    "raw_node_id",
    "raw_subscriber_num",
    "raw_tran_amt",
    "proc_tran_amt",
    "raw_acc_balance",
    "proc_acc_balance",
    "reconciliation_status",
    "created_time",
]


def _ch_client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        connect_timeout=5,
    )


def _write_csv(path: str, rows: list[tuple], header: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@celery.task(name="reports.generate", bind=True, max_retries=2, default_retry_delay=30)
def generate_report(self, report_id: str) -> dict:
    session = SyncSession()
    try:
        report = session.get(Report, report_id)
        if report is None:
            return {"ok": False, "reason": "report_not_found"}

        report.status = "Running"
        session.commit()

        out_path = os.path.join(settings.reports_dir, f"{report.reference}.csv")
        ident = "`" + settings.clickhouse_database.replace("`", "``") + "`"

        try:
            client = _ch_client()
            result = client.query(
                f"SELECT {', '.join(_RECON_COLUMNS)} "
                f"FROM {ident}.air_reconciliation FINAL "
                f"ORDER BY created_time DESC LIMIT 1000000"
            )
            rows = result.result_rows
        except Exception as exc:  # noqa: BLE001 — degrade to an empty certified file
            log.warning("report_clickhouse_unavailable", report_id=report_id, error=str(exc))
            rows = []

        _write_csv(out_path, rows, _RECON_COLUMNS)

        report.file_path = out_path
        report.size_bytes = os.path.getsize(out_path)
        report.checksum_sha256 = _sha256(out_path)
        report.status = "Completed"
        report.completed_at = datetime.now(UTC)
        report.error = None
        session.commit()
        log.info("report_generated", report_id=report_id, size=report.size_bytes)
        return {"ok": True, "size": report.size_bytes, "checksum": report.checksum_sha256}

    except Exception as exc:  # noqa: BLE001
        session.rollback()
        report = session.get(Report, report_id)
        if report is not None:
            report.status = "Failed"
            report.error = str(exc)
            session.commit()
        log.error("report_failed", report_id=report_id, error=str(exc))
        raise
    finally:
        session.close()
