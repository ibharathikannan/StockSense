from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.recommender import ContentBasedRecommender, Recommendation
from app.repositories.assets import AssetsRepository
from app.repositories.profiles import ProfilesRepository
from app.services.errors import Conflict

PROFILE_REQUIRED = "Complete your investor profile to get suggestions"


def recommend_for_profile(
    profile: Mapping[str, Any], catalogue: Sequence[Mapping[str, Any]], limit: int
) -> list[Recommendation]:
    """Rank the catalogue for a saved investor profile (an empty catalogue gives no suggestions)."""
    if not catalogue:
        return []
    # Fitted per call (about 10 ms for the 90-asset catalogue), so it is never stale.
    return ContentBasedRecommender(catalogue).recommend(
        interests=profile["interests"],
        followed_tickers=profile["followed_tickers"],
        risk_level=profile["risk_level"],
        asset_types=profile["asset_types"],
        limit=limit,
    )


class RecommendationService:
    """Content-based suggestions: catalogue assets that resemble the investor's profile."""

    def __init__(self, profiles: ProfilesRepository, assets: AssetsRepository) -> None:
        self._profiles = profiles
        self._assets = assets

    async def for_user(self, user_id: uuid.UUID, limit: int) -> list[Recommendation]:
        profile = await self._profiles.get(user_id)
        if not profile:
            raise Conflict(PROFILE_REQUIRED)
        return recommend_for_profile(profile, await self._assets.list_recommendable(), limit)
