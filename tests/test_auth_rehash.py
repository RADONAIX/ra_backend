"""Integration test: logging in with a legacy bcrypt hash upgrades it to Argon2id.

Uses the `db_session` fixture (conftest.py), which is skipped when the app
database is unreachable so the unit suite still runs without Postgres.
"""

from __future__ import annotations

import bcrypt
import pytest

from app.modules.identity.models import Role, User
from app.modules.identity.service import authenticate


@pytest.mark.asyncio
async def test_login_upgrades_bcrypt_hash_to_argon2id(db_session):
    # Self-contained fixtures inside the rolled-back test transaction.
    db_session.add(
        Role(
            id="rehash_test_role",
            name="Rehash Test",
            description="",
            status="Active",
            permissions={},
        )
    )
    await db_session.flush()

    legacy = bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode()
    user = User(
        full_name="Rehash Tester",
        email="rehash-test@radonaix.io",
        role_id="rehash_test_role",
        status="Active",
        hashed_password=legacy,
        avatar="RT",
    )
    db_session.add(user)
    await db_session.flush()
    assert user.hashed_password.startswith("$2")  # stored as bcrypt

    access, refresh, authed = await authenticate(db_session, "rehash-test@radonaix.io", "Test1234!")

    assert access and refresh
    # The stored hash was transparently upgraded on this same request.
    assert authed.hashed_password.startswith("$argon2id$")
