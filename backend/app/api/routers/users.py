from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Principal, get_user_service, require_permissions
from app.schemas.common import Page, paginate
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.users import UserService

# Thin HTTP layer: authenticate/authorize, parse, call the service, shape the response.
# The business rules (last admin, privilege escalation, ...) live in app/services/users.py.
router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    q: str | None = Query(None, max_length=100, description="Search email or name"),
    _: Principal = Depends(require_permissions("users:read")),
    service: UserService = Depends(get_user_service),
) -> Page[UserOut]:
    items, total = await service.list_page(page=page, page_size=page_size, search=q)
    return paginate([UserOut.from_doc(u) for u in items], total, page, page_size)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    _: Principal = Depends(require_permissions("users:read")),
    service: UserService = Depends(get_user_service),
) -> UserOut:
    return UserOut.from_doc(await service.get(user_id))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    principal: Principal = Depends(require_permissions("users:create")),
    service: UserService = Depends(get_user_service),
) -> UserOut:
    user = await service.create(
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
        is_active=payload.is_active,
        actor_is_admin=principal.is_admin,
    )
    return UserOut.from_doc(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    principal: Principal = Depends(require_permissions("users:update")),
    service: UserService = Depends(get_user_service),
) -> UserOut:
    updated = await service.update(
        user_id,
        payload.model_dump(exclude_unset=True),
        actor_id=principal.user["_id"],
        actor_is_admin=principal.is_admin,
    )
    return UserOut.from_doc(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    principal: Principal = Depends(require_permissions("users:delete")),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete(user_id, actor_id=principal.user["_id"], actor_is_admin=principal.is_admin)
