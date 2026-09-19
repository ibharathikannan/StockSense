from __future__ import annotations

import logging

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.permissions import ADMIN_ROLE, ALL_PERMISSIONS, DEFAULT_ROLE
from app.core.security import hash_password
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository

logger = logging.getLogger(__name__)

# Roles every deployment needs. Add your own defaults here (e.g. an "analyst"
# role) — they're only created if missing, so edits made in the UI are kept.
SYSTEM_ROLES = [
    {
        "name": ADMIN_ROLE,
        "description": "Full access. Always holds every permission.",
        "permissions": ALL_PERMISSIONS,
    },
    {
        "name": DEFAULT_ROLE,
        "description": "Default role for new users. Can sign in and manage their own account.",
        "permissions": [],
    },
]


async def seed_defaults(db: AsyncDatabase, settings: Settings) -> None:
    """Idempotent bootstrap, run at every startup."""
    roles = RolesRepository(db)
    for role in SYSTEM_ROLES:
        if not await roles.get(role["name"]):
            try:
                await roles.create(is_system=True, created_by="system", **role)
                logger.info("Created system role '%s'", role["name"])
            except DuplicateKeyError:  # another worker won the race
                pass

    users = UsersRepository(db)
    if await users.count_total() > 0:
        return
    if not (settings.first_admin_email and settings.first_admin_password):
        logger.warning("No users exist and FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD are not set — nobody can sign in")
        return
    password_hash = await run_in_threadpool(hash_password, settings.first_admin_password)
    try:
        await users.create(
            email=settings.first_admin_email,
            full_name=settings.first_admin_name,
            password_hash=password_hash,
            role=ADMIN_ROLE,
        )
        logger.info("Created first administrator %s — change this password after signing in", settings.first_admin_email)
    except DuplicateKeyError:
        pass
