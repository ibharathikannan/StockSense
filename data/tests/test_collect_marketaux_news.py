"""Tests for Marketaux collection: per-entity attribution, match_score normalisation,
dedup, and the request-budget guard. HTTP is mocked; no network, no key needed."""
from datetime import datetime, timezone

from data import collect_marketaux_news as mx


def _article(uuid="u1"):
    return {
        "uuid": uuid, "url": f"https://news.example/{uuid}", "title": "Apple and Microsoft",
        "description": "Apple and Microsoft headlines.", "source": "example.com",
        "published_at": "2026-10-07T12:00:00.000000Z",
        "entities": [
            {"symbol": "AAPL", "type": "equity", "sentiment_score": 0.2, "match_score": 40.0},
            {"symbol": "MSFT", "type": "equity", "sentiment_score": -0.3, "match_score": 10.0},
            {"symbol": "ZZZZ", "type": "equity", "sentiment_score": 0.9, "match_score": 99.0},
        ],
    }


def test_record_uses_per_entity_sentiment_and_normalises_match_score():
    rec = mx._record(_article(), {"AAPL", "MSFT"}, "2026-10-08T00:00:00Z")
    assert rec["provider"] == "marketaux" and rec["tickers"] == ["AAPL", "MSFT"]
    aapl = rec["provider_sentiment"]["AAPL"]
    assert aapl["score"] == 0.2 and aapl["relevance"] == 0.4 and aapl["label"] == "Bullish"
    msft = rec["provider_sentiment"]["MSFT"]
    assert msft["score"] == -0.3 and msft["relevance"] == 0.1 and msft["label"] == "Bearish"
    assert "ZZZZ" not in rec["provider_sentiment"]          # non-universe entity dropped


def test_record_none_when_no_universe_entity():
    assert mx._record(_article(), {"TSLA"}, "2026-10-08T00:00:00Z") is None


def test_collect_dedups_across_symbols_and_counts_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(mx, "fetch_json", lambda url, headers=None, timeout=30: {"data": [_article("same")]})
    cov = mx.collect(symbols=["AAPL", "MSFT"], published_after=datetime(2026, 10, 5, tzinfo=timezone.utc),
                     output_dir=tmp_path, key="k", limit=3, max_requests=10, pause=0)
    assert cov["requests"] == 2
    docs = mx.read_jsonl(tmp_path / "documents.jsonl")
    assert len(docs) == 1                                   # same uuid returned twice -> one doc


def test_collect_respects_request_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(mx, "fetch_json", lambda url, headers=None, timeout=30: {"data": [_article()]})
    cov = mx.collect(symbols=["AAPL", "MSFT", "NVDA"], published_after=datetime(2026, 10, 5, tzinfo=timezone.utc),
                     output_dir=tmp_path, key="k", limit=3, max_requests=1, pause=0)
    assert cov["requests"] == 1
    statuses = [info["status"] for info in cov["symbols"].values()]
    assert statuses.count("skipped_budget") == 2
