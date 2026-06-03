# syntax=docker/dockerfile:1.7
# --- Builder: resolve dependencies with uv into a venv -------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv from PyPI (avoids ghcr.io, which some corporate TLS proxies block).
# No apt needed: all dependencies ship prebuilt linux wheels, so there is no
# compiler/system-lib requirement at build time.
RUN pip install --no-cache-dir uv

# Layer-cache dependency install separately from app code.
COPY pyproject.toml ./
RUN uv venv /opt/venv && \
    VIRTUAL_ENV=/opt/venv uv pip install -r pyproject.toml

COPY . .
RUN VIRTUAL_ENV=/opt/venv uv pip install --no-deps .

# --- Runtime: slim image, non-root -----------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# No apt needed: psycopg2-binary bundles libpq; the healthcheck uses Python.
# Create a home dir for the app user (gunicorn's control server writes to $HOME).
RUN groupadd -r app && useradd -r -g app -m -d /home/app app \
    && mkdir -p /var/lib/radonaix/reports && chown -R app:app /var/lib/radonaix /home/app
ENV HOME=/home/app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
RUN chmod +x /app/docker-entrypoint.sh && chown -R app:app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=4).status==200 else 1)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Default: API server. Override command for the worker (see docker-compose).
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-"]
