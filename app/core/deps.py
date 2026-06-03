"""Shared FastAPI dependencies: DB session, current principal, RBAC guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.rbac import PermAction, PermissionMap, PermKey, has_permission
from app.core.security import decode_access_token
from app.modules.identity.models import User

DbSession = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """The authenticated caller, resolved from the JWT + DB."""

    id: str
    email: str
    full_name: str
    role: str
    permissions: PermissionMap = field(default_factory=dict)

    def can(self, key: PermKey, action: PermAction) -> bool:
        return has_permission(self.permissions, key, action)


async def get_current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> Principal:
    if creds is None or not creds.credentials:
        raise AuthenticationError("Missing bearer token.")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid token.") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token subject.")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AuthenticationError("User no longer exists.")
    if not user.is_active:
        raise AuthenticationError("Account is disabled.")

    return Principal(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role_id,
        permissions=user.role.permissions or {},
    )


CurrentUser = Annotated[Principal, Depends(get_current_principal)]


def require(key: PermKey, action: PermAction = "view"):
    """Dependency factory enforcing a permission for the current principal."""

    async def _guard(principal: CurrentUser) -> Principal:
        if not principal.can(key, action):
            raise PermissionDeniedError(
                f"Role '{principal.role}' lacks '{action}' on '{key.value}'."
            )
        return principal

    return _guard


@dataclass
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PageParams = Annotated[Pagination, Depends(pagination)]
