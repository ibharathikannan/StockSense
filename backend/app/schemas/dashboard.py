from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class AssetRisk(BaseModel):
    """One-year numbers from data/build_asset_profiles.py; null when price history is too short."""

    volatility_1y: float | None = None
    beta: float | None = None
    max_drawdown_1y: float | None = None
    dividend_yield: float | None = None


class DashboardAsset(BaseModel):
    ticker: str
    name: str
    asset_type: str
    category: str | None
    sector: str
    risk: AssetRisk | None


class DashboardSuggestion(DashboardAsset):
    score: float  # 0-1 similarity to the profile, for ordering; not a forecast
    reasons: list[str]  # content reasons first; the last one is always about risk


class DashboardRiskLevel(BaseModel):
    key: str
    label: str
    volatility_limit: float
    step: int | None  # position on the conservative-to-aggressive scale, 1-based
    steps: int


class DashboardInterest(BaseModel):
    key: str
    label: str


class DashboardOut(BaseModel):
    risk_level: DashboardRiskLevel
    interests: list[DashboardInterest]
    asset_types: str
    prices_as_of: date | None
    watchlist: list[DashboardAsset]
    suggestions: list[DashboardSuggestion]
