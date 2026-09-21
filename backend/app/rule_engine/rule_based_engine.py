"""
Rule-Based Engine
"""
from typing import Optional, List, Dict, Any

# Volatility boundaries
VOLATILITY_LIMITS: Dict[str, float] = {
    "very conservative": 0.15,
    "conservative": 0.20,
    "moderate": 0.35,
    "growth": 0.45,
    "aggressive": 0.55
}

# Maximum acceptable confidence interval width (upper_bound - lower_bound %)
MAX_ALLOWED_INTERVAL_WIDTH: float = 6.0


def normalize_risk_profile(raw_profile: str) -> str:
    """Normalizes string inputs like 'very_conservative' or 'Growth' to canonical key."""
    return raw_profile.strip().lower().replace("_", " ")


def evaluate_stock_stance(
    forecast_return: float,
    volatility: float,
    sentiment_score: Optional[float] = None,
    prediction_interval_width: Optional[float] = None,
    user_risk_profile: str = "moderate"
) -> Dict[str, Any]:
    """
    Deterministically evaluates an asset stance against user risk parameters.

    Args:
        forecast_return: Projected 10-day return % (e.g., 3.2 for +3.2%).
        volatility: Annualized 1-year volatility from asset_profiles.json.
        sentiment_score: Scaled news sentiment (-1.0 to 1.0), or None if missing.
        prediction_interval_width: Width of forecast uncertainty band (upper - lower %).
        user_risk_profile: Risk tier from user profile ('conservative', 'growth', etc.).

    Returns:
        Dict containing:
            - stance: 'EXPLORE', 'MONITOR', or 'CAUTION'
            - decision_trace: Ordered audit trail of strings detailing the rationale.
    """
    decision_trace: List[str] = []

    # 1. Resolve user risk ceiling (defaults to moderate if unrecognized)
    profile_key = normalize_risk_profile(user_risk_profile)
    max_allowed_volatility = VOLATILITY_LIMITS.get(profile_key, 0.35)
    display_profile = profile_key.title()

    # 2. Handle missing data fallback (Resilience Rule)
    if sentiment_score is None:
        effective_sentiment = 0.0
        decision_trace.append(
            "News coverage gap: No recent headlines detected; sentiment defaulted to neutral (0.00)."
        )
    else:
        effective_sentiment = sentiment_score

    # 3. Safety First: Caution Checks
    caution_triggered = False

    if forecast_return < 0.0:
        decision_trace.append(
            f"Downside risk: 10-day projected return is negative ({forecast_return:+.1f}%)."
        )
        caution_triggered = True

    if volatility > max_allowed_volatility:
        decision_trace.append(
            f"Risk mismatch: 1-year historical volatility ({volatility:.2f}) exceeds your {display_profile} limit ({max_allowed_volatility:.2f})."
        )
        caution_triggered = True

    if effective_sentiment <= -0.15:
        decision_trace.append(
            f"Adverse market environment: News sentiment is bearish ({effective_sentiment:+.2f})."
        )
        caution_triggered = True

    if caution_triggered:
        return {
            "stance": "CAUTION",
            "decision_trace": decision_trace
        }

    # 4. Uncertainty Check (Ambiguity Gate)
    high_uncertainty = False
    if prediction_interval_width is not None and prediction_interval_width > MAX_ALLOWED_INTERVAL_WIDTH:
        decision_trace.append(
            f"Forecast ambiguity: Uncertainty interval width ({prediction_interval_width:.1f}%) exceeds safety threshold ({MAX_ALLOWED_INTERVAL_WIDTH:.1f}%)."
        )
        high_uncertainty = True

    # 5. Explore Checks (High Confluence)
    is_forecast_strong = forecast_return >= 2.0
    is_sentiment_bullish = effective_sentiment >= 0.15
    is_volatility_safe = volatility <= max_allowed_volatility

    if is_forecast_strong and is_sentiment_bullish and is_volatility_safe and not high_uncertainty:
        decision_trace.append(f"Favorable trend: 10-day projected return is strong ({forecast_return:+.1f}%).")
        decision_trace.append(f"Supportive catalyst: News sentiment is bullish ({effective_sentiment:+.2f}).")
        decision_trace.append(f"Risk aligned: Asset volatility ({volatility:.2f}) fits within your {display_profile} boundary.")
        if prediction_interval_width is not None:
            decision_trace.append(f"Model confidence: Prediction interval is narrow ({prediction_interval_width:.1f}%).")
        return {
            "stance": "EXPLORE",
            "decision_trace": decision_trace
        }

    # 6. Monitor Checks (Default / Mixed Signals)
    if 0.0 <= forecast_return < 2.0:
        decision_trace.append(
            f"Moderate growth: Projected return is mildly positive ({forecast_return:+.1f}%), below high-conviction threshold (+2.0%)."
        )
    elif is_forecast_strong and high_uncertainty:
        decision_trace.append(
            f"Directionally positive ({forecast_return:+.1f}%), but conviction capped due to high forecast uncertainty."
        )
    else:
        decision_trace.append(f"Return outlook is positive ({forecast_return:+.1f}%).")

    if -0.15 < effective_sentiment < 0.15 and sentiment_score is not None:
        decision_trace.append(f"Balanced news backdrop: Market sentiment is neutral ({effective_sentiment:+.2f}).")

    decision_trace.append(f"Risk acceptable: Volatility ({volatility:.2f}) is within {display_profile} limits.")

    return {
        "stance": "MONITOR",
        "decision_trace": decision_trace
    }
