"""News-aware layer over the deterministic rule engine.

Keeps the team's `rule_based_engine.evaluate_stock_stance` as the single base decision engine.
It runs the base engine twice — once WITHOUT news (the forecast / volatility / risk baseline)
and once WITH a clean, relevance-weighted provider sentiment score (Marketaux; see
data/rag/news_sentiment.py) — and then applies a safety rule:

    unvalidated news may only make the stance MORE cautious, never more optimistic.

The operative stance is the more cautious of the two runs. Negative news can lower a stance
toward CAUTION (flagged experimental). Positive news is shown as context but never raises the
stance, and never softens a CAUTION — because the sentiment signal is not yet validated
(docs/ai/SENTIMENT_ATTRIBUTION.md; P10 would earn the right to let news be optimistic).

Nothing in `rule_based_engine.py` changes: sentiment flows in through its existing
`sentiment_score` argument and concentration through `sector_weight`.
"""
from __future__ import annotations

from typing import Any, Optional

from .rule_based_engine import evaluate_stock_stance, normalize_risk_profile

# Providers whose per-ticker/per-entity sentiment is trusted to move the stance. Both
# attribute sentiment themselves; our own FinBERT (Alpaca) stays evidence-only after the P1
# attribution diagnostic (docs/ai/SENTIMENT_ATTRIBUTION.md).
TRUSTED_NEWS_SOURCES = {"alpha_vantage", "marketaux"}
NEWS_MIN_ARTICLES = 2        # need at least this many recent articles to let news move the stance
NEWS_RECENCY_HOURS = 72      # only sentiment this fresh may change the stance


def _usable_news_score(news_signal: Optional[dict[str, Any]]) -> Optional[float]:
    """Return the sentiment score if the aggregated news signal clears the safeguards, else None.

    Expects the shape produced by `data.rag.news_sentiment.aggregate_ticker_sentiment`:
    {score, relevance, recency_hours, source, article_count, relevant}.
    """
    if not news_signal:
        return None
    try:
        score = float(news_signal.get("score"))
    except (TypeError, ValueError):
        return None
    if not -1.0 <= score <= 1.0:
        return None
    if news_signal.get("source") not in TRUSTED_NEWS_SOURCES or not news_signal.get("relevant", False):
        return None
    if int(news_signal.get("article_count", 0) or 0) < NEWS_MIN_ARTICLES:
        return None
    recency = news_signal.get("recency_hours")
    if recency is None or recency > NEWS_RECENCY_HOURS:
        return None
    return score


def _echo(news_signal: Optional[dict[str, Any]], score: Optional[float]) -> dict[str, Any]:
    ns = news_signal or {}
    return {
        "score": score,
        "relevance": ns.get("relevance"),
        "recency_hours": ns.get("recency_hours"),
        "source": ns.get("source") if score is not None else None,
        "article_count": int(ns.get("article_count", 0) or 0),
    }


# Stance ordering by caution (higher = more cautious). Used to apply "news may only add caution".
_CAUTION_RANK = {"EXPLORE": 0, "MONITOR": 1, "CAUTION": 2}


def evaluate_signal(
    forecast_return: float,
    volatility: float,
    risk_profile: str = "moderate",
    prediction_interval_width: Optional[float] = None,
    news_signal: Optional[dict[str, Any]] = None,
    sector_weight: Optional[float] = None,
    forecast_lower_bound: Optional[float] = None,
) -> dict[str, Any]:
    """Hybrid signal where unvalidated news may only add caution.

    Runs the base engine without news (baseline) and with news, then takes the MORE CAUTIOUS of
    the two as the operative stance. Returns {baseline_stance, news_aware_stance, provisional,
    decision_trace, reason_codes, news_signal, risk_profile}. `provisional` is True only when
    news is what lowered the stance (an experimental, news-driven caution).
    """
    base = evaluate_stock_stance(
        forecast_return, volatility, sentiment_score=None,
        prediction_interval_width=prediction_interval_width, user_risk_profile=risk_profile,
        forecast_lower_bound=forecast_lower_bound, sector_weight=sector_weight,
    )
    profile_key = normalize_risk_profile(risk_profile)
    score = _usable_news_score(news_signal)

    if score is None:
        trace = list(base["decision_trace"])
        trace.append("News-aware check abstained to the forecast-only stance: no eligible "
                     "provider news coverage.")
        return {
            "baseline_stance": base["stance"], "news_aware_stance": base["stance"],
            "provisional": False, "decision_trace": trace,
            "reason_codes": list(base.get("reason_codes", [])),
            "news_signal": _echo(news_signal, None), "risk_profile": profile_key,
        }

    aware = evaluate_stock_stance(
        forecast_return, volatility, sentiment_score=score,
        prediction_interval_width=prediction_interval_width, user_risk_profile=risk_profile,
        forecast_lower_bound=forecast_lower_bound, sector_weight=sector_weight,
    )
    source = news_signal.get("source")
    count = int(news_signal.get("article_count", 0) or 0)

    if _CAUTION_RANK[aware["stance"]] > _CAUTION_RANK[base["stance"]]:
        # News makes it more cautious — the safe direction, so apply it (flagged experimental).
        operative, provisional, trace = aware, True, list(aware["decision_trace"])
        trace.append(
            f"News-driven caution (experimental): recent {source} news is negative "
            f"({score:+.2f} over {count} articles), lowering the forecast-only stance from "
            f"{base['stance']} to {aware['stance']}, pending validation.")
    else:
        # News would raise or soften the stance — keep the conservative baseline; unvalidated
        # positive sentiment is never used to upgrade, and never softens a CAUTION.
        operative, provisional, trace = base, False, list(base["decision_trace"])
        if score >= 0.15:
            trace.append(
                f"Recent {source} news is positive ({score:+.2f} over {count} articles), but the "
                f"stance stays {base['stance']} — an unvalidated positive signal is not used to "
                f"raise it.")
        elif score <= -0.15:
            trace.append(
                f"Recent {source} news is also negative ({score:+.2f} over {count} articles), "
                f"consistent with this {base['stance']} stance.")

    return {
        "baseline_stance": base["stance"], "news_aware_stance": operative["stance"],
        "provisional": provisional, "decision_trace": trace,
        "reason_codes": list(operative.get("reason_codes", [])),
        "news_signal": _echo(news_signal, score), "risk_profile": profile_key,
    }
