"""Rules ORM models: Rule (versioned) and RuleRun.

A Rule is a revenue-assurance check with a JSON definition and optional cron
schedule. Versions of the "same" logical rule are grouped via ``parent_id``.
A RuleRun records one execution (typically an Airflow DAG run) of a rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class Rule(Base, TimestampMixin):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Groups versions of the same logical rule (nullable for the first version).
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), default="medium", server_default="medium", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="Draft", server_default="Draft", nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schedule: Mapped[str | None] = mapped_column(String(64), nullable=True)  # cron expression
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[list[RuleRun]] = relationship(back_populates="rule")


class RuleRun(Base):
    __tablename__ = "rule_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id"), nullable=False, index=True)
    dag_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="Triggered", server_default="Triggered", nullable=False, index=True
    )
    params: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rule: Mapped[Rule] = relationship(back_populates="runs")
