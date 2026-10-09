from __future__ import annotations

import json

import pytest

from app.core.config import Settings, get_settings
from conftest import run_sql

ASSETS = [
    ("NVDA", "NVIDIA Corporation", "stock", "AI chips", "Information Technology", ["semiconductors", "gpu"], True,
     {"volatility_1y": 0.38, "beta": 1.9, "max_drawdown_1y": -0.2, "dividend_yield": 0.002, "history_days": 252}),
    ("AMD", "Advanced Micro Devices, Inc.", "stock", "AI chips", "Information Technology", ["semiconductors", "gpu"], True,
     {"volatility_1y": 0.72, "beta": 3.1, "max_drawdown_1y": -0.28, "dividend_yield": 0.0}),
    ("XLV", "Health Care Select Sector SPDR Fund", "etf", "Healthcare ETF", "Health Care", ["healthcare"], True,
     {"volatility_1y": 0.16, "beta": 0.3, "max_drawdown_1y": -0.1, "dividend_yield": 0.015}),
    ("HIDE", "Hidden Health Inc.", "stock", "Healthcare", "Health Care", ["pharmaceuticals"], False, None),
]

PROFILE = {
    "risk_level": "moderate",
    "interests": ["technology", "healthcare"],
    "asset_types": "both",
    "followed_tickers": ["NVDA"],
}


@pytest.fixture
def seeded(client):
    for ticker, name, asset_type, category, sector, themes, eligible, risk in ASSETS:
        run_sql(
            "INSERT INTO assets (ticker, name, asset_type, category, sector, themes, recommendation_eligible, as_of, risk)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, '2026-09-18', $8::jsonb)",
            ticker, name, asset_type, category, sector, themes, eligible, json.dumps(risk) if risk else None,
        )
    return client


def test_requires_sign_in(seeded):
    seeded.cookies.clear()
    assert seeded.get("/api/dashboard").status_code == 401


def test_asks_for_a_profile_first(seeded, admin):
    assert seeded.get("/api/dashboard", headers=admin).status_code == 409


def test_summarises_the_profile_watchlist_and_suggestions(seeded, admin):
    seeded.put("/api/profile", headers=admin, json=PROFILE)
    body = seeded.get("/api/dashboard", headers=admin).json()

    assert body["risk_level"] == {"key": "moderate", "label": "Moderate", "volatility_limit": 0.35, "step": 3, "steps": 5}
    assert body["interests"] == [{"key": "technology", "label": "Technology"}, {"key": "healthcare", "label": "Healthcare"}]
    assert body["prices_as_of"] == "2026-09-18"

    assert [a["ticker"] for a in body["watchlist"]] == ["NVDA"]
    assert body["watchlist"][0]["risk"] == {"volatility_1y": 0.38, "beta": 1.9, "max_drawdown_1y": -0.2, "dividend_yield": 0.002}

    suggested = {s["ticker"]: s for s in body["suggestions"]}
    assert set(suggested) == {"AMD", "XLV"}  # NVDA is followed; HIDE is not recommendable
    assert suggested["AMD"]["risk"]["volatility_1y"] == 0.72
    assert suggested["AMD"]["reasons"][-1].startswith("Yearly price swings of 72%")


def test_suggestion_count_follows_the_recommendations_limit_setting(seeded, admin):
    seeded.put("/api/profile", headers=admin, json=PROFILE)
    seeded.app.dependency_overrides[get_settings] = lambda: Settings(recommendations_limit=1)
    assert len(seeded.get("/api/dashboard", headers=admin).json()["suggestions"]) == 1
