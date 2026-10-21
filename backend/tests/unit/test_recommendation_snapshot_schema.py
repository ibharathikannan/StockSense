"""Snapshot rows map stored signal detail, including SEC fundamentals, onto the API schema."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.schemas.recommendations import RecommendationSnapshot
from scripts.load_snapshots import _snapshot_row


def row(detail):
    return {"ticker": "AAPL", "name": "Apple", "sector": "Information Technology",
            "asset_type": "stock", "as_of": None, "risk_profile": "moderate",
            "baseline_stance": "MONITOR", "news_aware_stance": "EXPLORE", "provisional": True,
            "forecast": {}, "signal_detail": detail, "evidence": [], "explanation": {"text": "x"}}


FUNDAMENTALS = {"score": 0.8, "rating": "strong", "metric_count": 3, "age_days": 30,
                "source": "sec_xbrl", "period_end": "2025-12-31", "filed": "2026-02-15",
                "metrics": {"operating_margin": {"value": 0.3, "assessment": "strong"}}}


def test_fundamentals_are_served_from_signal_detail():
    snap = RecommendationSnapshot.from_row(row({"decision_trace": ["t"], "news_signal": {},
                                                "fundamentals_signal": FUNDAMENTALS}))
    signal = snap.signal.fundamentals_signal
    assert signal.rating == "strong" and signal.metrics["operating_margin"].value == 0.3
    assert str(signal.period_end) == "2025-12-31"


def test_rows_stored_before_fundamentals_still_load():
    snap = RecommendationSnapshot.from_row(row({"decision_trace": [], "news_signal": {}}))
    assert snap.signal.fundamentals_signal.score is None
    assert snap.signal.fundamentals_signal.metrics == {}


def test_loader_keeps_fundamentals_and_tolerates_old_artifacts():
    snap = {"ticker": "AAPL", "as_of": "2026-10-09T00:00:00+00:00", "forecast": {}, "evidence": [],
            "explanation": {}, "signal": {"risk_profile": "moderate", "baseline_stance": "MONITOR",
                                          "news_aware_stance": "MONITOR", "provisional": False,
                                          "decision_trace": [], "news_signal": {}}}
    assert _snapshot_row(snap)["signal_detail"]["fundamentals_signal"] is None
    snap["signal"]["fundamentals_signal"] = FUNDAMENTALS
    assert _snapshot_row(snap)["signal_detail"]["fundamentals_signal"] == FUNDAMENTALS
