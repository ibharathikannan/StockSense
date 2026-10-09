"""Behavioral checks for resumable offline news collection."""

from datetime import datetime, timezone, timedelta
import pytest

from data import collect_news as news


START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


@pytest.fixture(autouse=True)
def isolated_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "AV_QUOTA_PATH", tmp_path / "quota.sqlite3")


def test_av_records_persist_ticker_sentiment_with_relevance():
    """Alpha Vantage per-ticker sentiment must retain relevance_score (the field the P1
    diagnostic found was being dropped and cannot be recovered later)."""
    article = {
        "time_published": "20260110T110000",
        "url": "https://example.org/apple-earnings",
        "title": "Apple reports results", "summary": "Apple earnings summary.",
        "source": "Example Newswire",
        "ticker_sentiment": [
            {"ticker": "AAPL", "ticker_sentiment_label": "Bearish",
             "ticker_sentiment_score": "-0.3", "relevance_score": "0.92"},
            {"ticker": "ZZZZ", "ticker_sentiment_score": "0.1", "relevance_score": "0.4"},
        ],
    }
    records = news._av_records(article, {"AAPL"}, "2026-01-10T12:00:00Z")
    assert len(records) == 1
    sentiment = records[0]["provider_sentiment"]["AAPL"]
    assert sentiment == {"label": "Bearish", "score": "-0.3", "relevance": "0.92"}


def test_quota_is_shared_across_output_directories():
    for expected in range(1, 26):
        assert news.reserve_av_request("account", "2026-09-02") == expected
    with pytest.raises(RuntimeError, match="budget exhausted"):
        news.reserve_av_request("account", "2026-09-02", known_used=0)
    assert news.reserve_av_request("account", "2026-09-03") == 1


def alpaca_article(*, updated="2026-09-01T12:00:00Z", headline="AAPL story"):
    return {"id": 123, "created_at": "2026-09-01T11:00:00Z", "updated_at": updated,
            "headline": headline, "summary": "Summary", "content": "Story text",
            "symbols": ["AAPL", "OTHER"], "source": "benzinga",
            "url": "https://example.com/story"}


def test_alpaca_full_pagination_local_filter_and_resume(tmp_path, monkeypatch):
    calls = []
    def response(url, headers=None, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return {"news": [alpaca_article(), {**alpaca_article(), "id": 999, "symbols": ["OTHER"]}],
                    "next_page_token": "next"}
        return {"news": [{**alpaca_article(), "id": 124, "symbols": ["MSFT"]}],
                "next_page_token": None}
    monkeypatch.setattr(news, "fetch_json", response)
    monkeypatch.setattr(news, "utc_now", lambda: END)
    coverage = {"windows": {}, "quota": {}}
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL", "MSFT"}, key="key", secret="secret")
    records = news.read_jsonl(tmp_path / "documents.jsonl")
    assert len(records) == 2
    assert {tuple(record["tickers"]) for record in records} == {("AAPL",), ("MSFT",)}
    assert all(record["available_at"] == "2026-09-02T00:00:00Z" for record in records)
    assert next(iter(coverage["windows"].values()))["status"] == "collected"
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL", "MSFT"}, key="key", secret="secret")
    assert len(calls) == 2


def test_failed_page_does_not_mark_window_complete(tmp_path, monkeypatch):
    calls = 0
    def response(url, headers=None, timeout=30):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"news": [alpaca_article()], "next_page_token": "next"}
        if calls < 5:
            raise RuntimeError("temporary failure with secret")
        return {"news": [alpaca_article()], "next_page_token": None}
    monkeypatch.setattr(news, "fetch_json", response)
    monkeypatch.setattr(news.time, "sleep", lambda _: None)
    monkeypatch.setattr(news, "utc_now", lambda: END)
    coverage = {"windows": {}, "quota": {}}
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL"}, key="key", secret="secret")
    assert next(iter(coverage["windows"].values()))["status"] == "failed"
    assert not (tmp_path / "documents.jsonl").exists()
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL"}, key="key", secret="secret")
    assert next(iter(coverage["windows"].values()))["status"] == "collected"
    assert len(news.read_jsonl(tmp_path / "documents.jsonl")) == 1


def test_alpaca_revisions_are_retained(tmp_path, monkeypatch):
    current = alpaca_article()
    monkeypatch.setattr(news, "fetch_json", lambda *args, **kwargs: {"news": [current], "next_page_token": None})
    monkeypatch.setattr(news, "utc_now", lambda: END)
    coverage = {"windows": {}, "quota": {}}
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL"}, key="key", secret="secret")
    coverage["windows"].clear()
    current = alpaca_article(updated="2026-09-01T13:00:00Z", headline="Revised")
    news.collect_alpaca(start=START, end=END, output_dir=tmp_path, coverage=coverage,
                        universe={"AAPL"}, key="key", secret="secret")
    assert len(news.read_jsonl(tmp_path / "documents.jsonl")) == 2


def test_alpha_vantage_daily_budget_counts_retries_and_recovers_next_day(tmp_path, monkeypatch):
    clock = [datetime(2026, 9, 2, tzinfo=timezone.utc)]
    monkeypatch.setattr(news, "utc_now", lambda: clock[0])
    monkeypatch.setattr(news.time, "sleep", lambda _: None)
    calls = 0
    def response(url, headers=None, timeout=30):
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise RuntimeError("key in provider URL")
        return {"items": 0, "feed": []}
    monkeypatch.setattr(news, "fetch_json", response)
    coverage = {"windows": {}, "quota": {"2026-09-02": {"used": 24}}}
    news.collect_alpha_vantage(start=START, end=END, output_dir=tmp_path,
                               coverage=coverage, universe={"AAPL"}, key="private")
    assert coverage["quota"]["2026-09-02"]["used"] == 25
    assert next(iter(coverage["windows"].values()))["status"] == "failed"
    clock[0] += timedelta(days=1)
    news.collect_alpha_vantage(start=START, end=END, output_dir=tmp_path,
                               coverage=coverage, universe={"AAPL"}, key="private")
    assert next(iter(coverage["windows"].values()))["status"] == "no_results"
    assert coverage["quota"]["2026-09-03"]["used"] == 3
