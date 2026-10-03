from __future__ import annotations

import uuid
from typing import Any

import asyncpg


class ProfilesRepository:
    """Investor profiles: at most one row per user (``user_id`` is the primary key).

    Profiles are removed with their user by the ``ON DELETE CASCADE`` foreign key.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        row = await self._pool.fetchrow("SELECT * FROM profiles WHERE user_id = $1", user_id)
        return dict(row) if row else None

    async def upsert(self, user_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        """Create the profile, or replace its answers. ``completed_at`` is set once, on first save."""
        row = await self._pool.fetchrow(
            """
            INSERT INTO profiles (user_id, risk_level, interests, asset_types, followed_tickers,
                                  completed_at, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, now(), now(), now())
            ON CONFLICT (user_id) DO UPDATE SET
                risk_level = EXCLUDED.risk_level,
                interests = EXCLUDED.interests,
                asset_types = EXCLUDED.asset_types,
                followed_tickers = EXCLUDED.followed_tickers,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            user_id,
            data["risk_level"],
            data["interests"],
            data["asset_types"],
            data["followed_tickers"],
        )
        return dict(row)
