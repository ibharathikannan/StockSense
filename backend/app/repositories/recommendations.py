from __future__ import annotations

from typing import Any

import asyncpg

# A snapshot joined with its asset metadata, shaped for RecommendationSnapshot.from_row.
_SELECT = """
    SELECT rs.ticker, a.name, a.sector, a.asset_type, rs.as_of,
           rs.baseline_stance, rs.news_aware_stance, rs.provisional, rs.risk_profile,
           rs.forecast, rs.signal_detail, rs.evidence, rs.explanation
    FROM recommendation_snapshots rs
    JOIN assets a ON a.ticker = rs.ticker
"""


class RecommendationsRepository:
    """Precomputed research snapshots (one row per ticker x risk tier), written by the offline
    assembler and served read-only to the dashboard."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, ticker: str, risk_profile: str) -> dict[str, Any] | None:
        row = await self._pool.fetchrow(
            _SELECT + " WHERE UPPER(rs.ticker) = UPPER($1) AND rs.risk_profile = $2",
            ticker.strip(), risk_profile,
        )
        return dict(row) if row else None

    async def list_for_profile(self, risk_profile: str, sectors: list[str], themes: list[str],
                               limit: int) -> list[dict[str, Any]]:
        """Recommendation-eligible snapshots at this risk tier whose asset matches the user's
        interests (sector in `sectors` or any theme in `themes`)."""
        if not sectors and not themes:
            return []
        rows = await self._pool.fetch(
            _SELECT + """
            WHERE rs.risk_profile = $1 AND a.recommendation_eligible
              AND (a.sector = ANY($2::text[]) OR a.themes && $3::text[])
            ORDER BY rs.ticker
            LIMIT $4
            """,
            risk_profile, sectors, themes, limit,
        )
        return [dict(r) for r in rows]

    async def followed_sectors(self, tickers: list[str]) -> dict[str, str]:
        """Sector of each followed ticker (for the request-time diversification check)."""
        if not tickers:
            return {}
        rows = await self._pool.fetch(
            "SELECT ticker, sector FROM assets WHERE ticker = ANY($1::text[])", tickers
        )
        return {r["ticker"]: r["sector"] for r in rows}

    async def upsert_many(self, snapshots: list[dict[str, Any]]) -> int:
        """Load/refresh snapshots from the assembler. Idempotent on (ticker, risk_profile)."""
        sql = """
            INSERT INTO recommendation_snapshots
                (ticker, risk_profile, as_of, baseline_stance, news_aware_stance, provisional,
                 forecast, signal_detail, evidence, explanation, generated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
            ON CONFLICT (ticker, risk_profile) DO UPDATE SET
                as_of = EXCLUDED.as_of, baseline_stance = EXCLUDED.baseline_stance,
                news_aware_stance = EXCLUDED.news_aware_stance, provisional = EXCLUDED.provisional,
                forecast = EXCLUDED.forecast, signal_detail = EXCLUDED.signal_detail,
                evidence = EXCLUDED.evidence, explanation = EXCLUDED.explanation,
                generated_at = now()
        """
        async with self._pool.acquire() as conn, conn.transaction():
            for s in snapshots:
                await conn.execute(
                    sql, s["ticker"], s["risk_profile"], s["as_of"], s["baseline_stance"],
                    s["news_aware_stance"], s["provisional"], s["forecast"], s["signal_detail"],
                    s["evidence"], s["explanation"],
                )
        return len(snapshots)
