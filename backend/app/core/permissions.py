"""The permission catalogue — the single source of truth for authorization.

Permissions are plain ``resource:action`` strings. Roles (stored in MongoDB)
are just named sets of these strings, and endpoints are protected with
``require_permissions("users:read")`` (see ``app/api/deps.py``).

To protect a new module, add its permissions here — they show up in the role
editor automatically (the frontend reads them from ``GET /api/roles/permissions``).
"""

from __future__ import annotations

ADMIN_ROLE = "admin"
DEFAULT_ROLE = "user"

# key -> human description
PERMISSIONS: dict[str, str] = {
    "users:read": "View users",
    "users:create": "Create users",
    "users:update": "Edit users (role, status, reset password)",
    "users:delete": "Delete users",
    "roles:read": "View roles",
    "roles:create": "Create roles",
    "roles:update": "Edit roles and their permissions",
    "roles:delete": "Delete roles",
}

ALL_PERMISSIONS: list[str] = list(PERMISSIONS)


def group_of(permission: str) -> str:
    return permission.split(":", 1)[0]


def effective_permissions(role: dict | None) -> set[str]:
    """Permissions a role grants right now.

    The ``admin`` role always holds every permission in the catalogue, so a
    permission added later is granted to admins without a data migration.
    Permissions stored on a role but no longer in the catalogue are ignored.
    """
    if role is None:
        return set()
    if role["name"] == ADMIN_ROLE:
        return set(ALL_PERMISSIONS)
    return {p for p in role.get("permissions", []) if p in PERMISSIONS}
