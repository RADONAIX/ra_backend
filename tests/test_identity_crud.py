"""Tests for the permission catalog and user/role CRUD additions.

The permission-catalog test is pure; the user/role tests use the `db_session`
fixture (conftest.py), which skips when the app database is unreachable.
"""

from __future__ import annotations

import bcrypt
import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.core.rbac import PermKey
from app.modules.identity import schemas, service
from app.modules.identity.models import Role, User, UserSession


@pytest.mark.asyncio
async def test_permission_catalog_lists_all_feature_keys():
    perms = await service.list_permissions()
    keys = {p.key for p in perms}
    assert keys == {k.value for k in PermKey}
    # Every entry has a human label and a UI path.
    assert all(p.label and p.path for p in perms)


async def _make_user(db, *, email: str, status: str = "Active") -> User:
    db.add(
        Role(id="crud_test_role", name="CRUD Test", description="", status="Active", permissions={})
    )
    await db.flush()
    user = User(
        full_name="CRUD Tester",
        email=email,
        role_id="crud_test_role",
        status=status,
        hashed_password=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode(),
        avatar="CT",
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_soft_delete_hides_user_and_revokes_sessions(db_session):
    user = await _make_user(db_session, email="crud-del@radonaix.io")
    db_session.add(
        UserSession(
            user_id=user.id,
            refresh_jti="crud-test-jti",
            issued_at=user.created_at,
            expires_at=user.created_at,
        )
    )
    await db_session.flush()

    await service.soft_delete_user(db_session, user.id)

    assert user.deleted_at is not None
    assert user.is_active is False  # cannot authenticate anymore

    with pytest.raises(NotFoundError):
        await service.get_user(db_session, user.id)
    listed = await service.list_users(db_session, limit=500, offset=0)
    assert all(u.id != user.id for u in listed)

    session_row = (
        await db_session.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalar_one()
    assert session_row.revoked_at is not None


@pytest.mark.asyncio
async def test_update_role_renames(db_session):
    db_session.add(
        Role(id="rename_me", name="Old Name", description="", status="Active", permissions={})
    )
    await db_session.flush()
    role = await service.update_role(
        db_session, "rename_me", schemas.RoleUpdate(name="New Name", description="updated")
    )
    assert role.name == "New Name"
    assert role.description == "updated"
