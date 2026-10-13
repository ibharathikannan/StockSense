"""The content-based recommender on its own: no database needed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.onboarding import INTERESTS
from app.recommender.content_based import ContentBasedRecommender, attribute_matrix, risk_fit


def asset(ticker, sector, themes, *, category=None, asset_type="stock", volatility=0.2, beta=1.0):
    risk = None if volatility is None else {
        "volatility_1y": volatility, "beta": beta, "max_drawdown_1y": -0.2, "dividend_yield": 0.01,
    }
    return {"ticker": ticker, "name": f"{ticker} Inc.", "asset_type": asset_type, "category": category,
            "sector": sector, "themes": themes, "risk": risk}


CATALOGUE = [
    asset("CHIP", "Information Technology", ["semiconductors", "artificial_intelligence"], category="AI chips", volatility=0.40, beta=2.0),
    asset("GPU", "Information Technology", ["semiconductors", "artificial_intelligence", "gpu"], category="AI chips", volatility=0.45, beta=2.2),
    asset("SOFT", "Information Technology", ["enterprise_software", "cloud_computing"], category="Software", volatility=0.30),
    asset("SUN", "Information Technology", ["solar_energy", "renewable_energy"], category="AI power energy and grid", volatility=0.50),
    asset("OIL", "Energy", ["oil_and_gas", "traditional_energy"], category="AI power energy and grid", volatility=0.25),
    asset("PILL", "Health Care", ["pharmaceuticals", "defensive"], category="Healthcare", volatility=0.18, beta=0.3),
    asset("CARE", "Health Care", ["health_insurance"], category="Healthcare", volatility=0.40),
    asset("HLTH", "Health Care", ["healthcare", "sector_etf"], category="Healthcare ETF", asset_type="etf", volatility=0.15, beta=0.3),
    asset("NEW", "Health Care", ["biotechnology"], category="Healthcare", volatility=None),
]


@pytest.fixture(scope="module")
def recommender():
    return ContentBasedRecommender(CATALOGUE)


def tickers(recommendations):
    return [r.ticker for r in recommendations]


def test_suggests_only_assets_that_match_an_interest_and_says_which(recommender):
    results = recommender.recommend(interests=["healthcare"], risk_level="aggressive")
    assert set(tickers(results)) == {"PILL", "CARE", "HLTH", "NEW"}
    assert all(r.reasons[0] == "Matches your interest in Healthcare" for r in results)


def test_clean_energy_matches_renewables_not_oil(recommender):
    # Themes are whole tokens: "traditional_energy" must not match "renewable_energy".
    assert tickers(recommender.recommend(interests=["clean_energy"])) == ["SUN"]


def test_followed_tickers_are_left_out_and_similar_ones_explained(recommender):
    results = recommender.recommend(interests=["technology"], followed_tickers=["CHIP"], risk_level="growth")
    assert "CHIP" not in tickers(results)
    assert results[0].ticker == "GPU"
    assert "Similar to CHIP, which you follow" in results[0].reasons


def test_a_followed_ticker_can_bring_in_assets_outside_the_interests(recommender):
    results = recommender.recommend(interests=["healthcare"], followed_tickers=["CHIP"], risk_level="growth")
    gpu = next(r for r in results if r.ticker == "GPU")
    assert gpu.reasons[0] == "Similar to CHIP, which you follow"
    assert not any(reason.startswith("Matches your interest") for reason in gpu.reasons)


def test_asset_type_preference_filters_the_catalogue(recommender):
    assert tickers(recommender.recommend(interests=["healthcare"], asset_types="etf")) == ["HLTH"]
    assert "HLTH" not in tickers(recommender.recommend(interests=["healthcare"], asset_types="stock"))


def test_calmer_asset_ranks_first_for_a_cautious_investor():
    twins = [
        asset("CALM", "Health Care", ["pharmaceuticals"], volatility=0.15),
        asset("WILD", "Health Care", ["pharmaceuticals"], volatility=0.40),
    ]
    results = ContentBasedRecommender(twins).recommend(interests=["healthcare"], risk_level="conservative")
    assert tickers(results) == ["CALM", "WILD"]
    assert results[0].reasons[-1] == "Yearly price swings of 15% fit your Conservative risk level (up to 20%)"
    assert results[1].reasons[-1] == (
        "Yearly price swings of 40% are above your Conservative risk level (up to 20%), which lowers its rank"
    )


def test_asset_without_risk_history_is_not_promoted(recommender):
    new = next(r for r in recommender.recommend(interests=["healthcare"]) if r.ticker == "NEW")
    assert new.reasons[-1] == "Not enough price history yet to compare with your risk level"
    assert risk_fit(None, "aggressive") == 0.0


@pytest.mark.parametrize(
    "volatility,risk_level,expected",
    [(0.10, "conservative", 1.0), (0.20, "conservative", 1.0), (0.30, "conservative", 0.5),
     (0.45, "conservative", 0.0), (0.35, "not-a-level", 1.0)],  # unknown level falls back to moderate (0.35)
)
def test_risk_fit_falls_from_the_ceiling_to_zero_at_twice_it(volatility, risk_level, expected):
    assert risk_fit(volatility, risk_level) == pytest.approx(expected)


def test_results_are_limited_ordered_and_repeatable(recommender):
    first = recommender.recommend(interests=["healthcare", "technology"], limit=3)
    assert len(first) == 3
    assert [r.score for r in first] == sorted((r.score for r in first), reverse=True)
    assert first == recommender.recommend(interests=["healthcare", "technology"], limit=3)


def test_unknown_interests_and_tickers_are_ignored(recommender):
    results = recommender.recommend(interests=["healthcare", "astrology"], followed_tickers=["NOPE"])
    assert set(tickers(results)) == {"PILL", "CARE", "HLTH", "NEW"}


def test_attributes_are_scaled_so_none_dominates():
    names, matrix = attribute_matrix(CATALOGUE)
    assert matrix.shape == (len(CATALOGUE), len(names))
    assert matrix.min() >= 0.0 and matrix.max() <= 1.0
    assert "theme:semiconductors" in names and "beta" in names


def test_an_empty_catalogue_is_rejected():
    with pytest.raises(ValueError):
        ContentBasedRecommender([])


PROFILES_JSON = Path(__file__).resolve().parents[2] / "data" / "processed" / "asset_profiles.json"


@pytest.mark.skipif(not PROFILES_JSON.exists(), reason="data/processed/asset_profiles.json not available")
def test_every_interest_finds_matches_in_the_real_catalogue():
    recommender = ContentBasedRecommender(json.loads(PROFILES_JSON.read_text(encoding="utf-8")))
    for interest in INTERESTS:
        results = recommender.recommend(interests=[interest["key"]], limit=20)
        assert results, interest["key"]
        assert all(r.reasons[0] == f"Matches your interest in {interest['label']}" for r in results)
    clean = tickers(recommender.recommend(interests=["clean_energy"], limit=20))
    assert "FSLR" in clean and not {"XOM", "CVX"} & set(clean)
