# RADONAIX Backend — Production Deployment

Two supported tracks; pick one based on whether the client allows Docker:
- **Track A — Docker Compose** (recommended; self-contained)
- **Track B — bare VM + systemd** (no Docker)

Default deployment is **API-only** (`EXPORTS_ENABLED=false`), **single HTTPS origin**
(nginx serves the built UI *and* proxies `/api` — no separate `:8080`/`:8000`, no CORS):

```
            ┌──────────────── nginx (TLS :443) ─────────────────┐
client ───▶ │  https://10.200.36.156/       → built UI (static) │
            │  https://10.200.36.156/api/   → gunicorn :8000     │
            └───────────────────────────────────────────────────┘
                 api (gunicorn)
                        │
                 app DB (Postgres, administration schema)
                        │
   external read-only:  ClickHouse · ra_postgres · bi_postgres  (the ra-platform)

   (optional, only when EXPORTS_ENABLED=true:  Redis + worker (celery) for /exports)
```

> The bulk-export feature (`/exports`) is **off by default** (`EXPORTS_ENABLED=false`)
> → those routes return `503` and **no Redis/worker is needed**. Run only `api`
> (+ nginx + app DB). To turn exports on later, see "Enable bulk exports" below.
> Airflow is optional too (`AIRFLOW_ENABLED=false`) — pipeline retry/replay actions
> simply no-op when it's off.

---

## 0. Shared prerequisites (both tracks)

1. **VM**: Linux, ≥2 vCPU / 4 GB. Open **80 + 443** to the world; keep **8000 / 5433 / 6379 closed** (firewall).
2. **`.env`**: copy `deploy/.env.prod.example` → **`.env` at the backend root** (the app, compose `env_file`, and systemd all read `<backend>/.env` — not `deploy/.env`). Fill it in. Critical:
   - `EXPORTS_ENABLED=false` for an API-only deploy (default). Set `true` only after Redis + the worker are running.
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

# API-only (default, EXPORTS_ENABLED=false) — start only what's needed.
# First boot seeds the admin user:
RUN_SEED=true docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api postgres nginx

# Subsequent starts / after a pull:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api postgres nginx
```

What this runs: `api` (gunicorn, tuned), `postgres`, `nginx`. (Redis may start idle
because `api` declares `depends_on: redis`; that's harmless — the worker is not
started, and `/exports` returns 503.) Migrations run automatically on boot
(entrypoint → `alembic upgrade head`).

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

# 3) Services — API-only (default). The worker unit is only needed for exports.
sudo cp deploy/systemd/radonaix-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radonaix-api
sudo systemctl status radonaix-api
# (No Redis required for API-only — you can skip installing redis-server above.)

# 4) nginx (TLS) — upstream is 127.0.0.1:8000 (default in the conf)
sudo mkdir -p /etc/nginx/certs   # place radonaix.crt + radonaix.key here
sudo cp deploy/nginx/radonaix.conf /etc/nginx/sites-available/radonaix
sudo ln -sf /etc/nginx/sites-available/radonaix /etc/nginx/sites-enabled/radonaix
sudo nginx -t && sudo systemctl reload nginx
```

Logs: `journalctl -u radonaix-api -f` / `journalctl -u radonaix-worker -f`.
Tune workers: edit `Environment=WEB_CONCURRENCY=` (API) / `--concurrency=` (worker) → `daemon-reload` + restart.

---

## Enable bulk exports later (optional)

The `/exports` module (async million-row report downloads) is off by default. To turn it on:
1. Set `EXPORTS_ENABLED=true` in `.env`, and ensure `REDIS_URL` / `CELERY_*` point at a reachable Redis.
2. Run **Redis** + the **Celery worker**:
   - **Docker**: include all services — `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (adds `worker` + `redis`).
   - **Bare VM**: `sudo apt install -y redis-server && sudo systemctl enable --now redis-server`; then `sudo cp deploy/systemd/radonaix-worker.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now radonaix-worker`.
3. Restart the API so it picks up the flag. `/exports` now serves jobs instead of 503.

---

## 3. TLS (self-signed — internal / IP deployment)

This is an internal deployment (no public domain → Let's Encrypt isn't an option), so
use a **self-signed** cert. Generate it with the helper (CN/SAN = host or IP):

```bash
# Bare VM (writes to /etc/nginx/certs):
sudo make tls-selfsigned                      # defaults to 10.200.36.156
#   or: sudo bash deploy/gen-selfsigned-cert.sh <host-or-ip> /etc/nginx/certs
sudo nginx -t && sudo systemctl reload nginx

# Docker (writes into the mounted certs dir):
make tls-selfsigned OUT=deploy/nginx/certs
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

The conf's `server_name` is `10.200.36.156` and it reads `radonaix.crt` + `radonaix.key`
from `/etc/nginx/certs` (bare VM) / the mounted `deploy/nginx/certs` (Docker). Browsers show
a one-time "not secure" warning for self-signed certs — accept it, or distribute
`radonaix.crt` for clients to trust.

**Have a public domain instead?** `sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d <domain>` (free, trusted, auto-renews).

> The UI is served by the **same** nginx (next section) → single origin, so the UI calls
> the API with **relative** paths and CORS is a non-issue.

---

## 3b. Serve the UI (single HTTPS origin)

nginx (`deploy/nginx/radonaix.conf`) serves the **built UI** at `/` and proxies `/api/` to
the backend — so the browser only ever talks to `https://10.200.36.156`.

**1) Build the UI** (in the `radon-ai-vision` repo). Because it's same-origin, point the
build at **relative** API bases — no host, no port:
```bash
# radon-ai-vision/.env  (build-time; Vite bakes these in)
VITE_API_BASE_URL=/api
VITE_AUTH_API_BASE=
VITE_PIPELINES_API_BASE=
```
```bash
npm ci && npm run build      # produces dist/
```

**2) Deploy the build** where nginx's `root` points (`/var/www/radonaix`):
```bash
# Bare VM:
sudo mkdir -p /var/www/radonaix
sudo rsync -a --delete dist/ /var/www/radonaix/
sudo nginx -t && sudo systemctl reload nginx

# Docker: mount the build into the nginx service, e.g. add under its `volumes:`
#   - /path/to/radon-ai-vision/dist:/var/www/radonaix:ro
# and set the conf upstream to `server api:8000;`
```

**3) CORS** — with a single origin you can drop the cross-origin allowance entirely, or
just set `CORS_ORIGINS=https://10.200.36.156` to be safe. No `:3000`/`:8080` anywhere.

Now `https://10.200.36.156` loads the app; its `/api/...` calls are proxied to gunicorn.
Re-run `npm run build` + redeploy `dist/` whenever the UI changes.

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
