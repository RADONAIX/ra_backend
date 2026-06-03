"""Pydantic schemas for the identity module.

Response shapes intentionally mirror what the Lovable UI consumes
(``src/services/index.ts`` / ``src/lib/auth.tsx``):
  * auth login / profile use ``name`` + ``roleLabel``
  * the users table uses ``fullName`` + ``createdAt``
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.rbac import PermissionMap


# --- Auth ------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AuthUser(BaseModel):
    """User shape returned by /auth/login and /auth/me."""

    id: str
    name: str
    email: EmailStr
    role: str
    roleLabel: str | None = None
    department: str | None = None
    avatar: str | None = None
    status: str = "Active"
    lastLogin: datetime | None = None
    mustResetPassword: bool = False


class LoginResponse(BaseModel):
    token: str  # access token
    refreshToken: str
    user: AuthUser


class RefreshRequest(BaseModel):
    refreshToken: str = Field(min_length=1)


class TokenPair(BaseModel):
    token: str  # access token
    refreshToken: str


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=8)


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


# --- Users -----------------------------------------------------------------
class UserRow(BaseModel):
    """User shape returned by the /users table."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    fullName: str
    email: EmailStr
    phone: str | None = None
    department: str | None = None
    role: str
    status: str
    lastLogin: datetime | None = None
    createdAt: datetime


class UserCreate(BaseModel):
    fullName: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    role: str
    phone: str | None = None
    department: str | None = None
    status: str = "Active"
    # Force the user to change their password on first login.
    mustResetPassword: bool = False


class UserUpdate(BaseModel):
    fullName: str | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str | None = None
    phone: str | None = None
    department: str | None = None
    status: str | None = None


# --- Roles -----------------------------------------------------------------
class RoleRow(BaseModel):
    id: str
    name: str
    description: str
    status: str
    permissions: PermissionMap
    createdAt: datetime
    updatedAt: datetime


class RoleUpsert(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    description: str = ""
    status: str = "Active"
    permissions: PermissionMap | None = None


class RolePermissionsUpdate(BaseModel):
    permissions: PermissionMap


# --- Audit -----------------------------------------------------------------
class AuditRow(BaseModel):
    id: str
    actor: str
    action: str
    target: str | None = None
    at: datetime
