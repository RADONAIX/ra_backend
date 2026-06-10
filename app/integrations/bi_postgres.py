"""Read-only access to the BI Postgres database (`rafms` / `bi_reports`).

A dedicated async engine, separate from both the app DB and ``ra_postgres``
(which targets ``rafms_db``). The ``bi_reports`` schema holds the pre-computed
report materialized views (e.g. ``air_file_seq_mv``). Read-only by convention.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger

log = get_logger("bi_postgres")

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # Same host/port/creds as ra_pg, different database (rafms).
        url = (
            f"postgresql+asyncpg://{settings.ra_pg_user}:{settings.ra_pg_password}"
            f"@{settings.ra_pg_host}:{settings.ra_pg_port}/{settings.ra_bi_pg_name}"
        )
        _engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _engine


async def close_bi_postgres() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not settings.ra_pg_enabled:
        raise UpstreamUnavailableError("BI Postgres integration is disabled.")
    try:
        async with _get_engine().connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return [dict(row) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("bi_pg_query_failed", error=str(exc))
        raise UpstreamUnavailableError(
            "BI Postgres query failed.", details={"reason": str(exc)}
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
