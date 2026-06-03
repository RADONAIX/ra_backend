"""Password hashing (Argon2id, bcrypt verify-only) and JWT issuance.

Argon2id is the production hashing algorithm. bcrypt is retained ONLY to verify
legacy hashes created before the migration; logging in with a bcrypt hash
transparently upgrades it to Argon2id (rehash-on-login).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt  # NOTE: remove once all stored hashes start with "$argon2".
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# Argon2id parameters (OWASP-aligned): 3 iterations, 64 MiB, 4 lanes.
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


# --- Passwords -------------------------------------------------------------
def hash_password(plain: str) -> str:
    """Always returns an Argon2id hash."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against an Argon2id or (legacy) bcrypt hash.

    Detects the algorithm by hash prefix. Never raises — returns False on any
    mismatch or malformed/unknown hash.
    """
    if not hashed:
        return False
    try:
        if hashed.startswith("$argon2"):
            return _ph.verify(hashed, plain)
        if hashed.startswith(_BCRYPT_PREFIXES):
            return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
    except (ValueError, TypeError):
        return False
    return False


def needs_rehash(hashed: str) -> bool:
    """True if the stored hash should be re-computed with the current settings.

    Legacy bcrypt (or unknown) hashes always need rehashing to Argon2id; an
    Argon2id hash needs it only if its parameters differ from the current ones.
    """
    if not hashed:
        return True
    if hashed.startswith("$argon2"):
        try:
            return _ph.check_needs_rehash(hashed)
        except InvalidHashError:
            return True
    return True  # bcrypt or unknown → migrate to Argon2id


# --- JWT -------------------------------------------------------------------
def create_access_token(
    subject: str,
    *,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    subject: str,
    *,
    session_id: str,
    jti: str,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(
        minutes=expires_minutes or settings.refresh_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
        "sid": session_id,
        "jti": jti,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT (any type). Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# Backwards-compatible alias.
decode_access_token = decode_token
