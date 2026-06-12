"""Role-Based Access Control.

Mirrors the permission model the UI defines in ``src/lib/auth.tsx`` so the
backend is the authoritative enforcement point. Roles carry a permission
matrix of {view, edit} per feature key; matrices are stored on the Role row
in the DB (seeded from the defaults below) and may be customised at runtime.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

PermAction = Literal["view", "edit"]


class RoleSlug(StrEnum):
    ADMIN = "admin"
    RA_LEAD = "ra_lead"
    ANALYST = "analyst"
    VIEWER = "viewer"


class PermKey(StrEnum):
    DASHBOARD = "dashboard"
    REPORTS = "reports"
    WORKBENCH = "workbench"
    CASE_MANAGEMENT = "caseManagement"
    PIPELINES = "pipelines"
    USER_MANAGEMENT = "userManagement"
    ROLE_MANAGEMENT = "roleManagement"
    SETTINGS = "settings"
    EXPORTS = "exports"


ROLE_LABELS: dict[str, str] = {
    RoleSlug.ADMIN: "Administrator",
    RoleSlug.RA_LEAD: "RA Manager",
    RoleSlug.ANALYST: "RA Analyst",
    RoleSlug.VIEWER: "Report Viewer",
}

# Catalog of feature permission keys → (human label, UI path). Mirrors
# PERMISSION_KEYS in the UI (ui/radon-ai-vision/src/lib/auth.tsx) and backs the
# read-only GET /permissions endpoint. Each key carries {view, edit} actions.
PERMISSION_CATALOG: list[tuple[PermKey, str, str]] = [
    (PermKey.DASHBOARD, "Dashboard & KPIs", "/"),
    (PermKey.REPORTS, "Reports & Certified Exports", "/reports"),
    (PermKey.WORKBENCH, "Assurance Workbench", "/workbench"),
    (PermKey.CASE_MANAGEMENT, "Case Management", "/cases"),
    (PermKey.PIPELINES, "Pipelines & Job Monitor", "/pipelines"),
    (PermKey.USER_MANAGEMENT, "User Management", "/users"),
    (PermKey.ROLE_MANAGEMENT, "Role Management", "/roles"),
    (PermKey.SETTINGS, "Settings", "/system-config"),
    (PermKey.EXPORTS, "Bulk Exports", "/settings/exports"),
]

PermissionMap = dict[str, dict[str, bool]]


def _full() -> PermissionMap:
    return {k.value: {"view": True, "edit": True} for k in PermKey}


# Default permission matrices — kept in lockstep with the UI defaults.
DEFAULT_ROLE_PERMISSIONS: dict[str, PermissionMap] = {
    RoleSlug.ADMIN: _full(),
    RoleSlug.RA_LEAD: {
        PermKey.DASHBOARD: {"view": True, "edit": True},
        PermKey.REPORTS: {"view": True, "edit": True},
        PermKey.WORKBENCH: {"view": True, "edit": True},
        PermKey.CASE_MANAGEMENT: {"view": True, "edit": True},
        PermKey.PIPELINES: {"view": True, "edit": True},
        PermKey.USER_MANAGEMENT: {"view": False, "edit": False},
        PermKey.ROLE_MANAGEMENT: {"view": False, "edit": False},
        PermKey.SETTINGS: {"view": True, "edit": False},
        PermKey.EXPORTS: {"view": True, "edit": True},
    },
    RoleSlug.ANALYST: {
        PermKey.DASHBOARD: {"view": True, "edit": False},
        PermKey.REPORTS: {"view": True, "edit": False},
        PermKey.WORKBENCH: {"view": True, "edit": True},
        PermKey.CASE_MANAGEMENT: {"view": True, "edit": True},
        PermKey.PIPELINES: {"view": True, "edit": False},
        PermKey.USER_MANAGEMENT: {"view": False, "edit": False},
        PermKey.ROLE_MANAGEMENT: {"view": False, "edit": False},
        PermKey.SETTINGS: {"view": False, "edit": False},
        PermKey.EXPORTS: {"view": True, "edit": True},
    },
    RoleSlug.VIEWER: {
        PermKey.DASHBOARD: {"view": True, "edit": False},
        PermKey.REPORTS: {"view": True, "edit": False},
        PermKey.WORKBENCH: {"view": False, "edit": False},
        PermKey.CASE_MANAGEMENT: {"view": False, "edit": False},
        PermKey.PIPELINES: {"view": True, "edit": False},
        PermKey.USER_MANAGEMENT: {"view": False, "edit": False},
        PermKey.ROLE_MANAGEMENT: {"view": False, "edit": False},
        PermKey.SETTINGS: {"view": False, "edit": False},
        PermKey.EXPORTS: {"view": True, "edit": False},
    },
}


def default_permissions_for(role: str) -> PermissionMap:
    return DEFAULT_ROLE_PERMISSIONS.get(role, _full())


def has_permission(perms: PermissionMap, key: PermKey, action: PermAction) -> bool:
    entry = perms.get(key.value)
    return bool(entry and entry.get(action, False))
