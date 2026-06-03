"""Synchronous SQLAlchemy session for Celery tasks.

Celery tasks run outside the asyncio event loop, so they use a sync engine
(psycopg2) rather than the app's async engine.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine = create_engine(
    settings.app_database_url_sync,
    pool_pre_ping=True,
    future=True,
    # psycopg2: set search_path to the dedicated application schema.
    connect_args={"options": f"-csearch_path={settings.app_db_schema}"},
)
SyncSession: sessionmaker[Session] = sessionmaker(bind=_engine, expire_on_commit=False)
