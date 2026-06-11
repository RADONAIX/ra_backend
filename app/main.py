"""FastAPI application factory.

Modular monolith: every bounded-context module is mounted under the API
prefix via ``app.api.api_router``. Designed to split into independent services
later without changing module internals.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

# Import the models aggregate so every table is registered on Base.metadata.
import app.models  # noqa: F401
from app.api import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.integrations_shutdown import close_all_integrations
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware

configure_logging(level=settings.log_level, json_logs=settings.log_json)
log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info(
        "startup",
        environment=settings.environment,
        clickhouse=settings.clickhouse_enabled,
        ra_postgres=settings.ra_pg_enabled,
        airflow=settings.airflow_enabled,
    )
    yield
    await close_all_integrations()
    await engine.dispose()
    log.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Innermost: per-IP rate limit on login (returns 429 before the handler).
    # Added first so CORS/RequestContext wrap it and the 429 still gets their
    # headers (X-Request-ID + CORS for the browser to read the message).
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.login_rate_limit_max,
        window_seconds=settings.login_rate_limit_window_seconds,
        paths={("POST", f"{settings.api_prefix}/auth/login")},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Checksum-SHA256"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": settings.project_name, "docs": "/docs", "api": settings.api_prefix}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
