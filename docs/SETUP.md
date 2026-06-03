# Setup Guide — RADONAIX Revenue Assurance Backend

A step-by-step guide to install and run this backend on a **new server or computer**,
written in plain language. No prior experience with this project is assumed.

If anything here conflicts with [DATABASE.md](DATABASE.md), this guide wins for setup steps.

---

## 1. What is this, in one paragraph

This is the **backend** (the "engine") for the RADONAIX Revenue Assurance platform.
It's a web service written in Python (FastAPI) that the user interface (a separate
project called `radon-ai-vision`) talks to. It stores its data in a **PostgreSQL**
database, uses **Redis** for background jobs, and can optionally read reconciliation
data from a **ClickHouse** database. You talk to it over HTTP at `/api/...`.

You have **two ways** to run it:

| Path | Best for | What you install |
|---|---|---|
| **A. Docker** (recommended) | Getting it running fast; servers | Just Docker. Everything else (Python, Postgres, Redis) runs inside containers automatically. |
| **B. Manual / native** | Development, or machines without Docker | Python, PostgreSQL, and Redis installed directly on the machine. |

Pick **one**. If you're unsure, choose **Path A (Docker)**.

---

## 2. Before you start (both paths)

You need:

1. **The code.** Get it from GitHub (see step 3).
2. **Network access** to GitHub and the Python package index (PyPI). If you're on a
   corporate network with a security proxy, read [section 8](#8-corporate-network--proxy-notes) first — it matters.
3. About **2 GB free disk** and **2 GB RAM**.

You do **not** need the company VPN or ClickHouse to get a working backend — those are
optional and can be added later. Without ClickHouse, the dashboard/KPI screens simply
show placeholder numbers instead of live reconciliation data.

---

## 3. Get the code

Open a terminal and run **one** of these:

**Using SSH (if you've added an SSH key to GitHub):**
```bash
git clone git@github.com:RADONAIX/ra_backend.git
cd ra_backend
```

**Using HTTPS (it will ask for your GitHub username + a Personal Access Token):**
```bash
git clone https://github.com/RADONAIX/ra_backend.git
cd ra_backend
```

Everything below assumes you are **inside the `ra_backend` folder**.

---

## 4. Configure it (both paths)

The backend reads its settings from a file named `.env`. There's a template called
`.env.example`. Make your own copy:

```bash
cp .env.example .env
```

Now open `.env` in a text editor and review these settings. **Plain-English meaning:**

| Setting | What it means | What to put |
|---|---|---|
| `JWT_SECRET` | Secret key used to sign login tokens. | **Change this** to a long random string. Generate one with: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | The first admin login created automatically. | Set an email and a strong password you'll remember. |
| `DEMO_PASSWORD` | Password for the sample non-admin users. | Any value (or ignore if you don't want demo users). |
| `APP_DB_HOST` / `APP_DB_PORT` | Where the PostgreSQL database is. | **Path A:** leave as is (Docker fills it in). **Path B:** `localhost` and your Postgres port. |
| `APP_DB_NAME` | The database name. | `rafms_db` (or your choice). |
| `APP_DB_USER` / `APP_DB_PASSWORD` | Database login. | Your Postgres username/password. |
| `APP_DB_SCHEMA` | The "folder" inside the database for our tables. | `administration` (leave as is). |
| `REDIS_URL`, `CELERY_*` | Where Redis is. | **Path A:** leave as is. **Path B:** match your Redis port. |
| `CLICKHOUSE_ENABLED` | Turn live reconciliation data on/off. | `false` if you're not using ClickHouse yet. |
| `RA_PG_ENABLED`, `AIRFLOW_ENABLED` | Other optional integrations. | `false` for a basic setup. |

> **Important:** never commit your real `.env` to git. It's already ignored, so you're safe.

---

## 5. Path A — Run with Docker (recommended)

### 5.1 Install Docker
- **Linux server:** install Docker Engine + the Compose plugin (follow the official
  Docker docs for your distro). Confirm it works: `docker version` and `docker compose version`.
- **Mac/Windows:** install **Docker Desktop**, open it once so it finishes setup, then
  confirm `docker version` works in a terminal.

### 5.2 Start everything
From inside the `ra_backend` folder:
```bash
docker compose up -d --build
```
This single command:
1. Builds the backend image,
2. Starts **4 containers**: the API, a background worker, PostgreSQL, and Redis,
3. **Automatically** creates the database tables and loads the starter data
   (roles + the admin user).

The first run takes a few minutes (it downloads images). Later runs are fast.

### 5.3 Check it's working
```bash
docker compose ps                # all should say "healthy" or "Up"
curl http://localhost:8000/api/health
```
You should see: `{"status":"ok",...}`. 

Open **http://localhost:8000/docs** in a browser for the full interactive API.

### 5.4 Everyday Docker commands
```bash
docker compose logs -f api       # watch the API logs (Ctrl-C to stop watching)
docker compose stop              # pause everything (keeps data)
docker compose start             # resume
docker compose down              # stop and remove containers (KEEPS data volume)
docker compose down -v           # stop and ERASE the database too (fresh start)
docker compose up -d --build     # rebuild after you change the code
```

> **Note on ports:** the bundled Postgres is published on host port **5433** (not 5432)
> to avoid clashing with any Postgres already on the machine. The app itself talks to
> Postgres internally, so this only matters if you want to connect to the DB from
> outside Docker (`psql -h localhost -p 5433`).

**That's it for Path A.** Skip to [section 7](#7-connect-the-user-interface).

---

## 6. Path B — Run manually (without Docker)

Use this on a machine where you don't want Docker. You'll install three things:
Python, PostgreSQL, and Redis.

### 6.1 Install the prerequisites

**On a Mac (using Homebrew):**
```bash
brew install python@3.12 postgresql@16 redis
brew services start postgresql@16
brew services start redis
```

**On a Linux server (Debian/Ubuntu):**
```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv postgresql redis-server
sudo systemctl enable --now postgresql redis-server
```

> We also use **uv**, a fast Python installer. Install it with:
> `pip install uv`  (or `pipx install uv`).

### 6.2 Create the database and a login

Create a database named `rafms_db` and a user the app will use. Example (adjust names
to match your `.env`):
```bash
# Connect to Postgres as an admin and run:
createdb rafms_db
psql -d rafms_db -c "CREATE USER postgres WITH LOGIN SUPERUSER PASSWORD 'postgres';"
```
> On a real server, use a **non-superuser** with a strong password and grant it rights
> on the `administration` schema (see DATABASE.md → Privileges). For a quick test, the
> above is fine.

Make sure `.env` matches: `APP_DB_HOST=localhost`, the right `APP_DB_PORT`
(Postgres default is `5432`), `APP_DB_NAME=rafms_db`, and your user/password.

> **If port 5432 is already taken** (another Postgres is running), run yours on a
> different port (e.g. 5434) and set `APP_DB_PORT=5434` in `.env`. The same idea applies
> to Redis (default 6379) — if taken, use another port and update `REDIS_URL` and the
> `CELERY_*` lines.

### 6.3 Install the Python dependencies
```bash
uv venv                       # creates a .venv folder
uv pip install -e ".[dev]"    # installs everything the app needs
```

### 6.4 Create the tables and starter data
```bash
source .venv/bin/activate
alembic upgrade head          # creates the 'administration' schema + 10 tables
python -m app.seed            # creates roles + the admin user + sample data
```

### 6.5 Run the backend
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000          # or: make run
```
Leave that running. In a **second terminal** (only needed for report generation):
```bash
source .venv/bin/activate
make worker
```

### 6.6 Check it's working
```bash
curl http://localhost:8000/api/health
```
Expect `{"status":"ok",...}`. Browse **http://localhost:8000/docs**.

---

## 7. Connect the user interface

The UI (`radon-ai-vision`) needs to know where this backend lives. In the UI project,
set its environment file:
```
VITE_API_BASE_URL=http://<server-address>:8000/api
```
- Running both on the same machine → `http://localhost:8000/api`.
- Backend on a server → use that server's address, e.g. `http://10.0.0.5:8000/api`.

Then log in with the admin email/password you set in `.env`
(default `admin@radonaix.io` / `ChangeMe!123` if you didn't change it).

If the UI is served from a different web address, add that address to `CORS_ORIGINS`
in `.env` (comma-separated) so the browser is allowed to call the backend.

---

## 8. Corporate network / proxy notes

Some company networks run a security proxy that inspects encrypted traffic. This can
break downloads inside Docker even when your normal browser works. We've already made
the build resilient, but if you hit errors:

- **`x509: certificate signed by unknown authority`** when building → the proxy is
  intercepting a download. Our Dockerfile already avoids the usual culprit (`ghcr.io`)
  by installing tools from PyPI instead. If you still see this, ask IT for the
  corporate **root CA certificate** and have it added to the Docker build, or build on
  a network without the proxy.
- **`403 Forbidden` from `deb.debian.org`** → the proxy blocks the Linux package repo.
  Our image is built to **not** need those packages, so a clean rebuild
  (`docker compose build --no-cache`) should pass.
- **Manual (Path B) installs failing to download** → make sure `pip`/`uv` and your OS
  package manager are configured to use the corporate proxy/CA.

---

## 9. Common problems and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `docker: command not found` (Mac) | Docker Desktop installed but not on PATH | Open Docker Desktop once; or add `/Applications/Docker.app/Contents/Resources/bin` to your PATH. |
| `port is already allocated` / `address already in use` | Something already uses 8000, 5432, or 6379 | Stop the other program, or change the port in `docker-compose.yml` / `.env`. |
| `relation "roles" does not exist` | Tables weren't created | Run the migration: Path A is automatic; Path B run `alembic upgrade head`. |
| `password authentication failed` | DB user/password in `.env` don't match Postgres | Fix the `APP_DB_*` values, or reset the Postgres user's password. |
| API starts but `/pipelines/kpis` shows placeholder numbers | ClickHouse is off/unreachable | Expected when `CLICKHOUSE_ENABLED=false`. Turn it on and set `CLICKHOUSE_HOST` when ready. |
| `401 Unauthorized` on most endpoints | No/!invalid login token | Log in via `/api/auth/login` and send the returned token as `Authorization: Bearer <token>`. |
| Login fails for a user | Account disabled, or wrong password | Check the user's `status`; re-run `python -m app.seed` to recreate demo users. |

To see what went wrong, always check the logs:
- Docker: `docker compose logs api`
- Manual: look at the terminal where `uvicorn` is running.

---

## 10. Going to production (checklist)

For a real deployment (not just a test), do these:

1. **Change all secrets** in `.env`: a strong random `JWT_SECRET`, a real
   `BOOTSTRAP_ADMIN_PASSWORD`, and a strong database password.
2. **Use a managed/strong PostgreSQL** with a non-superuser app account (see DATABASE.md).
3. **Set `ENVIRONMENT=production`** and `DEBUG=false`.
4. **Put it behind HTTPS** — run a reverse proxy (Nginx/Caddy/Traefik or a cloud load
   balancer) in front of the API on port 8000, terminating TLS.
5. **Restrict `CORS_ORIGINS`** to only your real UI address (no `*`).
6. **Back up the database** regularly (just the one app database, `rafms_db`).
7. **Watch health & metrics:** `GET /api/health/ready` for readiness, and `/metrics`
   for Prometheus monitoring.
8. **Run multiple API workers** (the Docker image already runs 4 via gunicorn) and at
   least one background worker for reports.

---

## 11. Quick reference card

```bash
# --- Docker (Path A) ---
docker compose up -d --build      # build + start everything
docker compose ps                 # status
docker compose logs -f api        # logs
docker compose down               # stop (keeps data)

# --- Manual (Path B) ---
source .venv/bin/activate
alembic upgrade head              # create/upgrade tables
python -m app.seed                # load roles + admin user
make run                          # start the API (port 8000)
make worker                       # start the background worker

# --- Check it's alive (either path) ---
curl http://localhost:8000/api/health
# Browse the full API:  http://localhost:8000/docs
```

**Default login:** `admin@radonaix.io` / the password in your `.env`
(`ChangeMe!123` if unchanged — change it!).
