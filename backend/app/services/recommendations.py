from __future__ import annotations

from typing import Any

from app.repositories.recommendations import RecommendationsRepository
from app.schemas.recommendations import DiscoveryResponse, DiversificationNote, RecommendationSnapshot
from app.services.discovery import diversification as compute_diversification
from app.services.discovery import interest_targets
from app.services.errors import NotFound


class RecommendationService:
    """Serves precomputed snapshots and layers on the request-time, per-user view:
    the matching discovery set and a diversification note from the user's followed assets.
    The news-aware stance is the operative signal (see docs/ai/OPERATIONAL_MODEL.md)."""

    def __init__(self, recs: RecommendationsRepository) -> None:
        self._recs = recs

    async def get_detail(self, ticker: str, profile: dict[str, Any]) -> RecommendationSnapshot:
        row = await self._recs.get(ticker, profile["risk_level"])
        if not row:
            raise NotFound(f"No recommendation available for '{ticker.strip().upper()}'.")
        return RecommendationSnapshot.from_row(row)

    async def get_discovery(self, profile: dict[str, Any], limit: int = 20) -> DiscoveryResponse:
        sectors, themes = interest_targets(profile.get("interests") or [])
        rows = await self._recs.list_for_profile(profile["risk_level"], list(sectors),
                                                 list(themes), limit)
        candidates = [RecommendationSnapshot.from_row(r) for r in rows]

        followed = profile.get("followed_tickers") or []
        followed_sectors = await self._recs.followed_sectors(followed)
        assets_by_ticker = {t: {"ticker": t, "sector": s} for t, s in followed_sectors.items()}
        cand_dicts = [{"ticker": c.ticker, "sector": c.sector} for c in candidates]
        div = compute_diversification(assets_by_ticker, profile, cand_dicts)

        return DiscoveryResponse(candidates=candidates, diversification=DiversificationNote(**div))
