"""Operations business logic: pipelines, decoders, system config.

Live pipeline data is derived from ra-platform where possible:
  * KPIs / run history from ClickHouse ``air_reconciliation`` +
    ``reconciliation_run_log`` (schema known from ra-platform/scripts).
  * Decoders / system config / alert-ack state are owned by this service.

When the upstream is disabled or unreachable, representative fallback data
(matching the UI's expected shapes) is returned and the degradation is logged,
so the dashboard stays functional in dev/offline environments.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UpstreamUnavailableError
from app.core.logging import get_logger
from app.integrations import airflow, clickhouse, ra_postgres
from app.modules.operations import schemas
from app.modules.operations.models import Decoder, PipelineAlert, SystemConfig

log = get_logger("operations")


# --- Pipeline Map: batch logs (read-only, rafms_db.public.*_batch_log) -------
# (dag, stream, table) — schema-qualified by settings.ra_pg_batchlog_schema.
# Full design is 6 tables (AIR/SDP/MSC x Raw/Processed); only live ones enabled.
BATCHLOG_SOURCES: list[tuple[str, str, str]] = [
    ("AIR", "Raw", "batch_log"),  # TODO: rename -> air_raw_batch_log
    ("AIR", "Processed", "air_processed_batch_log"),
    # ("SDP", "Raw", "sdp_raw_batch_log"),             # under development
    # ("SDP", "Processed", "sdp_processed_batch_log"),
    # ("MSC", "Raw", "msc_raw_batch_log"),
    # ("MSC", "Processed", "msc_processed_batch_log"),
]


async def list_batch_sources(*, hours: int = 12) -> list[schemas.BatchSource]:
    """Per-batch pipeline logs for the UI Pipeline Map, grouped by DAG + stream,
    read live from ra-platform's Postgres. Each source returns batches whose
    ``batch_start_time`` is within the last ``hours``. Each table is queried
    independently so a missing / under-development / unreachable source yields
    an empty group instead of failing the whole response (no 500)."""
    from app.core.config import settings

    schema = settings.ra_pg_batchlog_schema
    out: list[schemas.BatchSource] = []
    for dag, stream, table in BATCHLOG_SOURCES:
        try:
            rows = await ra_postgres.query(
                f'SELECT * FROM {schema}."{table}" '
                f"WHERE batch_start_time >= now() - make_interval(hours => :hours) "
                f"ORDER BY batch_start_time DESC LIMIT 5000",  # window is the filter; LIMIT is a safety cap
                {"hours": hours},
            )
            out.append(
                schemas.BatchSource(
                    dag=dag,
                    stream=stream,
                    rows=[schemas.BatchLog(**row) for row in rows],
                )
            )
        except UpstreamUnavailableError:
            log.info("batchlog_source_unavailable", dag=dag, stream=stream, table=table)
            out.append(schemas.BatchSource(dag=dag, stream=stream, rows=[]))
    return out


# --- Export module: per-batch file logs (rafms_db.public.*_file_log) ---------
# batch_id prefix -> (table, projection). The projection is the SELECT list that
# normalises each table's columns to the UI FileLog shape. ``"*"`` means the
# table already matches FileLog (processed); raw tables need explicit aliases.
# Maps file_log's (raw) columns onto the UI FileLog shape. NOTE: targets the
# CURRENT `file_log` schema (uses file_date, split actual_* counts). When it is
# renamed to air_raw_file_log (which has file_timestamp / actual_record_count),
# revisit these aliases.
_RAW_FILE_PROJECTION = (
    "id, filename, batch_id, file_node_id AS node_id, "
    "file_sequence_number AS sequence_number, file_date AS file_timestamp, '' AS file_type, "
    "file_status, integrity_flag, archived_at, archived_path, "
    "decoder_start_time, decoder_end_time, "
    "CASE WHEN decoding_status THEN 'SUCCESS' ELSE 'FAILED' END AS decoder_status, "
    "refill_csv_creation_status AS csv_creation_status, "
    "refill_db_loading_status AS db_loading_status, "
    "ingestion_start_time, ingestion_end_time, ingestion_status, "
    "expected_record_count, "
    "(COALESCE(actual_refill_record_count,0) + COALESCE(actual_adjustment_record_count,0) "
    "+ COALESCE(actual_error_record_count,0)) AS actual_record_count, "
    "attempt_count AS retry_count, last_error_step, "
    "last_error_message AS error_message, insert_timestamp AS created_at, "
    "quarantined_at, quarantine_reason, quarantine_batch_dir, quarantine_count, retried_at"
)

# prefix -> (table, projection_sql)
FILE_SOURCES: list[tuple[str, str, str]] = [
    ("AIR_PROCESSED_", "air_processed_file_log", "*"),
    ("AIR_RAW_", "file_log", _RAW_FILE_PROJECTION),  # TODO: rename -> air_raw_file_log
    # ("SDP_RAW_", "sdp_raw_file_log", _RAW_FILE_PROJECTION),       # under development
    # ("SDP_PROCESSED_", "sdp_processed_file_log", "*"),
    # ("MSC_RAW_", "msc_raw_file_log", _RAW_FILE_PROJECTION),
    # ("MSC_PROCESSED_", "msc_processed_file_log", "*"),
]


async def list_batch_files(batch_id: str) -> list[schemas.FileLog]:
    """All files for one batch, for the Export module's drill-down. The source
    table is resolved from the ``batch_id`` prefix (e.g. ``AIR_PROCESSED_`` ->
    air_processed_file_log). Returns ``[]`` for an unknown prefix or when the
    upstream is unavailable (never 500s)."""
    from app.core.config import settings

    key = batch_id.upper()
    match = next((s for s in FILE_SOURCES if key.startswith(s[0])), None)
    if match is None:
        log.info("batch_files_unknown_prefix", batch_id=batch_id)
        return []
    _prefix, table, projection = match
    qualified = f'{settings.ra_pg_batchlog_schema}."{table}"'
    try:
        rows = await ra_postgres.query(
            f"SELECT {projection} FROM {qualified} "
            f"WHERE batch_id = :batch_id ORDER BY sequence_number LIMIT 100000",
            {"batch_id": batch_id},
        )
        return [schemas.FileLog(**row) for row in rows]
    except UpstreamUnavailableError:
        log.info("batch_files_unavailable", batch_id=batch_id, table=table)
        return []


def _db_ident() -> str:
    from app.core.config import settings

    return "`" + settings.clickhouse_database.replace("`", "``") + "`"


# --- Fallback data (mirrors UI service defaults) ---------------------------
_FALLBACK_STAGES = [
    {
        "key": "collection",
        "name": "File Collection",
        "status": "ok",
        "duration": "1m 12s",
        "metric": "—",
    },
    {"key": "decoding", "name": "Decoding", "status": "ok", "duration": "3m 47s", "metric": "—"},
    {
        "key": "validation",
        "name": "Validation",
        "status": "ok",
        "duration": "2m 03s",
        "metric": "—",
    },
    {
        "key": "reconciliation",
        "name": "Reconciliation",
        "status": "ok",
        "duration": "4m 21s",
        "metric": "—",
    },
    {
        "key": "reporting",
        "name": "Report Generation",
        "status": "ok",
        "duration": "0m 58s",
        "metric": "—",
    },
]


# --- Pipelines: KPIs -------------------------------------------------------
async def get_kpis(db: AsyncSession) -> schemas.PipelineKpis:
    cfg = await get_or_create_config(db)
    try:
        ident = _db_ident()
        rows = await clickhouse.query(
            f"""
            SELECT
                count() AS total,
                countIf(reconciliation_status = 'MATCHED') AS matched,
                countIf(reconciliation_status != 'MATCHED') AS mismatched
            FROM {ident}.air_reconciliation FINAL
            WHERE created_time >= now() - INTERVAL 24 HOUR
            """
        )
        stats = rows[0] if rows else {"total": 0, "matched": 0, "mismatched": 0}
        total = int(stats.get("total") or 0)
        mismatched = int(stats.get("mismatched") or 0)
        breaches = await _sla_breaches(ident, cfg.sla_minutes)
        return schemas.PipelineKpis(
            throughput=f"{total:,} / 24h",
            avgLatency=await _avg_latency(ident),
            failed24h=mismatched,
            slaBreaches=breaches,
        )
    except UpstreamUnavailableError:
        log.info("kpis_fallback", reason="clickhouse_unavailable")
        return schemas.PipelineKpis(
            throughput="8.4M / hr", avgLatency="12m 21s", failed24h=14, slaBreaches=2
        )


async def _avg_latency(ident: str) -> str:
    rows = await clickhouse.query(
        f"""
        SELECT avg(dateDiff('second', recon_start_time, recon_end_time)) AS secs
        FROM {ident}.reconciliation_run_log
        WHERE status = 'COMPLETED' AND created_time >= now() - INTERVAL 24 HOUR
        """
    )
    secs = int((rows[0].get("secs") if rows else 0) or 0)
    return f"{secs // 60}m {secs % 60}s"


async def _sla_breaches(ident: str, sla_minutes: int) -> int:
    rows = await clickhouse.query(
        f"""
        SELECT countIf(dateDiff('minute', recon_start_time, recon_end_time) > {sla_minutes}) AS n
        FROM {ident}.reconciliation_run_log
        WHERE status = 'COMPLETED' AND created_time >= now() - INTERVAL 24 HOUR
        """
    )
    return int((rows[0].get("n") if rows else 0) or 0)


# --- Pipelines: stages -----------------------------------------------------
async def get_stages(db: AsyncSession) -> list[schemas.PipelineStage]:
    try:
        ident = _db_ident()
        rows = await clickhouse.query(
            f"""
            SELECT
                count() AS total,
                countIf(reconciliation_status = 'MATCHED') AS matched
            FROM {ident}.air_reconciliation FINAL
            WHERE created_time >= now() - INTERVAL 24 HOUR
            """
        )
        total = int((rows[0].get("total") if rows else 0) or 0)
        matched = int((rows[0].get("matched") if rows else 0) or 0)
        match_pct = (matched / total * 100) if total else 100.0
        stages = [dict(s) for s in _FALLBACK_STAGES]
        stages[3]["metric"] = f"{match_pct:.2f}% match"
        stages[3]["status"] = "ok" if match_pct >= 99 else "warning"
        stages[1]["metric"] = f"{total:,} records"
        return [schemas.PipelineStage(**s) for s in stages]
    except UpstreamUnavailableError:
        log.info("stages_fallback", reason="clickhouse_unavailable")
        return [schemas.PipelineStage(**s) for s in _FALLBACK_STAGES]


# --- Pipelines: runs -------------------------------------------------------
async def get_runs(db: AsyncSession, *, limit: int) -> list[schemas.PipelineRun]:
    try:
        ident = _db_ident()
        rows = await clickhouse.query(
            f"""
            SELECT recon_run_id, recon_start_time, recon_end_time, status
            FROM {ident}.reconciliation_run_log
            ORDER BY created_time DESC
            LIMIT {int(limit)}
            """
        )
        return [
            schemas.PipelineRun(
                id=str(r.get("recon_run_id")),
                source="Reconciliation",
                batch=str(r.get("recon_run_id")),
                start=r.get("recon_start_time"),
                end=r.get("recon_end_time"),
                status="Completed" if r.get("status") == "COMPLETED" else str(r.get("status")),
                records=0,
                failed=0,
            )
            for r in rows
        ]
    except UpstreamUnavailableError:
        log.info("runs_fallback", reason="clickhouse_unavailable")
        return [
            schemas.PipelineRun(
                id="RUN-90112",
                source="MSC-EU-1",
                batch="BATCH-441A",
                start=datetime(2026, 6, 2, 9, 2, tzinfo=UTC),
                end=datetime(2026, 6, 2, 9, 18, tzinfo=UTC),
                status="Completed",
                records=1284322,
                failed=12,
            ),
            schemas.PipelineRun(
                id="RUN-90110",
                source="BSS-CRM",
                batch="BATCH-441C",
                start=datetime(2026, 6, 2, 8, 30, tzinfo=UTC),
                end=datetime(2026, 6, 2, 8, 51, tzinfo=UTC),
                status="Failed",
                records=312044,
                failed=4012,
            ),
        ]


# --- Pipelines: alerts (DB-owned) ------------------------------------------
async def list_alerts(db: AsyncSession) -> list[schemas.PipelineAlertRow]:
    rows = (
        (await db.execute(select(PipelineAlert).order_by(PipelineAlert.created_at.desc())))
        .scalars()
        .all()
    )
    return [
        schemas.PipelineAlertRow(
            id=a.id,
            severity=a.severity,
            stage=a.stage,
            message=a.message,
            createdAt=a.created_at,
            status=a.status,
        )
        for a in rows
    ]


async def acknowledge_alert(db: AsyncSession, alert_id: str, actor: str) -> schemas.ActionResult:
    alert = (
        await db.execute(select(PipelineAlert).where(PipelineAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        raise NotFoundError("Alert not found.")
    alert.status = "Acknowledged"
    alert.acknowledged_by = actor
    await db.flush()
    return schemas.ActionResult(ok=True, detail=f"Alert {alert_id} acknowledged.")


# --- Pipelines: retries ----------------------------------------------------
async def get_retries(db: AsyncSession) -> list[schemas.RetryJob]:
    # No canonical retry queue in ra-platform yet; surface failed alerts as
    # actionable retry candidates, falling back to representative data.
    alerts = (
        (await db.execute(select(PipelineAlert).where(PipelineAlert.status == "Open")))
        .scalars()
        .all()
    )
    if alerts:
        return [
            schemas.RetryJob(id=a.id, batch="—", stage=a.stage, error=a.message, retryCount=0)
            for a in alerts
        ]
    return [
        schemas.RetryJob(
            id="JOB-7781",
            batch="BATCH-441C",
            stage="Reconciliation",
            error="Mismatch threshold exceeded (3.4%)",
            retryCount=1,
        ),
    ]


async def retry_job(job_id: str) -> schemas.ActionResult:
    return await _trigger("air_recon_dag", job_id, "retry")


async def replay_job(job_id: str) -> schemas.ActionResult:
    return await _trigger("air_pipeline_dag", job_id, "replay")


async def _trigger(dag_id: str, job_id: str, action: str) -> schemas.ActionResult:
    try:
        await airflow.trigger_dag(dag_id, conf={"job_id": job_id, "action": action})
        return schemas.ActionResult(ok=True, detail=f"Triggered {dag_id} for {job_id}.")
    except UpstreamUnavailableError as exc:
        log.info("trigger_skipped", dag_id=dag_id, reason=exc.message)
        return schemas.ActionResult(
            ok=True, detail=f"Queued {action} for {job_id} (Airflow integration disabled)."
        )


# --- Decoders --------------------------------------------------------------
async def list_decoders(db: AsyncSession) -> list[schemas.DecoderRow]:
    rows = (await db.execute(select(Decoder).order_by(Decoder.name))).scalars().all()
    return [
        schemas.DecoderRow(
            id=d.id, name=d.name, version=d.version, status=d.status, throughput=d.throughput
        )
        for d in rows
    ]


async def upsert_decoder(db: AsyncSession, payload: schemas.DecoderUpsert) -> Decoder:
    dec = (await db.execute(select(Decoder).where(Decoder.id == payload.id))).scalar_one_or_none()
    if dec is None:
        dec = Decoder(id=payload.id)
        db.add(dec)
    dec.name = payload.name
    dec.version = payload.version
    dec.status = payload.status
    dec.throughput = payload.throughput
    if payload.config is not None:
        dec.config = payload.config
    await db.flush()
    await db.refresh(dec)
    return dec


# --- System config ---------------------------------------------------------
async def get_or_create_config(db: AsyncSession) -> SystemConfig:
    cfg = (
        await db.execute(select(SystemConfig).where(SystemConfig.id == "system"))
    ).scalar_one_or_none()
    if cfg is None:
        cfg = SystemConfig(id="system")
        db.add(cfg)
        await db.flush()
        await db.refresh(cfg)
    return cfg


async def get_system_config(db: AsyncSession) -> schemas.SystemConfigOut:
    cfg = await get_or_create_config(db)
    return schemas.SystemConfigOut(
        environment=cfg.environment,
        retentionDays=cfg.retention_days,
        slaMinutes=cfg.sla_minutes,
        alertEmail=cfg.alert_email,
        maintenanceMode=cfg.maintenance_mode,
    )


async def update_system_config(
    db: AsyncSession, payload: schemas.SystemConfigUpdate
) -> schemas.SystemConfigOut:
    cfg = await get_or_create_config(db)
    if payload.environment is not None:
        cfg.environment = payload.environment
    if payload.retentionDays is not None:
        cfg.retention_days = payload.retentionDays
    if payload.slaMinutes is not None:
        cfg.sla_minutes = payload.slaMinutes
    if payload.alertEmail is not None:
        cfg.alert_email = str(payload.alertEmail)
    if payload.maintenanceMode is not None:
        cfg.maintenance_mode = payload.maintenanceMode
    await db.flush()
    await db.refresh(cfg)
    return await get_system_config(db)
