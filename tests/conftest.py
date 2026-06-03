"""Shared pytest fixtures.

`db_session` yields an AsyncSession backed by a per-test NullPool engine so each
async test gets a connection bound to its own event loop (avoids cross-loop pool
reuse). The test is skipped if the app database is unreachable, keeping the unit
suite runnable without Postgres.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        settings.app_database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": settings.app_db_schema}},
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("app database not available")

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()
