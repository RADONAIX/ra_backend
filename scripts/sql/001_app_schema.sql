-- =====================================================================
-- RADONAIX Revenue Assurance — application schema (PostgreSQL)
-- Target database : rafms_db   (server 10.200.37.142:5432)
-- Schema          : administration   (single, dedicated application schema)
-- Tables          : 10 application tables (+ alembic_version, see below)
--
-- This script is the explicit DDL reference. It is equivalent to the
-- Alembic migration migrations/versions/0001_initial_schema.py.
-- Use EITHER Alembic (recommended, automatic) OR this script — not both.
-- If you run this script manually, afterwards run:  alembic stamp head
-- so the app does not try to recreate the tables.
--
-- Idempotent: safe to re-run. Run as a superuser / db owner:
--   psql "host=10.200.37.142 port=5432 dbname=rafms_db user=postgres password=postgres" \
--        -f 001_app_schema.sql
-- =====================================================================

-- --- Extensions (optional but recommended) ---------------------------
-- pgcrypto is only needed if you want the DB to generate UUIDs; the
-- application generates UUIDs in Python, so this is optional.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- --- Dedicated application schema ------------------------------------
CREATE SCHEMA IF NOT EXISTS administration;

-- Make every connection to this database resolve unqualified names to the
-- administration schema first. This lets the ORM / Alembic (which use unqualified
-- table names) operate in administration without any code change.
ALTER DATABASE rafms_db SET search_path TO administration, public;
SET search_path TO administration, public;

-- --- Shared updated_at trigger (defensive) ---------------------------
-- The application already sets updated_at on every ORM UPDATE. This trigger
-- guarantees it even for direct SQL writes. Optional but harmless.
CREATE OR REPLACE FUNCTION administration.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- 1. roles  — RBAC roles + per-feature {view,edit} permission matrix
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.roles (
    id          varchar(64)  NOT NULL,
    name        varchar(128) NOT NULL,
    description text         NOT NULL DEFAULT '',
    status      varchar(32)  NOT NULL DEFAULT 'Active',
    permissions jsonb        NOT NULL DEFAULT '{}'::jsonb,
    is_system   boolean      NOT NULL DEFAULT false,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_roles PRIMARY KEY (id)
);

