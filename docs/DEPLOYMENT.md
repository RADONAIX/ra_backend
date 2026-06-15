# RADONAIX Backend — Production Deployment

Two supported tracks; pick one based on whether the client allows Docker:
- **Track A — Docker Compose** (recommended; self-contained)
- **Track B — bare VM + systemd** (no Docker)

Both run the **same three processes** plus a TLS proxy:

```
            ┌─────────── nginx (TLS :443) ───────────┐
client ───▶ │  https://ra.example.com  →  api :8000   │
            └────────────────────────────────────────┘
                 api (gunicorn)        worker (celery)
                        │                     │
                        └──────── Redis ──────┘         (broker for /exports jobs)
                        │
                 app DB (Postgres, administration schema)
                        │
   external read-only:  ClickHouse · ra_postgres · bi_postgres  (the ra-platform)
```

> ⚠️ The **worker + Redis are mandatory** — the bulk-export feature (`/exports`) queues
> jobs through Redis; without the worker, jobs stay `Queued` forever. Running only
> `gunicorn` is **not** a complete deployment.

---

## 0. Shared prerequisites (both tracks)

1. **VM**: Linux, ≥2 vCPU / 4 GB. Open **80 + 443** to the world; keep **8000 / 5433 / 6379 closed** (firewall).
2. **`.env`**: copy `deploy/.env.prod.example` → `.env` and fill it in. Critical:
   - Generate a real secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"` → `JWT_SECRET`.
   - Change `BOOTSTRAP_ADMIN_PASSWORD`.
   - `ENVIRONMENT=production`, `DEBUG=false`.
   - `CORS_ORIGINS=https://<your UI origin>` (no `*`).
   - Point the **external** read-only sources (`CLICKHOUSE_*`, `RA_PG_*`, `RA_BI_PG_*`) at the client network.
   > The app **refuses to start** in production if `JWT_SECRET` is a default/<32 chars or
   > `BOOTSTRAP_ADMIN_PASSWORD` is the default — this is intentional.
3. **App database** — choose one:
   - *Bundled* (default): the compose/`docker` Postgres, or a locally-installed Postgres.
   - *External managed DB*: set `APP_DB_HOST/PORT/NAME/USER/PASSWORD`; for Docker, drop the `postgres` service from the compose command.
4. **TLS cert**: a client-provided cert, or Let's Encrypt (`certbot`). See §3.

---

## Track A — Docker Compose

```bash
cd /opt/radonaix/backend                 # repo checkout
cp deploy/.env.prod.example .env         # then edit (see §0.2)

# Docker nginx: set the upstream in deploy/nginx/radonaix.conf to:  server api:8000;
# Put TLS cert/key in deploy/nginx/certs/  (radonaix.crt, radonaix.key)

# First boot (seeds the admin user):
RUN_SEED=true docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Subsequent starts / after a pull:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

What this runs: `api` (gunicorn, tuned), `worker` (celery), `postgres`, `redis`, `nginx`.
Migrations run automatically on boot (entrypoint → `alembic upgrade head`).

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps     # status
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker
```

**External app DB instead of the bundled one**: remove `postgres` from the `up` (or add a
`docker-compose.prod.yml` entry setting `api.depends_on` without postgres) and set
`APP_DB_HOST` in `.env` to the managed DB. Keep `RUN_MIGRATIONS=true` so the schema is applied.

---

## Track B — bare VM + systemd (no Docker)

```bash
# 1) System packages
sudo apt update && sudo apt install -y python3.12 python3.12-venv redis-server nginx
sudo systemctl enable --now redis-server

# 2) App user + code
sudo useradd -r -m -d /opt/radonaix radonaix
sudo mkdir -p /opt/radonaix/backend /var/lib/radonaix/reports
sudo chown -R radonaix:radonaix /opt/radonaix /var/lib/radonaix
# deploy the repo to /opt/radonaix/backend (git clone / rsync), then as `radonaix`:

sudo -u radonaix bash -lc '
  cd /opt/radonaix/backend
  python3.12 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  cp deploy/.env.prod.example .env          # then edit (see §0.2)
  set -a; . ./.env; set +a
  .venv/bin/alembic upgrade head            # create/upgrade schema
  .venv/bin/python -m app.seed              # seed admin (first time only)
'

# 3) Services
sudo cp deploy/systemd/radonaix-api.service deploy/systemd/radonaix-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radonaix-api radonaix-worker
sudo systemctl status radonaix-api radonaix-worker

# 4) nginx (TLS) — upstream is 127.0.0.1:8000 (default in the conf)
sudo mkdir -p /etc/nginx/certs   # place radonaix.crt + radonaix.key here
sudo cp deploy/nginx/radonaix.conf /etc/nginx/sites-available/radonaix
sudo ln -sf /etc/nginx/sites-available/radonaix /etc/nginx/sites-enabled/radonaix
sudo nginx -t && sudo systemctl reload nginx
```

Logs: `journalctl -u radonaix-api -f` / `journalctl -u radonaix-worker -f`.
Tune workers: edit `Environment=WEB_CONCURRENCY=` (API) / `--concurrency=` (worker) → `daemon-reload` + restart.

---

## 3. TLS

- **Client cert**: drop `radonaix.crt` + `radonaix.key` where the conf expects them
  (Docker: `deploy/nginx/certs/`; bare VM: `/etc/nginx/certs/`).
- **Let's Encrypt** (bare VM): `sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d ra.example.com` — it edits the conf + auto-renews.

---

## 4. Smoke test (after either track)

```bash
curl -k https://<host>/api/health                      # {"status":"ok",...}
# log in, then create an export and watch it run end-to-end:
TOKEN=$(curl -ks https://<host>/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@radonaix.io","password":"<your prod pwd>"}' | jq -r .token)
curl -ks https://<host>/api/exports -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reportKey":"air_reconciliation","dateFrom":"2026-05-01","dateTo":"2026-05-31"}'
# poll GET /api/exports/{id} until status=Completed, then GET /api/exports/{id}/download
```
Negative test (proves the fail-fast): start with a default `JWT_SECRET` under `ENVIRONMENT=production` → the app exits with "Refusing to start … insecure configuration".

---

## 5. Upgrade & rollback

- **Docker**: `git pull` → `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (entrypoint re-runs migrations). Rollback: `git checkout <prev>` + same `up`; DB rollback via `alembic downgrade -1`.
- **Bare VM**: `git pull` → `.venv/bin/pip install -r requirements.txt` → `alembic upgrade head` → `systemctl restart radonaix-api radonaix-worker`. Rollback symmetrically (`alembic downgrade -1`, checkout previous, restart).

---

## Out of scope (plan separately)
CI/CD pipeline + image registry, secrets vault, horizontal autoscaling / multiple worker nodes,
S3/object-storage for exports (Phase 2), and the observability stack (Sentry/OpenTelemetry) —
see `docs/PRODUCTION_READINESS.md`.
