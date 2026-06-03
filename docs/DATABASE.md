# Database Design — RADONAIX Revenue Assurance Backend

This document specifies the PostgreSQL data model for the application backend:
how many databases, schemas and tables are required, the CREATE scripts, and
operational guidance.

---

## 1. Summary (the short answer)

| Question | Answer |
|---|---|
| **Databases** | **1** application database — `rafms_db` |
| **Schemas** | **1** dedicated application schema — `administration` (plus the default `public`, unused) |
| **Tables** | **10** application tables + **1** Alembic bookkeeping table (`alembic_version`) = **11** total |
| **Owns the data?** | This service fully owns `rafms_db`. ra-platform's recon data (ClickHouse) and `file_log` (its own Postgres) are **read-only integrations** — *not* in this database. |

> Why a dedicated schema instead of `public`? It keeps the application's tables
> isolated and namespaced, makes grants/backups easy to scope, and avoids any
> collision if other tooling ever shares the database. One schema is enough —
> there is no need to split tables across multiple schemas at this scale.

### Connection (your server)
```
host=10.200.37.142  port=5432  dbname=rafms_db  user=postgres  password=postgres
schema (search_path)=administration
```

---

## 2. The 10 tables

Grouped by the module that owns them (the backend is a modular monolith).

### identity module
| # | Table | Purpose | Key columns |
|---|---|---|---|
| 1 | `roles` | RBAC roles + per-feature `{view,edit}` permission matrix (JSONB) | `id` (slug PK), `permissions` |
| 2 | `users` | Application users; auth + profile + role assignment | `id` (uuid PK), `email` (unique), `hashed_password`, `role_id`→roles, `deleted_at` (soft-delete) |
| 3 | `audit_logs` | Append-only trail of user/system actions | `id`, `actor`, `action`, `target`, `at` |

### assurance module
| # | Table | Purpose | Key columns |
|---|---|---|---|
| 4 | `cases` | Revenue-leakage investigation cases | `id`, `reference` (unique, e.g. CASE-2031), `severity`, `status` |
| 5 | `case_comments` | Comment thread per case | `id`, `case_id`→cases (ON DELETE CASCADE) |
| 6 | `saved_queries` | Workbench saved investigations / filters | `id`, `reference` (unique, e.g. Q-512), `definition` (JSONB) |

### operations module
| # | Table | Purpose | Key columns |
|---|---|---|---|
| 7 | `decoders` | CDR decoder registry + config | `id` (e.g. DEC-ASN1-v3), `status`, `config` (JSONB) |
| 8 | `system_config` | **Singleton** platform config (row id always `system`) | `retention_days`, `sla_minutes`, `alert_email`, `maintenance_mode` |
| 9 | `pipeline_alerts` | Operator-facing alerts + acknowledgement state | `id` (e.g. ALT-2231), `severity`, `stage`, `status` |

### reporting module
| # | Table | Purpose | Key columns |
|---|---|---|---|
| 10 | `reports` | Certified report generation + export metadata | `id`, `reference` (unique, e.g. RPT-9921), `status`, `file_path`, `checksum_sha256` |

> **Not stored here (by design):** reconciliation results (`air_reconciliation`,
> `reconciliation_run_log`) live in ra-platform's **ClickHouse**; file/batch
> processing status (`file_log`) lives in ra-platform's **Postgres**. Pipeline
> *runs/KPIs* are read live from those sources, never duplicated.

### Relationships (ER overview)
```
roles (1) ───< (N) users
cases (1) ───< (N) case_comments        [ON DELETE CASCADE]
system_config  → single row (id = 'system')
everything else is a standalone lookup/registry table
```
Only two foreign keys exist (`users.role_id → roles.id`,
`case_comments.case_id → cases.id`), keeping the model simple and fast.

---

## 3. How to create the schema

You have **two equivalent options**. Pick one.

