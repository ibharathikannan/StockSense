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

SEC fundamentals (data/rag/fundamentals_signal.py) are applied last, in both directions, one
step at most: weak fundamentals move the stance one step more cautious; strong fundamentals may
raise MONITOR to EXPLORE. They never lift a CAUTION (a negative forecast, a risk-profile
volatility breach or news-driven caution), never upgrade without a forecast interval or under
sector concentration, and any stance they change is flagged provisional because the thresholds
are unvalidated.

Nothing in `rule_based_engine.py` changes: sentiment flows in through its existing
`sentiment_score` argument and concentration through `sector_weight`.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from .rule_based_engine import evaluate_stock_stance, normalize_risk_profile

# Providers whose per-ticker/per-entity sentiment is trusted to move the stance. Both
# attribute sentiment themselves; our own FinBERT (Alpaca) stays evidence-only after the P1
# attribution diagnostic (docs/ai/SENTIMENT_ATTRIBUTION.md).
TRUSTED_NEWS_SOURCES = {"alpha_vantage", "marketaux"}
NEWS_MIN_ARTICLES = 2        # need at least this many recent articles to let news move the stance
NEWS_RECENCY_HOURS = 168     # 7 days, matching the assembler window; MVP leniency
FUNDAMENTALS_SOURCE = "sec_xbrl"
FUNDAMENTALS_MIN_METRICS = 3
FUNDAMENTALS_MAX_FILING_AGE_DAYS = 456   # older annual data may not move the stance


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
_BY_RANK = {rank: stance for stance, rank in _CAUTION_RANK.items()}


def _usable_fundamentals(signal: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the fundamentals signal if it clears the safeguards, else None."""
    if not signal or signal.get("source") != FUNDAMENTALS_SOURCE:
        return None
    score = signal.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) \
            or not -1.0 <= score <= 1.0:
        return None
    if signal.get("rating") not in {"strong", "neutral", "weak"}:
        return None
    if int(signal.get("metric_count", 0) or 0) < FUNDAMENTALS_MIN_METRICS:
        return None
    age = signal.get("age_days")
    if not isinstance(age, (int, float)) or not 0 <= age <= FUNDAMENTALS_MAX_FILING_AGE_DAYS:
        return None
    return signal


def _fundamentals_echo(signal: Optional[dict[str, Any]]) -> dict[str, Any]:
    keys = ("score", "rating", "metrics", "metric_count", "period_end", "filed", "age_days", "source")
    if signal is None:
        return {k: ({} if k == "metrics" else 0 if k == "metric_count" else None) for k in keys}
    return {k: signal.get(k) for k in keys}


def _metric_summary(signal: dict[str, Any], assessment: str) -> str:
    names = [name.replace("_", " ") for name, m in (signal.get("metrics") or {}).items()
             if m.get("assessment") == assessment]
    return ", ".join(names) if names else "no single metric"


def evaluate_signal(
    forecast_return: float,
    volatility: float,
    risk_profile: str = "moderate",
    prediction_interval_width: Optional[float] = None,
    news_signal: Optional[dict[str, Any]] = None,
    sector_weight: Optional[float] = None,
    forecast_lower_bound: Optional[float] = None,
    fundamentals_signal: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Hybrid signal: news may only add caution; SEC fundamentals may move one step either way.

    Runs the base engine without news (baseline) and with news, then takes the MORE CAUTIOUS of
    the two, then applies the fundamentals step. Returns {baseline_stance, news_aware_stance,
    provisional, decision_trace, reason_codes, news_signal, fundamentals_signal, risk_profile}.
    `news_aware_stance` is the final operative stance. `provisional` is True when news or
    fundamentals changed the stance (an experimental, unvalidated adjustment).
    """
    base = evaluate_stock_stance(
        forecast_return, volatility, sentiment_score=None,
        prediction_interval_width=prediction_interval_width, user_risk_profile=risk_profile,
        forecast_lower_bound=forecast_lower_bound, sector_weight=sector_weight,
    )
    profile_key = normalize_risk_profile(risk_profile)
    score = _usable_news_score(news_signal)

    if score is None:
        stance, provisional = base["stance"], False
        trace = list(base["decision_trace"])
        codes = list(base.get("reason_codes", []))
    else:
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
        stance, codes = operative["stance"], list(operative.get("reason_codes", []))

    fundamentals = _usable_fundamentals(fundamentals_signal)
    if fundamentals is None:
        trace.append("Fundamentals check abstained: no recent SEC filing data with enough "
                     "reported metrics for this asset.")
    else:
        period = fundamentals.get("period_end")
        rating = fundamentals["rating"]
        if rating == "weak":
            lowered = _BY_RANK[min(_CAUTION_RANK[stance] + 1, _CAUTION_RANK["CAUTION"])]
            if lowered != stance:
                codes.append("FUNDAMENTALS_WEAK")
                trace.append(
                    f"Fundamentals-driven caution (experimental): SEC filings for fiscal year "
                    f"ending {period} show weak {_metric_summary(fundamentals, 'weak')}, lowering "
                    f"the stance from {stance} to {lowered}, pending validation.")
                stance, provisional = lowered, True
            else:
                trace.append(f"SEC fundamentals (fiscal year ending {period}) are also weak, "
                             f"consistent with this CAUTION stance.")
        elif rating == "strong":
            # Bearish news already yields CAUTION above, so it cannot reach this upgrade. Without
            # a forecast interval the base engine caps conviction at MONITOR; keep that cap.
            blocked = [c for c in ("SECTOR_CONCENTRATION", "INTERVAL_MISSING") if c in codes]
            if stance == "MONITOR" and not blocked:
                codes.append("FUNDAMENTALS_STRONG")
                trace.append(
                    f"Fundamentals-driven upgrade (experimental): SEC filings for fiscal year "
                    f"ending {period} show strong {_metric_summary(fundamentals, 'strong')}, "
                    f"raising the stance from MONITOR to EXPLORE, pending validation. Forecast "
                    f"caveats above still apply.")
                stance, provisional = "EXPLORE", True
            elif stance == "CAUTION":
                trace.append(f"SEC fundamentals (fiscal year ending {period}) are strong, but they "
                             f"never lift a CAUTION from forecast, risk or news rules.")
            elif stance == "MONITOR":
                reason = ("sector concentration" if "SECTOR_CONCENTRATION" in blocked
                          else "the missing forecast")
                trace.append(f"SEC fundamentals (fiscal year ending {period}) are strong, but "
                             f"{reason} blocks an upgrade.")
            else:
                trace.append(f"SEC fundamentals (fiscal year ending {period}) are also strong.")
        else:
            trace.append(f"SEC fundamentals (fiscal year ending {period}) are mixed; they do not "
                         f"move the stance.")

    return {
        "baseline_stance": base["stance"], "news_aware_stance": stance,
        "provisional": provisional, "decision_trace": trace, "reason_codes": codes,
        "news_signal": _echo(news_signal, score),
        "fundamentals_signal": _fundamentals_echo(fundamentals), "risk_profile": profile_key,
    }
