"""Financial Statement Data Set cleaning on small in-memory zips."""
import json
import zipfile

from data import import_sec_financial_statements as module
from data.rag.fundamentals_signal import build_fundamentals_signals

SUB_HEADER = "adsh\tcik\tname\tform\tperiod\tfy\tfp\tfiled\n"
NUM_HEADER = "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\tfootnote\n"


def write_zip(path, sub_rows, num_rows):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sub.txt", SUB_HEADER + "".join("\t".join(r) + "\n" for r in sub_rows))
        archive.writestr("num.txt", NUM_HEADER + "".join("\t".join(r) + "\n" for r in num_rows))


def num(tag, ddate, qtrs, value, adsh="0001-26-1", version="us-gaap/2025", uom="USD", seg="", coreg=""):
    return [adsh, tag, version, ddate, qtrs, uom, seg, coreg, value, ""]


def test_keeps_only_needed_consolidated_facts_and_feeds_signal(tmp_path):
    (tmp_path / "tickers.json").write_text(json.dumps(
        {"0": {"ticker": "AAPL", "cik_str": 1}, "1": {"ticker": "OTHER", "cik_str": 2}}))
    sub = [["0001-26-1", "1", "Apple", "10-K", "20251231", "2025", "FY", "20260215"],
           ["0001-26-2", "1", "Apple", "8-K", "20251231", "2025", "", "20260110"],
           ["0002-26-1", "2", "Other", "10-K", "20251231", "2025", "FY", "20260215"]]
    rows = [num("Revenues", "20251231", "4", "120"), num("Revenues", "20241231", "4", "100"),
            num("OperatingIncomeLoss", "20251231", "4", "30"),
            num("AssetsCurrent", "20251231", "0", "200"), num("LiabilitiesCurrent", "20251231", "0", "100"),
            # Each of these must be dropped.
            num("Revenues", "20251231", "1", "30"),                       # quarterly duration
            num("Revenues", "20251231", "4", "50", seg="Product=iPhone;"),  # segment
            num("Revenues", "20251231", "4", "60", coreg="Sub LLC"),        # co-registrant
            num("Revenues", "20251231", "4", "70", version="0000320193-26-1"),  # custom tag
            num("Revenues", "20251231", "4", "80", uom="EUR"),
            num("Unrelated", "20251231", "4", "1"),
            num("Revenues", "20251231", "4", "1", adsh="0001-26-2"),       # 8-K
            num("Revenues", "20251231", "4", "1", adsh="0002-26-1")]       # not our stock
    write_zip(tmp_path / "2026q1.zip", sub, rows)
    write_zip(tmp_path / "2025q3.zip", [], [])
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,asset_type\nAAPL,stock\nMSFT,stock\nSPY,etf\n")

    result = module.run(tmp_path, tmp_path / "tickers.json", tmp_path / "out", universe_path=universe)
    facts = [json.loads(l) for l in (tmp_path / "out/facts.jsonl").read_text().splitlines()]
    assert {(f["concept"], f["end"], f["val"]) for f in facts} == {
        ("Revenues", "2025-12-31", 120.0), ("Revenues", "2024-12-31", 100.0),
        ("OperatingIncomeLoss", "2025-12-31", 30.0), ("AssetsCurrent", "2025-12-31", 200.0),
        ("LiabilitiesCurrent", "2025-12-31", 100.0)}
    annual = next(f for f in facts if f["concept"] == "Revenues" and f["end"] == "2025-12-31")
    assert annual["start"] == "2025-01-01" and annual["filed"] == "2026-02-15"
    assert annual["ticker"] == "AAPL" and annual["accn"] == "0001-26-1" and annual["fy"] == 2025
    assert all(f["start"] is None for f in facts if f["concept"] == "AssetsCurrent")
    assert result["missing_quarters"] == ["2025q4"]
    assert result["tickers"]["AAPL"]["status"] == "collected"
    assert result["tickers"]["MSFT"] == {"status": "failed", "reason": "no_sec_ticker_mapping"}
    assert "SPY" not in result["tickers"]

    signal = build_fundamentals_signals(facts, ["AAPL"], "2026-03-01")["AAPL"]
    assert signal["metrics"]["revenue_growth"]["value"] == 0.2
    assert signal["metrics"]["operating_margin"]["value"] == 0.25
    assert signal["metrics"]["current_ratio"]["value"] == 2.0


def test_predecessor_cik_alias_is_matched(tmp_path):
    (tmp_path / "tickers.json").write_text(json.dumps({"0": {"ticker": "XOM", "cik_str": 2115436}}))
    assert module.stock_ciks(tmp_path / "tickers.json", [{"ticker": "XOM", "asset_type": "stock"}]) == {
        2115436: "XOM", 34088: "XOM"}
