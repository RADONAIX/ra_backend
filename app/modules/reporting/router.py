"""Reporting routes: /reports."""

from __future__ import annotations

import os

import anyio.to_thread
from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse

from app.core.deps import DbSession, PageParams, Principal, require
from app.core.errors import NotFoundError
from app.core.rbac import PermKey
from app.modules.reporting import schemas, service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[schemas.ReportRow])
async def list_reports(
    db: DbSession,
    page: PageParams,
    _: Principal = Depends(require(PermKey.REPORTS, "view")),
) -> list[schemas.ReportRow]:
    return await service.list_reports(db, limit=page.limit, offset=page.offset)


@router.post("", response_model=schemas.ReportRow, status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    payload: schemas.ReportCreate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.REPORTS, "edit")),
) -> schemas.ReportRow:
    report = await service.create_report(db, payload, requested_by=principal.email)
    return service.to_row(report)


@router.get("/{reference}/download")
async def download_report(
    reference: str,
    db: DbSession,
    _: Principal = Depends(require(PermKey.REPORTS, "view")),
) -> FileResponse:
    report = await service.get_report(db, reference)
    file_exists = await anyio.to_thread.run_sync(os.path.exists, report.file_path or "")
    if report.status != "Completed" or not report.file_path or not file_exists:
        raise NotFoundError("Report file is not available yet.")
    filename = f"{report.reference}_{report.name.replace(' ', '_')}.csv"
    headers = {}
    if report.checksum_sha256:
        headers["X-Checksum-SHA256"] = report.checksum_sha256
    return FileResponse(report.file_path, media_type="text/csv", filename=filename, headers=headers)
