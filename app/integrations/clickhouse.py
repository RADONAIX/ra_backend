"""Read-only ClickHouse client for ra-platform recon tables.

Wraps ``clickhouse-connect`` in a thin async-friendly facade. ClickHouse
queries are blocking, so they are dispatched to a thread via
``asyncio.to_thread`` to avoid blocking the event loop. All access is
read-only — this service never writes to the rafms ClickHouse database.
"""

from __future__ import annotations

import asyncio
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from app.core.config import settings
from app.core.errors import UpstreamUnavailableError
from app.core.logging import get_logger

log = get_logger("clickhouse")

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            connect_timeout=5,
            send_receive_timeout=30,
        )
    return _client


def close_clickhouse() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def _query_sync(sql: str, params: dict[str, Any] | None) -> list[dict[str, Any]]:
    client = _get_client()
    result = client.query(sql, parameters=params or {})
    cols = result.column_names
    return [dict(zip(cols, row, strict=False)) for row in result.result_rows]


async def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read query, returning a list of row dicts.

    Raises UpstreamUnavailableError if ClickHouse is disabled or unreachable.
    """
    if not settings.clickhouse_enabled:
        raise UpstreamUnavailableError("ClickHouse integration is disabled.")
    try:
        return await asyncio.to_thread(_query_sync, sql, params)
    except UpstreamUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as a clean 503
        close_clickhouse()
        log.warning("clickhouse_query_failed", error=str(exc))
        raise UpstreamUnavailableError(
            "ClickHouse query failed.", details={"reason": str(exc)}
        ) from exc


async def ping() -> bool:
    if not settings.clickhouse_enabled:
        return False
    try:
        await asyncio.to_thread(lambda: _get_client().command("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        close_clickhouse()
        return False
