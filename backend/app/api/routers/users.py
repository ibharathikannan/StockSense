from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.api.deps import Principal, get_roles_repo, get_users_repo, require_permissions
from app.core.permissions import ADMIN_ROLE
from app.core.security import hash_password
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository
from app.schemas.common import Page, paginate
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _forbid(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


async def _load_user(users: UsersRepository, user_id: str) -> dict[str, Any]:
    user = await users.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _assert_role_exists(roles: RolesRepository, name: str) -> None:
    if not await roles.get(name):
        raise _bad_request(f"Role '{name}' does not exist")


async def _assert_not_last_admin(users: UsersRepository, target: dict[str, Any]) -> None:
    """Never let the system end up with no active administrator."""
    if target["role"] == ADMIN_ROLE and target.get("is_active", True):
        if await users.count_active_with_role(ADMIN_ROLE) <= 1:
            raise _bad_request("This is the last active administrator")


@router.get("", response_model=Page[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    q: str | None = Query(None, max_length=100, description="Search email or name"),
    _: Principal = Depends(require_permissions("users:read")),
    users: UsersRepository = Depends(get_users_repo),
) -> Page[UserOut]:
    items = await users.list(skip=(page - 1) * page_size, limit=page_size, search=q)
    total = await users.count(search=q)
    return paginate([UserOut.from_doc(u) for u in items], total, page, page_size)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    _: Principal = Depends(require_permissions("users:read")),
    users: UsersRepository = Depends(get_users_repo),
) -> UserOut:
    return UserOut.from_doc(await _load_user(users, user_id))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    principal: Principal = Depends(require_permissions("users:create")),
    users: UsersRepository = Depends(get_users_repo),
    roles: RolesRepository = Depends(get_roles_repo),
) -> UserOut:
    await _assert_role_exists(roles, payload.role)
    if payload.role == ADMIN_ROLE and not principal.is_admin:
        raise _forbid("Only administrators can create administrators")

    password_hash = await run_in_threadpool(hash_password, payload.password)
    try:
        user = await users.create(
            email=payload.email,
            full_name=payload.full_name,
            password_hash=password_hash,
            role=payload.role,
            is_active=payload.is_active,
        )
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A user with this email already exists") from None
    return UserOut.from_doc(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    principal: Principal = Depends(require_permissions("users:update")),
    users: UsersRepository = Depends(get_users_repo),
    roles: RolesRepository = Depends(get_roles_repo),
) -> UserOut:
    target = await _load_user(users, user_id)
    is_self = target["_id"] == principal.user["_id"]
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}

    new_role = changes.get("role", target["role"])
    role_changes = new_role != target["role"]
    deactivating = changes.get("is_active") is False and target.get("is_active", True)

    if is_self and (role_changes or deactivating):
        raise _bad_request("You can't change your own role or deactivate your own account")
    # Touching an administrator, or granting the admin role, is admin-only —
    # otherwise 'users:update' would be a path to privilege escalation.
    if (target["role"] == ADMIN_ROLE or new_role == ADMIN_ROLE) and not principal.is_admin:
        raise _forbid("Only administrators can modify administrators or grant the admin role")
    if role_changes:
        await _assert_role_exists(roles, new_role)
    if role_changes or deactivating:
        await _assert_not_last_admin(users, target)

    if "password" in changes:
        changes["password_hash"] = await run_in_threadpool(hash_password, changes.pop("password"))

    updated = await users.update(user_id, changes) if changes else target
    return UserOut.from_doc(updated)  # type: ignore[arg-type]


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    principal: Principal = Depends(require_permissions("users:delete")),
    users: UsersRepository = Depends(get_users_repo),
) -> None:
    target = await _load_user(users, user_id)
    if target["_id"] == principal.user["_id"]:
        raise _bad_request("You can't delete your own account")
    if target["role"] == ADMIN_ROLE and not principal.is_admin:
        raise _forbid("Only administrators can delete administrators")
    await _assert_not_last_admin(users, target)
    await users.delete(user_id)
