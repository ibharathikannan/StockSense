"""Unit tests for snapshot assembly (P7). Pure — exercises the real engine + explainer, no DB."""
from datetime import datetime, timezone

from data.rag.assemble_snapshots import build_snapshot, placeholder_forecast

AS_OF = datetime(2026, 10, 9, tzinfo=timezone.utc)
PROFILE = {"ticker": "AAPL", "name": "Apple", "sector": "Information Technology",
           "asset_type": "stock", "risk": {"volatility_1y": 0.22}}
EVIDENCE = [{"title": "Apple update", "source_type": "news",
             "published_at": "2026-10-07T00:00:00Z", "source_url": "u", "snippet": "s"}]


def _news(score):
    return {"score": score, "article_count": 3, "recency_hours": 10.0, "relevant": True,
            "source": "marketaux", "relevance": 0.1}


def test_placeholder_forecast_is_pending():
    f = placeholder_forecast("AAPL")
    assert f["return_10d"] is None and "pending" in f["basis"].lower()


def test_placeholder_never_yields_explore_and_notes_pending():
    snap = build_snapshot(PROFILE, "moderate", _news(0.3), EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    assert snap["forecast"]["return_10d"] is None
    assert snap["signal"]["news_aware_stance"] in ("MONITOR", "CAUTION")   # EXPLORE needs a real forecast
    assert any("Forecast pending" in t for t in snap["signal"]["decision_trace"])
    assert snap["explanation"]["text"]


def test_bearish_news_still_drives_caution_under_placeholder():
    snap = build_snapshot(PROFILE, "moderate", _news(-0.3), EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    assert snap["signal"]["news_aware_stance"] == "CAUTION"


def test_snapshot_has_full_shape():
    snap = build_snapshot(PROFILE, "conservative", None, EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    for key in ("ticker", "name", "sector", "asset_type", "as_of", "forecast", "signal",
                "evidence", "explanation"):
        assert key in snap
    assert snap["signal"]["risk_profile"] == "conservative"
    assert snap["evidence"] == EVIDENCE
