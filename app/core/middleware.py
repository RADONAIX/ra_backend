"""HTTP middleware: request-id binding, access logging, Prometheus metrics."""

from __future__ import annotations

import time
import uuid

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP fixed-window rate limit on sensitive endpoints (e.g. login).

    In-memory and per-worker — a brute-force speed bump, not a distributed
    limiter. For cross-worker/instance enforcement, back it with Redis (see
    docs/PRODUCTION_READINESS.md).
    """

    def __init__(
        self,
        app,
        *,
        max_requests: int,
        window_seconds: int,
        paths: set[tuple[str, str]],
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._paths = paths  # set of (METHOD, path) the limit applies to
        self._hits: dict[tuple[str, str], tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        if (request.method, request.url.path) not in self._paths:
            return await call_next(request)

        ip = client_ip(request) or "unknown"
        key = (request.url.path, ip)
        now = time.monotonic()
        window_start, count = self._hits.get(key, (now, 0))
        if now - window_start >= self._window:
            window_start, count = now, 0
        count += 1
        self._hits[key] = (window_start, count)
        if len(self._hits) > 10_000:
            self._prune(now)

        if count > self._max:
            retry_after = max(1, int(self._window - (now - window_start)))
            log.warning("rate_limited", ip=ip, path=request.url.path, count=count)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many attempts. Please wait and try again.",
                        "details": {},
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    def _prune(self, now: float) -> None:
        for k in [k for k, (start, _) in self._hits.items() if now - start >= self._window]:
            del self._hits[k]


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
