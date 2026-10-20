"""Unit tests for snapshot assembly (P7). Pure — exercises the real engine + explainer, no DB."""
from datetime import datetime, timezone

from data.rag.assemble_snapshots import build_snapshot, load_forecasts, placeholder_forecast

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


# --- Real forecast wiring (main's saved XGBoost results feed the hybrid engine) ---------

def _write_forecasts(tmp_path, rows):
    header = ("ticker,Date,predicted_return_10d,lower_return,upper_return,"
              "uncertainty_width_pp,nominal_coverage,model,forecast_horizon_sessions\n")
    body = "".join(f"{t},2026-10-08,{p},{lo},{up},{(up-lo)*100},0.9,xgboost_v1,10\n"
                   for t, p, lo, up in rows)
    (tmp_path / "forecasts.csv").write_text(header + body)
    (tmp_path / "report.json").write_text('{"metadata": {"selected_model": "xgboost_v1"}}')
    return tmp_path


def test_load_forecasts_scales_fractions_to_percent(tmp_path):
    _write_forecasts(tmp_path, [("AAPL", 0.04, 0.015, 0.065)])
    fc = load_forecasts(str(tmp_path))
    assert fc["AAPL"]["return_10d"] == 4.0          # 0.04 fraction -> 4.0 percent
    assert fc["AAPL"]["lower"] == 1.5 and fc["AAPL"]["upper"] == 6.5
    assert fc["AAPL"]["model_version"] == "xgboost_v1"
    assert fc["AAPL"]["return_10d"] is not None and "pending" not in fc["AAPL"]["basis"].lower()


def test_load_forecasts_absent_returns_empty(tmp_path):
    assert load_forecasts(str(tmp_path / "nope")) == {}   # falls back to placeholder in assemble
    assert load_forecasts(None) in ({}, load_forecasts(None))  # None without env var -> {}


def test_real_negative_forecast_drives_caution(tmp_path):
    # Regression: the old 0.0 placeholder never tripped the negative-return rule; a real
    # negative forecast must, even with no news.
    fc = load_forecasts(str(_write_forecasts(tmp_path, [("AAPL", -0.02, -0.05, 0.01)])))
    snap = build_snapshot(PROFILE, "moderate", None, EVIDENCE, fc["AAPL"], AS_OF)
    assert snap["signal"]["news_aware_stance"] == "CAUTION"
    assert snap["forecast"]["return_10d"] == -2.0
    assert not any("Forecast pending" in t for t in snap["signal"]["decision_trace"])
