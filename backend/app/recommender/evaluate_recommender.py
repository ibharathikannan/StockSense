"""Offline evaluation of the content-based recommender (app/recommender/content_based.py).

Builds recommendations for a set of predefined investor profiles from
data/processed/asset_profiles.json and reports four metrics per profile and on average:

  Precision@K              share of the top K that are fully relevant (grade 2)
  NDCG@K                   ranking quality using graded relevance (0, 1, 2)
  Risk Compatibility Rate  share of the top K whose 1-year volatility is within the profile's risk limit
  Diversification Score    distinct sectors in the top K divided by K

Three systems are compared so the numbers have something to be read against:

  Random          a random draw from the allowed assets (average of 200 draws)
  Interest-only   the recommender's interest similarity alone, with no risk fit and no follow signal
  Content-based   ContentBasedRecommender.recommend(), the system the app uses

Relevance grades come from the sector/theme rules in app/core/onboarding.py and the rule engine's
volatility limits, not from the recommender's score. They are a proxy for a human judge, so treat
the results as a sanity check of the pipeline, not as proof of quality for real users.

Run from the repository root:

    backend/.venv/Scripts/python backend/app/recommender/evaluate_recommender.py      (Windows)
    backend/.venv/bin/python backend/app/recommender/evaluate_recommender.py          (macOS / Linux)

Options: --k 10 changes the list length. Writes data/processed/recommender_evaluation.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.onboarding import INTERESTS  # noqa: E402
from app.recommender.content_based import ContentBasedRecommender, volatility_limit  # noqa: E402

PROFILES_JSON = ROOT / "data" / "processed" / "asset_profiles.json"
OUTPUT_CSV = ROOT / "data" / "processed" / "recommender_evaluation.csv"
RANDOM_DRAWS = 200

# Predefined test profiles: same fields as the onboarding form.
TEST_PROFILES = [
    {"name": "Cautious health and finance", "risk_level": "conservative", "interests": ["healthcare", "financials"], "asset_types": "both", "followed_tickers": []},
    {"name": "Very cautious, ETFs only", "risk_level": "very_conservative", "interests": ["financials", "healthcare", "consumer"], "asset_types": "etf", "followed_tickers": []},
    {"name": "Balanced tech and media", "risk_level": "moderate", "interests": ["technology", "communication"], "asset_types": "stock", "followed_tickers": ["AAPL", "MSFT"]},
    {"name": "Growth tech and clean energy", "risk_level": "growth", "interests": ["technology", "clean_energy"], "asset_types": "both", "followed_tickers": []},
    {"name": "Aggressive tech only", "risk_level": "aggressive", "interests": ["technology"], "asset_types": "stock", "followed_tickers": ["NVDA"]},
    {"name": "Aggressive, every interest", "risk_level": "aggressive", "interests": [i["key"] for i in INTERESTS], "asset_types": "both", "followed_tickers": []},
    {"name": "Cautious energy", "risk_level": "conservative", "interests": ["energy", "clean_energy"], "asset_types": "both", "followed_tickers": []},
    {"name": "Balanced industrials", "risk_level": "moderate", "interests": ["industrials", "materials"], "asset_types": "stock", "followed_tickers": []},
]

METRICS = [("precision", "Precision@{k}"), ("ndcg", "NDCG@{k}"), ("risk_compat", "Risk Compatibility"), ("diversification", "Diversification")]


# --------------------------------------------------------------------------- ground truth


def vol(asset: dict) -> float:
    return asset["risk"]["volatility_1y"]


def matches_interest(asset: dict, interest_keys: list[str]) -> bool:
    for interest in INTERESTS:
        if interest["key"] in interest_keys and (asset["sector"] in interest["sectors"] or set(asset["themes"]) & set(interest["themes"])):
            return True
    return False


def relevance(asset: dict, profile: dict) -> int:
    """2 = matches an interest and is within the risk limit, 1 = only one of the two, 0 = neither."""
    return int(matches_interest(asset, profile["interests"])) + int(vol(asset) <= volatility_limit(profile["risk_level"]))


def candidates_for(assets: list[dict], profile: dict) -> list[dict]:
    return [a for a in assets if profile["asset_types"] in ("both", a["asset_type"]) and a["ticker"] not in profile["followed_tickers"]]


# --------------------------------------------------------------------------- systems


def interest_only(model: ContentBasedRecommender, candidates: list[dict], profile: dict, k: int) -> list[dict]:
    sim = model.interest_similarity(profile["interests"]).max(axis=0)
    row = {t: i for i, t in enumerate(model.tickers)}
    return sorted(candidates, key=lambda a: (-sim[row[a["ticker"]]], a["ticker"]))[:k]


def content_based(model: ContentBasedRecommender, candidates: list[dict], profile: dict, k: int) -> list[dict]:
    recs = model.recommend(interests=profile["interests"], followed_tickers=profile["followed_tickers"],
                           risk_level=profile["risk_level"], asset_types=profile["asset_types"], limit=k)
    by_ticker = {a["ticker"]: a for a in candidates}
    return [by_ticker[r.ticker] for r in recs]


# --------------------------------------------------------------------------- metrics


def precision_at_k(recs: list[dict], profile: dict, k: int) -> float:
    return sum(relevance(a, profile) == 2 for a in recs) / k


def ndcg_at_k(recs: list[dict], candidates: list[dict], profile: dict, k: int) -> float:
    def dcg(grades: list[int]) -> float:
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))

    best = dcg(sorted((relevance(a, profile) for a in candidates), reverse=True)[:k])
    return dcg([relevance(a, profile) for a in recs]) / best if best else 0.0


def risk_compatibility(recs: list[dict], profile: dict, k: int) -> float:
    return sum(vol(a) <= volatility_limit(profile["risk_level"]) for a in recs) / k


def diversification(recs: list[dict], k: int) -> float:
    return len({a["sector"] for a in recs}) / k


def score(recs: list[dict], candidates: list[dict], profile: dict, k: int) -> dict[str, float]:
    # Divides by k, not len(recs), so a system that returns fewer than k items is not rewarded for it.
    return {
        "precision": precision_at_k(recs, profile, k),
        "ndcg": ndcg_at_k(recs, candidates, profile, k),
        "risk_compat": risk_compatibility(recs, profile, k),
        "diversification": diversification(recs, k),
    }


def random_baseline(candidates: list[dict], profile: dict, k: int) -> dict[str, float]:
    rng = np.random.default_rng(42)
    runs = [score([candidates[i] for i in rng.choice(len(candidates), k, replace=False)], candidates, profile, k) for _ in range(RANDOM_DRAWS)]
    return {m: float(np.mean([r[m] for r in runs])) for m in runs[0]}


# --------------------------------------------------------------------------- report


def markdown_table(title: str, rows: list[tuple[str, dict[str, float]]], k: int) -> str:
    lines = ["| " + title + " | " + " | ".join(label.format(k=k) for _, label in METRICS) + " |", "|" + "---|" * (len(METRICS) + 1)]
    lines += ["| " + name + " | " + " | ".join(f"{vals[m]:.2f}" for m, _ in METRICS) + " |" for name, vals in rows]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, default=5, help="list length to evaluate (default 5)")
    k = parser.parse_args().k

    # The same catalogue the app recommends from (AssetsRepository.list_recommendable).
    assets = [a for a in json.loads(PROFILES_JSON.read_text(encoding="utf-8")) if a["recommendation_eligible"] and a["risk"]["volatility_1y"] is not None]
    model = ContentBasedRecommender(assets)

    systems = {"Random": None, "Interest-only": interest_only, "Content-based": content_based}
    results: dict[str, list[tuple[str, dict[str, float]]]] = {name: [] for name in systems}
    csv_rows: list[dict] = []
    for profile in TEST_PROFILES:
        candidates = candidates_for(assets, profile)
        for name, build in systems.items():
            recs = [] if build is None else build(model, candidates, profile, k)
            values = random_baseline(candidates, profile, k) if build is None else score(recs, candidates, profile, k)
            results[name].append((profile["name"], values))
            csv_rows.append({"profile": profile["name"], "system": name, **{m: round(values[m], 4) for m, _ in METRICS},
                             "recommended": " ".join(a["ticker"] for a in recs)})

    print(f"Assets: {len(assets)} recommendable | profiles: {len(TEST_PROFILES)} | K = {k}\n")
    summary = [(name, {m: float(np.mean([v[m] for _, v in rows])) for m, _ in METRICS}) for name, rows in results.items()]
    print(markdown_table("Average over all profiles", summary, k), "\n")
    print(markdown_table("Content-based, per profile", results["Content-based"], k), "\n")
    print("Recommended tickers (Content-based):")
    for row in csv_rows:
        if row["system"] == "Content-based":
            print(f"  {row['profile']:<30} {row['recommended']}")

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nWrote {OUTPUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
