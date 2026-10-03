from __future__ import annotations

from typing import Any

import asyncpg

from app.db.postgres import like_pattern, to_uuid

# Columns a caller may change through ``update``; guards the dynamic SET clause.
_UPDATABLE = {"full_name", "password_hash", "role", "is_active"}


class UsersRepository:
    """Thin data-access layer over the ``users`` table.

    ``create`` raises ``asyncpg.UniqueViolationError`` if the email exists
    (unique constraint) — callers map that to a 409.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_id(self, user_id: Any) -> dict[str, Any] | None:
        uid = to_uuid(user_id)
        if uid is None:
            return None
        row = await self._pool.fetchrow("SELECT * FROM users WHERE id = $1", uid)
        return dict(row) if row else None

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        row = await self._pool.fetchrow("SELECT * FROM users WHERE email = $1", email.strip().lower())
        return dict(row) if row else None

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        password_hash: str,
        role: str,
        is_active: bool = True,
    ) -> dict[str, Any]:
        row = await self._pool.fetchrow(
            """
            INSERT INTO users (email, full_name, password_hash, role, is_active, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, now(), now())
            RETURNING *
            """,
            email.strip().lower(),
            full_name.strip(),
            password_hash,
            role,
            is_active,
        )
        return dict(row)

    async def list(self, *, skip: int, limit: int, search: str | None = None) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM users
            WHERE $1::text IS NULL OR email ILIKE $1 OR full_name ILIKE $1
            ORDER BY created_at DESC, id
            OFFSET $2 LIMIT $3
            """,
            self._search_pattern(search),
            skip,
            limit,
        )
        return [dict(r) for r in rows]

    async def count(self, search: str | None = None) -> int:
        return await self._pool.fetchval(
            "SELECT count(*) FROM users WHERE $1::text IS NULL OR email ILIKE $1 OR full_name ILIKE $1",
            self._search_pattern(search),
        )

    @staticmethod
    def _search_pattern(search: str | None) -> str | None:
        return like_pattern(search.strip()) if search and search.strip() else None

    async def update(self, user_id: Any, fields: dict[str, Any]) -> dict[str, Any] | None:
        uid = to_uuid(user_id)
        if uid is None:
            return None
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"Not updatable: {', '.join(sorted(unknown))}")
        columns = list(fields)
        assignments = "".join(f"{col} = ${i}, " for i, col in enumerate(columns, start=2))
        row = await self._pool.fetchrow(
            f"UPDATE users SET {assignments}updated_at = now() WHERE id = $1 RETURNING *",
            uid,
            *(fields[c] for c in columns),
        )
        return dict(row) if row else None

    async def touch_last_login(self, user_id: Any) -> None:
        await self._pool.execute("UPDATE users SET last_login_at = now() WHERE id = $1", to_uuid(user_id))

    async def delete(self, user_id: Any) -> bool:
        uid = to_uuid(user_id)
        if uid is None:
            return False
        return await self._pool.execute("DELETE FROM users WHERE id = $1", uid) != "DELETE 0"

    async def count_total(self) -> int:
        return await self._pool.fetchval("SELECT count(*) FROM users")

    async def count_active_with_role(self, role: str) -> int:
        return await self._pool.fetchval("SELECT count(*) FROM users WHERE role = $1 AND is_active", role)

    async def count_with_role(self, role: str) -> int:
        return await self._pool.fetchval("SELECT count(*) FROM users WHERE role = $1", role)

    async def counts_by_role(self) -> dict[str, int]:
        rows = await self._pool.fetch("SELECT role, count(*) AS n FROM users GROUP BY role")
        return {r["role"]: r["n"] for r in rows}
