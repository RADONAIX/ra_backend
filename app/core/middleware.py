"""HTTP middleware: request-id binding, access logging, Prometheus metrics."""

from __future__ import annotations

import time
import uuid

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import client_ip_ctx, get_logger, request_id_ctx, user_agent_ctx

log = get_logger("http")


def client_ip(request: Request) -> str | None:
    """Best-effort client IP, honouring a reverse proxy's X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        ip_token = client_ip_ctx.set(client_ip(request))
        ua_token = user_agent_ctx.set(request.headers.get("user-agent"))
        start = time.perf_counter()
        # Route template (e.g. /api/users/{id}) keeps metric cardinality low.
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - start
            REQUEST_COUNT.labels(request.method, path_label, "500").inc()
            log.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(elapsed * 1000, 2),
            )
            raise
        finally:
            request_id_ctx.reset(token)
            client_ip_ctx.reset(ip_token)
            user_agent_ctx.reset(ua_token)

        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(request.method, path_label).observe(elapsed)
        REQUEST_COUNT.labels(request.method, path_label, str(response.status_code)).inc()
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed * 1000, 2),
        )
        return response
