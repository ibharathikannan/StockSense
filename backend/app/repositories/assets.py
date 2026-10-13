from __future__ import annotations

from datetime import date
from typing import Any

import asyncpg

from app.db.postgres import like_pattern

_UPSERT = """
INSERT INTO assets (ticker, name, asset_type, category, sector, themes, recommendation_eligible,
                    forecast_eligible, history_note, as_of, risk, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now(), now())
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    asset_type = EXCLUDED.asset_type,
    category = EXCLUDED.category,
    sector = EXCLUDED.sector,
    themes = EXCLUDED.themes,
    recommendation_eligible = EXCLUDED.recommendation_eligible,
    forecast_eligible = EXCLUDED.forecast_eligible,
    history_note = EXCLUDED.history_note,
    as_of = EXCLUDED.as_of,
    risk = EXCLUDED.risk,
    updated_at = EXCLUDED.updated_at
RETURNING (xmax = 0) AS inserted
"""


def _upsert_args(asset: dict[str, Any]) -> tuple[Any, ...]:
    as_of = asset.get("as_of")
    return (
        asset["ticker"],
        asset["name"],
        asset["asset_type"],
        asset.get("category"),
        asset["sector"],
        asset.get("themes", []),
        asset.get("recommendation_eligible", False),
        asset.get("forecast_eligible", False),
        asset.get("history_note"),
        date.fromisoformat(as_of) if isinstance(as_of, str) else as_of,
        asset.get("risk"),
    )


class AssetsRepository:
    """The recommendable stocks/ETFs (one row per ticker, loaded from data/processed/asset_profiles.json)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, assets: list[dict[str, Any]]) -> tuple[int, int]:
        """Insert new tickers and update existing ones. Returns (inserted, updated); safe to re-run."""
        inserted = 0
        async with self._pool.acquire() as conn, conn.transaction():
            for asset in assets:
                # xmax = 0 only for a freshly inserted row, which tells inserts and updates apart.
                inserted += bool(await conn.fetchval(_UPSERT, *_upsert_args(asset)))
        return inserted, len(assets) - inserted

    async def count(self) -> int:
        return await self._pool.fetchval("SELECT count(*) FROM assets")

    async def count_matching(self, sectors: list[str], themes: list[str]) -> int:
        """Recommendable assets whose sector is in `sectors` or that carry any of `themes`."""
        if not sectors and not themes:
            return 0
        return await self._pool.fetchval(
            """
            SELECT count(*) FROM assets
            WHERE recommendation_eligible AND (sector = ANY($1::text[]) OR themes && $2::text[])
            """,
            sectors,
            themes,
        )

    async def eligible_tickers(self, tickers: list[str]) -> set[str]:
        """Which of `tickers` exist and may be recommended/followed."""
        rows = await self._pool.fetch(
            "SELECT ticker FROM assets WHERE ticker = ANY($1::text[]) AND recommendation_eligible", tickers
        )
        return {r["ticker"] for r in rows}

    async def list_recommendable(self) -> list[dict[str, Any]]:
        """Every recommendable asset with the content the recommender compares."""
        rows = await self._pool.fetch(
            """
            SELECT ticker, name, asset_type, category, sector, themes, risk, as_of FROM assets
            WHERE recommendation_eligible
            ORDER BY ticker
            """
        )
        return [dict(r) for r in rows]

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Type-ahead: ticker prefix or name substring, case-insensitive."""
        contains = like_pattern(query.strip())
        rows = await self._pool.fetch(
            """
            SELECT ticker, name, asset_type, sector FROM assets
            WHERE recommendation_eligible AND (ticker ILIKE $1 OR name ILIKE $2)
            ORDER BY ticker
            LIMIT $3
            """,
            contains[1:],  # drop the leading % so the ticker match is a prefix match
            contains,
            limit,
        )
        return [dict(r) for r in rows]
