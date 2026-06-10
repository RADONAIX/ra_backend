"""Coordinated shutdown of all external clients (called from lifespan)."""

from __future__ import annotations

from app.core.redis import close_redis
from app.integrations.bi_postgres import close_bi_postgres
from app.integrations.clickhouse import close_clickhouse
from app.integrations.ra_postgres import close_ra_postgres


async def close_all_integrations() -> None:
    await close_redis()
    await close_ra_postgres()
    await close_bi_postgres()
    close_clickhouse()
