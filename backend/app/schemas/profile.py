from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.onboarding import INTERESTS, MAX_FOLLOWED_TICKERS


class ProfileIn(BaseModel):
    """What the onboarding page submits. Keys are validated against app/core/onboarding.py."""

    risk_level: str
    interests: list[str] = Field(min_length=1, max_length=len(INTERESTS))
    asset_types: str = "both"
    followed_tickers: list[str] = Field(default_factory=list, max_length=MAX_FOLLOWED_TICKERS)


class ProfileOut(BaseModel):
    risk_level: str
    interests: list[str]
    asset_types: str
    followed_tickers: list[str]
    completed_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "ProfileOut":
        return cls(
            risk_level=doc["risk_level"],
            interests=doc["interests"],
            asset_types=doc["asset_types"],
            followed_tickers=doc["followed_tickers"],
            completed_at=doc["completed_at"],
            updated_at=doc["updated_at"],
        )


class RiskLevelOption(BaseModel):
    key: str
    label: str
    description: str


class InterestOption(BaseModel):
    key: str
    label: str
    asset_count: int  # recommendable assets behind this interest


class AssetTypeOption(BaseModel):
    key: str
    label: str


class ProfileOptions(BaseModel):
    risk_levels: list[RiskLevelOption]
    interests: list[InterestOption]
    asset_types: list[AssetTypeOption]
    max_followed: int


class AssetSummary(BaseModel):
    ticker: str
    name: str
    asset_type: str
    sector: str

class AssetEvaluationRequest(BaseModel):
    forecast_return: float = Field(..., description="Projected 10-day return % (e.g. 2.5 for +2.5%)")
    volatility: float | None = Field(None, description="Annualized volatility. If None, pulled from asset profile.")
    sentiment_score: float | None = Field(None, ge=-1.0, le=1.0, description="News sentiment between -1.0 and 1.0")
    prediction_interval_width: float | None = Field(None, ge=0.0, description="Width of prediction uncertainty interval %")
    user_risk_profile: str | None = Field("moderate", description="User risk tier (e.g. conservative, moderate, growth)")


class AssetStanceResponse(BaseModel):
    ticker: str
    stance: str
    decision_trace: list[str]