-- =====================================================================
-- 2. users  — application users (auth, profile, role assignment)
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.users (
    id              varchar(36)  NOT NULL,
    full_name       varchar(255) NOT NULL,
    email           varchar(255) NOT NULL,
    phone           varchar(64),
    department      varchar(128),
    hashed_password varchar(255) NOT NULL,
    role_id         varchar(64)  NOT NULL,
    status          varchar(32)  NOT NULL DEFAULT 'Active',
    avatar          varchar(16),
    last_login      timestamptz,
    deleted_at      timestamptz,                -- soft-delete marker (NULL = active)
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT fk_users_role_id_roles FOREIGN KEY (role_id)
        REFERENCES administration.roles (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email   ON administration.users (email);
CREATE INDEX        IF NOT EXISTS ix_users_role_id ON administration.users (role_id);

-- =====================================================================
-- 3. audit_logs  — immutable audit trail of user/system actions
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.audit_logs (
    id     varchar(36)  NOT NULL,
    actor  varchar(128) NOT NULL,
    action varchar(255) NOT NULL,
    target varchar(255),
    meta   jsonb        NOT NULL DEFAULT '{}'::jsonb,
    at     timestamptz  NOT NULL,
    CONSTRAINT pk_audit_logs PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor ON administration.audit_logs (actor);
CREATE INDEX IF NOT EXISTS ix_audit_logs_at    ON administration.audit_logs (at);

-- =====================================================================
-- 4. cases  — revenue-leakage investigation cases
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.cases (
    id               varchar(36)  NOT NULL,
    reference        varchar(32)  NOT NULL,
    title            varchar(512) NOT NULL,
    description      text         NOT NULL DEFAULT '',
    severity         varchar(16)  NOT NULL DEFAULT 'medium',
    status           varchar(32)  NOT NULL DEFAULT 'Open',
    owner            varchar(128),
    owner_id         varchar(36),
    linked_txn_id    varchar(128),
    estimated_impact double precision,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_cases PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_cases_reference ON administration.cases (reference);
CREATE INDEX        IF NOT EXISTS ix_cases_status    ON administration.cases (status);

-- =====================================================================
-- 5. case_comments  — discussion thread on a case
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.case_comments (
    id         varchar(36)  NOT NULL,
    case_id    varchar(36)  NOT NULL,
    author     varchar(128) NOT NULL,
    body       text         NOT NULL,
    created_at timestamptz  NOT NULL,
    CONSTRAINT pk_case_comments PRIMARY KEY (id),
    CONSTRAINT fk_case_comments_case_id_cases FOREIGN KEY (case_id)
        REFERENCES administration.cases (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_case_comments_case_id ON administration.case_comments (case_id);

-- =====================================================================
-- 6. saved_queries  — workbench saved investigations / filters
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.saved_queries (
    id         varchar(36)  NOT NULL,
    reference  varchar(32)  NOT NULL,
    name       varchar(512) NOT NULL,
    owner      varchar(128),
    definition jsonb        NOT NULL DEFAULT '{}'::jsonb,
    last_count integer      NOT NULL DEFAULT 0,
    created_at timestamptz  NOT NULL DEFAULT now(),
    updated_at timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_saved_queries PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_saved_queries_reference ON administration.saved_queries (reference);

-- =====================================================================
-- 7. decoders  — CDR decoder registry + config (Settings → Decoders)
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.decoders (
    id         varchar(64)  NOT NULL,
    name       varchar(255) NOT NULL,
    version    varchar(32)  NOT NULL,
    status     varchar(32)  NOT NULL DEFAULT 'Enabled',
    throughput varchar(32),
    config     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz  NOT NULL DEFAULT now(),
    updated_at timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_decoders PRIMARY KEY (id)
);

-- =====================================================================
-- 8. system_config  — singleton platform configuration (id = 'system')
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.system_config (
    id               varchar(32) NOT NULL DEFAULT 'system',
    environment      varchar(32) NOT NULL DEFAULT 'production',
    retention_days   integer     NOT NULL DEFAULT 365,
    sla_minutes      integer     NOT NULL DEFAULT 15,
    alert_email      varchar(255),
    maintenance_mode boolean     NOT NULL DEFAULT false,
    extra            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_system_config PRIMARY KEY (id)
);

-- =====================================================================
-- 9. pipeline_alerts  — operator-facing pipeline alerts + ack state
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.pipeline_alerts (
    id              varchar(64)  NOT NULL,
    severity        varchar(16)  NOT NULL DEFAULT 'medium',
    stage           varchar(64)  NOT NULL,
    message         text         NOT NULL,
    status          varchar(32)  NOT NULL DEFAULT 'Open',
    acknowledged_by varchar(128),
    created_at      timestamptz  NOT NULL,
    CONSTRAINT pk_pipeline_alerts PRIMARY KEY (id)
);

-- =====================================================================
-- 10. reports  — certified report generation + export metadata
-- =====================================================================
CREATE TABLE IF NOT EXISTS administration.reports (
    id              varchar(36)  NOT NULL,
    reference       varchar(32)  NOT NULL,
    name            varchar(255) NOT NULL,
    report_type     varchar(64)  NOT NULL DEFAULT 'reconciliation',
    period          varchar(32),
    status          varchar(32)  NOT NULL DEFAULT 'Queued',
    size_bytes      bigint,
    file_path       varchar(1024),
    checksum_sha256 varchar(64),
    requested_by    varchar(128),
    params          jsonb        NOT NULL DEFAULT '{}'::jsonb,
    error           text,
    completed_at    timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_reports PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_reference ON administration.reports (reference);
CREATE INDEX        IF NOT EXISTS ix_reports_status    ON administration.reports (status);

-- --- Attach updated_at triggers (optional) ---------------------------
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'roles','users','cases','saved_queries','decoders','system_config','reports'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_set_updated_at ON administration.%I;', t);
        EXECUTE format(
            'CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON administration.%I '
            'FOR EACH ROW EXECUTE FUNCTION administration.set_updated_at();', t);
    END LOOP;
END $$;

-- =====================================================================
-- alembic_version is created/managed by Alembic itself. If you ran THIS
-- script manually (instead of `alembic upgrade head`), stamp the schema:
--     alembic stamp head
-- which creates administration.alembic_version and records revision 0001.
-- =====================================================================
