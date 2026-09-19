from __future__ import annotations

from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.core.permissions import ADMIN_ROLE
from app.core.security import hash_password
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository
from app.services.errors import BadRequest, Conflict, Forbidden, NotFound


class UserService:
    """Business rules for user management.

    Used by the admin ``/api/users`` routes and (for creation) by public
    registration, so the rules live in exactly one place. Methods take the
    acting user's id/admin flag as plain values — no dependency on the HTTP layer.
    """

    def __init__(self, users: UsersRepository, roles: RolesRepository) -> None:
        self._users = users
        self._roles = roles

    # ---- reads -------------------------------------------------------------

    async def get(self, user_id: str) -> dict[str, Any]:
        user = await self._users.get_by_id(user_id)
        if not user:
            raise NotFound("User not found")
        return user

    async def list_page(self, *, page: int, page_size: int, search: str | None) -> tuple[list[dict[str, Any]], int]:
        items = await self._users.list(skip=(page - 1) * page_size, limit=page_size, search=search)
        return items, await self._users.count(search=search)

    # ---- writes ------------------------------------------------------------

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        password: str,
        role: str,
        is_active: bool = True,
        actor_is_admin: bool = False,
    ) -> dict[str, Any]:
        """Create a user. The single place that hashes the password and inserts.

        ``actor_is_admin`` defaults to False (fail closed): only an admin
        caller may create an administrator, so public registration can never
        produce one.
        """
        await self._assert_role_exists(role)
        if role == ADMIN_ROLE and not actor_is_admin:
            raise Forbidden("Only administrators can create administrators")

        password_hash = await run_in_threadpool(hash_password, password)
        try:
            return await self._users.create(
                email=email,
                full_name=full_name,
                password_hash=password_hash,
                role=role,
                is_active=is_active,
            )
        except DuplicateKeyError:
            raise Conflict("A user with this email already exists") from None

    async def update(
        self, user_id: str, changes: dict[str, Any], *, actor_id: ObjectId, actor_is_admin: bool
    ) -> dict[str, Any]:
        """Apply a partial update. ``changes`` may contain full_name, role, is_active, password."""
        target = await self.get(user_id)
        changes = {k: v for k, v in changes.items() if v is not None}

        is_self = target["_id"] == actor_id
        new_role = changes.get("role", target["role"])
        role_changes = new_role != target["role"]
        deactivating = changes.get("is_active") is False and target.get("is_active", True)

        if is_self and (role_changes or deactivating):
            raise BadRequest("You can't change your own role or deactivate your own account")
        # Touching an administrator, or granting the admin role, is admin-only —
        # otherwise 'users:update' would be a path to privilege escalation.
        if (target["role"] == ADMIN_ROLE or new_role == ADMIN_ROLE) and not actor_is_admin:
            raise Forbidden("Only administrators can modify administrators or grant the admin role")
        if role_changes:
            await self._assert_role_exists(new_role)
        if role_changes or deactivating:
            await self._assert_not_last_admin(target)

        if "password" in changes:
            changes["password_hash"] = await run_in_threadpool(hash_password, changes.pop("password"))

        if not changes:
            return target
        return await self._users.update(user_id, changes)  # type: ignore[return-value]

    async def delete(self, user_id: str, *, actor_id: ObjectId, actor_is_admin: bool) -> None:
        target = await self.get(user_id)
        if target["_id"] == actor_id:
            raise BadRequest("You can't delete your own account")
        if target["role"] == ADMIN_ROLE and not actor_is_admin:
            raise Forbidden("Only administrators can delete administrators")
        await self._assert_not_last_admin(target)
        await self._users.delete(user_id)

    # ---- rules -------------------------------------------------------------

    async def _assert_role_exists(self, name: str) -> None:
        if not await self._roles.get(name):
            raise BadRequest(f"Role '{name}' does not exist")

    async def _assert_not_last_admin(self, target: dict[str, Any]) -> None:
        """Never let the system end up with no active administrator."""
        if target["role"] == ADMIN_ROLE and target.get("is_active", True):
            if await self._users.count_active_with_role(ADMIN_ROLE) <= 1:
                raise BadRequest("This is the last active administrator")
