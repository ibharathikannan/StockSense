"""One-off copy of roles, users and investor profiles from the old MongoDB database into PostgreSQL.

Assets are not copied: load them from the source file with ``python -m scripts.import_assets``.

Safe to re-run: roles are upserted by name, users already present (same email) are kept as they
are, and profiles are only added for users that don't have one. Mongo ObjectIds become new UUIDs,
so sessions issued before the migration stop working and everyone signs in again.

Needs pymongo, which is no longer an app dependency. From backend/ with the venv active:

    pip install "pymongo>=4.13"
    # PostgreSQL target: the POSTGRES_* settings in .env. MongoDB source: these two variables.
    MONGO_URI="mongodb+srv://..." MONGO_DB_NAME=stocksensedb python -m scripts.migrate_from_mongo
"""

from __future__ import annotations

import asyncio
import os

from app.core.config import get_settings
from app.db.postgres import create_pool, ensure_schema


def _read_mongo() -> dict[str, list[dict]]:
    try:
        from pymongo import MongoClient
    except ImportError:
        raise SystemExit('pymongo is not installed: pip install "pymongo>=4.13"') from None
    uri, db_name = os.environ.get("MONGO_URI"), os.environ.get("MONGO_DB_NAME")
    if not (uri and db_name):
        raise SystemExit("Set MONGO_URI and MONGO_DB_NAME to the MongoDB database to copy from.")
    with MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=10000) as client:
        db = client[db_name]
        return {name: list(db[name].find()) for name in ("roles", "users", "profiles")}


async def main() -> None:
    source = _read_mongo()
    settings = get_settings()
    pool = await create_pool(settings)
    try:
        await ensure_schema(pool)
        async with pool.acquire() as conn, conn.transaction():
            for r in source["roles"]:
                await conn.execute(
                    """
                    INSERT INTO roles (name, description, permissions, is_system, created_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description, permissions = EXCLUDED.permissions,
                        updated_at = EXCLUDED.updated_at
                    """,
                    r["name"], r.get("description"), sorted(set(r.get("permissions", []))),
                    r.get("is_system", False), r.get("created_by"), r["created_at"], r.get("updated_at"),
                )

            user_ids = {}  # Mongo ObjectId -> PostgreSQL UUID
            added_users = 0
            for u in source["users"]:
                new_id = await conn.fetchval(
                    """
                    INSERT INTO users (email, full_name, password_hash, role, is_active,
                                       created_at, updated_at, last_login_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                    """,
                    u["email"].strip().lower(), u.get("full_name", ""), u["password_hash"], u["role"],
                    u.get("is_active", True), u["created_at"], u.get("updated_at"), u.get("last_login_at"),
                )
                if new_id is None:  # already migrated, or created by the startup seed
                    new_id = await conn.fetchval("SELECT id FROM users WHERE email = $1", u["email"].strip().lower())
                else:
                    added_users += 1
                user_ids[u["_id"]] = new_id

            added_profiles = 0
            for p in source["profiles"]:
                user_id = user_ids.get(p["user_id"])
                if user_id is None:  # orphaned profile
                    continue
                status = await conn.execute(
                    """
                    INSERT INTO profiles (user_id, risk_level, interests, asset_types, followed_tickers,
                                          completed_at, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    user_id, p["risk_level"], p["interests"], p["asset_types"], p["followed_tickers"],
                    p["completed_at"], p["created_at"], p["updated_at"],
                )
                added_profiles += status == "INSERT 0 1"

        print(f"Into '{settings.postgres_db}' on {settings.postgres_host}:")
        print(f"  roles {len(source['roles'])} upserted")
        print(f"  users {added_users} added, {len(source['users']) - added_users} already present")
        print(f"  profiles {added_profiles} added (of {len(source['profiles'])})")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
