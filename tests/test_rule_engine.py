"""
Unit tests for Rule Engine.
"""
from backend.app.rule_engine.rule_based_engine import evaluate_stock_stance


def test_explore_stance_high_confluence():
    """All positive signals produce an EXPLORE stance."""
    result = evaluate_stock_stance(
        forecast_return=3.4,
        volatility=0.18,
        sentiment_score=0.28,
        prediction_interval_width=3.2,
        user_risk_profile="conservative"
    )
    assert result["stance"] == "EXPLORE"
    assert any("Favorable trend" in trace for trace in result["decision_trace"])


def test_missing_sentiment_fallback():
    """Missing news sentiment (None) defaults to neutral and yields MONITOR."""
    result = evaluate_stock_stance(
        forecast_return=2.5,
        volatility=0.25,
        sentiment_score=None,
        prediction_interval_width=4.0,
        user_risk_profile="moderate"
    )
    assert result["stance"] == "MONITOR"
    assert any("News coverage gap" in trace for trace in result["decision_trace"])


def test_high_uncertainty_blocks_explore():
    """Wide uncertainty band (>6.0%) prevents an EXPLORE stance."""
    result = evaluate_stock_stance(
        forecast_return=4.8,
        volatility=0.30,
        sentiment_score=0.35,
        prediction_interval_width=8.5,
        user_risk_profile="growth"
    )
    assert result["stance"] == "MONITOR"
    assert any("Forecast ambiguity" in trace for trace in result["decision_trace"])


def test_volatility_exceeds_profile_triggers_caution():
    """High volatility asset triggers CAUTION for a conservative user."""
    result = evaluate_stock_stance(
        forecast_return=3.0,
        volatility=0.3815,
        sentiment_score=0.20,
        prediction_interval_width=4.5,
        user_risk_profile="conservative"
    )
    assert result["stance"] == "CAUTION"
    assert any("Risk mismatch" in trace for trace in result["decision_trace"])


def test_growth_profile_accommodates_higher_volatility():
    """Higher volatility is acceptable within a growth risk profile."""
    result = evaluate_stock_stance(
        forecast_return=3.0,
        volatility=0.3815,
        sentiment_score=0.20,
        prediction_interval_width=4.5,
        user_risk_profile="growth"
    )
    assert result["stance"] == "EXPLORE"


def test_negative_forecast_triggers_caution():
    """Negative projected return triggers immediate CAUTION."""
    result = evaluate_stock_stance(
        forecast_return=-1.2,
        volatility=0.12,
        sentiment_score=0.10,
        user_risk_profile="moderate"
    )
    assert result["stance"] == "CAUTION"
    assert any("Downside risk" in trace for trace in result["decision_trace"])


def test_profile_string_normalization():
    """Ensures casing and formatting variants resolve identically."""
    res1 = evaluate_stock_stance(1.0, 0.14, 0.0, user_risk_profile="very_conservative")
    res2 = evaluate_stock_stance(1.0, 0.14, 0.0, user_risk_profile="Very Conservative")
    assert res1["stance"] == res2["stance"]
