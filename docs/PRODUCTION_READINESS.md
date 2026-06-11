# Production Readiness — RADONAIX Backend (`ra_backend`)

**Verdict:** The service is already well-architected and roughly **80% production-ready**. Core security, RBAC, observability, containerization, and migrations are in place and solid. The remaining work is **operational hardening and delivery automation**, not rewrites. This document is the prioritized roadmap; nothing here is a blocker to *functioning*, but the **P0** items should be closed before serving real/external traffic.

---

## 1. Already in place ✅ (don't re-do these)

**Security & Auth**
- Argon2id password hashing (OWASP params) + transparent bcrypt→argon2 rehash-on-login — `app/core/security.py`
- JWT (HS256) with **refresh-token rotation + reuse detection** and DB-backed **session revocation** (logout is immediate) — `app/modules/identity/service.py`
- Account lockout (failed-login counter, `locked_until`) and **generic** auth errors (no user enumeration) — `app/modules/identity/service.py`
- RBAC feature-matrix with `require()` guards on **every** mutating endpoint — `app/core/rbac.py`, `app/core/deps.py`, all `*/router.py`
- Comprehensive audit logging (actor, action, target, IP, user-agent, request-id) — `app/modules/identity/`
- Input validation: Pydantic bodies, pagination caps (1–500), query bounds (e.g. `hours` 1–720) — `app/core/deps.py`

**Observability**
- structlog JSON logging with **request/correlation IDs** + per-request middleware — `app/core/logging.py`, `app/core/middleware.py`
- Prometheus `/metrics` with request count + latency histograms (route-template cardinality) — `app/main.py`, `app/core/middleware.py`
- `/api/health` (liveness) and `/api/health/ready` (readiness pings DB/ClickHouse/PG) — `app/modules/meta/router.py`

**Resilience & Delivery**
- Graceful degradation via `UpstreamUnavailableError` (integrations never 500 the app) — `app/core/errors.py`, `app/integrations/*`
- Consistent error envelope + global handlers (no stack-trace leaks) — `app/core/errors.py`
- Connection pooling (`pool_pre_ping`, sized) + lifespan shutdown disposing all clients — `app/core/database.py`, `app/core/integrations_shutdown.py`
- Multi-stage **Dockerfile** (non-root, healthcheck, gunicorn+uvicorn workers) + docker-compose + entrypoint migration runner
- **Alembic** migrations with schema isolation (3 revisions) — `migrations/`
- 25 tests (auth, JWT, RBAC, identity CRUD, rehash) — `tests/`; strong docs (README, API_REFERENCE, SETUP, SECURITY, DATABASE)

**Verified safe (don't chase these):** Bearer tokens (not cookies) → naturally **CSRF-immune**; all SQL is parameterized and report keys are dict-looked-up from a fixed registry → **injection surface is minimal**.

---

## 2. Gap roadmap

### 🔴 P0 — close before production traffic
| Gap | Why it matters | Where | Recommended fix |
|---|---|---|---|
| No CI/CD | PRs aren't validated; regressions ship | `.github/workflows/` (absent) | Add a workflow running ruff + mypy + pytest on PRs |
| Secrets fail **open** | Default `JWT_SECRET` makes tokens forgeable; default admin password is public | `app/core/config.py`, `.env` | On startup, **fail fast** if `ENVIRONMENT=production` and `JWT_SECRET`/`BOOTSTRAP_ADMIN_PASSWORD` are unset or equal the known default |
| No login rate limiting | Only DB lockout; no per-IP throttle → distributed brute force / DoS | `/auth/login` | Add per-IP limiter (e.g. SlowAPI) on auth routes |
| No security headers / host check | Clickjacking, MIME-sniff, Host-header attacks | `app/main.py` | Middleware for HSTS, `X-Frame-Options`, `X-Content-Type-Options`, CSP + `TrustedHostMiddleware` |
| CORS wildcards | `allow_methods/headers=["*"]` is over-permissive | `app/main.py:60-61` | Whitelist explicit methods + headers (origins already env-driven) |
| No `.dockerignore` | `.git`/`.venv`/caches bloat the image and risk leaking files | repo root | Add `.dockerignore` |

### 🟠 P1 — enterprise baseline
| Gap | Why it matters | Where | Recommended fix |
|---|---|---|---|
| No error tracking / tracing | Failures only hit stdout; no aggregation or spans | app-wide | Add Sentry SDK + OpenTelemetry (FastAPI/SQLAlchemy/httpx/ClickHouse) |
| `tenacity` unused | Flaky ClickHouse/Airflow calls have no retry/backoff/circuit-breaker | `app/integrations/*` | Wrap external calls with `@retry` + circuit-breaker (dep already present) |
| Thin test coverage | reporting/pipeline/assurance endpoints untested; no coverage gate | `tests/` | Add `pytest-cov` threshold + endpoint/integration tests |
| No dependency scanning | Transitive CVEs go unnoticed; `uv.lock` not committed | CI, `.gitignore` | Add pip-audit/Dependabot; **commit `uv.lock`** for reproducibility |
| No immediate token revocation | Deleted user's access token stays valid until `exp` (~12h) | `app/modules/identity/service.py` | Redis-backed token blacklist, or shorten access TTL + rely on refresh |
| Redis/Celery inactive | Heavy ClickHouse reports run synchronously; no caching | `app/workers/`, `app/core/redis.py` | Activate cache for expensive aggregations + move report-gen to Celery (+ Flower/DLQ) |

### 🟡 P2 — operational maturity
- Graceful **SIGTERM draining** of in-flight requests (signal handling beyond gunicorn default)
- Request **body-size limit** (memory-exhaustion guard)
- **Slow-query** + **pool-utilization** Prometheus metrics
- **Password-complexity** policy (today: min length 8 only)
- Migration **rollback/downgrade** tests + `alembic check` drift gate in CI
- **Runbook / DR / backup** docs (RTO/RPO, restore drill), **audit-log retention/archival**
- Staging↔prod **config separation** + **secrets vault** (Vault / AWS Secrets Manager) instead of `.env`

---

## 3. Suggested sequencing
1. **P0 sprint (days):** `.dockerignore` + CORS tighten + security-headers/TrustedHost middleware + secrets fail-fast → all quick wins; then login rate-limiting; then the CI workflow.
2. **P1 (1–2 sprints):** Sentry+OTel → tenacity retries → coverage + endpoint tests → dependency scanning + commit `uv.lock` → token blacklist → Redis/Celery activation (only if async reports are needed).
3. **P2 (ongoing):** fold into normal ops hardening and the DR/runbook documentation effort.

## 4. Pre-deploy checklist (must-set before go-live)
- [ ] Override `JWT_SECRET` with a 48+ char random value (`python -c "import secrets;print(secrets.token_urlsafe(48))"`)
- [ ] Override `BOOTSTRAP_ADMIN_PASSWORD` with a unique strong password (rotate the seeded admin)
- [ ] `ENVIRONMENT=production`, `DEBUG=false`
- [ ] TLS terminated at the reverse proxy; add HSTS; backend bound behind it (`--host 0.0.0.0`)
- [ ] CORS set to explicit origins/methods/headers (no `*`)
- [ ] `.env` never committed (already gitignored); secrets injected via env/vault
- [ ] Run `alembic upgrade head` + seed admin against the prod DB
