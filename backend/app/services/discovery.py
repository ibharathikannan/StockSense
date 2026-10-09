"""Content-based asset discovery and diversification (P6).

Pure logic: given the recommendable assets and a user's investor profile, produce a ranked
candidate set, the user's sector exposure (from the assets they already follow), and a
diversification note that warns against single-industry concentration and suggests
diversifying assets. The backend (P8) supplies the asset rows and profile; this module does
no I/O so it is easy to test.

Interests map to `sector`/`themes` via `app.core.onboarding.INTERESTS` — the single source of
truth shared with onboarding and the frontend. The sector-exposure output feeds the rule
engine's request-time concentration adjustment.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

try:
    from app.core.onboarding import INTERESTS
except ImportError:  # allow importing as backend.app.services.discovery (repo-root tests)
    from backend.app.core.onboarding import INTERESTS

CONCENTRATION_WARNING_SHARE = 0.5   # a followed set more than half in one sector is "concentrated"


def interest_targets(interest_keys: Iterable[str]) -> tuple[set[str], set[str]]:
    """Expand interest keys to the union of their sectors and themes."""
    keys = set(interest_keys or [])
    sectors: set[str] = set()
    themes: set[str] = set()
    for interest in INTERESTS:
        if interest["key"] in keys:
            sectors.update(interest.get("sectors", []))
            themes.update(interest.get("themes", []))
    return sectors, themes


def _asset_type_ok(asset: dict, preference: str) -> bool:
    if preference in (None, "", "both"):
        return True
    return (asset.get("asset_type") or "").lower() == preference.lower()


def _match_score(asset: dict, interest_keys: Iterable[str]) -> int:
    """How many of the user's interests this asset satisfies (by sector or theme)."""
    sector = asset.get("sector")
    themes = set(asset.get("themes") or [])
    score = 0
    for interest in INTERESTS:
        if interest["key"] not in set(interest_keys or []):
            continue
        if sector in set(interest.get("sectors", [])) or themes & set(interest.get("themes", [])):
            score += 1
    return score


def sector_exposure(assets_by_ticker: dict[str, dict], followed: Iterable[str]) -> dict[str, float]:
    """Share of the user's followed tickers in each sector (empty if they follow nothing)."""
    sectors = [assets_by_ticker[t]["sector"] for t in (followed or [])
               if t in assets_by_ticker and assets_by_ticker[t].get("sector")]
    if not sectors:
        return {}
    counts = Counter(sectors)
    total = sum(counts.values())
    return {sector: count / total for sector, count in counts.items()}


def rank_candidates(assets: list[dict], profile: dict, limit: int) -> list[dict]:
    """Recommendation-eligible assets matching the profile, best match first, excluding
    anything the user already follows. Deterministic ties by ticker."""
    followed = set(profile.get("followed_tickers") or [])
    interests = profile.get("interests") or []
    asset_type = profile.get("asset_types", "both")
    scored = []
    for asset in assets:
        if not asset.get("recommendation_eligible"):
            continue
        if asset["ticker"] in followed or not _asset_type_ok(asset, asset_type):
            continue
        score = _match_score(asset, interests)
        if score > 0:
            scored.append((score, asset))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["ticker"]))
    return [asset for _, asset in scored[:limit]]


def diversification(assets_by_ticker: dict[str, dict], profile: dict,
                    candidates: list[dict]) -> dict[str, Any]:
    """Diversification note from the user's followed-set sector mix + diversifying picks."""
    exposure = sector_exposure(assets_by_ticker, profile.get("followed_tickers"))
    dominant_sector, dominant_share = (max(exposure.items(), key=lambda kv: kv[1])
                                       if exposure else (None, 0.0))
    concentrated = dominant_share > CONCENTRATION_WARNING_SHARE
    # Suggest candidates outside the dominant sector to diversify away from it.
    diversifiers = [c["ticker"] for c in candidates
                    if c.get("sector") and c["sector"] != dominant_sector][:5]
    warning = None
    if concentrated:
        warning = (f"{dominant_share:.0%} of the assets you follow are in {dominant_sector}. "
                   f"Consider diversifying across other sectors to reduce single-industry risk.")
    return {
        "sector_exposure": exposure,
        "dominant_sector": dominant_sector,
        "concentrated": concentrated,
        "warning": warning,
        "diversifying_tickers": diversifiers,
    }


def discover(assets: list[dict], profile: dict, limit: int = 10) -> dict[str, Any]:
    """Full discovery result: ranked candidates + diversification context."""
    assets_by_ticker = {a["ticker"]: a for a in assets}
    candidates = rank_candidates(assets, profile, limit)
    return {
        "candidates": candidates,
        "diversification": diversification(assets_by_ticker, profile, candidates),
    }
