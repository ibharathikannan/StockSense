"""SEC company-facts flattening and coverage, without network calls."""
import json

from data import collect_sec_fundamentals as module


FACTS = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 10, "form": "10-K", "fy": 2025,
         "fp": "FY", "filed": "2026-02-15", "accn": "0000000000-26-000001"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 10, "form": "8-K", "filed": "2026-01-20"},
        {"end": "2025-12-31", "val": 10, "form": "10-K"},
    ], "shares": [{"end": "2025-12-31", "val": 1, "form": "10-K", "filed": "2026-02-15"}]}},
    "Unrelated": {"units": {"USD": [{"end": "2025-12-31", "val": 1, "form": "10-K", "filed": "2026-02-15"}]}},
}}}


def test_keeps_only_periodic_usd_facts_for_known_concepts():
    rows = module.fact_records("AAA", 1, FACTS)
    assert rows == [{"ticker": "AAA", "cik": 1, "concept": "Revenues", "start": "2025-01-01",
                     "end": "2025-12-31", "val": 10, "form": "10-K", "fy": 2025, "fp": "FY",
                     "filed": "2026-02-15", "accn": "0000000000-26-000001"}]


def test_collect_records_failures_without_error_details(tmp_path):
    class Client:
        def json(self, url):
            if "company_tickers" in url:
                return {"0": {"ticker": "AAA", "cik_str": 1}, "1": {"ticker": "BBB", "cik_str": 2}}
            if url.endswith("CIK0000000002.json"):
                raise RuntimeError("secret request detail")
            return FACTS

    result = module.collect(tmp_path, ["AAA", "BBB", "ZZZ"], Client())
    assert result["tickers"]["AAA"] == {"status": "collected", "cik": 1, "facts": 1}
    assert result["tickers"]["BBB"] == {"status": "failed", "reason": "RuntimeError"}
    assert result["tickers"]["ZZZ"]["reason"] == "no_sec_ticker_mapping"
    assert "secret" not in (tmp_path / "coverage.json").read_text()
    assert [json.loads(l)["ticker"] for l in (tmp_path / "facts.jsonl").read_text().splitlines()] == ["AAA"]
