"""Identity routes: /auth, /users, /roles, /audit-logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.core.deps import CurrentUser, DbSession, PageParams, Principal, require
from app.core.errors import AppError
from app.core.middleware import client_ip
from app.core.rbac import PermKey
from app.modules.identity import schemas, service

router = APIRouter(tags=["identity"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), client_ip(request)


# --- Auth ------------------------------------------------------------------
@router.post("/auth/login", response_model=schemas.LoginResponse)
async def login(
    payload: schemas.LoginRequest, request: Request, db: DbSession
) -> schemas.LoginResponse:
    ua, ip = _client_meta(request)
    access, refresh, user = await service.authenticate(
        db, payload.email, payload.password, user_agent=ua, ip=ip
    )
    await service.record_audit(
        db, actor=user.email, actor_id=user.id, action="Signed in", target=user.id
    )
    return schemas.LoginResponse(
        token=access, refreshToken=refresh, user=service.to_auth_user(user)
    )


@router.post("/auth/refresh", response_model=schemas.TokenPair)
async def refresh(
    payload: schemas.RefreshRequest, request: Request, db: DbSession
) -> schemas.TokenPair:
    ua, ip = _client_meta(request)
    access, new_refresh = await service.refresh_session(
        db, payload.refreshToken, user_agent=ua, ip=ip
    )
    return schemas.TokenPair(token=access, refreshToken=new_refresh)


@router.post("/auth/logout", response_model=schemas.ActionResult)
async def logout(principal: CurrentUser, db: DbSession) -> schemas.ActionResult:
    await service.revoke_session(db, principal.session_id)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Signed out"
    )
    return schemas.ActionResult(ok=True, detail="Signed out.")


@router.post("/auth/change-password", response_model=schemas.ActionResult)
async def change_password(
    payload: schemas.ChangePasswordRequest, principal: CurrentUser, db: DbSession
) -> schemas.ActionResult:
    await service.change_password(db, principal.id, payload.currentPassword, payload.newPassword)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Changed password"
    )
    return schemas.ActionResult(ok=True, detail="Password updated.")


@router.get("/auth/me", response_model=schemas.AuthUser)
async def me(principal: CurrentUser, db: DbSession) -> schemas.AuthUser:
    user = await service.get_user(db, principal.id)
    return service.to_auth_user(user)


@router.get("/permissions", response_model=list[schemas.PermissionInfo])
async def list_permissions(
    _: Principal = Depends(require(PermKey.ROLE_MANAGEMENT, "view")),
) -> list[schemas.PermissionInfo]:
    return await service.list_permissions()


# --- Users -----------------------------------------------------------------
users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=list[schemas.UserRow])
async def list_users(
    db: DbSession,
    page: PageParams,
    _: Principal = Depends(require(PermKey.USER_MANAGEMENT, "view")),
) -> list[schemas.UserRow]:
    return await service.list_users(db, limit=page.limit, offset=page.offset)


@users_router.post("", response_model=schemas.UserRow, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: schemas.UserCreate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.USER_MANAGEMENT, "edit")),
) -> schemas.UserRow:
    user = await service.create_user(db, payload)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Created user", target=user.id
    )
    return service.to_user_row(user)


@users_router.patch("/{user_id}", response_model=schemas.UserRow)
async def update_user(
    user_id: str,
    payload: schemas.UserUpdate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.USER_MANAGEMENT, "edit")),
) -> schemas.UserRow:
    user = await service.update_user(db, user_id, payload)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Updated user", target=user.id
    )
    return service.to_user_row(user)


@users_router.get("/{user_id}", response_model=schemas.UserRow)
async def get_user(
    user_id: str,
    db: DbSession,
    _: Principal = Depends(require(PermKey.USER_MANAGEMENT, "view")),
) -> schemas.UserRow:
    user = await service.get_user(db, user_id)
    return service.to_user_row(user)


@users_router.delete("/{user_id}", response_model=schemas.ActionResult)
async def delete_user(
    user_id: str,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.USER_MANAGEMENT, "edit")),
) -> schemas.ActionResult:
    if user_id == principal.id:
        raise AppError("You cannot delete your own account.")
    user = await service.soft_delete_user(db, user_id)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Deleted user", target=user.id
    )
    return schemas.ActionResult(ok=True, detail="User deleted.")


# --- Roles -----------------------------------------------------------------
roles_router = APIRouter(prefix="/roles", tags=["roles"])


@roles_router.get("", response_model=list[schemas.RoleRow])
async def list_roles(
    db: DbSession,
    _: Principal = Depends(require(PermKey.ROLE_MANAGEMENT, "view")),
) -> list[schemas.RoleRow]:
    return await service.list_roles(db)


@roles_router.patch("/{role_id}", response_model=schemas.RoleRow)
async def update_role(
    role_id: str,
    payload: schemas.RoleUpdate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.ROLE_MANAGEMENT, "edit")),
) -> schemas.RoleRow:
    role = await service.update_role(db, role_id, payload)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Updated role", target=role.id
    )
    return service.to_role_row(role)


@roles_router.put("/{role_id}/permissions", response_model=schemas.RoleRow)
async def update_role_permissions(
    role_id: str,
    payload: schemas.RolePermissionsUpdate,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.ROLE_MANAGEMENT, "edit")),
) -> schemas.RoleRow:
    role = await service.update_role_permissions(db, role_id, payload.permissions)
    await service.record_audit(
        db,
        actor=principal.email,
        actor_id=principal.id,
        action="Updated role permissions",
        target=role_id,
    )
    return service.to_role_row(role)


@roles_router.post("", response_model=schemas.RoleRow, status_code=status.HTTP_201_CREATED)
async def upsert_role(
    payload: schemas.RoleUpsert,
    db: DbSession,
    principal: Principal = Depends(require(PermKey.ROLE_MANAGEMENT, "edit")),
) -> schemas.RoleRow:
    role = await service.upsert_role(db, payload)
    await service.record_audit(
        db, actor=principal.email, actor_id=principal.id, action="Saved role", target=role.id
    )
    return service.to_role_row(role)


# --- Audit -----------------------------------------------------------------
audit_router = APIRouter(prefix="/audit-logs", tags=["audit"])


@audit_router.get("", response_model=list[schemas.AuditRow])
async def list_audit(
    db: DbSession,
    page: PageParams,
    _: Principal = Depends(require(PermKey.SETTINGS, "view")),
) -> list[schemas.AuditRow]:
    return await service.list_audit(db, limit=page.limit, offset=page.offset)


router.include_router(users_router)
router.include_router(roles_router)
router.include_router(audit_router)
