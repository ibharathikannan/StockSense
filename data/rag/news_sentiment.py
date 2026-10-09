"""Relevance-weighted news-sentiment aggregation (Alpha Vantage ticker-level).

Turns Alpha Vantage per-ticker sentiment records into the deterministic ``news_signal``
the hybrid signal engine consumes (`backend/app/rule_engine`). After the P1 attribution
diagnostic (docs/ai/SENTIMENT_ATTRIBUTION.md) Alpha Vantage is the trusted source; local
FinBERT is kept only for Alpaca articles and is never aggregated here.

Aggregation is relevance- and recency-weighted:

    S_news = Σ (w_i · r_i · s_i) / Σ (w_i · r_i)

with ``r_i`` the AV relevance_score (0..1), ``s_i`` the AV ticker_sentiment_score (-1..1),
and ``w_i = exp(-ln2 · age_hours / half_life_hours)`` a recency decay. Relevance decides how
much an article *contributes*, not how strongly sentiment overrides the forecast (the engine
owns the override).

Safeguards (all configurable): a relevance floor, a recency window, deduplication of repeated
stories, and a minimum article count below which the signal abstains (returns None). No
look-ahead: only records with ``published_at <= as_of`` and ``available_at <= as_of`` count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional


@dataclass(frozen=True)
class AggregationConfig:
    relevance_floor: float = 0.1      # ignore articles below this AV relevance
    window_hours: float = 72.0        # only articles within this age of as_of
    half_life_hours: float = 24.0     # recency decay half-life
    min_articles: int = 2             # abstain below this many eligible articles


@dataclass(frozen=True)
class AVSentimentRecord:
    """One Alpha Vantage per-ticker sentiment observation."""

    ticker: str
    score: float                      # AV ticker_sentiment_score, -1..1
    relevance: float                  # AV relevance_score, 0..1
    published_at: datetime
    available_at: datetime
    url: str = ""
    content_hash: str = ""
    article_id: str = ""
    relevance_assumed: bool = False   # True when relevance was not provided (free-tier corpus)
    source: str = "alpha_vantage"     # provider that attributed the sentiment (e.g. "marketaux")


def _as_utc(value: datetime | str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _dedup_key(record: AVSentimentRecord) -> str:
    """Collapse the same story seen more than once."""
    return record.url or record.content_hash or record.article_id or f"{record.ticker}:{record.published_at}"


def records_from_documents(
    documents: Iterable[dict], default_relevance: Optional[float] = None
) -> list[AVSentimentRecord]:
    """Extract AV ticker-sentiment records from normalised news documents.

    Reads `provider_sentiment[ticker] = {score, label, relevance}` written by the fixed
    `collect_news._av_records`. Alpaca documents (provider_sentiment is None) are skipped —
    they carry no provider sentiment. A record missing a *score* is always skipped.

    Relevance handling: when `relevance` is present it is used. When it is absent (the
    existing free-tier corpus — `relevance_score` was never persisted, and `NEWS_SENTIMENT`
    is now a premium endpoint) the record is skipped if `default_relevance` is None, or kept
    with that default and marked `relevance_assumed=True`. Pass e.g. `default_relevance=1.0`
    to run the degraded, equal-weight news-aware mode on the existing corpus.
    """
    records: list[AVSentimentRecord] = []
    for doc in documents:
        # Any provider that supplies its own per-ticker sentiment (Alpha Vantage,
        # Marketaux, ...). Alpaca carries no provider_sentiment and is skipped.
        provider_sentiment = doc.get("provider_sentiment") or {}
        if not provider_sentiment:
            continue
        source = doc.get("provider") or "alpha_vantage"
        for ticker, payload in provider_sentiment.items():
            try:
                score = float(payload.get("score"))
            except (TypeError, ValueError):
                continue
            assumed = False
            try:
                relevance = float(payload.get("relevance"))
            except (TypeError, ValueError):
                if default_relevance is None:
                    continue
                relevance, assumed = float(default_relevance), True
            records.append(AVSentimentRecord(
                ticker=ticker, score=score, relevance=relevance,
                published_at=_as_utc(doc["published_at"]),
                available_at=_as_utc(doc.get("available_at") or doc["published_at"]),
                url=doc.get("source_url", ""), content_hash=doc.get("content_hash", ""),
                article_id=str(doc.get("provider_id", "")), relevance_assumed=assumed,
                source=source,
            ))
    return records


def aggregate_ticker_sentiment(
    records: Iterable[AVSentimentRecord],
    ticker: str,
    as_of: datetime | str,
    config: AggregationConfig = AggregationConfig(),
) -> Optional[dict]:
    """Relevance- and recency-weighted sentiment for one ticker, or None to abstain.

    Returns the ``news_signal`` shape the engine expects:
        {score, relevance, recency_hours, source, article_count, relevant}
    None when fewer than ``min_articles`` eligible articles remain after the safeguards.
    """
    as_of = _as_utc(as_of)
    # Filter: ticker, no look-ahead, finite ranges, relevance floor, recency window. Dedup.
    eligible: dict[str, tuple[AVSentimentRecord, float]] = {}
    for rec in records:
        if rec.ticker != ticker:
            continue
        published, available = _as_utc(rec.published_at), _as_utc(rec.available_at)
        if published > as_of or available > as_of:      # no look-ahead
            continue
        if not (math.isfinite(rec.score) and -1.0 <= rec.score <= 1.0):
            continue
        if not (math.isfinite(rec.relevance) and 0.0 <= rec.relevance <= 1.0):
            continue
        if rec.relevance < config.relevance_floor:
            continue
        age_hours = (as_of - published).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > config.window_hours:
            continue
        key = _dedup_key(rec)
        # On duplicates keep the most recent observation of the story.
        if key not in eligible or published > _as_utc(eligible[key][0].published_at):
            eligible[key] = (rec, age_hours)

    if len(eligible) < config.min_articles:
        return None

    num = den = 0.0
    newest_age = math.inf
    for rec, age_hours in eligible.values():
        weight = math.exp(-math.log(2) * age_hours / config.half_life_hours)
        contribution = weight * rec.relevance
        num += contribution * rec.score
        den += contribution
        newest_age = min(newest_age, age_hours)
    if den == 0:
        return None

    mean_relevance = sum(rec.relevance for rec, _ in eligible.values()) / len(eligible)
    relevance_available = any(not rec.relevance_assumed for rec, _ in eligible.values())
    source = next(iter(eligible.values()))[0].source
    return {
        "score": num / den,
        "relevance": mean_relevance,
        "recency_hours": newest_age,
        "source": source,
        "article_count": len(eligible),
        "relevant": True,
        # False on the existing corpus: AV relevance_score is a premium field that was never
        # persisted, so weighting falls back to equal relevance. Surface this as a caveat.
        "relevance_available": relevance_available,
    }


def build_news_signals(
    records: Iterable[AVSentimentRecord],
    tickers: Iterable[str],
    as_of: datetime | str,
    config: AggregationConfig = AggregationConfig(),
) -> dict[str, Optional[dict]]:
    """Per-ticker news_signal map; value is None where the ticker abstains."""
    records = list(records)
    return {t: aggregate_ticker_sentiment(records, t, as_of, config) for t in tickers}
