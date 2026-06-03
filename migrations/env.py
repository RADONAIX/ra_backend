"""Alembic environment — uses the app's settings + sync engine URL."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so target_metadata is fully populated for autogenerate.
import app.models  # noqa: F401,E402  (side-effect import)
from app.core.config import settings
from app.core.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.app_database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):
    # Alembic's own bookkeeping table sits in the search_path and would
    # otherwise show up as a spurious "removed table" during autogenerate/check.
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.app_database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    schema = settings.app_db_schema
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Ensure the dedicated schema exists and is the active search_path so
        # unqualified DDL + the alembic_version table live in it. Commit this
        # setup first so Alembic owns (and commits) its own transaction —
        # otherwise SQLAlchemy 2.0 autobegin leaves a transaction open that
        # Alembic won't commit, and the whole migration rolls back on close.
        connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        connection.exec_driver_sql(f'SET search_path TO "{schema}", public')
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema=schema,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
