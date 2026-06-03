"""Pydantic schemas for the reporting module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReportRow(BaseModel):
    """Shape consumed by the Reports table (id shown is the reference)."""

    id: str
    name: str
    period: str | None = None
    status: str
    size: str


class ReportDetail(ReportRow):
    reportType: str
    requestedBy: str | None = None
    checksum: str | None = None
    error: str | None = None
    createdAt: datetime
    completedAt: datetime | None = None


class ReportCreate(BaseModel):
    name: str = Field(min_length=1)
    reportType: str = "reconciliation"
    period: str | None = None
    params: dict = Field(default_factory=dict)
