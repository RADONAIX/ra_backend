# Security Notes — RADONAIX Backend

## Password hashing

- **Production algorithm: Argon2id** (`argon2-cffi`). All new and updated
  passwords are hashed with Argon2id. Parameters (see
  [`app/core/security.py`](app/core/security.py)):
  - `time_cost=3`, `memory_cost=65536` (64 MiB), `parallelism=4` (OWASP-aligned).
- **bcrypt is verify-only** during the transition window. `verify_password`
  detects the algorithm by hash prefix:
  - `$argon2*` → verified with Argon2id
  - `$2a$` / `$2b$` / `$2y$` → verified with bcrypt (legacy)
- **Rehash-on-login:** on a successful login, if the stored hash is bcrypt (or
  an Argon2id hash whose parameters are now out of date), it is transparently
  re-hashed to current Argon2id and saved **in the same transaction** as the
  login-success audit event. Users notice nothing — no prompt, no forced reset.
- `verify_password` never raises; it returns `False` for any mismatch or
  malformed/unknown hash.

> The bcrypt fallback (and the `bcrypt` dependency) can be removed once every
> stored `hashed_password` begins with `$argon2`. There is a one-line marker
> comment at the `import bcrypt` in `app/core/security.py`.

The `hashed_password` column is `varchar(255)`, which comfortably fits an
Argon2id hash (~96 chars) — no schema change was required for this migration.

## Authentication & sessions

- **JWT access tokens** (short-lived) + **refresh tokens** with server-side
  sessions (`administration.user_sessions`). Refresh tokens rotate on every use;
  replaying a rotated token is treated as reuse and revokes the session.
- **Logout** revokes the session immediately (access tokens carry a `sid` that
  is checked against revocation on every request).
- **Login lockout:** after `MAX_FAILED_LOGINS` failures an account is locked for
  `LOCKOUT_MINUTES`.

## Audit

Every audited action records `actor` / `actor_id`, plus the request's
`ip_address`, `user_agent`, and `request_id` (captured by middleware).

## Production checklist

- Set a strong random `JWT_SECRET`; change all default/seed passwords.
- Serve behind HTTPS (TLS-terminating reverse proxy); restrict `CORS_ORIGINS`.
- Use a least-privilege DB account (see [docs/DATABASE.md](docs/DATABASE.md)).
