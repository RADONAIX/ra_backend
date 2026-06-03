"""Read-only access to ra-platform's Postgres (rafms) — file_log / batches.

A dedicated async engine separate from the app database. Used to surface
file/batch processing status in the Pipelines view. Read-only by convention.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger

log = get_logger("ra_postgres")

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = (
            f"postgresql+asyncpg://{settings.ra_pg_user}:{settings.ra_pg_password}"
            f"@{settings.ra_pg_host}:{settings.ra_pg_port}/{settings.ra_pg_name}"
        )
        _engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _engine


async def close_ra_postgres() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not settings.ra_pg_enabled:
        raise UpstreamUnavailableError("ra-platform Postgres integration is disabled.")
    try:
        async with _get_engine().connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return [dict(row) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("ra_pg_query_failed", error=str(exc))
        raise UpstreamUnavailableError(
            "ra-platform Postgres query failed.", details={"reason": str(exc)}
        ) from exc


async def ping() -> bool:
    if not settings.ra_pg_enabled:
        return False
    try:
        async with _get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
