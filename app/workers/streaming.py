"""Synchronous, chunked readers for the Celery export worker.

Both report sources (BI Postgres `rafms`, ClickHouse) normally materialise the
full result set. For million-row exports the worker must stream instead:
 - Postgres: a SQLAlchemy server-side cursor (`yield_per`) over the BI DSN.
 - ClickHouse: `clickhouse_connect.query_row_block_stream` (block-by-block).

Each stream generator yields the COLUMN LIST first, then successive row-chunks
(lists of lists). Param syntax matches what reporting.service builds: `:name`
for Postgres (SQLAlchemy text), `{name:Type}` for ClickHouse.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import clickhouse_connect
from sqlalchemy import Engine, create_engine, text

from app.core.config import settings

_bi_engine_singleton: Engine | None = None


def _bi_engine() -> Engine:
    """Sync psycopg2 engine to the BI Postgres database (rafms)."""
    global _bi_engine_singleton
    if _bi_engine_singleton is None:
        url = (
            f"postgresql+psycopg2://{settings.ra_pg_user}:{settings.ra_pg_password}"
            f"@{settings.ra_pg_host}:{settings.ra_pg_port}/{settings.ra_bi_pg_name}"
        )
        _bi_engine_singleton = create_engine(url, pool_pre_ping=True, future=True)
    return _bi_engine_singleton


def _ch_client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        connect_timeout=5,
    )


# --- One-shot (count / KPIs — single small row) ----------------------------
def query_one(source: str, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if source == "bi_pg":
        with _bi_engine().connect() as conn:
            row = conn.execute(text(sql), params or {}).mappings().first()
            return dict(row) if row else None
    if source == "clickhouse":
        qr = _ch_client().query(sql, parameters=params or {})
        if not qr.result_rows:
            return None
        return dict(zip(qr.column_names, qr.result_rows[0], strict=False))
    raise ValueError(f"Unknown source: {source}")


# --- Streaming (export rows) -----------------------------------------------
def stream_rows(
    source: str, sql: str, params: dict[str, Any] | None, chunk: int
) -> Iterator[Any]:
    """First yield = column list; subsequent yields = chunks (list[list])."""
    if source == "bi_pg":
        yield from _pg_stream(sql, params, chunk)
    elif source == "clickhouse":
        yield from _ch_stream(sql, params, chunk)
    else:
        raise ValueError(f"Unknown source: {source}")


def _pg_stream(sql: str, params: dict[str, Any] | None, chunk: int) -> Iterator[Any]:
    conn = _bi_engine().connect()
    try:
        result = conn.execution_options(yield_per=chunk).execute(text(sql), params or {})
        yield list(result.keys())
        for part in result.partitions():
            yield [list(r) for r in part]
    finally:
        conn.close()


def _ch_stream(sql: str, params: dict[str, Any] | None, chunk: int) -> Iterator[Any]:
    client = _ch_client()
    with client.query_row_block_stream(
        sql, parameters=params or {}, settings={"max_block_size": chunk}
    ) as stream:
        cols = getattr(stream, "source", None)
        yield list(getattr(cols, "column_names", None) or getattr(stream, "column_names", []))
        for block in stream:
            yield [list(r) for r in block]