### Option A — Alembic migrations (recommended, automatic)
The app ships a migration that creates all 10 tables + indexes. In Docker
Compose it runs automatically (`RUN_MIGRATIONS=true`). Manually:
```bash
cd backend
export APP_DB_HOST=10.200.37.142 APP_DB_NAME=rafms_db \
       APP_DB_USER=postgres APP_DB_PASSWORD=postgres
# Ensure the schema + search_path exist first (one-time):
psql "host=10.200.37.142 dbname=rafms_db user=postgres password=postgres" -c \
  "CREATE SCHEMA IF NOT EXISTS administration; ALTER DATABASE rafms_db SET search_path TO administration, public;"
alembic upgrade head      # creates the 10 tables in administration
python -m app.seed        # roles + demo users + decoders + config + alerts
```

### Option B — Raw SQL scripts (for DBAs / manual provisioning)
```bash
psql "host=10.200.37.142 port=5432 dbname=rafms_db user=postgres password=postgres" \
     -f scripts/sql/001_app_schema.sql      # schema + 10 tables + indexes + triggers
psql "host=10.200.37.142 port=5432 dbname=rafms_db user=postgres password=postgres" \
     -f scripts/sql/002_seed_reference.sql  # roles, system config, decoders, alerts
# Then, so Alembic knows the schema already exists:
alembic stamp head
# And create at least one login (SQL cannot hash passwords):
python -m app.seed        # adds demo users (idempotent)
```

> **Do not run both A and B fully** — they create the same tables. If you ran
> the SQL, use `alembic stamp head` (not `upgrade`) so Alembic just records the
> current revision without re-running DDL.

The CREATE scripts live in:
- [`scripts/sql/001_app_schema.sql`](../scripts/sql/001_app_schema.sql) — schema, 10 tables, indexes, optional `updated_at` triggers
- [`scripts/sql/002_seed_reference.sql`](../scripts/sql/002_seed_reference.sql) — roles, config, decoders, alerts

---

## 4. Conventions & "required things"

- **Types:** `timestamptz` for all timestamps (UTC), `jsonb` for permission
  matrices / configs / params, `bigint` for `reports.size_bytes`,
  `double precision` for `cases.estimated_impact`. UUID PKs are `varchar(36)`
  (generated in Python); slug PKs (`roles`, `decoders`, `system_config`) are short text.
- **Constraint naming** (matches Alembic): `pk_<table>`, `fk_<table>_<col>_<reftable>`,
  `ix_<col>` / unique `ix_<col>`. Keeps migrations diff-clean.
- **Indexes:** unique on every `reference`/`email`; lookup indexes on
  `users.role_id`, `cases.status`, `reports.status`, `audit_logs.actor/at`.
- **Extensions:** `pgcrypto` only if you want DB-side UUIDs (optional — the app
  generates them). No other extensions required.
- **`updated_at`:** maintained by the ORM on every update; the SQL script also
  installs a defensive trigger for direct-SQL writes.
- **`system_config`:** a single row with `id='system'`; the app auto-creates it
  on first read if missing.
- **Privileges (least privilege, recommended for prod):**
  ```sql
  CREATE ROLE radonaix_app LOGIN PASSWORD '****';
  GRANT USAGE ON SCHEMA administration TO radonaix_app;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA administration TO radonaix_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA administration
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO radonaix_app;
  ```
  Then point `APP_DB_USER`/`APP_DB_PASSWORD` at `radonaix_app` instead of `postgres`.

---

## 5. Sizing & growth notes

- 9 of the 10 tables are low-volume (operational/config/workflow): users, roles,
  cases, comments, decoders, config, alerts, saved queries, reports — typically
  thousands to low-millions of rows. Default Postgres settings are ample.
- `audit_logs` is the only continuously-growing table. Add a retention job (or
  monthly `PARTITION BY RANGE (at)`) if you expect heavy audit volume; the
  `retention_days` config (default 365) is the intended driver.
- Large recon datasets are **not** here — they remain in ClickHouse, which is
  built for that scale. This database stays small and fast.
