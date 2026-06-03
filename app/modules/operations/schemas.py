"""Pydantic schemas for the operations module (shapes match the UI)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr


# --- Pipelines -------------------------------------------------------------
class PipelineStage(BaseModel):
    key: str
    name: str
    status: str  # ok | warning | error
    duration: str
    metric: str


class PipelineKpis(BaseModel):
    throughput: str
    avgLatency: str
    failed24h: int
    slaBreaches: int


class PipelineRun(BaseModel):
    id: str
    source: str
    batch: str
    start: datetime | None = None
    end: datetime | None = None
    status: str
    records: int
    failed: int


class PipelineAlertRow(BaseModel):
    id: str
    severity: str
    stage: str
    message: str
    createdAt: datetime
    status: str


class RetryJob(BaseModel):
    id: str
    batch: str
    stage: str
    error: str
    retryCount: int


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


# --- Decoders --------------------------------------------------------------
class DecoderRow(BaseModel):
    id: str
    name: str
    version: str
    status: str
    throughput: str | None = None


class DecoderUpsert(BaseModel):
    id: str
    name: str
    version: str
    status: str = "Enabled"
    throughput: str | None = None
    config: dict | None = None


# --- System config ---------------------------------------------------------
class SystemConfigOut(BaseModel):
    environment: str
    retentionDays: int
    slaMinutes: int
    alertEmail: EmailStr | None = None
    maintenanceMode: bool


class SystemConfigUpdate(BaseModel):
    environment: str | None = None
    retentionDays: int | None = None
    slaMinutes: int | None = None
    alertEmail: EmailStr | None = None
    maintenanceMode: bool | None = None
