from __future__ import annotations

from typing import Any

import asyncpg

# Columns a caller may change through ``update``; guards the dynamic SET clause.
_UPDATABLE = {"description", "permissions"}


class RolesRepository:
    """Roles are identified by their unique, immutable ``name``.

    ``create`` raises ``asyncpg.UniqueViolationError`` on a name clash.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, name: str) -> dict[str, Any] | None:
        row = await self._pool.fetchrow("SELECT * FROM roles WHERE name = $1", name)
        return dict(row) if row else None

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM roles ORDER BY is_system DESC, name OFFSET $1 LIMIT $2", skip, limit
        )
        return [dict(r) for r in rows]

    async def count(self) -> int:
        return await self._pool.fetchval("SELECT count(*) FROM roles")

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        permissions: list[str],
        is_system: bool = False,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        row = await self._pool.fetchrow(
            """
            INSERT INTO roles (name, description, permissions, is_system, created_by, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, now(), now())
            RETURNING *
            """,
            name,
            description,
            sorted(set(permissions)),
            is_system,
            created_by,
        )
        return dict(row)

    async def update(self, name: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"Not updatable: {', '.join(sorted(unknown))}")
        if "permissions" in fields:
            fields = {**fields, "permissions": sorted(set(fields["permissions"]))}
        columns = list(fields)
        assignments = "".join(f"{col} = ${i}, " for i, col in enumerate(columns, start=2))
        row = await self._pool.fetchrow(
            f"UPDATE roles SET {assignments}updated_at = now() WHERE name = $1 RETURNING *",
            name,
            *(fields[c] for c in columns),
        )
        return dict(row) if row else None

    async def delete(self, name: str) -> bool:
        return await self._pool.execute("DELETE FROM roles WHERE name = $1", name) != "DELETE 0"
