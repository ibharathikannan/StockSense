"""Unit tests for relevance-weighted news-sentiment aggregation (P1c).

Covers the aggregation math, relevance filtering, recency weighting, deduplication,
the minimum-article abstention, no-look-ahead, document extraction, and the hand-off
into the hybrid signal engine. Deterministic; fixed timestamps, no network.
"""
from datetime import datetime, timedelta, timezone

from data.rag.news_sentiment import (
    AggregationConfig,
    AVSentimentRecord,
    aggregate_ticker_sentiment,
    build_news_signals,
    records_from_documents,
)
from backend.app.rule_engine.hybrid_engine import evaluate_signal

AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def rec(ticker="AAPL", score=0.0, relevance=0.9, age_hours=1.0, url="", content_hash="", article_id=""):
    published = AS_OF - timedelta(hours=age_hours)
    return AVSentimentRecord(ticker=ticker, score=score, relevance=relevance,
                             published_at=published, available_at=published,
                             url=url, content_hash=content_hash, article_id=article_id)


def test_relevance_weighted_mean_matches_formula():
    # The user's Apple example; all same age so recency weights cancel.
    records = [
        rec(score=-0.8, relevance=0.95, url="a"),   # disappointing earnings
        rec(score=0.3, relevance=0.15, url="b"),    # tangential MSFT mention
        rec(score=0.7, relevance=0.90, url="c"),    # iPhone launch
    ]
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF,
                                     AggregationConfig(relevance_floor=0.1, min_articles=2))
    # (0.95*-0.8 + 0.15*0.3 + 0.90*0.7) / (0.95+0.15+0.90) = -0.085 / 2.0
    assert out is not None
    assert abs(out["score"] - (-0.0425)) < 1e-6
    assert out["article_count"] == 3
    assert out["source"] == "alpha_vantage" and out["relevant"] is True


def test_relevance_floor_excludes_low_relevance():
    records = [rec(score=-0.8, relevance=0.95, url="a"),
               rec(score=0.3, relevance=0.15, url="b"),
               rec(score=0.7, relevance=0.90, url="c")]
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF,
                                     AggregationConfig(relevance_floor=0.2, min_articles=2))
    assert out["article_count"] == 2   # the 0.15 article dropped
    assert abs(out["score"] - (-0.13 / 1.85)) < 1e-6


def test_recency_weighting_favours_newer():
    records = [rec(score=0.5, relevance=0.9, age_hours=1, url="new"),
               rec(score=-0.5, relevance=0.9, age_hours=48, url="old")]
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF,
                                     AggregationConfig(half_life_hours=24, min_articles=2))
    assert out["score"] > 0          # newer positive outweighs older negative
    assert abs(out["recency_hours"] - 1.0) < 1e-6


def test_duplicate_stories_counted_once():
    records = [rec(score=-0.4, relevance=0.9, url="dup"),
               rec(score=-0.4, relevance=0.9, url="dup"),
               rec(score=-0.4, relevance=0.9, url="other")]
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF, AggregationConfig(min_articles=2))
    assert out["article_count"] == 2


def test_min_articles_abstains():
    out = aggregate_ticker_sentiment([rec(score=-0.9, relevance=0.9, url="a")], "AAPL", AS_OF,
                                     AggregationConfig(min_articles=2))
    assert out is None


def test_no_lookahead_excludes_future_publication_and_availability():
    future_pub = AVSentimentRecord("AAPL", -0.9, 0.9, AS_OF + timedelta(hours=1), AS_OF - timedelta(hours=1))
    future_avail = AVSentimentRecord("AAPL", -0.9, 0.9, AS_OF - timedelta(hours=1), AS_OF + timedelta(hours=1))
    out = aggregate_ticker_sentiment([future_pub, future_avail, rec(score=-0.5, url="a")],
                                     "AAPL", AS_OF, AggregationConfig(min_articles=2))
    assert out is None   # only one eligible record remains


def test_window_excludes_stale_articles():
    records = [rec(score=-0.5, age_hours=10, url="a"), rec(score=-0.5, age_hours=200, url="b")]
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF,
                                     AggregationConfig(window_hours=72, min_articles=1))
    assert out["article_count"] == 1


