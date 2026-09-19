from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.core.permissions import ADMIN_ROLE, effective_permissions
from app.core.security import decode_access_token
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> AsyncDatabase:
    return request.app.state.db


def get_users_repo(db: AsyncDatabase = Depends(get_db)) -> UsersRepository:
    return UsersRepository(db)


def get_roles_repo(db: AsyncDatabase = Depends(get_db)) -> RolesRepository:
    return RolesRepository(db)


@dataclass
class Principal:
    """The authenticated caller: their user document and resolved permissions."""

    user: dict[str, Any]
    permissions: set[str]

    @property
    def is_admin(self) -> bool:
        return self.user["role"] == ADMIN_ROLE


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
    users: UsersRepository = Depends(get_users_repo),
    roles: RolesRepository = Depends(get_roles_repo),
) -> Principal:
    """Authenticate the request.

    The token comes from the ``Authorization: Bearer`` header (API clients,
    Swagger) or, failing that, the httpOnly cookie set at login (the browser
    app). The user and their role are re-read from MongoDB on every request,
    so deactivating a user or editing a role takes effect immediately.
    """
    token = credentials.credentials if credentials else request.cookies.get(settings.cookie_name)
    if not token:
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_access_token(token, settings)
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    user = await users.get_by_id(payload["sub"])
    if not user or not user.get("is_active", True):
        raise _unauthorized("User not found or inactive")

    role = await roles.get(user["role"])
    return Principal(user=user, permissions=effective_permissions(role))


def require_permissions(*required: str):
    """Dependency factory: the caller must hold **all** of the given permissions."""

    def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        missing = [p for p in required if p not in principal.permissions]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {', '.join(missing)}")
        return principal

    return _check


def require_any_permission(*allowed: str):
    """Dependency factory: the caller must hold **at least one** of the given permissions."""

    def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.permissions.intersection(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Requires one of: {', '.join(allowed)}")
        return principal

    return _check
