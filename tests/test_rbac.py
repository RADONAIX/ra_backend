"""Unit tests for the RBAC permission model."""

from __future__ import annotations

from app.core.rbac import (
    DEFAULT_ROLE_PERMISSIONS,
    PermKey,
    RoleSlug,
    default_permissions_for,
    has_permission,
)


def test_admin_has_everything():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.ADMIN]
    for key in PermKey:
        assert has_permission(perms, key, "view")
        assert has_permission(perms, key, "edit")


def test_viewer_is_read_only_dashboard():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.VIEWER]
    assert has_permission(perms, PermKey.DASHBOARD, "view")
    assert not has_permission(perms, PermKey.DASHBOARD, "edit")
    assert not has_permission(perms, PermKey.USER_MANAGEMENT, "view")


def test_analyst_can_edit_workbench_not_users():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.ANALYST]
    assert has_permission(perms, PermKey.WORKBENCH, "edit")
    assert not has_permission(perms, PermKey.USER_MANAGEMENT, "edit")


def test_unknown_role_falls_back_to_full():
    perms = default_permissions_for("nope")
    assert has_permission(perms, PermKey.SETTINGS, "edit")


def test_missing_key_denied():
    assert not has_permission({}, PermKey.REPORTS, "view")
