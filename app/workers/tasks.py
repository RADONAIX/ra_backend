"""Celery tasks.

run_export: streams a report (optionally date-filtered) to a gzipped CSV on the
configured storage, updating progress on the ExportJob row chunk-by-chunk, then
records size/checksum/KPIs and marks the job Completed. All DB access is sync
(SyncSession); report data is read via the sync streaming readers.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import Storage, get_storage
from app.modules.exports.models import ExportJob
from app.modules.reporting import service as reporting
from app.workers import streaming
from app.workers.celery_app import celery
from app.workers.db import SyncSession

log = get_logger("worker")


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _parse_date(v: Any) -> date | None:
    if not v:
        return None
    return date.fromisoformat(v) if isinstance(v, str) else v


def _sha256_of(storage: Storage, key: str) -> str:
    digest = hashlib.sha256()
    with storage.open_read(key) as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_cancelled(session, job_id: str) -> bool:
    status = session.execute(
        select(ExportJob.status).where(ExportJob.id == job_id)
    ).scalar_one_or_none()
    return status == "Cancelled"


@celery.task(name="exports.run", bind=True, max_retries=2, default_retry_delay=30)
def run_export(self, job_id: str) -> dict:
    session = SyncSession()
    storage = get_storage()
    key = ""
    try:
        job = session.get(ExportJob, job_id)
        if job is None:
            return {"ok": False, "reason": "job_not_found"}

        job.status = "Running"
        job.started_at = datetime.now(UTC)
        job.celery_task_id = self.request.id
        session.commit()

        report_key = job.report_key
        date_from = _parse_date((job.params or {}).get("date_from"))
        date_to = _parse_date((job.params or {}).get("date_to"))
        # date_to is inclusive for the user → exclusive upper bound for the query.
        date_to_excl = (date_to + timedelta(days=1)) if date_to else None

        # 1) total rows (for % progress)
        c_src, c_sql, c_params = reporting.count_query(
            report_key, date_from=date_from, date_to=date_to_excl
        )
        total = int((streaming.query_one(c_src, c_sql, c_params) or {}).get("n") or 0)
        job.total_rows = total
        session.commit()

        # 2) stream rows → gzipped CSV
        key = f"{job.reference}.csv.gz"
        e_src, e_sql, e_params = reporting.export_query(
            report_key, date_from=date_from, date_to=date_to_excl
        )
        processed = 0
        with (
            storage.open_write(key) as raw,
            gzip.GzipFile(fileobj=raw, mode="wb") as gz,
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as txt,
        ):
            writer = csv.writer(txt)
            rows = streaming.stream_rows(e_src, e_sql, e_params, settings.export_chunk_rows)
            writer.writerow(next(rows))  # first item = column header
            for chunk in rows:
                writer.writerows(chunk)  # csv stringifies cells (dates/decimals)
                processed += len(chunk)
                if _is_cancelled(session, job_id):
                    log.info("export_cancelled", job_id=job_id, processed=processed)
                    storage.delete(key)
                    return {"ok": False, "reason": "cancelled"}
                job.processed_rows = processed
                job.progress_pct = int(processed / total * 100) if total else 0
                session.commit()

        # 3) finalize: size + checksum + KPIs
        k_src, k_sql, k_params = reporting.kpi_query(
            report_key, date_from=date_from, date_to=date_to_excl
        )
        kpi_row = streaming.query_one(k_src, k_sql, k_params) or {}

        job.file_path = storage.locator(key)
        job.file_size_bytes = storage.size(key)
        job.checksum_sha256 = _sha256_of(storage, key)
        job.kpis = {k: _jsonable(v) for k, v in kpi_row.items()}
        job.processed_rows = processed
        job.progress_pct = 100
        job.status = "Completed"
        job.completed_at = datetime.now(UTC)
        job.expires_at = datetime.now(UTC) + timedelta(days=settings.export_retention_days)
        job.error = None
        session.commit()
        log.info("export_completed", job_id=job_id, rows=processed, size=job.file_size_bytes)
        return {"ok": True, "rows": processed, "size": job.file_size_bytes}

    except Exception as exc:  # noqa: BLE001
        session.rollback()
        if key:
            storage.delete(key)
        job = session.get(ExportJob, job_id)
        if job is not None and job.status != "Cancelled":
            job.status = "Failed"
            job.error = str(exc)[:2000]
            session.commit()
        log.error("export_failed", job_id=job_id, error=str(exc))
        raise
    finally:
        session.close()
