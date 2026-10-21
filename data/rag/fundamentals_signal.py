"""Point-in-time SEC fundamentals signal for the hybrid engine.

Turns the XBRL facts written by data/collect_sec_fundamentals.py into the
``fundamentals_signal`` shape that ``hybrid_engine.evaluate_signal`` expects:

    {score, rating, metrics, metric_count, period_end, filed, age_days, source}

Only facts filed on or before ``as_of`` are visible, and for each period the
latest such filing wins, so later restatements never leak backwards. Each
metric is assessed strong (+1), weak (-1) or neutral (0) against fixed
thresholds; the score is their mean. The thresholds are deliberately simple,
sector-agnostic and unvalidated; the engine labels any stance they move as
experimental. Missing, stale or too-thin data abstains (returns None), which
is not the same as neutral fundamentals.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable, Optional

SOURCE = "sec_xbrl"
MIN_METRICS = 3              # abstain unless at least this many metrics can be computed
MAX_PERIOD_AGE_DAYS = 456    # ~15 months: a fiscal year plus the 10-K filing window
STRONG_SCORE = 0.6     # roughly 3 of 5 metrics strong with none weak; chosen 2026-10-21
WEAK_SCORE = -0.4

REVENUE_CONCEPTS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "RegulatedAndUnregulatedOperatingRevenue", "SalesRevenueNet",
                    "RevenuesNetOfInterestExpense")
# Issuers tag the same line differently; each tuple is in order of preference.
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
TOTAL_DEBT_CONCEPTS = ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities")
NONCURRENT_DEBT_CONCEPTS = ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations")
CURRENT_DEBT_CONCEPTS = ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent")

# (strong_at_or_above, weak_below) for higher-is-better metrics.
THRESHOLDS = {
    "revenue_growth": (0.10, 0.0),
    "operating_margin": (0.15, 0.0),
    "free_cash_flow_margin": (0.10, 0.0),
    "current_ratio": (1.5, 1.0),
}
# Lower-is-better: strong at or below 0.5, weak above 2.0.
DEBT_TO_EQUITY = (0.5, 2.0)


def _day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _latest_known(records: list[dict], as_of: date) -> dict[tuple, dict]:
    """(concept, start, end) -> the most recently filed record visible at as_of."""
    known: dict[tuple, dict] = {}
    for r in records:
        if _day(r["filed"]) > as_of:
            continue
        key = (r["concept"], r.get("start"), r["end"])
        if key not in known or _day(r["filed"]) >= _day(known[key]["filed"]):
            known[key] = r
    return known


def _annual(known: dict[tuple, dict]) -> dict[str, dict[date, dict]]:
    """concept -> {fiscal-year end: record} for roughly one-year durations."""
    series: dict[str, dict[date, dict]] = defaultdict(dict)
    for (concept, start, end), r in known.items():
        if start and 350 <= (_day(end) - _day(start)).days <= 380:
            series[concept][_day(end)] = r
    return series


def _instants(known: dict[tuple, dict]) -> dict[str, dict[date, dict]]:
    series: dict[str, dict[date, dict]] = defaultdict(dict)
    for (concept, start, end), r in known.items():
        if not start:
            series[concept][_day(end)] = r
    return series


def _first_at(series: dict[str, dict[date, dict]], concepts: tuple[str, ...], when: date) -> Optional[float]:
    """Value of the first concept in preference order reported for this date."""
    for concept in concepts:
        if when in series.get(concept, {}):
            return float(series[concept][when]["val"])
    return None


def _assess(name: str, value: float) -> str:
    if name == "debt_to_equity":
        strong, weak = DEBT_TO_EQUITY
        return "strong" if value <= strong else "weak" if value > weak else "neutral"
    strong, weak = THRESHOLDS[name]
    return "strong" if value >= strong else "weak" if value < weak else "neutral"


def fundamentals_signal(records: Iterable[dict], as_of: datetime | date | str) -> Optional[dict]:
    """Signal for one ticker's facts, or None to abstain."""
    as_of = _day(as_of)
    known = _latest_known(list(records), as_of)
    annual, instants = _annual(known), _instants(known)

    # Issuers switch revenue concepts over time; use the one with the latest year.
    revenue_concept = max((c for c in REVENUE_CONCEPTS if annual.get(c)),
                          key=lambda c: (max(annual[c]), -REVENUE_CONCEPTS.index(c)), default=None)
    if revenue_concept is None:
        return None
    revenue = annual[revenue_concept]
    end = max(revenue)
    if (as_of - end).days > MAX_PERIOD_AGE_DAYS:
        return None
    current = float(revenue[end]["val"])

    values: dict[str, float] = {}
    previous = [d for d in revenue if 330 <= (end - d).days <= 400]
    if previous and float(revenue[max(previous)]["val"]) > 0:
        values["revenue_growth"] = current / float(revenue[max(previous)]["val"]) - 1
    if current > 0:
        if end in annual.get("OperatingIncomeLoss", {}):
            values["operating_margin"] = float(annual["OperatingIncomeLoss"][end]["val"]) / current
        cash = annual.get("NetCashProvidedByUsedInOperatingActivities", {})
        capex = _first_at(annual, CAPEX_CONCEPTS, end)
        if end in cash and capex is not None:
            values["free_cash_flow_margin"] = (float(cash[end]["val"]) - capex) / current

    # Balance-sheet ratios use the latest date where both sides were reported.
    def latest_pair(numerator: str, denominator: str) -> Optional[date]:
        common = set(instants.get(numerator, {})) & set(instants.get(denominator, {}))
        return max(common) if common else None

    when = latest_pair("AssetsCurrent", "LiabilitiesCurrent")
    if when and float(instants["LiabilitiesCurrent"][when]["val"]) > 0:
        values["current_ratio"] = (float(instants["AssetsCurrent"][when]["val"])
                                   / float(instants["LiabilitiesCurrent"][when]["val"]))
    equity = instants.get("StockholdersEquity", {})
    debt_dates = {d for c in TOTAL_DEBT_CONCEPTS + NONCURRENT_DEBT_CONCEPTS for d in instants.get(c, {})}
    common = debt_dates & set(equity)
    if common:
        when = max(common)
        debt = _first_at(instants, TOTAL_DEBT_CONCEPTS, when)
        if debt is None:
            debt = (_first_at(instants, NONCURRENT_DEBT_CONCEPTS, when)
                    + (_first_at(instants, CURRENT_DEBT_CONCEPTS, when) or 0.0))
        # Negative equity (common after large buybacks) makes the ratio meaningless.
        if float(equity[when]["val"]) > 0:
            values["debt_to_equity"] = debt / float(equity[when]["val"])

    if len(values) < MIN_METRICS:
        return None
    metrics = {name: {"value": round(value, 4), "assessment": _assess(name, value)}
               for name, value in values.items()}
    points = {"strong": 1, "neutral": 0, "weak": -1}
    score = sum(points[m["assessment"]] for m in metrics.values()) / len(metrics)
    rating = "strong" if score >= STRONG_SCORE else "weak" if score <= WEAK_SCORE else "neutral"
    filed = _day(revenue[end]["filed"])
    return {"score": round(score, 4), "rating": rating, "metrics": metrics,
            "metric_count": len(metrics), "period_end": end.isoformat(),
            "filed": filed.isoformat(), "age_days": (as_of - filed).days, "source": SOURCE}


def build_fundamentals_signals(records: Iterable[dict], tickers: Iterable[str],
                               as_of: datetime | date | str) -> dict[str, Optional[dict]]:
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_ticker[str(r["ticker"]).upper()].append(r)
    return {t: fundamentals_signal(by_ticker.get(t.upper(), []), as_of) for t in tickers}
