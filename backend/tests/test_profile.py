from __future__ import annotations

import pytest
from pymongo import MongoClient

from conftest import TEST_DB, TEST_MONGO_URI, login, make_user

ASSETS = [
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "asset_type": "stock", "sector": "Information Technology",
     "themes": ["semiconductors"], "recommendation_eligible": True},
    {"ticker": "FSLR", "name": "First Solar, Inc.", "asset_type": "stock", "sector": "Information Technology",
     "themes": ["solar_energy", "renewable_energy"], "recommendation_eligible": True},
    {"ticker": "XLV", "name": "Health Care Select Sector SPDR Fund", "asset_type": "etf", "sector": "Health Care",
     "themes": ["healthcare"], "recommendation_eligible": True},
    {"ticker": "HIDE", "name": "Not Recommendable Inc.", "asset_type": "stock", "sector": "Financials",
     "themes": [], "recommendation_eligible": False},
]

PROFILE = {
    "risk_level": "moderate",
    "interests": ["technology", "healthcare"],
    "asset_types": "both",
    "followed_tickers": ["NVDA"],
}


@pytest.fixture
def seeded(client):
    """The test app with a few assets in the `assets` collection."""
    with MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=5000) as mongo:
        mongo[TEST_DB]["assets"].insert_many([dict(a) for a in ASSETS])
    return client


def test_options_list_choices_with_real_asset_counts(seeded, admin):
    body = seeded.get("/api/profile/options", headers=admin).json()
    assert [r["key"] for r in body["risk_levels"]] == ["very_conservative", "conservative", "moderate", "growth", "aggressive"]
    counts = {i["key"]: i["asset_count"] for i in body["interests"]}
    assert counts["technology"] == 2  # NVDA + FSLR (sector)
    assert counts["healthcare"] == 1
    assert counts["clean_energy"] == 1  # FSLR via its renewable/solar themes
    assert counts["financials"] == 0  # the only financial asset is not recommendable
    assert body["max_followed"] == 20


def test_profile_is_null_until_saved_then_round_trips(seeded, admin):
    assert seeded.get("/api/profile", headers=admin).json() is None

    saved = seeded.put("/api/profile", headers=admin, json=PROFILE)
    assert saved.status_code == 200
    body = saved.json()
    assert body["risk_level"] == "moderate" and body["followed_tickers"] == ["NVDA"]
    assert seeded.get("/api/profile", headers=admin).json()["interests"] == ["technology", "healthcare"]


def test_saving_again_updates_answers_and_keeps_completed_at(seeded, admin):
    first = seeded.put("/api/profile", headers=admin, json=PROFILE).json()
    second = seeded.put("/api/profile", headers=admin, json={**PROFILE, "risk_level": "aggressive", "interests": ["technology"]}).json()
    assert second["risk_level"] == "aggressive" and second["interests"] == ["technology"]
    assert second["completed_at"] == first["completed_at"]
    assert second["updated_at"] >= first["updated_at"]


def test_tickers_are_normalised_and_deduplicated(seeded, admin):
    body = seeded.put("/api/profile", headers=admin, json={**PROFILE, "followed_tickers": [" nvda", "NVDA", "xlv"]}).json()
    assert body["followed_tickers"] == ["NVDA", "XLV"]


@pytest.mark.parametrize(
    "change,status",
    [
        ({"risk_level": "yolo"}, 400),
        ({"interests": ["astrology"]}, 400),
        ({"asset_types": "crypto"}, 400),
        ({"followed_tickers": ["NOPE"]}, 400),
        ({"followed_tickers": ["HIDE"]}, 400),  # exists but is not recommendable
        ({"interests": []}, 422),
        ({"followed_tickers": [f"T{i}" for i in range(21)]}, 422),
    ],
)
def test_invalid_profiles_are_rejected(seeded, admin, change, status):
    assert seeded.put("/api/profile", headers=admin, json={**PROFILE, **change}).status_code == status
    assert seeded.get("/api/profile", headers=admin).json() is None  # nothing was stored


def test_each_user_has_their_own_profile_and_no_permission_is_needed(seeded, admin):
    make_user(seeded, admin, "pat@example.com")  # default role: no permissions at all
    pat = login(seeded, "pat@example.com", "Passw0rd!x")
    assert seeded.get("/api/profile", headers=pat).json() is None
    assert seeded.put("/api/profile", headers=pat, json={**PROFILE, "risk_level": "conservative"}).status_code == 200
    assert seeded.get("/api/profile", headers=pat).json()["risk_level"] == "conservative"
    assert seeded.get("/api/profile", headers=admin).json() is None  # the admin's own profile is separate


def test_profile_endpoints_require_sign_in(seeded):
    seeded.post("/api/auth/logout")
    for method, path in [("get", "/api/profile"), ("put", "/api/profile"), ("get", "/api/profile/options"), ("get", "/api/assets/search?q=nv")]:
        assert getattr(seeded, method)(path).status_code == 401, path


def test_asset_search_matches_ticker_prefix_and_name(seeded, admin):
    def tickers(q):
        return [a["ticker"] for a in seeded.get(f"/api/assets/search?q={q}", headers=admin).json()]

    assert tickers("nv") == ["NVDA"]
    assert tickers("solar") == ["FSLR"]  # name match
    assert tickers("hide") == []  # not recommendable, so never offered
    assert seeded.get("/api/assets/search?q=", headers=admin).status_code == 422


def test_deleting_a_user_removes_their_profile(seeded, admin):
    user = make_user(seeded, admin, "gone@example.com")
    gone = login(seeded, "gone@example.com", "Passw0rd!x")
    seeded.put("/api/profile", headers=gone, json=PROFILE)
    with MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=5000) as mongo:
        assert mongo[TEST_DB]["profiles"].count_documents({}) == 1
        assert seeded.delete(f"/api/users/{user['id']}", headers=admin).status_code == 204
        assert mongo[TEST_DB]["profiles"].count_documents({}) == 0
