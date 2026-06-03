"""Identity business logic: auth, users, roles, audit."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.rbac import ROLE_LABELS, default_permissions_for
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.identity import schemas
from app.modules.identity.models import AuditLog, Role, User


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _role_label(role: Role | None, role_id: str) -> str:
    if role and role.name:
        return role.name
    return ROLE_LABELS.get(role_id, role_id)


# --- Mappers ---------------------------------------------------------------
def to_auth_user(user: User) -> schemas.AuthUser:
    return schemas.AuthUser(
        id=user.id,
        name=user.full_name,
        email=user.email,
        role=user.role_id,
        roleLabel=_role_label(user.role, user.role_id),
        department=user.department,
        avatar=user.avatar or _initials(user.full_name),
        status=user.status,
        lastLogin=user.last_login,
    )


def to_user_row(user: User) -> schemas.UserRow:
    return schemas.UserRow(
        id=user.id,
        fullName=user.full_name,
        email=user.email,
        phone=user.phone,
        department=user.department,
        role=user.role_id,
        status=user.status,
        lastLogin=user.last_login,
        createdAt=user.created_at,
    )


def to_role_row(role: Role) -> schemas.RoleRow:
    return schemas.RoleRow(
        id=role.id,
        name=role.name,
        description=role.description,
        status=role.status,
        permissions=role.permissions or {},
        createdAt=role.created_at,
        updatedAt=role.updated_at,
    )


# --- Audit -----------------------------------------------------------------
async def record_audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    target: str | None = None,
    meta: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            meta=meta or {},
            at=datetime.now(UTC),
        )
    )
    await db.flush()


async def list_audit(db: AsyncSession, *, limit: int, offset: int) -> list[schemas.AuditRow]:
    rows = (
        (
            await db.execute(
                select(AuditLog).order_by(AuditLog.at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [
        schemas.AuditRow(id=r.id, actor=r.actor, action=r.action, target=r.target, at=r.at)
        for r in rows
    ]


# --- Auth ------------------------------------------------------------------
async def authenticate(db: AsyncSession, email: str, password: str) -> tuple[str, User]:
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid email or password.")
    if not user.is_active:
        raise AuthenticationError("Your account has been disabled. Please contact administrator.")

    user.last_login = datetime.now(UTC)
    await db.flush()
    token = create_access_token(user.id, extra_claims={"email": user.email, "role": user.role_id})
    return token, user


async def get_user(db: AsyncSession, user_id: str) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found.")
    return user


# --- Users -----------------------------------------------------------------
async def list_users(db: AsyncSession, *, limit: int, offset: int) -> list[schemas.UserRow]:
    rows = (
        (
            await db.execute(
                select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [to_user_row(u) for u in rows]


async def _require_role(db: AsyncSession, role_id: str) -> Role:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Role '{role_id}' does not exist.")
    return role


async def create_user(db: AsyncSession, payload: schemas.UserCreate) -> User:
    await _require_role(db, payload.role)
    exists = (
        await db.execute(select(User).where(func.lower(User.email) == payload.email.lower()))
    ).scalar_one_or_none()
    if exists:
        raise ConflictError("A user with this email already exists.")
    user = User(
        full_name=payload.fullName,
        email=payload.email,
        phone=payload.phone,
        department=payload.department,
        role_id=payload.role,
        status=payload.status,
        hashed_password=hash_password(payload.password),
        avatar=_initials(payload.fullName),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user_id: str, payload: schemas.UserUpdate) -> User:
    user = await get_user(db, user_id)
    if payload.role and payload.role != user.role_id:
        await _require_role(db, payload.role)
        user.role_id = payload.role
    if payload.fullName is not None:
        user.full_name = payload.fullName
        user.avatar = _initials(payload.fullName)
    if payload.email is not None:
        user.email = payload.email
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.department is not None:
        user.department = payload.department
    if payload.status is not None:
        user.status = payload.status
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    await db.flush()
    await db.refresh(user)
    return user


# --- Roles -----------------------------------------------------------------
async def list_roles(db: AsyncSession) -> list[schemas.RoleRow]:
    rows = (await db.execute(select(Role).order_by(Role.created_at))).scalars().all()
    return [to_role_row(r) for r in rows]


async def upsert_role(db: AsyncSession, payload: schemas.RoleUpsert) -> Role:
    role_id = payload.id or payload.name.lower().replace(" ", "_")
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    perms = payload.permissions or default_permissions_for(role_id)
    if role is None:
        role = Role(
            id=role_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            permissions=perms,
        )
        db.add(role)
    else:
        role.name = payload.name
        role.description = payload.description
        role.status = payload.status
        if payload.permissions is not None:
            role.permissions = payload.permissions
    await db.flush()
    await db.refresh(role)
    return role


async def update_role_permissions(db: AsyncSession, role_id: str, permissions: dict) -> Role:
    role = await _require_role(db, role_id)
    role.permissions = permissions
    await db.flush()
    await db.refresh(role)
    return role
