"""Exports business logic: create/track/download bulk export jobs + KPI preview."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.modules.exports import schemas
from app.modules.exports.models import ExportJob
from app.modules.reporting import service as reporting

log = get_logger("exports")

_ACTIVE_STATUSES = ("Queued", "Running")


class TooManyJobsError(AppError):
    status_code = 429
    code = "too_many_jobs"


class ExportNotReadyError(AppError):
    status_code = 409
    code = "export_not_ready"


class ExportExpiredError(AppError):
    status_code = 410
    code = "export_expired"


def _reference() -> str:
    return f"EXP-{uuid.uuid4().hex[:10].upper()}"


def _to_row(job: ExportJob) -> schemas.ExportJobRow:
    return schemas.ExportJobRow(
        id=job.id,
        reference=job.reference,
        reportKey=job.report_key,
        status=job.status,
        progressPct=job.progress_pct,
        processedRows=job.processed_rows,
        totalRows=job.total_rows,
        fileSizeBytes=job.file_size_bytes,
        requestedBy=job.requested_by,
        createdAt=job.created_at,
        startedAt=job.started_at,
        completedAt=job.completed_at,
        expiresAt=job.expires_at,
        error=job.error,
    )


def _to_detail(job: ExportJob) -> schemas.ExportJobDetail:
    return schemas.ExportJobDetail(
        **_to_row(job).model_dump(),
        params=job.params or {},
        kpis=job.kpis,
        checksumSha256=job.checksum_sha256,
        fileFormat=job.file_format,
    )


async def create_export_job(
    db: AsyncSession, payload: schemas.ExportJobCreate, *, requester_id: str
) -> schemas.ExportJobRow:
    report = reporting.get_report(payload.reportKey)
    if report is None or not report.get("available"):
        raise NotFoundError(f"Unknown report '{payload.reportKey}'.")
    if not report.get("date_column"):
        raise ValidationFailedError("This report does not support date-range export.")
    if payload.dateFrom > payload.dateTo:
        raise ValidationFailedError("dateFrom must be on or before dateTo.")
    span = (payload.dateTo - payload.dateFrom).days + 1
    if span > settings.export_max_date_span_days:
        raise ValidationFailedError(
            f"Date span {span}d exceeds the maximum of {settings.export_max_date_span_days}d."
        )

    active = (
        await db.execute(
            select(func.count(ExportJob.id)).where(
                ExportJob.requested_by == requester_id,
                ExportJob.status.in_(_ACTIVE_STATUSES),
            )
        )
    ).scalar_one()
    if active >= settings.export_max_concurrent_per_user:
        raise TooManyJobsError(
            f"You already have {active} export(s) running. Wait for one to finish."
        )

    job = ExportJob(
        reference=_reference(),
        report_key=payload.reportKey,
        status="Queued",
        params={
            "date_from": payload.dateFrom.isoformat(),
            "date_to": payload.dateTo.isoformat(),
            "filters": payload.filters,
        },
        requested_by=requester_id,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    # Commit before enqueuing so the worker can read the row (avoids a race).
    await db.commit()

    try:
        from app.workers.tasks import run_export

        result = run_export.delay(job.id)
        job.celery_task_id = result.id
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — broker unreachable: surface as Failed
        log.error("export_enqueue_failed", job_id=job.id, error=str(exc))
        job.status = "Failed"
        job.error = "Could not queue the export (job broker unavailable)."
        await db.commit()
    await db.refresh(job)
    return _to_row(job)


async def list_export_jobs(
    db: AsyncSession, *, requester_id: str, all_jobs: bool, limit: int, offset: int
) -> list[schemas.ExportJobRow]:
    stmt = select(ExportJob).order_by(ExportJob.created_at.desc())
    if not all_jobs:
        stmt = stmt.where(ExportJob.requested_by == requester_id)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [_to_row(j) for j in rows]


async def _get(db: AsyncSession, job_id: str) -> ExportJob:
    job = (
        await db.execute(select(ExportJob).where(ExportJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Export job not found.")
    return job


async def get_export_job(db: AsyncSession, job_id: str) -> schemas.ExportJobDetail:
    return _to_detail(await _get(db, job_id))


async def get_export_download(db: AsyncSession, job_id: str) -> tuple[str, Iterator[bytes]]:
    job = await _get(db, job_id)
    if job.status != "Completed" or not job.file_path:
        raise ExportNotReadyError(f"Export is '{job.status}', not ready for download.")
    if job.expires_at and job.expires_at < datetime.now(UTC):
        raise ExportExpiredError("This export has expired and is no longer available.")
    storage = get_storage()
    key = f"{job.reference}.csv.gz"
    if not storage.exists(key):
        raise ExportExpiredError("The export file is no longer available.")

    def _iter() -> Iterator[bytes]:
        with storage.open_read(key) as fh:
            yield from iter(lambda: fh.read(1 << 16), b"")

    return f"{job.reference}.csv.gz", _iter()


async def cancel_export_job(db: AsyncSession, job_id: str) -> schemas.ExportJobRow:
    job = await _get(db, job_id)
    if job.status in ("Completed", "Failed", "Cancelled"):
        # Terminal: just drop the file (if any) and report current state.
        get_storage().delete(f"{job.reference}.csv.gz")
        if job.status == "Completed":
            job.status = "Cancelled"
            await db.flush()
        return _to_row(job)

    job.status = "Cancelled"
    await db.flush()
    if job.celery_task_id:
        try:
            from app.workers.celery_app import celery

            celery.control.revoke(job.celery_task_id, terminate=True)
        except Exception as exc:  # noqa: BLE001 — best-effort; status is already Cancelled
            log.warning("export_revoke_failed", job_id=job_id, error=str(exc))
    get_storage().delete(f"{job.reference}.csv.gz")
    return _to_row(job)


async def preview_kpis(payload: schemas.KpiPreviewRequest) -> schemas.KpiPreviewResponse:
    report = reporting.get_report(payload.reportKey)
    if report is None or not report.get("available"):
        raise NotFoundError(f"Unknown report '{payload.reportKey}'.")
    if not report.get("date_column"):
        raise ValidationFailedError("This report does not support date-range KPIs.")
    if payload.dateFrom > payload.dateTo:
        raise ValidationFailedError("dateFrom must be on or before dateTo.")
    kpis = await reporting.report_kpis(
        payload.reportKey,
        date_from=payload.dateFrom,
        date_to=payload.dateTo + timedelta(days=1),  # inclusive end
    )
    return schemas.KpiPreviewResponse(
        reportKey=payload.reportKey, dateFrom=payload.dateFrom, dateTo=payload.dateTo, kpis=kpis
    )


