"""Operations routes: /pipelines, /decoders, /system/config."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, Principal, require
from app.core.rbac import PermKey
from app.modules.operations import schemas, service

# --- Pipelines -------------------------------------------------------------
pipelines_router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@pipelines_router.get("/stages", response_model=list[schemas.PipelineStage])
async def stages(
    db: DbSession, _: Principal = Depends(require(PermKey.PIPELINES, "view"))
) -> list[schemas.PipelineStage]:
    return await service.get_stages(db)


@pipelines_router.get("/kpis", response_model=schemas.PipelineKpis)
async def kpis(
    db: DbSession, _: Principal = Depends(require(PermKey.PIPELINES, "view"))
) -> schemas.PipelineKpis:
    return await service.get_kpis(db)


@pipelines_router.get("/runs", response_model=list[schemas.PipelineRun])
async def runs(
    db: DbSession,
    limit: int = Query(default=25, ge=1, le=200),
    _: Principal = Depends(require(PermKey.PIPELINES, "view")),
) -> list[schemas.PipelineRun]:
    return await service.get_runs(db, limit=limit)


@pipelines_router.get("/alerts", response_model=list[schemas.PipelineAlertRow])
async def alerts(
    db: DbSession, _: Principal = Depends(require(PermKey.PIPELINES, "view"))
) -> list[schemas.PipelineAlertRow]:
    return await service.list_alerts(db)


@pipelines_router.get("/retries", response_model=list[schemas.RetryJob])
async def retries(
    db: DbSession, _: Principal = Depends(require(PermKey.PIPELINES, "view"))
) -> list[schemas.RetryJob]:
    return await service.get_retries(db)


@pipelines_router.post("/jobs/{job_id}/retry", response_model=schemas.ActionResult)
async def retry_job(
    job_id: str, principal: Principal = Depends(require(PermKey.PIPELINES, "edit"))
) -> schemas.ActionResult:
    return await service.retry_job(job_id)


@pipelines_router.post("/jobs/{job_id}/replay", response_model=schemas.ActionResult)
async def replay_job(
    job_id: str, principal: Principal = Depends(require(PermKey.PIPELINES, "edit"))
) -> schemas.ActionResult:
    return await service.replay_job(job_id)


@pipelines_router.post("/alerts/{alert_id}/ack", response_model=schemas.ActionResult)
async def ack_alert(
    alert_id: str,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.PIPELINES, "edit")),
) -> schemas.ActionResult:
    return await service.acknowledge_alert(db, alert_id, principal.email)


# --- Decoders --------------------------------------------------------------
decoders_router = APIRouter(prefix="/decoders", tags=["decoders"])


@decoders_router.get("", response_model=list[schemas.DecoderRow])
async def list_decoders(
    db: DbSession, _: Principal = Depends(require(PermKey.SETTINGS, "view"))
) -> list[schemas.DecoderRow]:
    return await service.list_decoders(db)


@decoders_router.post("", response_model=schemas.DecoderRow)
async def upsert_decoder(
    payload: schemas.DecoderUpsert,
    db: DbSession,
    _: Principal = Depends(require(PermKey.SETTINGS, "edit")),
) -> schemas.DecoderRow:
    dec = await service.upsert_decoder(db, payload)
    return schemas.DecoderRow(
        id=dec.id, name=dec.name, version=dec.version, status=dec.status, throughput=dec.throughput
    )


# --- System config ---------------------------------------------------------
system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/config", response_model=schemas.SystemConfigOut)
async def get_config(
    db: DbSession, _: Principal = Depends(require(PermKey.SETTINGS, "view"))
) -> schemas.SystemConfigOut:
    return await service.get_system_config(db)


@system_router.put("/config", response_model=schemas.SystemConfigOut)
async def update_config(
    payload: schemas.SystemConfigUpdate,
    db: DbSession,
    _: Principal = Depends(require(PermKey.SETTINGS, "edit")),
) -> schemas.SystemConfigOut:
    return await service.update_system_config(db, payload)


router = APIRouter()
router.include_router(pipelines_router)
router.include_router(decoders_router)
router.include_router(system_router)
