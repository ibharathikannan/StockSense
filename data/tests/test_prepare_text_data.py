"""Preparation checks: citation integrity, temporal eligibility and attribution."""

from datetime import datetime, timezone
import re

from data import prepare_text_data as prep


UNIVERSE = {"AAPL": {"name": "Apple Inc."}, "MSFT": {"name": "Microsoft Corporation"}, "A": {"name": "Agilent Technologies, Inc."}}
AS_OF = datetime(2026, 10, 2, tzinfo=timezone.utc)


def record(**changes):
    return {"document_id": "news:1:v1", "source_type": "news", "provider": "alpaca",
            "provider_id": "1", "tickers": ["AAPL"], "published_at": "2026-10-01T10:00:00Z",
            "available_at": "2026-10-01T10:15:00Z", "fetched_at": "2026-10-01T10:15:00Z",
            "updated_at": "2026-10-01T10:00:00Z", "source_url": "https://example.org/story?utm_source=x",
            "title": "Apple reports growth", "text": "<p>Apple earnings improved.</p>",
            "content_hash": "raw", "content_available": True, **changes}


class TokenizerFixture:
    def __call__(self, text, **kwargs):
        return {"offset_mapping": [match.span() for match in re.finditer(r"\S+", text)]}


def test_future_revisions_and_unavailable_sources_are_excluded():
    future = record(document_id="news:1:v2", updated_at="2026-10-03T10:00:00Z")
    unobserved = record(document_id="news:2:v1", provider_id="2", available_at="2026-10-04T10:00:00Z", fetched_at="2026-10-04T10:00:00Z")
    docs, rejected = prep.normalize_documents([record(), future, unobserved], UNIVERSE, AS_OF)
    assert [r["document_id"] for r in docs] == ["news:1:v1"]
    assert {r["reason"] for r in rejected} == {"revision_after_cutoff", "not_available_at_cutoff"}


def test_cross_provider_copy_keeps_full_text_and_provider_sentiment():
    av = record(document_id="av:1", provider="alpha_vantage", provider_id="av1", text="Summary", content_available=False,
                provider_sentiment={"AAPL": {"score": "0.2"}}, source_url="https://example.org/story?utm_medium=y")
    docs, rejected = prep.normalize_documents([record(), av], UNIVERSE, AS_OF)
    assert len(docs) == 1
    assert set(docs[0]["source_document_ids"]) == {"news:1:v1", "av:1"}
    assert docs[0]["provider_sentiment"]["AAPL"]["score"] == "0.2"
    assert "Apple earnings improved." in docs[0]["text"]
    assert not rejected


def test_chunks_preserve_source_offsets_and_token_bound():
    text = "Item 1. Business\n" + " ".join(f"word{i}" for i in range(500)) + "\nItem 1A. Risk Factors\nOperational risks."
    docs, _ = prep.normalize_documents([record(source_type="sec", text=text)], UNIVERSE, AS_OF)
    chunks = prep.chunk_documents(docs, TokenizerFixture())
    assert len(chunks) >= 4
    for chunk in chunks:
        assert chunk["text"] == docs[0]["text"][chunk["start_char"]:chunk["end_char"]]
        assert chunk["token_count"] <= 220
        assert chunk["source_url"] == docs[0]["source_url"]
    assert any("Risk Factors" in chunk["section"] for chunk in chunks)


def test_sentiment_does_not_assign_shared_sentence_to_both_companies():
    doc = record(tickers=["AAPL", "MSFT"], text="Apple and Microsoft report results. Apple profit rose. Microsoft revenue fell.")
    rows = prep.sentiment_inputs([doc], UNIVERSE)
    assert rows[0]["text"] == "Apple profit rose."
    assert rows[1]["text"] == "Microsoft revenue fell."
    short = prep.sentiment_inputs([record(tickers=["A"], text="A new product was announced.")], UNIVERSE)
    assert short[0]["status"] == "unavailable_ambiguous_attribution"


def test_aggregates_keep_missing_sentiment_null_and_provider_separate():
    docs, _ = prep.normalize_documents([record(provider_sentiment={"AAPL": {"score": "0.4"}})], UNIVERSE, AS_OF)
    aggregates = {row["ticker"]: row for row in prep.aggregate_sentiment(docs, [], UNIVERSE, AS_OF)}
    assert aggregates["AAPL"]["articles_7d"] == 1
    assert aggregates["AAPL"]["local_sentiment_7d"] is None
    assert aggregates["AAPL"]["alpha_vantage_sentiment_7d"] == 0.4
    assert aggregates["MSFT"]["sentiment_status"] == "unavailable"
    assert aggregates["MSFT"]["local_sentiment_7d"] is None
    assert not aggregates["AAPL"]["historical_training_eligible"]
