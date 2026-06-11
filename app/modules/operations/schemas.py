"""Pydantic schemas for the operations module (shapes match the UI)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


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


# --- Pipeline Map: batch logs (read-only from rafms_db.public.*_batch_log) --
def _coerce_int(v: object) -> object:
    return 0 if v is None else v


def _coerce_str(v: object) -> object:
    """None → "", datetime → "YYYY-MM-DD HH:MM:SS.ffffff" (matches UI mocks)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return v


class BatchLog(BaseModel):
    """One pipeline batch run. Fields are the UNION of the per-DAG/stream batch
    log tables (processed: ``batch_status``/``total_aa_rows``/``total_rr_rows``;
    raw: ``insert_timestamp``/``total_adjustment_rows``/``total_refill_rows``/
    ``total_error_rows``), so one model passes through any source table. SQL
    NULLs and columns absent from a given table coerce to sentinels (``0`` for
    counts, ``""`` for strings) so the UI needs no null-handling."""

    model_config = {"extra": "ignore"}

    batch_id: str = ""
    total_files: int = 0
    batch_start_time: str = ""
    batch_end_time: str = ""
    batch_status: str = ""
    batch_timestamp: str = ""

    watcher_start_time: str = ""
    watcher_end_time: str = ""
    watcher_status: str = ""

    archive_start_time: str = ""
    archive_end_time: str = ""
    archive_status: str = ""
    archived_file_count: int = 0

    decoder_start_time: str = ""
    decoder_end_time: str = ""
    decoder_status: str = ""
    decode_complete_count: int = 0
    decode_failed_count: int = 0

    validation_start_time: str = ""
    validation_end_time: str = ""
    validation_status: str = ""
    validation_message: str = ""

    ingestion_start_time: str = ""
    ingestion_end_time: str = ""
    ingestion_status: str = ""
    load_complete_count: int = 0
    load_failed_count: int = 0
    total_aa_rows: int = 0
    total_rr_rows: int = 0

    normalization_start_time: str = ""
    normalization_end_time: str = ""
    normalization_status: str = ""

    zero_kb_file_count: int = 0
    duplicate_file_count: int = 0
    corrupt_file_count: int = 0
    error_message: str = ""
    created_at: str = ""
    quarantined_at: str = ""
    quarantine_reason: str = ""
    quarantined_file_count: int = 0
    retried_at: str = ""
    retried_by: str = ""

    # Raw-stream-only columns (present in batch_log / *_raw_batch_log).
    insert_timestamp: str = ""
    total_adjustment_rows: int = 0
    total_refill_rows: int = 0
    total_error_rows: int = 0

    _v_int = field_validator(
        "total_files",
        "archived_file_count",
        "decode_complete_count",
        "decode_failed_count",
        "load_complete_count",
        "load_failed_count",
        "total_aa_rows",
        "total_rr_rows",
        "zero_kb_file_count",
        "duplicate_file_count",
        "corrupt_file_count",
        "quarantined_file_count",
        "total_adjustment_rows",
        "total_refill_rows",
        "total_error_rows",
        mode="before",
    )(_coerce_int)

    _v_str = field_validator(
        "batch_id",
        "batch_status",
        "batch_timestamp",
        "batch_start_time",
        "batch_end_time",
        "watcher_start_time",
        "watcher_end_time",
        "watcher_status",
        "archive_start_time",
        "archive_end_time",
        "archive_status",
        "decoder_start_time",
        "decoder_end_time",
        "decoder_status",
        "validation_start_time",
        "validation_end_time",
        "validation_status",
        "validation_message",
        "ingestion_start_time",
        "ingestion_end_time",
        "ingestion_status",
        "normalization_start_time",
        "normalization_end_time",
        "normalization_status",
        "error_message",
        "created_at",
        "quarantined_at",
        "quarantine_reason",
        "retried_at",
        "retried_by",
        "insert_timestamp",
        mode="before",
    )(_coerce_str)


class BatchSource(BaseModel):
    """A group of batch rows for one DAG + stream (maps to the UI's dataset)."""

    dag: str  # AIR | SDP | MSC
    stream: str  # Raw | Processed
    rows: list[BatchLog]


# --- Export module: per-batch file logs (rafms_db.public.*_file_log) --------
class FileLog(BaseModel):
    """One file inside a batch. Fields mirror the UI's ``FileLog`` interface
    (src/lib/airFiles.ts). The processed file-log table maps ~1:1; raw tables
    are aliased to this shape in the service. SQL NULLs / absent columns coerce
    to sentinels."""

    model_config = {"extra": "ignore"}

    id: str = ""
    filename: str = ""
    batch_id: str = ""
    node_id: str = ""
    sequence_number: int = 0
    file_timestamp: str = ""
    file_status: str = ""
    integrity_flag: str = ""

    archived_at: str = ""
    archived_path: str = ""

    watcher_start_time: str = ""
    watcher_end_time: str = ""
    watcher_status: str = ""

    picker_start_time: str = ""
    picker_end_time: str = ""
    picker_status: str = ""

    decoder_start_time: str = ""
    decoder_end_time: str = ""
    decoder_status: str = ""

    csv_creation_start_time: str = ""
    csv_creation_end_time: str = ""
    csv_creation_status: str = ""

    db_loading_start_time: str = ""
    db_loading_end_time: str = ""
    db_loading_status: str = ""

    ingestion_start_time: str = ""
    ingestion_end_time: str = ""
    ingestion_status: str = ""

    expected_record_count: int = 0
    actual_record_count: int = 0
    retry_count: int = 0
    last_error_step: str = ""
    error_message: str = ""
    created_at: str = ""

    quarantined_at: str = ""
    quarantine_reason: str = ""
    quarantine_batch_dir: str = ""
    quarantine_count: int = 0
    retried_at: str = ""

    _vf_int = field_validator(
        "sequence_number",
        "expected_record_count",
        "actual_record_count",
        "retry_count",
        "quarantine_count",
        mode="before",
    )(_coerce_int)

    _vf_str = field_validator(
        "filename",
        "batch_id",
        "node_id",
        "file_timestamp",
        "file_status",
        "archived_at",
        "archived_path",
        "watcher_start_time",
        "watcher_end_time",
        "watcher_status",
        "picker_start_time",
        "picker_end_time",
        "picker_status",
        "decoder_start_time",
        "decoder_end_time",
        "decoder_status",
        "csv_creation_start_time",
        "csv_creation_end_time",
        "csv_creation_status",
        "db_loading_start_time",
        "db_loading_end_time",
        "db_loading_status",
        "ingestion_start_time",
        "ingestion_end_time",
        "ingestion_status",
        "last_error_step",
        "error_message",
        "created_at",
        "quarantined_at",
        "quarantine_reason",
        "quarantine_batch_dir",
        "retried_at",
        mode="before",
    )(_coerce_str)

    @field_validator("integrity_flag", mode="before")
    @classmethod
    def _flag_to_str(cls, v: object) -> object:
        # Surface the raw DB value as a string — no assumed code→label mapping.
        return "" if v is None else str(v)

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v: object) -> object:
        # DB id is bigint; UI treats it as a string.
        return "" if v is None else str(v)
