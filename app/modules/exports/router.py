"""Exports routes: bulk async report downloads (/exports)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.deps import DbSession, PageParams, Principal, require
from app.core.rbac import PermKey, RoleSlug
from app.modules.exports import schemas, service


def _require_exports_enabled() -> None:
    """Gate the whole module: 503 when bulk exports are turned off (no Redis/worker)."""
    if not settings.exports_enabled:
        raise service.ExportsDisabledError("Bulk exports are disabled on this deployment.")


router = APIRouter(
    prefix="/exports", tags=["exports"], dependencies=[Depends(_require_exports_enabled)]
)


@router.post("", response_model=schemas.ExportJobRow, status_code=201)
async def create_export(
    payload: schemas.ExportJobCreate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.EXPORTS, "edit")),
) -> schemas.ExportJobRow:
    return await service.create_export_job(db, payload, requester_id=principal.id)


@router.get("", response_model=list[schemas.ExportJobRow])
async def list_exports(
    db: DbSession,
    page: PageParams,
    principal: Principal = Depends(require(PermKey.EXPORTS, "view")),
) -> list[schemas.ExportJobRow]:
    # Admins see every job; everyone else sees only their own.
    return await service.list_export_jobs(
        db,
        requester_id=principal.id,
        all_jobs=(principal.role == RoleSlug.ADMIN),
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/kpis", response_model=schemas.KpiPreviewResponse)
async def kpi_preview(
    payload: schemas.KpiPreviewRequest,
    _: Principal = Depends(require(PermKey.EXPORTS, "view")),
) -> schemas.KpiPreviewResponse:
    return await service.preview_kpis(payload)


@router.get("/{job_id}", response_model=schemas.ExportJobDetail)
async def get_export(
    job_id: str,
    db: DbSession,
    _: Principal = Depends(require(PermKey.EXPORTS, "view")),
) -> schemas.ExportJobDetail:
    return await service.get_export_job(db, job_id)


@router.get("/{job_id}/download")
async def download_export(
    job_id: str,
    db: DbSession,
    _: Principal = Depends(require(PermKey.EXPORTS, "view")),
) -> StreamingResponse:
    filename, body = await service.get_export_download(db, job_id)
    return StreamingResponse(
        body,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{job_id}", response_model=schemas.ExportJobRow)
async def cancel_export(
    job_id: str,
    db: DbSession,
    _: Principal = Depends(require(PermKey.EXPORTS, "edit")),
) -> schemas.ExportJobRow:
    return await service.cancel_export_job(db, job_id)
