"""Airflow REST API client for pipeline control (trigger/retry/replay).

Targets the Airflow stable REST API (v1). Used to trigger DAG runs that map
to ra-platform's pipelines (air_pipeline_dag, air_processed_pipeline_dag,
air_recon_dag). Disabled by default; enable via AIRFLOW_ENABLED=true.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger

log = get_logger("airflow")

# Logical pipeline keys (as the UI uses) → Airflow DAG ids.
DAG_MAP: dict[str, str] = {
    "collection": "air_pipeline_dag",
    "decoding": "air_pipeline_dag",
    "validation": "air_processed_pipeline_dag",
    "reconciliation": "air_recon_dag",
    "reporting": "air_recon_dag",
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.airflow_base_url,
        auth=(settings.airflow_username, settings.airflow_password),
        timeout=10.0,
    )


async def trigger_dag(dag_id: str, conf: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.airflow_enabled:
        raise UpstreamUnavailableError("Airflow integration is disabled.")
    try:
        async with _client() as client:
            resp = await client.post(f"/dags/{dag_id}/dagRuns", json={"conf": conf or {}})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        log.warning("airflow_trigger_failed", dag_id=dag_id, error=str(exc))
        raise UpstreamUnavailableError(
            "Airflow trigger failed.", details={"reason": str(exc)}
        ) from exc


async def ping() -> bool:
    if not settings.airflow_enabled:
        return False
    try:
        async with _client() as client:
            resp = await client.get("/health")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False
