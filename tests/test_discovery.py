"""Unit tests for content-based discovery and diversification (P6). Pure; no DB."""
from backend.app.services.discovery import (
    discover,
    interest_targets,
    rank_candidates,
    sector_exposure,
)

ASSETS = [
    {"ticker": "AAPL", "name": "Apple", "asset_type": "stock", "sector": "Information Technology",
     "themes": [], "recommendation_eligible": True},
    {"ticker": "MSFT", "name": "Microsoft", "asset_type": "stock", "sector": "Information Technology",
     "themes": [], "recommendation_eligible": True},
    {"ticker": "JPM", "name": "JPMorgan", "asset_type": "stock", "sector": "Financials",
     "themes": [], "recommendation_eligible": True},
    {"ticker": "XOM", "name": "Exxon", "asset_type": "stock", "sector": "Energy",
     "themes": [], "recommendation_eligible": True},
    {"ticker": "ICLN", "name": "Clean Energy ETF", "asset_type": "etf", "sector": "Utilities",
     "themes": ["solar_energy"], "recommendation_eligible": True},
    {"ticker": "PRIV", "name": "Private", "asset_type": "stock", "sector": "Information Technology",
     "themes": [], "recommendation_eligible": False},
]
BY_TICKER = {a["ticker"]: a for a in ASSETS}


def test_interest_targets_expand_to_sectors_and_themes():
    sectors, themes = interest_targets(["technology", "clean_energy"])
    assert "Information Technology" in sectors
    assert "solar_energy" in themes


def test_rank_filters_by_eligibility_type_and_followed():
    profile = {"interests": ["technology"], "asset_types": "stock", "followed_tickers": ["AAPL"]}
    out = rank_candidates(ASSETS, profile, limit=10)
    tickers = [a["ticker"] for a in out]
    assert "MSFT" in tickers          # tech stock, matches
    assert "AAPL" not in tickers      # already followed
    assert "PRIV" not in tickers      # not recommendation_eligible
    assert "JPM" not in tickers       # financials, no interest match


def test_etf_matched_by_theme_and_type_filter():
    profile = {"interests": ["clean_energy"], "asset_types": "etf", "followed_tickers": []}
    out = rank_candidates(ASSETS, profile, limit=10)
    assert [a["ticker"] for a in out] == ["ICLN"]


def test_sector_exposure_shares():
    exp = sector_exposure(BY_TICKER, ["AAPL", "MSFT", "JPM"])
    assert exp["Information Technology"] == 2 / 3
    assert exp["Financials"] == 1 / 3


def test_discover_flags_concentration_and_suggests_diversifiers():
    # Follows 3 tech names -> concentrated; interested broadly.
    profile = {"interests": ["technology", "financials", "energy"], "asset_types": "both",
               "followed_tickers": ["AAPL", "MSFT", "PRIV"]}
    out = discover(ASSETS, profile, limit=10)
    div = out["diversification"]
    assert div["concentrated"] is True
    assert div["dominant_sector"] == "Information Technology"
    assert "Information Technology" in div["warning"]
    # Diversifiers should steer away from the dominant sector.
    assert all(BY_TICKER[t]["sector"] != "Information Technology" for t in div["diversifying_tickers"])
    assert {"JPM", "XOM"} & set(div["diversifying_tickers"])


def test_discover_no_followed_means_no_concentration():
    profile = {"interests": ["technology"], "asset_types": "both", "followed_tickers": []}
    div = discover(ASSETS, profile, limit=10)["diversification"]
    assert div["concentrated"] is False and div["warning"] is None
