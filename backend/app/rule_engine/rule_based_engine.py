"""
Rule-Based Reasoning Engine (v1.1.0)

Deterministic, auditable decision layer: EXPLORE / MONITOR / CAUTION.
Research signal only; not financial advice.
"""
import math
from typing import Any, Dict, List, Optional

RULES_VERSION = "1.1.0"

DISCLAIMER = (
    "Research signal only, not financial advice. Based on model forecasts "
    "and simplified risk rules; past performance does not predict future results."
)

# --- Thresholds (all tunable in one place) -------------------------------
VOLATILITY_LIMITS: Dict[str, float] = {  # annualised volatility, decimal
    "very conservative": 0.15,
    "conservative": 0.20,
    "moderate": 0.35,
    "growth": 0.45,
    "aggressive": 0.55,
}
DEFAULT_PROFILE = "moderate"

NEGATIVE_RETURN_THRESHOLD = 0.0       # % ; below this -> CAUTION
STRONG_RETURN_THRESHOLD = 2.0         # % ; at/above this can be EXPLORE
SENTIMENT_BEARISH = -0.15             # at/below -> CAUTION
SENTIMENT_BULLISH = 0.15              # at/above can be EXPLORE
MAX_ALLOWED_INTERVAL_WIDTH = 6.0      # % ; wider -> high uncertainty
MAX_SECTOR_WEIGHT = 0.30              # fraction of portfolio in same sector


def normalize_risk_profile(raw_profile: str) -> str:
    """Normalises 'very_conservative' / 'Growth' to a canonical key."""
    return raw_profile.strip().lower().replace("_", " ")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate(forecast_return, volatility, sentiment_score,
              prediction_interval_width, forecast_lower_bound, sector_weight) -> None:
    if not _is_number(forecast_return):
        raise ValueError("forecast_return must be a finite number")
    if not _is_number(volatility) or volatility < 0:
        raise ValueError("volatility must be a finite number >= 0")
    if sentiment_score is not None and (
        not _is_number(sentiment_score) or not -1.0 <= sentiment_score <= 1.0
    ):
        raise ValueError("sentiment_score must be None or within [-1, 1]")
    if prediction_interval_width is not None and (
        not _is_number(prediction_interval_width) or prediction_interval_width < 0
    ):
        raise ValueError("prediction_interval_width must be None or >= 0")
    if forecast_lower_bound is not None and not _is_number(forecast_lower_bound):
        raise ValueError("forecast_lower_bound must be None or a finite number")
    if sector_weight is not None and (
        not _is_number(sector_weight) or not 0.0 <= sector_weight <= 1.0
    ):
        raise ValueError("sector_weight must be None or within [0, 1]")


