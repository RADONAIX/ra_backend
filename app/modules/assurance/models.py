"""Assurance ORM models: Case, CaseComment, SavedQuery (workbench).

Reconciliation *results* live in ra-platform's ClickHouse and are read via
the integration client — they are not modelled here. These tables capture the
human workflow layered on top: investigations and leakage cases.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

# Allowed values, enforced both in Pydantic schemas (→ 422) and via DB CHECKs.
CASE_SEVERITIES = ("low", "medium", "high", "critical")
CASE_STATUSES = ("Open", "In Progress", "Resolved", "Closed", "Cancelled")


def _uuid() -> str:
    return str(uuid.uuid4())


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class Case(Base, TimestampMixin):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(_in_list("severity", CASE_SEVERITIES), name="chk_cases_severity"),
        CheckConstraint(_in_list("status", CASE_STATUSES), name="chk_cases_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Human-friendly reference, e.g. CASE-2031.
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="Open", nullable=False, index=True)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Optional linkage to a recon anomaly (txn_id / status bucket).
    linked_txn_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    estimated_impact: Mapped[float | None] = mapped_column(nullable=True)

    comments: Mapped[list[CaseComment]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class CaseComment(Base):
    __tablename__ = "case_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case: Mapped[Case] = relationship(back_populates="comments")


class SavedQuery(Base, TimestampMixin):
    """A saved workbench investigation / query."""

    __tablename__ = "saved_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Stored filter definition (field/op/value list) executed against recon data.
    definition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
