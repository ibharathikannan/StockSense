from __future__ import annotations

from pydantic import BaseModel


class RecommendationOut(BaseModel):
    ticker: str
    name: str
    asset_type: str
    category: str | None
    sector: str
    score: float  # 0-1 similarity to the profile, for ordering; not a forecast
    reasons: list[str]