def evaluate_stock_stance(
    forecast_return: float,
    volatility: float,
    sentiment_score: Optional[float] = None,
    prediction_interval_width: Optional[float] = None,
    user_risk_profile: str = DEFAULT_PROFILE,
    forecast_lower_bound: Optional[float] = None,
    sector_weight: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Args:
        forecast_return: Projected 10-day return % (3.2 means +3.2%).
        volatility: Annualised 1-year volatility, decimal (0.35 = 35%).
        sentiment_score: News sentiment in [-1, 1], or None if no coverage.
        prediction_interval_width: Upper minus lower bound of forecast, in %.
        user_risk_profile: very conservative / conservative / moderate /
            growth / aggressive.
        forecast_lower_bound: Lower end of the prediction interval, in %.
        sector_weight: Fraction of the user's portfolio already in this
            asset's sector (0-1), if holdings are known.

    Returns:
        stance, decision_trace (display strings), reason_codes (machine
        readable), inputs, thresholds, rules_version, disclaimer.
    """
    _validate(forecast_return, volatility, sentiment_score,
              prediction_interval_width, forecast_lower_bound, sector_weight)

    trace: List[str] = []
    codes: List[str] = []

    def note(code: str, message: str) -> None:
        codes.append(code)
        trace.append(message)

    # 1. Resolve risk ceiling; flag unknown profiles instead of hiding it
    profile_key = normalize_risk_profile(user_risk_profile)
    if profile_key in VOLATILITY_LIMITS:
        max_vol = VOLATILITY_LIMITS[profile_key]
        display_profile = profile_key.title()
    else:
        max_vol = VOLATILITY_LIMITS[DEFAULT_PROFILE]
        display_profile = f"{DEFAULT_PROFILE.title()} (default)"
        note("UNKNOWN_PROFILE",
             f"Risk profile '{user_risk_profile}' not recognised; "
             f"using {DEFAULT_PROFILE.title()} limits.")

    # 2. Missing-sentiment fallback (neutral, so it can never reach EXPLORE)
    if sentiment_score is None:
        sentiment = 0.0
        note("SENTIMENT_MISSING",
             "News coverage gap: sentiment defaulted to neutral (0.00).")
    else:
        sentiment = sentiment_score

    # 3. CAUTION checks (hard safety rules)
    caution = False
    if forecast_return < NEGATIVE_RETURN_THRESHOLD:
        note("NEGATIVE_FORECAST",
             f"Downside risk: 10-day projected return is negative ({forecast_return:+.1f}%).")
        caution = True
    if volatility > max_vol:
        note("VOLATILITY_EXCEEDS_LIMIT",
             f"Risk mismatch: volatility ({volatility:.2f}) exceeds your "
             f"{display_profile} limit ({max_vol:.2f}).")
        caution = True
    if sentiment <= SENTIMENT_BEARISH:
        note("BEARISH_SENTIMENT",
             f"Adverse market environment: news sentiment is bearish ({sentiment:+.2f}).")
        caution = True

    # 4. Uncertainty and concentration (always recorded, even for CAUTION)
    high_uncertainty = False
    if prediction_interval_width is None:
        note("INTERVAL_MISSING",
             "No forecast uncertainty available; conviction capped at MONITOR.")
        high_uncertainty = True
    elif prediction_interval_width > MAX_ALLOWED_INTERVAL_WIDTH:
        note("INTERVAL_TOO_WIDE",
             f"Forecast ambiguity: interval width ({prediction_interval_width:.1f}%) "
             f"exceeds threshold ({MAX_ALLOWED_INTERVAL_WIDTH:.1f}%).")
        high_uncertainty = True
    if forecast_lower_bound is not None and forecast_lower_bound < 0 and forecast_return >= 0:
        note("INTERVAL_INCLUDES_LOSS",
             f"Forecast range includes a loss (lower bound {forecast_lower_bound:+.1f}%).")
        high_uncertainty = True

    concentrated = sector_weight is not None and sector_weight > MAX_SECTOR_WEIGHT
    if concentrated:
        note("SECTOR_CONCENTRATION",
             f"Portfolio concentration: {sector_weight:.0%} already in this sector "
             f"(limit {MAX_SECTOR_WEIGHT:.0%}).")

    def result(stance: str) -> Dict[str, Any]:
        return {
            "stance": stance,
            "decision_trace": trace,
            "reason_codes": codes,
            "inputs": {
                "forecast_return": forecast_return,
                "volatility": volatility,
                "sentiment_score": sentiment_score,
                "prediction_interval_width": prediction_interval_width,
                "forecast_lower_bound": forecast_lower_bound,
                "sector_weight": sector_weight,
                "user_risk_profile": profile_key,
            },
            "thresholds": {
                "max_volatility": max_vol,
                "strong_return": STRONG_RETURN_THRESHOLD,
                "sentiment_bullish": SENTIMENT_BULLISH,
                "sentiment_bearish": SENTIMENT_BEARISH,
                "max_interval_width": MAX_ALLOWED_INTERVAL_WIDTH,
                "max_sector_weight": MAX_SECTOR_WEIGHT,
            },
            "rules_version": RULES_VERSION,
            "disclaimer": DISCLAIMER,
        }

    if caution:
        return result("CAUTION")

    # 5. EXPLORE: every condition must align (volatility already passed above)
    strong_return = forecast_return >= STRONG_RETURN_THRESHOLD
    bullish = sentiment >= SENTIMENT_BULLISH and sentiment_score is not None

    if strong_return and bullish and not high_uncertainty and not concentrated:
        note("EXPLORE_CONFLUENCE",
             f"Favorable trend: projected return is strong ({forecast_return:+.1f}%).")
        trace.append(f"Supportive catalyst: news sentiment is bullish ({sentiment:+.2f}).")
        trace.append(f"Risk aligned: volatility ({volatility:.2f}) fits your {display_profile} boundary.")
        trace.append(f"Model confidence: prediction interval is narrow ({prediction_interval_width:.1f}%).")
        return result("EXPLORE")

    # 6. MONITOR (default / mixed signals)
    if not strong_return:
        note("RETURN_BELOW_THRESHOLD",
             f"Moderate growth: projected return ({forecast_return:+.1f}%) is below "
             f"the high-conviction threshold (+{STRONG_RETURN_THRESHOLD:.1f}%).")
    else:
        trace.append(f"Return outlook is positive ({forecast_return:+.1f}%).")
    if sentiment_score is not None and not bullish:
        note("SENTIMENT_NEUTRAL",
             f"Balanced news backdrop: sentiment is neutral ({sentiment:+.2f}).")
    trace.append(f"Risk acceptable: volatility ({volatility:.2f}) is within {display_profile} limits.")
    return result("MONITOR")
