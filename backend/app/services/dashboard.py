from __future__ import annotations

import uuid
from typing import Any

from app.core.onboarding import INTERESTS, RISK_LEVELS
from app.recommender.content_based import volatility_limit
from app.repositories.assets import AssetsRepository
from app.repositories.profiles import ProfilesRepository
from app.services.errors import Conflict
from app.services.recommendations import PROFILE_REQUIRED, recommend_for_profile

_INTEREST_LABELS = {i["key"]: i["label"] for i in INTERESTS}
_RISK_STEPS = [r["key"] for r in RISK_LEVELS]
_RISK_LABELS = {r["key"]: r["label"] for r in RISK_LEVELS}


class DashboardService:
    """Everything the signed-in investor's dashboard shows, in one read."""

    def __init__(self, profiles: ProfilesRepository, assets: AssetsRepository) -> None:
        self._profiles = profiles
        self._assets = assets

    async def for_user(self, user_id: uuid.UUID, suggestion_limit: int) -> dict[str, Any]:
        profile = await self._profiles.get(user_id)
        if not profile:
            raise Conflict(PROFILE_REQUIRED)
        catalogue = await self._assets.list_recommendable()
        by_ticker = {a["ticker"]: a for a in catalogue}
        suggestions = recommend_for_profile(profile, catalogue, suggestion_limit)
        risk_key = profile["risk_level"]

        return {
            "risk_level": {
                "key": risk_key,
                "label": _RISK_LABELS.get(risk_key, risk_key),
                "volatility_limit": volatility_limit(risk_key),
                "step": _RISK_STEPS.index(risk_key) + 1 if risk_key in _RISK_STEPS else None,
                "steps": len(_RISK_STEPS),
            },
            "interests": [{"key": k, "label": _INTEREST_LABELS[k]} for k in profile["interests"] if k in _INTEREST_LABELS],
            "asset_types": profile["asset_types"],
            "prices_as_of": max((a["as_of"] for a in catalogue if a.get("as_of")), default=None),
            # A followed ticker that is no longer recommendable is left out rather than shown without data.
            "watchlist": [by_ticker[t] for t in profile["followed_tickers"] if t in by_ticker],
            "suggestions": [{**by_ticker[r.ticker], "score": r.score, "reasons": list(r.reasons)} for r in suggestions],
        }
