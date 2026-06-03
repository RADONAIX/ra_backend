"""Operations ORM models: Decoder, SystemConfig, PipelineAlert.

Pipeline *runs* and *stage metrics* are derived live from ra-platform
(Postgres file_log / ClickHouse), not stored here. Decoders, system config
and alert acknowledgement state are owned by this service.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class Decoder(Base, TimestampMixin):
    __tablename__ = "decoders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="Enabled", nullable=False)
    throughput: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SystemConfig(Base, TimestampMixin):
    """Single-row system configuration (id is always 'system')."""

    __tablename__ = "system_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="system")
    environment: Mapped[str] = mapped_column(String(32), default="production", nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    sla_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    alert_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PipelineAlert(Base):
    """Acknowledgement state for pipeline alerts surfaced to operators."""

    __tablename__ = "pipeline_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="Open", nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
