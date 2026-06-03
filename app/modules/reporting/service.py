"""Reporting business logic: list, request (enqueue), fetch for download."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.modules.reporting import schemas
from app.modules.reporting.models import Report

log = get_logger("reporting")


def format_bytes(num: int | None) -> str:
    if not num:
        return "—"
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def to_row(r: Report) -> schemas.ReportRow:
    return schemas.ReportRow(
        id=r.reference,
        name=r.name,
        period=r.period,
        status=r.status,
        size=format_bytes(r.size_bytes),
    )


async def list_reports(db: AsyncSession, *, limit: int, offset: int) -> list[schemas.ReportRow]:
    rows = (
        (
            await db.execute(
                select(Report).order_by(Report.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [to_row(r) for r in rows]


async def _next_reference(db: AsyncSession) -> str:
    count = (await db.execute(select(func.count(Report.id)))).scalar_one()
    return f"RPT-{9900 + int(count) + 1}"


async def create_report(
    db: AsyncSession, payload: schemas.ReportCreate, *, requested_by: str
) -> Report:
    report = Report(
        reference=await _next_reference(db),
        name=payload.name,
        report_type=payload.reportType,
        period=payload.period,
        status="Queued",
        requested_by=requested_by,
        params=payload.params,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)

    # Enqueue async generation. If the broker is unreachable, the report stays
    # "Queued" and can be retried; we never fail the request because of it.
    try:
        from app.workers.tasks import generate_report

        generate_report.delay(report.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("report_enqueue_failed", report_id=report.id, error=str(exc))

    return report


async def get_report(db: AsyncSession, reference: str) -> Report:
    report = (
        await db.execute(select(Report).where(Report.reference == reference))
    ).scalar_one_or_none()
    if report is None:
        raise NotFoundError("Report not found.")
    return report
