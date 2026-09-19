from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import Principal, get_roles_repo, get_users_repo, require_any_permission, require_permissions
from app.core.permissions import ADMIN_ROLE, DEFAULT_ROLE, PERMISSIONS, group_of
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository
from app.schemas.common import Page, paginate
from app.schemas.role import PermissionOut, RoleCreate, RoleOption, RoleOut, RoleUpdate

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _validate_permissions(permissions: list[str]) -> None:
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        raise HTTPException(422, detail=f"Unknown permissions: {', '.join(unknown)}")


async def _load_role(roles: RolesRepository, name: str) -> dict:
    role = await roles.get(name)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


# NOTE: the fixed paths below must stay above "/{name}" so they aren't captured by it.


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(_: Principal = Depends(require_permissions("roles:read"))) -> list[PermissionOut]:
    """The permission catalogue (drives the role editor)."""
    return [PermissionOut(key=k, description=d, group=group_of(k)) for k, d in PERMISSIONS.items()]


@router.get("/options", response_model=list[RoleOption])
async def list_role_options(
    _: Principal = Depends(require_any_permission("roles:read", "users:create", "users:update")),
    roles: RolesRepository = Depends(get_roles_repo),
) -> list[RoleOption]:
    """Lightweight role list for the 'assign role' dropdown on the user form."""
    return [RoleOption(name=r["name"], description=r.get("description")) for r in await roles.list()]


@router.get("", response_model=Page[RoleOut])
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    _: Principal = Depends(require_permissions("roles:read")),
    roles: RolesRepository = Depends(get_roles_repo),
    users: UsersRepository = Depends(get_users_repo),
) -> Page[RoleOut]:
    items = await roles.list(skip=(page - 1) * page_size, limit=page_size)
    counts = await users.counts_by_role()
    return paginate(
        [RoleOut.from_doc(r, counts.get(r["name"], 0)) for r in items],
        await roles.count(),
        page,
        page_size,
    )


@router.get("/{name}", response_model=RoleOut)
async def get_role(
    name: str,
    _: Principal = Depends(require_permissions("roles:read")),
    roles: RolesRepository = Depends(get_roles_repo),
    users: UsersRepository = Depends(get_users_repo),
) -> RoleOut:
    role = await _load_role(roles, name)
    return RoleOut.from_doc(role, await users.count_with_role(name))


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    principal: Principal = Depends(require_permissions("roles:create")),
    roles: RolesRepository = Depends(get_roles_repo),
) -> RoleOut:
    _validate_permissions(payload.permissions)
    try:
        role = await roles.create(
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
            created_by=principal.user["email"],
        )
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A role named '{payload.name}' already exists") from None
    return RoleOut.from_doc(role)


@router.patch("/{name}", response_model=RoleOut)
async def update_role(
    name: str,
    payload: RoleUpdate,
    principal: Principal = Depends(require_permissions("roles:update")),
    roles: RolesRepository = Depends(get_roles_repo),
    users: UsersRepository = Depends(get_users_repo),
) -> RoleOut:
    await _load_role(roles, name)
    changes = payload.model_dump(exclude_unset=True)
    if "permissions" in changes:
        if changes["permissions"] is None:
            del changes["permissions"]
        else:
            _validate_permissions(changes["permissions"])
            if name == ADMIN_ROLE:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="The admin role always has every permission and can't be edited",
                )
            # Stop a role editor from locking themselves out of role management.
            if name == principal.user["role"] and "roles:update" not in changes["permissions"]:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="You can't remove 'roles:update' from your own role",
                )
    role = await roles.update(name, changes) if changes else await _load_role(roles, name)
    return RoleOut.from_doc(role, await users.count_with_role(name))  # type: ignore[arg-type]


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    name: str,
    _: Principal = Depends(require_permissions("roles:delete")),
    roles: RolesRepository = Depends(get_roles_repo),
    users: UsersRepository = Depends(get_users_repo),
) -> None:
    role = await _load_role(roles, name)
    if role.get("is_system") or name in (ADMIN_ROLE, DEFAULT_ROLE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="System roles can't be deleted")
    assigned = await users.count_with_role(name)
    if assigned:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Cannot delete role '{name}': {assigned} user(s) are assigned to it",
        )
    await roles.delete(name)
