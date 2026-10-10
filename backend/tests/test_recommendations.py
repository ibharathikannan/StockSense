"""Integration tests for the recommendations endpoints (P8). Real local test DB."""
from __future__ import annotations

import json

from conftest import login, make_user, run_sql


def _seed_snapshot(ticker="AAPL", sector="Information Technology", risk="moderate", stance="CAUTION"):
    run_sql(
        "INSERT INTO assets (ticker, name, asset_type, sector, themes, recommendation_eligible, "
        "forecast_eligible) VALUES ($1, 'Apple Inc.', 'stock', $2, $3::text[], true, true)",
        ticker, sector, ["artificial_intelligence"],
    )
    run_sql(
        """INSERT INTO recommendation_snapshots
           (ticker, risk_profile, as_of, baseline_stance, news_aware_stance, provisional,
            forecast, signal_detail, evidence, explanation)
           VALUES ($1, $2, current_date, $3, $3, false, $4::jsonb, $5::jsonb, '[]'::jsonb, $6::jsonb)""",
        ticker, risk, stance,
        json.dumps({"return_10d": None, "basis": "placeholder — pending XGBoost serving"}),
        json.dumps({"decision_trace": ["Risk mismatch: volatility exceeds your Moderate limit."],
                    "news_signal": {"score": None, "source": None, "article_count": 0}}),
        json.dumps({"text": "Caution for AAPL.", "citations": [], "abstained": True, "caveats": []}),
    )


def _investor(client, admin, email="inv@example.com", risk="moderate", interests=("technology",),
              followed=()):
    user = make_user(client, admin, email)
    run_sql(
        "INSERT INTO profiles (user_id, risk_level, interests, asset_types, followed_tickers, "
        "completed_at, created_at, updated_at) "
        "VALUES ($1::uuid, $2, $3::text[], 'both', $4::text[], now(), now(), now())",
        user["id"], risk, list(interests), list(followed),
    )
    return login(client, email, "Passw0rd!x")


def test_detail_returns_snapshot_for_user_tier(client, admin):
    _seed_snapshot()
    headers = _investor(client, admin)
    res = client.get("/api/recommendations/AAPL", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["signal"]["news_aware_stance"] == "CAUTION"
    assert body["signal"]["risk_profile"] == "moderate"
    assert body["forecast"]["return_10d"] is None            # placeholder forecast
    assert body["explanation"]["abstained"] is True


def test_detail_unknown_ticker_404(client, admin):
    headers = _investor(client, admin)
    assert client.get("/api/recommendations/ZZZZ", headers=headers).status_code == 404


def test_discovery_lists_interest_matching_candidate(client, admin):
    _seed_snapshot()
    headers = _investor(client, admin, interests=("technology",))
    res = client.get("/api/recommendations", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert any(c["ticker"] == "AAPL" for c in body["candidates"])
    assert "diversification" in body


def test_discovery_requires_completed_profile_409(client, admin):
    make_user(client, admin, "noprofile@example.com")
    headers = login(client, "noprofile@example.com", "Passw0rd!x")
    assert client.get("/api/recommendations", headers=headers).status_code == 409


def test_requires_authentication_401(client):
    assert client.get("/api/recommendations/AAPL").status_code == 401
