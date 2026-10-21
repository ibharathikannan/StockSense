"""Point-in-time SEC fundamentals signal; pure, no network."""
from data.rag.fundamentals_signal import build_fundamentals_signals, fundamentals_signal


def fact(concept, val, end, filed, start=None, ticker="AAA"):
    return {"ticker": ticker, "concept": concept, "val": val, "start": start, "end": end,
            "filed": filed, "form": "10-K"}


def annual(concept, val, year, filed=None):
    return fact(concept, val, f"{year}-12-31", filed or f"{year + 1}-02-15", start=f"{year}-01-01")


def instant(concept, val, year, filed=None):
    return fact(concept, val, f"{year}-12-31", filed or f"{year + 1}-02-15")


def company(revenue=(100, 120), operating=30, cash=40, capex=10, assets=200, liabilities=100,
            debt=40, equity=200):
    return [annual("Revenues", revenue[0], 2024), annual("Revenues", revenue[1], 2025),
            annual("OperatingIncomeLoss", operating, 2025),
            annual("NetCashProvidedByUsedInOperatingActivities", cash, 2025),
            annual("PaymentsToAcquirePropertyPlantAndEquipment", capex, 2025),
            instant("AssetsCurrent", assets, 2025), instant("LiabilitiesCurrent", liabilities, 2025),
            instant("LongTermDebt", debt, 2025), instant("StockholdersEquity", equity, 2025)]


def test_strong_company_scores_every_metric():
    signal = fundamentals_signal(company(), "2026-03-01")
    assert signal["rating"] == "strong" and signal["score"] == 1.0
    assert signal["metric_count"] == 5 and signal["source"] == "sec_xbrl"
    assert signal["metrics"]["revenue_growth"]["value"] == 0.2
    assert signal["metrics"]["operating_margin"]["value"] == 0.25
    assert signal["metrics"]["free_cash_flow_margin"]["value"] == 0.25
    assert signal["metrics"]["current_ratio"]["value"] == 2.0
    assert signal["metrics"]["debt_to_equity"]["value"] == 0.2
    assert signal["period_end"] == "2025-12-31" and signal["age_days"] == 14


def test_weak_company():
    signal = fundamentals_signal(company(revenue=(120, 100), operating=-5, cash=5, capex=20,
                                         assets=80, liabilities=100, debt=500, equity=100), "2026-03-01")
    assert signal["rating"] == "weak" and signal["score"] == -1.0


def test_facts_filed_after_as_of_are_invisible():
    # The FY2025 10-K is filed 2026-02-15; before that the latest year is FY2024.
    records = company() + [annual("Revenues", 90, 2023), annual("OperatingIncomeLoss", 20, 2024),
                           annual("NetCashProvidedByUsedInOperatingActivities", 20, 2024),
                           annual("PaymentsToAcquirePropertyPlantAndEquipment", 5, 2024)]
    signal = fundamentals_signal(records, "2026-02-01")
    assert signal["period_end"] == "2024-12-31"
    assert signal["metrics"]["operating_margin"]["value"] == 0.2


def test_later_restatement_does_not_leak_backwards():
    records = company() + [annual("Revenues", 60, 2025, filed="2026-08-01")]
    assert fundamentals_signal(records, "2026-03-01")["metrics"]["revenue_growth"]["value"] == 0.2
    assert fundamentals_signal(records, "2026-09-01")["metrics"]["revenue_growth"]["value"] == -0.4


def test_negative_equity_skips_debt_ratio_instead_of_scoring_it():
    signal = fundamentals_signal(company(equity=-50), "2026-03-01")
    assert "debt_to_equity" not in signal["metrics"] and signal["metric_count"] == 4


def test_abstains_when_missing_thin_or_stale():
    assert fundamentals_signal([], "2026-03-01") is None
    thin = [annual("Revenues", 100, 2024), annual("Revenues", 120, 2025)]
    assert fundamentals_signal(thin, "2026-03-01") is None
    assert fundamentals_signal(company(), "2027-06-01") is None


def test_build_signals_covers_requested_tickers_only():
    signals = build_fundamentals_signals(company(), ["AAA", "SPY"], "2026-03-01")
    assert set(signals) == {"AAA", "SPY"}
    assert signals["AAA"]["rating"] == "strong" and signals["SPY"] is None


def test_alternative_tags_for_capex_and_split_debt():
    records = [r for r in company() if r["concept"] not in {
        "PaymentsToAcquirePropertyPlantAndEquipment", "LongTermDebt", "Revenues"}]
    records += [annual("RevenueFromContractWithCustomerIncludingAssessedTax", 100, 2024),
                annual("RevenueFromContractWithCustomerIncludingAssessedTax", 120, 2025),
                annual("PaymentsToAcquireProductiveAssets", 10, 2025),
                instant("LongTermDebtAndCapitalLeaseObligations", 30, 2025), instant("DebtCurrent", 10, 2025)]
    signal = fundamentals_signal(records, "2026-03-01")
    assert signal["metrics"]["revenue_growth"]["value"] == 0.2
    assert signal["metrics"]["free_cash_flow_margin"]["value"] == 0.25
    assert signal["metrics"]["debt_to_equity"]["value"] == 0.2


def test_strong_requires_score_of_at_least_0_6():
    # Two strong metrics and three neutral ones (score 0.4) are only neutral.
    two_strong = company(revenue=(100, 105), operating=30, cash=40, capex=10, assets=120, liabilities=100,
                         debt=150, equity=200)
    signal = fundamentals_signal(two_strong, "2026-03-01")
    assert signal["score"] == 0.4 and signal["rating"] == "neutral"
    three_strong = company(revenue=(100, 105), operating=30, cash=40, capex=10, assets=120, liabilities=100,
                           debt=40, equity=200)
    signal = fundamentals_signal(three_strong, "2026-03-01")
    assert signal["score"] == 0.6 and signal["rating"] == "strong"
