#!/usr/bin/env bash
# Entrypoint helper: wait for the app DB, run migrations, optionally seed,
# then exec the given command (API server or worker).
set -euo pipefail

echo "[entrypoint] waiting for app database at ${APP_DB_HOST:-postgres}:${APP_DB_PORT:-5432} ..."
python - <<'PY'
import os, time, socket
host = os.getenv("APP_DB_HOST", "postgres")
port = int(os.getenv("APP_DB_PORT", "5432"))
for _ in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print("[entrypoint] database is reachable")
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("[entrypoint] database not reachable in time")
PY

if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
    echo "[entrypoint] running migrations ..."
    alembic upgrade head
fi

if [[ "${RUN_SEED:-false}" == "true" ]]; then
    echo "[entrypoint] seeding database ..."
    python -m app.seed
fi

exec "$@"