def test_records_from_documents_extracts_relevance_and_skips_alpaca():
    docs = [
        {"provider": "alpha_vantage", "published_at": "2026-01-10T10:00:00Z",
         "available_at": "2026-01-10T10:00:00Z", "source_url": "u1", "content_hash": "h1",
         "provider_id": "p1",
         "provider_sentiment": {"AAPL": {"score": "-0.3", "label": "Bearish", "relevance": "0.8"}}},
        {"provider": "alpaca", "published_at": "2026-01-10T10:00:00Z",
         "available_at": "2026-01-10T10:00:00Z", "provider_sentiment": None},
        {"provider": "alpha_vantage", "published_at": "2026-01-10T10:00:00Z",
         "available_at": "2026-01-10T10:00:00Z",
         "provider_sentiment": {"MSFT": {"score": "0.2", "label": "Bullish"}}},  # missing relevance
    ]
    records = records_from_documents(docs)
    assert len(records) == 1
    assert records[0].ticker == "AAPL" and records[0].relevance == 0.8 and records[0].score == -0.3


def test_records_from_documents_default_relevance_keeps_free_tier_corpus():
    # The existing free-tier corpus has score/label but no relevance. With a default,
    # those records are kept and flagged assumed rather than dropped.
    docs = [
        {"provider": "alpha_vantage", "published_at": "2026-01-10T10:00:00Z",
         "available_at": "2026-01-10T10:00:00Z", "source_url": "u1",
         "provider_sentiment": {"AAPL": {"score": "-0.3", "label": "Bearish", "relevance": "0.8"}}},
        {"provider": "alpha_vantage", "published_at": "2026-01-10T10:00:00Z",
         "available_at": "2026-01-10T10:00:00Z", "source_url": "u2",
         "provider_sentiment": {"MSFT": {"score": "0.2", "label": "Bullish"}}},  # no relevance
    ]
    records = records_from_documents(docs, default_relevance=1.0)
    by_ticker = {r.ticker: r for r in records}
    assert by_ticker["AAPL"].relevance == 0.8 and by_ticker["AAPL"].relevance_assumed is False
    assert by_ticker["MSFT"].relevance == 1.0 and by_ticker["MSFT"].relevance_assumed is True


def test_aggregate_flags_relevance_unavailable_when_all_assumed():
    recs = [AVSentimentRecord("AAPL", -0.4, 1.0, AS_OF - timedelta(hours=1), AS_OF - timedelta(hours=1),
                              url="a", relevance_assumed=True),
            AVSentimentRecord("AAPL", -0.4, 1.0, AS_OF - timedelta(hours=2), AS_OF - timedelta(hours=2),
                              url="b", relevance_assumed=True)]
    out = aggregate_ticker_sentiment(recs, "AAPL", AS_OF, AggregationConfig(min_articles=2))
    assert out is not None and out["relevance_available"] is False


def test_build_news_signals_maps_abstention_to_none():
    records = [rec(ticker="AAPL", score=-0.5, url="a"), rec(ticker="AAPL", score=-0.5, url="b"),
               rec(ticker="MSFT", score=0.5, url="c")]
    signals = build_news_signals(records, ["AAPL", "MSFT"], AS_OF, AggregationConfig(min_articles=2))
    assert signals["AAPL"] is not None
    assert signals["MSFT"] is None   # only one MSFT article


def test_marketaux_source_flows_through_and_engine_accepts_it():
    docs = [{"provider": "marketaux", "published_at": "2026-01-10T11:00:00Z",
             "available_at": "2026-01-10T11:00:00Z", "source_url": u, "provider_id": u,
             "provider_sentiment": {"AAPL": {"score": -0.4, "relevance": 0.6, "label": "Bearish"}}}
            for u in ("m1", "m2")]
    records = records_from_documents(docs)
    assert all(r.source == "marketaux" for r in records)
    out = aggregate_ticker_sentiment(records, "AAPL", AS_OF, AggregationConfig(min_articles=2))
    assert out["source"] == "marketaux"
    signal = evaluate_signal(forecast_return=4.0, volatility=0.18, prediction_interval_width=3.0,
                             risk_profile="moderate", news_signal=out)
    # Strongly negative Marketaux sentiment (-0.4) drives the base engine to CAUTION.
    assert signal["news_aware_stance"] == "CAUTION" and signal["provisional"] is True
    assert signal["news_signal"]["source"] == "marketaux"


def test_feeds_engine_strong_negative_triggers_provisional_monitor():
    records = [rec(score=-0.4, relevance=0.9, url="a"), rec(score=-0.4, relevance=0.9, url="b")]
    news_signal = aggregate_ticker_sentiment(records, "AAPL", AS_OF, AggregationConfig(min_articles=2))
    signal = evaluate_signal(forecast_return=4.0, volatility=0.18, prediction_interval_width=3.0,
                             risk_profile="moderate", news_signal=news_signal)
    # Baseline is conservative (no news -> MONITOR); strongly negative news -> CAUTION.
    assert signal["baseline_stance"] == "MONITOR"
    assert signal["news_aware_stance"] == "CAUTION"
    assert signal["provisional"] is True
