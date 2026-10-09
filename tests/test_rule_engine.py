"""Unit tests for the news-aware hybrid layer over the team's base rule engine.

The base engine (backend/app/rule_engine/rule_based_engine.py, PR #16) is unchanged and has
its own tests under backend/tests/. Here we test the hybrid wrapper that runs it without/with
news: the baseline is conservative (never EXPLORE without bullish sentiment), and eligible
recent news can upgrade to EXPLORE or downgrade to CAUTION, flagged provisional. Deterministic.
"""
from backend.app.rule_engine.hybrid_engine import evaluate_signal
from backend.app.rule_engine.rule_based_engine import evaluate_stock_stance


def _news(score, *, articles=3, recency=10.0, relevant=True, source="marketaux"):
    return {"score": score, "article_count": articles, "recency_hours": recency,
            "relevant": relevant, "source": source}


# --- Baseline (no news) ------------------------------------------------------------

def test_baseline_without_news_tops_out_at_monitor():
    s = evaluate_signal(4.0, 0.18, risk_profile="moderate", prediction_interval_width=3.0)
    assert s["baseline_stance"] == "MONITOR"          # base engine needs bullish sentiment for EXPLORE
    assert s["news_aware_stance"] == "MONITOR" and s["provisional"] is False


def test_negative_forecast_is_caution():
    s = evaluate_signal(-1.2, 0.12, prediction_interval_width=3.0)
    assert s["baseline_stance"] == "CAUTION"


def test_volatility_exceeds_profile_is_caution():
    s = evaluate_signal(3.0, 0.3815, prediction_interval_width=4.5, risk_profile="conservative")
    assert s["baseline_stance"] == "CAUTION"


# --- News-aware changes ------------------------------------------------------------

def test_bullish_news_upgrades_monitor_to_explore_provisional():
    s = evaluate_signal(4.0, 0.18, prediction_interval_width=3.0, news_signal=_news(0.3))
    assert s["baseline_stance"] == "MONITOR"
    assert s["news_aware_stance"] == "EXPLORE" and s["provisional"] is True
    assert any("News-driven change" in t for t in s["decision_trace"])
    assert s["news_signal"]["source"] == "marketaux"


def test_bearish_news_downgrades_to_caution_provisional():
    s = evaluate_signal(4.0, 0.18, prediction_interval_width=3.0, news_signal=_news(-0.3))
    assert s["news_aware_stance"] == "CAUTION" and s["provisional"] is True


def test_no_usable_news_stays_at_baseline():
    base = dict(forecast_return=4.0, volatility=0.18, prediction_interval_width=3.0)
    for ns in (None, _news(-0.5, source="local"), _news(-0.5, relevant=False),
               _news(-0.5, recency=200.0), _news(-0.5, articles=1)):
        s = evaluate_signal(news_signal=ns, **base)
        assert s["news_aware_stance"] == s["baseline_stance"] and s["provisional"] is False


def test_sector_concentration_blocks_explore():
    # Bullish news that would normally reach EXPLORE, but heavy sector weight holds it at MONITOR.
    s = evaluate_signal(4.0, 0.18, prediction_interval_width=3.0, news_signal=_news(0.3),
                        sector_weight=0.5)
    assert s["news_aware_stance"] == "MONITOR"


def test_high_uncertainty_blocks_explore():
    s = evaluate_signal(4.0, 0.18, prediction_interval_width=8.5, news_signal=_news(0.3))
    assert s["news_aware_stance"] == "MONITOR"


def test_profile_normalization():
    a = evaluate_signal(1.0, 0.14, risk_profile="very_conservative")
    b = evaluate_signal(1.0, 0.14, risk_profile="Very Conservative")
    assert a["risk_profile"] == b["risk_profile"] == "very conservative"


# --- The team's base engine is preserved and usable --------------------------------

def test_base_engine_still_available_with_reason_codes():
    res = evaluate_stock_stance(3.0, 0.18, sentiment_score=0.3, prediction_interval_width=3.0,
                                user_risk_profile="moderate")
    assert res["stance"] == "EXPLORE"
    assert "reason_codes" in res and "decision_trace" in res
