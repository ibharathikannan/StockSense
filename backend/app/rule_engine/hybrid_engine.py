"""News-aware layer over the deterministic rule engine.

This keeps the team's `rule_based_engine.evaluate_stock_stance` as the single base decision
engine and adds the baseline-vs-news-aware view the RAG explanation needs. It runs the base
engine twice — once WITHOUT news (the forecast / volatility / risk baseline) and once WITH a
clean, relevance-weighted provider sentiment score (Marketaux; see data/rag/news_sentiment.py)
— and flags when recent news changed the stance (experimental, pending validation).

Nothing in `rule_based_engine.py` changes: sentiment flows in through its existing
`sentiment_score` argument and concentration through `sector_weight`. Because the base engine
only reaches EXPLORE with bullish sentiment, the baseline is conservative (never EXPLORE) and
news can upgrade it to EXPLORE or downgrade it to CAUTION — which is exactly the "the forecast
said X; incorporating recent news it becomes Y" story the explainer tells.
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


def evaluate_signal(
    forecast_return: float,
    volatility: float,
    risk_profile: str = "moderate",
    prediction_interval_width: Optional[float] = None,
    news_signal: Optional[dict[str, Any]] = None,
    sector_weight: Optional[float] = None,
    forecast_lower_bound: Optional[float] = None,
) -> dict[str, Any]:
    """Hybrid signal: the base engine's stance without news and with news.

    Returns {baseline_stance, news_aware_stance, provisional, decision_trace, reason_codes,
    news_signal, risk_profile}. `provisional` is True exactly when eligible recent news changed
    the stance relative to the forecast-only baseline (treat as experimental).
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
    provisional = aware["stance"] != base["stance"]
    trace = list(aware["decision_trace"])
    if provisional:
        trace.append(
            f"News-driven change (experimental): incorporating recent {news_signal.get('source')} "
            f"sentiment ({score:+.2f} over {int(news_signal.get('article_count', 0) or 0)} articles) "
            f"changed the forecast-only stance from {base['stance']} to {aware['stance']}, pending "
            f"validation against historical performance."
        )
    return {
        "baseline_stance": base["stance"], "news_aware_stance": aware["stance"],
        "provisional": provisional, "decision_trace": trace,
        "reason_codes": list(aware.get("reason_codes", [])),
        "news_signal": _echo(news_signal, score), "risk_profile": profile_key,
    }
