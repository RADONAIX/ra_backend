"""Health, readiness and dashboard headline KPIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.database import engine
from app.core.deps import Principal, require
from app.core.rbac import PermKey
from app.integrations import airflow, clickhouse, ra_postgres
from app.modules.assurance import service as assurance_service

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    version: str
    environment: str


class Readiness(BaseModel):
    ready: bool
    checks: dict[str, bool]


class DashboardKpis(BaseModel):
    assuredRevenue: float
    matchRate: float
    openLeakageRisk: float
    criticalAlerts: int


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", version=__version__, environment=settings.environment)


@router.get("/health/ready", response_model=Readiness)
async def readiness() -> Readiness:
    checks: dict[str, bool] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["app_db"] = True
    except Exception:  # noqa: BLE001
        checks["app_db"] = False
    checks["clickhouse"] = await clickhouse.ping()
    checks["ra_postgres"] = await ra_postgres.ping()
    checks["airflow"] = await airflow.ping()
    # Readiness only requires the owned app DB; integrations are optional.
    return Readiness(ready=checks["app_db"], checks=checks)


@router.get("/dashboard/kpis", response_model=DashboardKpis)
async def dashboard_kpis(
    _: Principal = Depends(require(PermKey.DASHBOARD, "view")),
) -> DashboardKpis:
    summary = await assurance_service.recon_summary(hours=24)
    matched_amount = summary.total - summary.amountMismatch - summary.rawOnly - summary.procOnly
    return DashboardKpis(
        assuredRevenue=round(max(matched_amount, 0), 2),
        matchRate=summary.matchRate,
        openLeakageRisk=summary.estimatedLeakage,
        criticalAlerts=summary.amountMismatch + summary.rawOnly,
    )
