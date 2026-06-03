"""Integration test: logging in with a legacy bcrypt hash upgrades it to Argon2id.

Requires the app database to be reachable; skipped otherwise so the unit suite
still runs in environments without Postgres.
"""

from __future__ import annotations

import bcrypt
import pytest
from sqlalchemy import text

from app.core.database import SessionFactory, engine
from app.modules.identity.models import Role, User
from app.modules.identity.service import authenticate


async def _db_available() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_login_upgrades_bcrypt_hash_to_argon2id():
    if not await _db_available():
        pytest.skip("app database not available")

    async with SessionFactory() as db:
        # Self-contained fixtures inside a transaction we roll back at the end.
        db.add(
            Role(
                id="rehash_test_role",
                name="Rehash Test",
                description="",
                status="Active",
                permissions={},
            )
        )
        await db.flush()

        legacy = bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode()
        user = User(
            full_name="Rehash Tester",
            email="rehash-test@radonaix.io",
            role_id="rehash_test_role",
            status="Active",
            hashed_password=legacy,
            avatar="RT",
        )
        db.add(user)
        await db.flush()
        assert user.hashed_password.startswith("$2")  # stored as bcrypt

        access, refresh, authed = await authenticate(db, "rehash-test@radonaix.io", "Test1234!")

        assert access and refresh
        # The stored hash was transparently upgraded on this same request.
        assert authed.hashed_password.startswith("$argon2id$")

        # Don't persist test data.
        await db.rollback()
