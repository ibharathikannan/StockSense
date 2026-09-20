from __future__ import annotations

from typing import Any

from bson import ObjectId

from app.core.onboarding import (
    ASSET_TYPE_CHOICES,
    ASSET_TYPE_KEYS,
    INTEREST_KEYS,
    INTERESTS,
    MAX_FOLLOWED_TICKERS,
    RISK_LEVEL_KEYS,
    RISK_LEVELS,
)
from app.repositories.assets import AssetsRepository
from app.repositories.profiles import ProfilesRepository
from app.services.errors import BadRequest


class ProfileService:
    """Investor profile: the answers from onboarding that personalise recommendations."""

    def __init__(self, profiles: ProfilesRepository, assets: AssetsRepository) -> None:
        self._profiles = profiles
        self._assets = assets

    async def get(self, user_id: ObjectId) -> dict[str, Any] | None:
        return await self._profiles.get(user_id)

    async def options(self) -> dict[str, Any]:
        """The choices for the form, with how many real assets sit behind each interest."""
        interests = [
            {
                "key": i["key"],
                "label": i["label"],
                "asset_count": await self._assets.count_matching(i["sectors"], i["themes"]),
            }
            for i in INTERESTS
        ]
        return {
            "risk_levels": RISK_LEVELS,
            "interests": interests,
            "asset_types": ASSET_TYPE_CHOICES,
            "max_followed": MAX_FOLLOWED_TICKERS,
        }

    async def save(
        self,
        user_id: ObjectId,
        *,
        risk_level: str,
        interests: list[str],
        asset_types: str,
        followed_tickers: list[str],
    ) -> dict[str, Any]:
        if risk_level not in RISK_LEVEL_KEYS:
            raise BadRequest(f"Unknown risk level '{risk_level}'")
        unknown = [i for i in interests if i not in INTEREST_KEYS]
        if unknown:
            raise BadRequest(f"Unknown interests: {', '.join(unknown)}")
        if asset_types not in ASSET_TYPE_KEYS:
            raise BadRequest(f"Unknown asset type '{asset_types}'")

        tickers = list(dict.fromkeys(t.strip().upper() for t in followed_tickers if t.strip()))  # dedupe, keep order
        known = await self._assets.eligible_tickers(tickers) if tickers else set()
        missing = [t for t in tickers if t not in known]
        if missing:
            raise BadRequest(f"Unknown tickers: {', '.join(missing)}")

        return await self._profiles.upsert(
            user_id,
            {
                "risk_level": risk_level,
                "interests": list(dict.fromkeys(interests)),
                "asset_types": asset_types,
                "followed_tickers": tickers,
            },
        )
