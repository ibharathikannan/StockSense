"""Choices offered on the onboarding / investor-profile page.

Single source of truth: the API validates against these lists, the frontend renders them
(via GET /api/profile/options), and the recommender maps interests to assets with them.

Interests are defined in terms of the `sector` and `themes` fields of the `assets`
collection (see data/asset_universe.csv), so every chip is backed by real assets.
"""

from __future__ import annotations

from typing import Any

MAX_FOLLOWED_TICKERS = 20

RISK_LEVELS: list[dict[str, str]] = [
    {"key": "very_conservative", "label": "Very Conservative", "description": "Focus on stability and capital preservation."},
    {"key": "conservative", "label": "Conservative", "description": "Prefer low risk with some growth."},
    {"key": "moderate", "label": "Moderate", "description": "Balance of growth and risk."},
    {"key": "growth", "label": "Growth", "description": "Comfortable with higher risk for higher growth."},
    {"key": "aggressive", "label": "Aggressive", "description": "Seek high growth and can accept high volatility."},
]

# An asset matches an interest if its sector is in `sectors` OR any of its themes is in `themes`.
INTERESTS: list[dict[str, Any]] = [
    {"key": "technology", "label": "Technology", "sectors": ["Information Technology"], "themes": []},
    {"key": "healthcare", "label": "Healthcare", "sectors": ["Health Care"], "themes": []},
    {"key": "financials", "label": "Financials", "sectors": ["Financials"], "themes": []},
    {"key": "energy", "label": "Energy", "sectors": ["Energy", "Utilities"], "themes": []},
    {"key": "consumer", "label": "Consumer", "sectors": ["Consumer Discretionary", "Consumer Staples"], "themes": []},
    {"key": "industrials", "label": "Industrials", "sectors": ["Industrials"], "themes": []},
    {
        "key": "clean_energy",
        "label": "Clean Energy",
        "sectors": [],
        "themes": ["renewable_energy", "solar_energy", "energy_transition", "grid_infrastructure", "electrification", "hydrogen"],
    },
    {"key": "communication", "label": "Communication", "sectors": ["Communication Services"], "themes": []},
    {"key": "materials", "label": "Materials", "sectors": ["Materials"], "themes": []},
]

ASSET_TYPE_CHOICES: list[dict[str, str]] = [
    {"key": "both", "label": "Stocks & ETFs"},
    {"key": "stock", "label": "Stocks"},
    {"key": "etf", "label": "ETFs"},
]

RISK_LEVEL_KEYS = {r["key"] for r in RISK_LEVELS}
INTEREST_KEYS = {i["key"] for i in INTERESTS}
ASSET_TYPE_KEYS = {a["key"] for a in ASSET_TYPE_CHOICES}
