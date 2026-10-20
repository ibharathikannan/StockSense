"""Content-based recommender: rank catalogue assets against one investor profile.

The classic content-based filtering pipeline, as in the RS content-based workshop:

1. Content analyser. Every asset gets two item profiles:
   - a *description* (name, category, sector and themes) weighted with TF-IDF, and
   - *attributes*: one-hot sector, category and asset type, multi-hot themes and the
     one-year risk numbers, all min-max scaled to [0, 1].
2. Profile learner. Each chosen interest becomes a TF-IDF query in the description
   space; each followed ticker is a point in the attribute space.
3. Filtering. Candidates are scored by cosine similarity to the interests and to the
   followed tickers, plus how well their volatility fits the investor's risk level.
   Every suggestion carries the plain-English reasons behind its score.

Similarity means an asset *resembles* what the investor described. It is not a
forecast and not advice to buy anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler, MultiLabelBinarizer

from app.core.onboarding import INTERESTS, RISK_LEVELS
from app.rule_engine.rule_based_engine import VOLATILITY_LIMITS, normalize_risk_profile

# Weights of the three signals in the final score. When the investor follows no
# tickers, the follow weight drops out and the other two are rescaled.
INTEREST_WEIGHT = 0.5
FOLLOW_WEIGHT = 0.3
RISK_WEIGHT = 0.2

# Cosine similarity an interest or followed ticker needs to count as a reason.
# An asset is suggested only if it has at least one such reason.
MIN_INTEREST_SIMILARITY = 0.1
MIN_FOLLOW_SIMILARITY = 0.5

# Numeric attributes, read from the asset's `risk` object (see data/build_asset_profiles.py).
RISK_FEATURES = ("volatility_1y", "beta", "max_drawdown_1y", "dividend_yield")

_INTERESTS = {i["key"]: i for i in INTERESTS}
_RISK_LABELS = {r["key"]: r["label"] for r in RISK_LEVELS}


@dataclass(frozen=True)
class Recommendation:
    ticker: str
    name: str
    asset_type: str
    category: str | None
    sector: str
    score: float  # 0-1, for ordering only
    reasons: tuple[str, ...]


# What TF-IDF reads is the asset's category, sector and themes. Deliberate choices:
# - Sectors and themes stay single tokens ("communication_services", "renewable_energy"),
#   like the workshop's genre labels. Split into words, "energy" would make oil majors
#   look like clean-energy matches and "services" would tie telecoms to "Financial services".
# - The free-text category is split into words, so "AI power energy and grid" still
#   relates grid and power companies to an interest in the Energy sector.
# - Company names are left out: "Applied Materials" is a chip-equipment maker, not a
#   Materials company, and names otherwise only repeat the category.
def _token(label: str) -> str:
    return label.replace(" ", "_")


def item_document(asset: Mapping[str, Any]) -> str:
    """The text TF-IDF reads for an asset: category words, sector and themes."""
    parts = [asset.get("category"), _token(asset["sector"]), *(asset.get("themes") or [])]
    return " ".join(p for p in parts if p)


def interest_document(interest_key: str) -> str:
    """The query for an onboarding interest: the sectors and themes that define it.

    The display label is left out: "Clean Energy" would add "energy", which every oil
    company's description also contains.
    """
    interest = _INTERESTS[interest_key]
    return " ".join([*map(_token, interest["sectors"]), *interest["themes"]])


def _risk_number(asset: Mapping[str, Any], key: str) -> float:
    value = (asset.get("risk") or {}).get(key)
    return np.nan if value is None else float(value)


def attribute_matrix(assets: Sequence[Mapping[str, Any]]) -> tuple[list[str], np.ndarray]:
    """Column names and the (assets x attributes) matrix, every column in [0, 1].

    Without min-max scaling, beta (roughly -0.5 to 4.4) would dominate dividend yield
    (0 to 0.07) and the 0/1 columns in any comparison between assets. Missing risk
    numbers (too little price history) take the catalogue median.
    """
    binarizer = MultiLabelBinarizer()
    categorical = binarizer.fit_transform(
        [
            [
                f"sector:{a['sector']}",
                f"type:{a['asset_type']}",
                *([f"category:{a['category']}"] if a.get("category") else []),
                *(f"theme:{t}" for t in a.get("themes") or []),
            ]
            for a in assets
        ]
    )
    raw = np.array([[_risk_number(a, key) for key in RISK_FEATURES] for a in assets], dtype=float)
    scaler = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), MinMaxScaler())
    return [*binarizer.classes_, *RISK_FEATURES], np.hstack([categorical, scaler.fit_transform(raw)])


def volatility_limit(risk_level: str) -> float:
    """The rule engine's one-year volatility ceiling for a risk level (moderate if unknown)."""
    return VOLATILITY_LIMITS.get(normalize_risk_profile(risk_level), VOLATILITY_LIMITS["moderate"])


