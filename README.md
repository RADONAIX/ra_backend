# RADONAIX — Revenue Assurance Backend

Production-grade **FastAPI** backend for the RADONAIX Telecom Revenue Assurance
platform. Built as a **modular monolith** (clean bounded-context modules,
microservice-ready) that serves the Lovable UI (`radon-ai-vision`) and
integrates read-only with the existing **ra-platform** data pipeline
(Airflow → ClickHouse → Postgres).

> This repository is intended to live in its **own** GitHub repo, separate from
> the UI. See [Pushing to a new repo](#pushing-to-a-new-github-repo).

> 📦 **Setting this up on a new server or machine?** Follow the plain-language,
> step-by-step **[Setup Guide](docs/SETUP.md)** (Docker and manual paths).
> Database schema details are in **[docs/DATABASE.md](docs/DATABASE.md)**.

---

## Architecture

```
                       ┌─────────────────────────────┐
  radon-ai-vision UI ─▶│  FastAPI (this service)     │
  (axios, JWT bearer)  │  /api/* under one app       │
                       │                             │
                       │  modules/                   │
                       │   ├─ identity   auth/users/roles/audit
                       │   ├─ operations pipelines/decoders/config
                       │   ├─ assurance  recon/cases/workbench
                       │   ├─ reporting  certified exports (Celery)
                       │   └─ meta       health/readiness/dashboard
                       └───────┬─────────┬───────────┘
        owns (read/write)      │         │      read-only integrations
        ┌──────────────────────┘         └───────────────────────────┐
   ┌────▼─────┐   ┌───────┐                ┌──────────────┐   ┌───────▼──────┐
   │ Postgres │   │ Redis │                │ ClickHouse   │   │ ra-platform  │
   │ app data │   │ cache │                │ rafms recon  │   │ Postgres /   │
   │          │   │+broker│                │ (read-only)  │   │ Airflow REST │
   └──────────┘   └───┬───┘                └──────────────┘   └──────────────┘
                      │
                 ┌────▼─────┐
                 │ Celery   │  report generation, future events
                 │ worker   │
                 └──────────┘
```

**Design decisions** (see also the project memory):
- **Modular monolith first** — one deployable, strict module boundaries.
- **REST + Redis** now (cache + Celery jobs); event bus deferrable behind an interface.
- **New app Postgres** owns users/roles/cases/reports/audit. ra-platform's
  ClickHouse and Postgres are read **read-only**; the recon engine is never duplicated.
- **Docker Compose** for deploy-anywhere.

---

## Tech stack

| Concern | Choice |
|---|---|
| Runtime | Python 3.12, FastAPI, Uvicorn/Gunicorn |
| Packaging | `uv` + `pyproject.toml` |
| Data | PostgreSQL, SQLAlchemy 2.0 (async), Alembic |
| Async/jobs | Redis, Celery |
| Analytics read | ClickHouse (`clickhouse-connect`) |
| Auth | JWT (PyJWT) + **Argon2id** (bcrypt verify-only, see [SECURITY.md](SECURITY.md)), RBAC matrix |
| Observability | structlog (JSON), Prometheus `/metrics`, `/api/health[/ready]` |

---

## Quickstart (Docker Compose)

```bash
cp .env.example .env          # then edit JWT_SECRET and passwords
docker compose up -d --build  # starts api, worker, postgres, redis
# migrations + seed run automatically (RUN_MIGRATIONS / RUN_SEED in compose)
```

- API:        http://localhost:8000/api
- Swagger UI:  http://localhost:8000/docs
- Metrics:     http://localhost:8000/metrics

Point the UI at it via `ui/radon-ai-vision/.env`:
```
VITE_API_BASE_URL=http://localhost:8000/api
```

### Demo accounts (seeded)
| Email | Role | Password |
|---|---|---|
| admin@radonaix.io | admin | `BOOTSTRAP_ADMIN_PASSWORD` (default `ChangeMe!123`) |
| admin@radonaix.io | ra_lead | `DEMO_PASSWORD` (default `ChangeMe!123`) |
| priya.shah@radonaix.io | analyst | `DEMO_PASSWORD` |
| viewer@radonaix.io | viewer | `DEMO_PASSWORD` |

> Change these before any non-local deployment.

---

## Local development (without Docker)

```bash
make install         # uv venv + deps (incl. dev)
# bring up Postgres + Redis however you like, set .env accordingly
make migrate         # alembic upgrade head
make seed            # roles/users/decoders/config/alerts
make run             # uvicorn with reload  → http://localhost:8000
make worker          # in another shell, the Celery worker (REQUIRED for bulk exports)
make test            # pytest
make lint            # ruff
```

**Bulk exports** (`/exports`): `POST /exports` with `{reportKey, dateFrom, dateTo}`
enqueues a Celery job that streams the (date-filtered) report to a gzipped CSV
under `REPORTS_DIR`, tracking `progressPct` on the job row (poll `GET /exports/{id}`);
`GET /exports/{id}/download` serves it when complete. `POST /exports/kpis` returns
aggregate KPIs for a selection synchronously (no download). **Requires Redis + a
running worker** (`make worker`). Chunked streaming keeps worker memory flat even
for millions of rows.

---

## API surface (consumed by the UI)

All routes are under `/api`. Protected routes require `Authorization: Bearer <jwt>`.

| Module | Method & Path | Purpose |
|---|---|---|
| identity | `POST /auth/login` · `GET /auth/me` | login, current user |
| identity | `GET/POST /users` · `PATCH /users/{id}` | user management |
| identity | `GET/POST /roles` · `PUT /roles/{id}/permissions` | roles + RBAC matrix |
| identity | `GET /audit-logs` | audit trail |
| operations | `GET /pipelines/{stages,kpis,runs,alerts,retries}` | pipeline monitor |
| operations | `POST /pipelines/jobs/{id}/{retry,replay}` · `POST /pipelines/alerts/{id}/ack` | actions |
| operations | `GET/POST /decoders` · `GET/PUT /system/config` | settings |
| assurance | `GET /recon/summary` · `GET /recon/records` | reconciliation reads (ClickHouse) |
| assurance | `GET/POST /cases` · `GET/PATCH /cases/{id}` · `POST /cases/{id}/comments` | case management |
| assurance | `GET/POST /workbench/queries` · `GET /workbench/stats` | investigation workbench |
| reporting | `GET/POST /reports` · `GET /reports/{ref}/download` | certified exports |
| exports | `POST /exports` · `GET /exports[/{id}]` · `GET /exports/{id}/download` · `DELETE /exports/{id}` · `POST /exports/kpis` | bulk async report downloads + KPI preview |
| meta | `GET /health` · `GET /health/ready` · `GET /dashboard/kpis` | ops + headline KPIs |

The dashboard's main analytics are an **embedded Superset iframe** in the UI,
so heavy charting is not served here — this backend provides operational data,
auth, RBAC, cases, reports and headline KPIs.

---

## ra-platform integration

Read-only, all optional (toggled by env). When disabled or unreachable, the
relevant endpoints degrade gracefully (representative data + a logged warning)
so the UI stays functional offline.

- **ClickHouse** (`rafms`): `air_reconciliation`, `reconciliation_run_log` drive
  recon summaries, KPIs, run history and certified report contents.
- **ra-platform Postgres** (`rafms`): `file_log` / batch status (file processing).
- **Airflow REST**: triggers `air_pipeline_dag` / `air_recon_dag` for retry/replay.

---

## Project structure

```
app/
  core/         config, logging, security, database, redis, rbac, deps, errors, middleware
  integrations/ clickhouse, ra_postgres, airflow  (read-only / control)
  modules/
    identity/   auth, users, roles, audit
    operations/ pipelines, decoders, system config
    assurance/  reconciliation reads, cases, workbench
    reporting/  certified report generation
    meta/       health, readiness, dashboard KPIs
  workers/      celery app + tasks (report generation)
  api.py        router aggregator
  main.py       app factory
migrations/     alembic
tests/
```

---

## Configuration

Every setting is environment-driven — see [`.env.example`](.env.example) for the
full annotated list. Key ones: `JWT_SECRET`, `APP_DB_*`, `REDIS_URL`,
`CELERY_*`, `CLICKHOUSE_*`, `RA_PG_*`, `AIRFLOW_*`, `REPORTS_DIR`.

---

## Pushing to a new GitHub repo

This backend is a standalone repo. After creating an empty repo on GitHub:

```bash
cd backend
git init -b main
git add .
git commit -m "feat: initial Revenue Assurance FastAPI backend"
git remote add origin https://github.com/<you>/<backend-repo>.git
git push -u origin main
```

`.env` is gitignored — only `.env.example` is committed.
