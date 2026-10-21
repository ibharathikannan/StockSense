from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# The three research signals. These guide research priority, not trading action.
Stance = Literal["EXPLORE", "MONITOR", "CAUTION"]


class Forecast(BaseModel):
    """The 10-trading-day return estimate and its uncertainty band.

    Always a development-fold estimate from the price-only XGBoost comparison, never a
    live or validated prediction. `basis` is shown to the user so the caveat travels
    with the number.
    """

    return_10d: float | None = None
    lower: float | None = None
    upper: float | None = None
    model_version: str | None = None
    basis: str = "development-fold estimate"


class NewsSignal(BaseModel):
    """The deterministic news input to the signal (Path 1 — a number, not prose).

    Aggregated ticker-specific sentiment after the relevance/recency/dedup/attribution
    safeguards. `source` records which sentiment the attribution diagnostic cleared us to
    trust. `score`/`relevance` are None when the ticker has no eligible coverage.
    """

    score: float | None = None
    relevance: float | None = None
    recency_hours: float | None = None
    source: str | None = None          # "alpha_vantage" | "local" | None
    article_count: int = 0


class NewsSentiment(BaseModel):
    """The most recent stored provider news sentiment for a ticker (display-only).

    The mean provider score over the `lookback_days` ending at `as_of`, the newest scored
    article. Marketaux scores accumulate nightly; Alpha Vantage aggregates are older and no
    longer refreshed. It never moves the precomputed stance. Absent when nothing was scored.
    """

    score: float
    source: Literal["marketaux", "alpha_vantage"]
    as_of: datetime
    article_count: int = 0
    lookback_days: int = 7


class FundamentalMetric(BaseModel):
    value: float
    assessment: Literal["strong", "neutral", "weak"]


class FundamentalsSignal(BaseModel):
    """Point-in-time SEC XBRL fundamentals input (data/rag/fundamentals_signal.py).

    Thresholds are unvalidated, so any stance change they cause is marked provisional.
    `score`/`rating` are None when the check abstained (ETF, missing or stale filings).
    """

    score: float | None = None
    rating: Literal["strong", "neutral", "weak"] | None = None
    metrics: dict[str, FundamentalMetric] = Field(default_factory=dict)
    metric_count: int = 0
    period_end: date | None = None
    filed: date | None = None
    age_days: int | None = None
    source: str | None = None          # "sec_xbrl" | None


class Signal(BaseModel):
    """The hybrid signal in both modes.

    `baseline_stance` ignores news and fundamentals; `news_aware_stance` is the operative
    stance after the gated news and SEC-fundamentals adjustments. `provisional` is True when
    either adjustment changed the stance (experimental, surfaced as unvalidated). The final stance a user
    sees may be further downgraded by the request-time concentration adjustment, which
    appends to `decision_trace`.
    """

    baseline_stance: Stance
    news_aware_stance: Stance
    provisional: bool = False
    decision_trace: list[str] = Field(default_factory=list)
    news_signal: NewsSignal = Field(default_factory=NewsSignal)
    fundamentals_signal: FundamentalsSignal = Field(default_factory=FundamentalsSignal)
    risk_profile: str


class Citation(BaseModel):
    title: str
    source_type: str                   # "sec" | "news"
    published_at: datetime | None = None
    source_url: str | None = None


class Evidence(BaseModel):
    """A retrieved passage backing the explanation. Dates and citations are preserved so
    the user can trace every claim to a source."""

    title: str
    source_type: str
    published_at: datetime | None = None
    source_url: str | None = None
    snippet: str
    # Provider (Marketaux) per-article sentiment, -1..1, for news items; None for filings.
    sentiment: float | None = None


class Explanation(BaseModel):
    """The grounded 'Why?' narrative. `abstained` is True when there was no eligible
    evidence and the model declined to invent a reason; `caveats` carries the standing
    disclaimers (development-fold forecast, exploratory sentiment, no financial figures)."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    caveats: list[str] = Field(default_factory=list)


class Diversification(BaseModel):
    """Discovery-time context, computed per user at request time (not precomputed)."""

    sector: str
    diversifying_tickers: list[str] = Field(default_factory=list)


class DiversificationNote(BaseModel):
    """Request-time diversification view computed from the user's followed assets."""

    sector_exposure: dict[str, float] = Field(default_factory=dict)
    dominant_sector: str | None = None
    concentrated: bool = False
    warning: str | None = None
    diversifying_tickers: list[str] = Field(default_factory=list)


# Missing-news notes that older snapshots stored in their decision trace. The engine no longer
# writes them (missing news shows nothing), so they are dropped from snapshots built before that.
_RETIRED_TRACE_PREFIXES = (
    "Sentiment is unavailable. News coverage gap",
    "News-aware check abstained to the forecast-only stance",
)


class RecommendationSnapshot(BaseModel):
    """The single object every dashboard view reads.

    The base snapshot (forecast + signal + evidence + explanation) is precomputed per
    ticker x risk tier by the offline assembler. `diversification` and any concentration
    downgrade are applied per user at request time.
    """

    ticker: str
    name: str
    sector: str
    asset_type: str
    as_of: date | None = None
    forecast: Forecast
    signal: Signal
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: Explanation
    diversification: Diversification | None = None
    # Read from stored news at request time (company detail only), so they reflect the latest
    # nightly collection even when the precomputed snapshot is older.
    recent_news: list[Evidence] = Field(default_factory=list)
    news_sentiment: NewsSentiment | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RecommendationSnapshot":
        """Build from a joined assets + recommendation_snapshots row.

        asyncpg's jsonb codec decodes the JSONB columns to dicts/lists already, so the
        rich detail (decision_trace, news_signal, evidence, explanation) arrives shaped.
        """
        detail = row.get("signal_detail") or {}
        return cls(
            ticker=row["ticker"],
            name=row["name"],
            sector=row["sector"],
            asset_type=row["asset_type"],
            as_of=row.get("as_of"),
            forecast=Forecast(**(row.get("forecast") or {})),
            signal=Signal(
                baseline_stance=row["baseline_stance"],
                news_aware_stance=row["news_aware_stance"],
                provisional=row.get("provisional", False),
                decision_trace=[line for line in detail.get("decision_trace", [])
                                if not line.startswith(_RETIRED_TRACE_PREFIXES)],
                news_signal=NewsSignal(**(detail.get("news_signal") or {})),
                fundamentals_signal=FundamentalsSignal(**(detail.get("fundamentals_signal") or {})),
                risk_profile=row["risk_profile"],
            ),
            evidence=[Evidence(**e) for e in (row.get("evidence") or [])],
            explanation=Explanation(**(row.get("explanation") or {"text": ""})),
        )


class DiscoveryResponse(BaseModel):
    """The personalised discovery screen: ranked candidate snapshots + a diversification note."""

    candidates: list[RecommendationSnapshot] = Field(default_factory=list)
    diversification: DiversificationNote
