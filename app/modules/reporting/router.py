"""Reporting routes: the RA report catalog (/reports)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.deps import Principal, require
from app.core.rbac import PermKey
from app.modules.reporting import schemas, service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{key}", response_model=schemas.ReportDetail)
async def detail(
    key: str,
    _: Principal = Depends(require(PermKey.REPORTS, "view")),
) -> schemas.ReportDetail:
    return await service.report_detail(key)


@router.get("/{key}/export")
async def export(
    key: str,
    _: Principal = Depends(require(PermKey.REPORTS, "view")),
) -> Response:
    filename, csv_text = await service.report_export_csv(key)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