def risk_fit(volatility: float | None, risk_level: str) -> float:
    """1 up to the risk level's volatility ceiling, falling linearly to 0 at twice the ceiling.

    Unknown volatility scores 0, so an asset is never promoted on risk it cannot show.
    """
    if volatility is None:
        return 0.0
    return float(np.clip(2 - volatility / volatility_limit(risk_level), 0.0, 1.0))


def _join(labels: Sequence[str]) -> str:
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"


def _risk_reason(volatility: float | None, risk_level: str) -> str:
    if volatility is None:
        return "Not enough price history yet to compare with your risk level"
    label = _RISK_LABELS.get(risk_level, risk_level.replace("_", " ").title())
    limit = volatility_limit(risk_level)
    if volatility <= limit:
        return f"Yearly price swings of {volatility:.0%} fit your {label} risk level (up to {limit:.0%})"
    return f"Yearly price swings of {volatility:.0%} are above your {label} risk level (up to {limit:.0%}), which lowers its rank"


class ContentBasedRecommender:
    """Fits the item profiles for a catalogue, then ranks it for any number of investors.

    `assets` are rows of the `assets` table: ticker, name, asset_type, category, sector,
    themes and the `risk` object. Fitting takes milliseconds for a few hundred assets.
    """

    def __init__(self, assets: Sequence[Mapping[str, Any]]) -> None:
        if not assets:
            raise ValueError("Cannot build a recommender from an empty catalogue")
        self.assets = list(assets)
        self.tickers = [a["ticker"] for a in self.assets]
        self._row = {ticker: i for i, ticker in enumerate(self.tickers)}

        # Description view. Unlike the workshop's min_df=2 / max_df=0.8 (45k movies), every
        # word is kept: in a catalogue this small a theme such as "hydrogen" may belong to a
        # single asset and still be the clearest signal for an interest, and a max_df cut
        # can prune the whole vocabulary of a few similar assets. IDF already down-weights
        # common words.
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.descriptions = self.vectorizer.fit_transform([item_document(a) for a in self.assets])

        # Attribute view: item-item cosine similarity, used for "similar to what you follow".
        self.attribute_names, self.attributes = attribute_matrix(self.assets)
        self.item_similarity = cosine_similarity(self.attributes)

    def interest_similarity(self, interest_keys: Sequence[str]) -> np.ndarray:
        """Cosine similarity of each interest's query to each asset description, (interests x assets)."""
        if not interest_keys:
            return np.zeros((0, len(self.assets)))
        queries = self.vectorizer.transform([interest_document(k) for k in interest_keys])
        return cosine_similarity(queries, self.descriptions)

    def recommend(
        self,
        *,
        interests: Sequence[str],
        followed_tickers: Sequence[str] = (),
        risk_level: str = "moderate",
        asset_types: str = "both",
        limit: int = 10,
    ) -> list[Recommendation]:
        """The `limit` best-matching assets the investor does not already follow, best first.

        Each suggestion's reasons list its content reasons first and its risk reason last.
        """
        interest_keys = [k for k in dict.fromkeys(interests) if k in _INTERESTS]
        followed = [t for t in dict.fromkeys(followed_tickers) if t in self._row]
        by_interest = self.interest_similarity(interest_keys)
        by_followed = self.item_similarity[[self._row[t] for t in followed]]

        follow_weight = FOLLOW_WEIGHT if followed else 0.0
        total_weight = INTEREST_WEIGHT + follow_weight + RISK_WEIGHT

        ranked: list[Recommendation] = []
        for col, asset in enumerate(self.assets):
            if asset["ticker"] in followed or asset_types not in ("both", asset["asset_type"]):
                continue

            reasons: list[str] = []
            interest_scores = by_interest[:, col]
            matched = [
                _INTERESTS[interest_keys[i]]["label"]
                for i in np.argsort(-interest_scores, kind="stable")
                if interest_scores[i] >= MIN_INTEREST_SIMILARITY
            ]
            if matched:
                noun = "interest" if len(matched) == 1 else "interests"
                reasons.append(f"Matches your {noun} in {_join(matched)}")

            follow_scores = by_followed[:, col]
            if followed and follow_scores.max() >= MIN_FOLLOW_SIMILARITY:
                reasons.append(f"Similar to {followed[int(follow_scores.argmax())]}, which you follow")

            if not reasons:
                continue  # resembles nothing the investor told us about

            volatility = _risk_number(asset, "volatility_1y")
            volatility = None if np.isnan(volatility) else volatility
            reasons.append(_risk_reason(volatility, risk_level))

            score = (
                INTEREST_WEIGHT * interest_scores.max(initial=0.0)
                + follow_weight * follow_scores.max(initial=0.0)
                + RISK_WEIGHT * risk_fit(volatility, risk_level)
            ) / total_weight
            ranked.append(
                Recommendation(
                    ticker=asset["ticker"],
                    name=asset["name"],
                    asset_type=asset["asset_type"],
                    category=asset.get("category"),
                    sector=asset["sector"],
                    score=round(float(score), 4),
                    reasons=tuple(reasons),
                )
            )

        ranked.sort(key=lambda r: (-r.score, r.ticker))
        return ranked[:limit]
