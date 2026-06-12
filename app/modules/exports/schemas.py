"""Exports API schemas (camelCase, mirroring the UI)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class ExportJobCreate(BaseModel):
    reportKey: str = Field(min_length=1)
    dateFrom: date
    dateTo: date
    filters: dict[str, Any] = Field(default_factory=dict)  # reserved (phase 2)


class ExportJobRow(BaseModel):
    id: str
    reference: str
    reportKey: str
    status: str
    progressPct: int
    processedRows: int
    totalRows: int | None = None
    fileSizeBytes: int | None = None
    requestedBy: str | None = None
    createdAt: datetime
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    expiresAt: datetime | None = None
    error: str | None = None


class ExportJobDetail(ExportJobRow):
    params: dict[str, Any] = Field(default_factory=dict)
    kpis: dict[str, Any] | None = None
    checksumSha256: str | None = None
    fileFormat: str = "csv.gz"


class KpiPreviewRequest(BaseModel):
    reportKey: str = Field(min_length=1)
    dateFrom: date
    dateTo: date
    filters: dict[str, Any] = Field(default_factory=dict)


class KpiPreviewResponse(BaseModel):
    reportKey: str
    dateFrom: date
    dateTo: date
    kpis: dict[str, Any] | None = None
