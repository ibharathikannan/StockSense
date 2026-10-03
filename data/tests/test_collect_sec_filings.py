"""Offline tests for bounded SEC collection and provenance."""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_sec_filings as sec


AS_OF = datetime(2026, 10, 2, tzinfo=timezone.utc)


def row(form, accession, filed, accepted=None):
    return {
        "form": form,
        "accessionNumber": accession,
        "filingDate": filed,
        "reportDate": "2025-12-31",
        "acceptanceDateTime": accepted or f"{filed}T16:15:00",
        "primaryDocument": "report.htm",
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def json(self, url):
        self.calls.append(url)
        return self.responses[url]

    def text(self, url):
        self.calls.append(url)
        return "<html><script>secret</script><h1>Annual report</h1><p>Business risk.</p></html>"


class SecCollectionTests(unittest.TestCase):
    def test_identity_required_before_request(self):
        for value in (None, "", "StockSense", "StockSense x@example.com\nFake: 1"):
            with self.assertRaises(ValueError):
                sec.validate_identity(value)
        self.assertEqual(sec.validate_identity("StockSense sec@example.org"), "StockSense sec@example.org")

    def test_select_bounded_forms_and_excludes_future_acceptance(self):
        rows = [
            row("10-K", "0000000001-26-000001", "2026-09-01"),
            row("10-K", "0000000001-25-000001", "2025-09-01"),
            row("10-K", "0000000001-24-000001", "2024-09-01"),
            *[row("10-Q", f"0000000001-26-{i:06d}", f"2026-0{i}-01") for i in range(1, 6)],
            row("8-K", "0000000001-26-000010", "2026-09-15"),
            row("8-K", "0000000001-26-000011", "2026-01-15"),
            row("8-K", "0000000001-26-000012", "2026-10-02", "2026-10-02T19:00:00"),
        ]
        chosen = sec.select_filings(rows, AS_OF)
        self.assertEqual(sum(r["form"] == "10-K" for r in chosen), 2)
        self.assertEqual(sum(r["form"] == "10-Q" for r in chosen), 4)
        self.assertEqual(sum(r["form"] == "8-K" for r in chosen), 1)

    def test_foreign_issuer_uses_20f_and_recent_6k(self):
        rows = [
            row("20-F", "0000000002-26-000001", "2026-04-01"),
            row("20-F", "0000000002-25-000001", "2025-04-01"),
            row("6-K", "0000000002-26-000002", "2026-09-01"),
        ]
        self.assertEqual([r["form"] for r in sec.select_filings(rows, AS_OF)], ["20-F", "20-F", "6-K"])

    def test_collect_persists_provenance_and_resumes_without_refetch(self):
        cik = 1
        filing = row("10-K", "0000000001-26-000001", "2026-09-01")
        recent = {key: [value] for key, value in filing.items()}
        responses = {
            sec.TICKER_FILE: {"0": {"ticker": "TEST", "cik_str": cik, "title": "Test Inc"}},
            sec.SUBMISSIONS.format(cik=cik): {"name": "Test Inc", "tickers": ["TEST"], "filings": {"recent": recent, "files": []}},
        }
        universe = [{"ticker": "TEST", "asset_type": "stock"}, {"ticker": "SPY", "asset_type": "etf"}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            client = FakeClient(responses)
            first = sec.collect(output, AS_OF, ["TEST", "SPY"], universe, client)
            self.assertEqual(first["tickers"]["TEST"]["status"], "collected")
            self.assertEqual(first["tickers"]["SPY"]["status"], "not-applicable")
            records = list(sec.read_jsonl(output / "documents.jsonl"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["accession"], filing["accessionNumber"])
            self.assertEqual(records[0]["published_at"], "2026-09-01T20:15:00Z")
            self.assertIn("Business risk.", records[0]["text"])
            self.assertNotIn("secret", records[0]["text"])
            self.assertEqual(json.loads((output / "coverage.json").read_text())["tickers"]["SPY"]["status"], "not-applicable")
            client.calls.clear()
            sec.collect(output, AS_OF, ["TEST", "SPY"], universe, client)
            self.assertEqual(sum("Archives" in call for call in client.calls), 0)
            original_fetch = records[0]["fetched_at"]
            records[0].pop("normalization_version")
            records[0]["text"] = "obsolete hidden metadata"
            sec.write_jsonl(output / "documents.jsonl", records)
            sec.collect(output, AS_OF, ["TEST"], universe, client)
            refreshed = sec.read_jsonl(output / "documents.jsonl")[0]
            self.assertEqual(refreshed["fetched_at"], original_fetch)
            self.assertEqual(refreshed["normalization_version"], sec.NORMALIZATION_VERSION)
            self.assertIn("Business risk.", refreshed["text"])
            self.assertNotIn("obsolete", refreshed["text"])


    def test_mapping_mismatch_never_fetches_document(self):
        responses = {
            sec.TICKER_FILE: {"0": {"ticker": "TEST", "cik_str": 1, "title": "Test Inc"}},
            sec.SUBMISSIONS.format(cik=1): {"name": "Other", "tickers": ["OTHER"], "filings": {"recent": {}, "files": []}},
        }
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(responses)
            result = sec.collect(Path(directory), AS_OF, ["TEST"], [{"ticker": "TEST", "asset_type": "stock"}], client)
            self.assertEqual(result["tickers"]["TEST"]["status"], "unavailable")
            self.assertFalse(any("Archives" in call for call in client.calls))

    def test_older_submission_shard_supplies_second_annual(self):
        recent = row("10-K", "0000000001-26-000001", "2026-09-01")
        old = row("10-K", "0000000001-25-000001", "2025-09-01")
        name = "CIK0000000001-submissions-001.json"
        client = FakeClient({
            sec.SUBMISSIONS.format(cik=1): {"filings": {"recent": {key: [value] for key, value in recent.items()}, "files": [{"name": name}]}},
            sec.SHARD.format(name=name): {key: [value] for key, value in old.items()},
        })
        _, rows = sec.all_submissions(client, 1, AS_OF)
        self.assertEqual({r["accessionNumber"] for r in rows}, {recent["accessionNumber"], old["accessionNumber"]})

    def test_failed_filing_preserves_partial_coverage(self):
        cik = 1
        filing = row("10-K", "0000000001-26-000001", "2026-09-01")
        responses = {
            sec.TICKER_FILE: {"0": {"ticker": "TEST", "cik_str": cik, "title": "Test Inc"}},
            sec.SUBMISSIONS.format(cik=cik): {"name": "Test Inc", "tickers": ["TEST"], "filings": {"recent": {key: [value] for key, value in filing.items()}, "files": []}},
        }
        class FailingClient(FakeClient):
            def text(self, url):
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as directory:
            result = sec.collect(Path(directory), AS_OF, ["TEST"], [{"ticker": "TEST", "asset_type": "stock"}], FailingClient(responses))
            self.assertEqual(result["tickers"]["TEST"]["status"], "failed")
            self.assertEqual(sec.read_jsonl(Path(directory) / "documents.jsonl"), [])

    def test_rate_limit_retry_and_cache(self):
        class Retryable(Exception):
            status = 429
            retry_after = 3

        clock = [0.0]
        pauses = []
        def pause(seconds):
            pauses.append(seconds)
            clock[0] += seconds
        def monotonic():
            return clock[0]
        attempts = [0]
        def fetch(url, headers=None):
            attempts[0] += 1
            if attempts[0] == 1:
                raise Retryable()
            return {"ok": True}

        with tempfile.TemporaryDirectory() as directory:
            client = sec.SecClient("StockSense sec@example.org", Path(directory), pause=pause, monotonic=monotonic)
            with patch.object(sec, "fetch_json", fetch):
                self.assertEqual(client.json("https://sec.example/x"), {"ok": True})
                self.assertEqual(client.json("https://sec.example/x"), {"ok": True})
            self.assertEqual(attempts[0], 2)
            self.assertTrue(any(seconds >= 3 for seconds in pauses))

    def test_submission_cache_refreshes_in_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sec, "fetch_json", side_effect=[{"version": 1}, {"version": 2}]) as fetch:
                first = sec.SecClient("StockSense sec@example.org", Path(directory))
                self.assertEqual(first.json("https://sec.example/inventory"), {"version": 1})
                self.assertEqual(first.json("https://sec.example/inventory"), {"version": 1})
                second = sec.SecClient("StockSense sec@example.org", Path(directory))
                self.assertEqual(second.json("https://sec.example/inventory"), {"version": 2})
                self.assertEqual(fetch.call_count, 2)

    def test_shared_issuer_preserves_both_ticker_associations(self):
        filing = row("10-K", "0000000001-26-000001", "2026-09-01")
        responses = {
            sec.TICKER_FILE: {str(i): {"ticker": ticker, "cik_str": 1} for i, ticker in enumerate(["AAA", "AAB"])},
            sec.SUBMISSIONS.format(cik=1): {"name": "Issuer", "tickers": ["AAA", "AAB"], "filings": {"recent": {key: [value] for key, value in filing.items()}, "files": []}},
        }
        universe = [{"ticker": ticker, "asset_type": "stock"} for ticker in ["AAA", "AAB"]]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sec.collect(output, AS_OF, ["AAA", "AAB"], universe, FakeClient(responses))
            records = sec.read_jsonl(output / "documents.jsonl")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tickers"], ["AAA", "AAB"])

    def test_mapping_failure_records_coverage(self):
        class FailedMapping(FakeClient):
            def json(self, url):
                raise RuntimeError("transport unavailable")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = sec.collect(output, AS_OF, ["AAA", "SPY"], [{"ticker": "AAA", "asset_type": "stock"}, {"ticker": "SPY", "asset_type": "etf"}], FailedMapping({}))
            self.assertEqual(result["tickers"]["AAA"]["status"], "failed")
            self.assertEqual(result["tickers"]["SPY"]["status"], "not-applicable")
            self.assertTrue((output / "coverage.json").exists())


if __name__ == "__main__":
    unittest.main()


def test_hidden_xbrl_removed_visible_facts_and_cells_preserved():
    html = '''<head><title>metadata</title></head><div style="display: none"><ix:header><div>hidden taxonomy</div></ix:header></div><input hidden><p>Revenue <ix:nonfraction>123</ix:nonfraction></p><table><tr><td>Year</td><td>2025</td></tr></table><div hidden><span>secret</span></div><p>Visible</p>'''
    text = sec.normalize_filing(html)
    assert text == 'Revenue 123\nYear 2025\nVisible'


def test_canadian_issuer_40f_annual_selection():
    rows = [row('40-F', '0000000002-26-000001', '2026-04-01'), row('40-F', '0000000002-25-000001', '2025-04-01')]
    assert len(sec.select_filings(rows, AS_OF)) == 2
