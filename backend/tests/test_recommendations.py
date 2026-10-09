from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from conftest import login, make_user, run_sql

ASSETS = [
    ("NVDA", "NVIDIA Corporation", "stock", "AI chips", "Information Technology", ["semiconductors", "gpu"], True, 0.38),
    ("AMD", "Advanced Micro Devices, Inc.", "stock", "AI chips", "Information Technology", ["semiconductors", "gpu", "cpu"], True, 0.72),
    ("XLV", "Health Care Select Sector SPDR Fund", "etf", "Healthcare ETF", "Health Care", ["healthcare"], True, 0.16),
    ("JNJ", "Johnson & Johnson", "stock", "Healthcare", "Health Care", ["pharmaceuticals"], True, 0.19),
    ("HIDE", "Hidden Health Inc.", "stock", "Healthcare", "Health Care", ["pharmaceuticals"], False, 0.10),
]

PROFILE = {
    "risk_level": "moderate",
    "interests": ["technology", "healthcare"],
    "asset_types": "both",
    "followed_tickers": ["NVDA"],
}


@pytest.fixture
def seeded(client):
    for ticker, name, asset_type, category, sector, themes, eligible, volatility in ASSETS:
        run_sql(
            "INSERT INTO assets (ticker, name, asset_type, category, sector, themes, recommendation_eligible, risk)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
            ticker, name, asset_type, category, sector, themes, eligible, json.dumps({"volatility_1y": volatility}),
        )
    return client


def test_requires_sign_in(seeded):
    seeded.cookies.clear()
    assert seeded.get("/api/recommendations").status_code == 401


def test_asks_for_a_profile_first(seeded, admin):
    res = seeded.get("/api/recommendations", headers=admin)
    assert res.status_code == 409
    assert "profile" in res.json()["detail"]


def test_suggests_matching_assets_with_reasons(seeded, admin):
    assert seeded.put("/api/profile", headers=admin, json=PROFILE).status_code == 200

    body = seeded.get("/api/recommendations", headers=admin).json()
    tickers = [r["ticker"] for r in body]
    assert set(tickers) == {"AMD", "XLV", "JNJ"}  # NVDA is followed; HIDE is not recommendable
    amd = next(r for r in body if r["ticker"] == "AMD")
    assert amd["reasons"][:2] == ["Matches your interest in Technology", "Similar to NVDA, which you follow"]
    assert amd["category"] == "AI chips" and 0 < amd["score"] <= 1


def test_respects_asset_type_and_limit(seeded, admin):
    seeded.put("/api/profile", headers=admin, json={**PROFILE, "asset_types": "etf"})
    assert [r["ticker"] for r in seeded.get("/api/recommendations", headers=admin).json()] == ["XLV"]

    seeded.put("/api/profile", headers=admin, json=PROFILE)
    assert len(seeded.get("/api/recommendations?limit=1", headers=admin).json()) == 1


@pytest.mark.parametrize("limit", [0, 21])
def test_rejects_out_of_range_limits(seeded, admin, limit):
    assert seeded.get(f"/api/recommendations?limit={limit}", headers=admin).status_code == 422


def test_default_count_comes_from_the_recommendations_limit_setting(seeded, admin):
    seeded.put("/api/profile", headers=admin, json=PROFILE)
    seeded.app.dependency_overrides[get_settings] = lambda: Settings(recommendations_limit=1)
    assert len(seeded.get("/api/recommendations", headers=admin).json()) == 1
    assert len(seeded.get("/api/recommendations?limit=2", headers=admin).json()) == 2  # an explicit limit wins


@pytest.mark.parametrize("value", [0, 21])
def test_recommendations_limit_setting_must_be_1_to_20(value):
    with pytest.raises(ValidationError):
        Settings(recommendations_limit=value)


def test_uses_only_the_callers_own_profile(seeded, admin):
    seeded.put("/api/profile", headers=admin, json=PROFILE)
    make_user(seeded, admin, "investor@example.com")
    investor = login(seeded, "investor@example.com", "Passw0rd!x")
    assert seeded.get("/api/recommendations", headers=investor).status_code == 409
