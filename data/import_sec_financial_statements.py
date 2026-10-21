#!/usr/bin/env python3
"""Clean SEC Financial Statement Data Sets into the fundamentals fact format.

Offline alternative to data/collect_sec_fundamentals.py for manually downloaded
quarterly zips (https://www.sec.gov/dera/data/financial-statement-data-sets).
Zips are read in place, never extracted. Output matches the collector's
``facts.jsonl`` so data/rag/fundamentals_signal.py reads either source.

Kept: our stock tickers' 10-K/10-Q (and amendments), the us-gaap concepts the
signal uses, USD, consolidated values (no segments or co-registrants), and
annual (4-quarter) or point-in-time (0-quarter) values. Each value keeps the
filing's date and accession so the signal stays point-in-time.

The data sets identify issuers by CIK only. Download the SEC ticker map
(https://www.sec.gov/files/company_tickers.json) alongside the zips.

    python -m data.import_sec_financial_statements \\
        --zips-dir ~/Downloads --tickers-json ~/Downloads/company_tickers.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile

import pandas as pd

from data.collect_sec_fundamentals import CONCEPTS, DEFAULT_OUTPUT, FORMS
from data.collect_sec_filings import universe_rows
from data.collection_common import atomic_write_json, utc_now, write_jsonl

DATA_DIR = Path(__file__).resolve().parent
QUARTER_ZIP = re.compile(r"^(\d{4})q([1-4])\.zip$")
CHUNK_ROWS = 1_000_000
# The SEC ticker map lists only the current CIK. Exxon's filings in the data sets
# (through 2026q3) are under its long-standing CIK, "EXXON MOBIL CORP", while the
# map now points XOM at a new holding-company CIK. Extra CIKs are matched too.
CIK_ALIASES = {"XOM": (34088,)}


def stock_ciks(tickers_json: Path, universe: list[dict]) -> dict[int, str]:
    """CIK -> StockSense ticker for universe stocks; unmapped tickers are omitted."""
    # A pasted plain-text copy may start with a byte-order mark from the editor.
    try:
        raw = json.loads(Path(tickers_json).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise ValueError("Ticker map is not valid JSON; save it as plain text, not rich text") from None
    entries = raw.values() if isinstance(raw, dict) else raw
    by_ticker: dict[str, int] = {}
    for entry in entries:
        ticker, cik = str(entry.get("ticker", "")).upper(), int(entry["cik_str"])
        if by_ticker.setdefault(ticker, cik) != cik:
            raise ValueError(f"SEC ticker map is ambiguous for {ticker}")
    stocks = [row["ticker"].upper() for row in universe if row["asset_type"] == "stock"]
    mapped = {by_ticker[t]: t for t in stocks if t in by_ticker}
    for ticker, aliases in CIK_ALIASES.items():
        if ticker in stocks:
            mapped.update({cik: ticker for cik in aliases})
    return mapped


def _text(value) -> str:
    return "" if pd.isna(value) else str(value)


def quarter_facts(path: Path, ciks: dict[int, str]) -> list[dict]:
    """Filtered fact records from one quarterly zip."""
    with zipfile.ZipFile(path) as archive:
        with archive.open("sub.txt") as stream:
            sub = pd.read_csv(stream, sep="\t", dtype=str, usecols=["adsh", "cik", "form", "fy", "fp", "filed"],
                              keep_default_na=False, encoding="utf-8", encoding_errors="replace")
        sub = sub.loc[sub["form"].isin(FORMS) & sub["cik"].astype(int).isin(ciks)]
        if sub.empty:
            return []
        filings = sub.set_index("adsh")
        records = []
        with archive.open("num.txt") as stream:
            for chunk in pd.read_csv(stream, sep="\t", dtype=str, chunksize=CHUNK_ROWS,
                                     usecols=lambda c: c in {"adsh", "tag", "version", "ddate", "qtrs", "uom",
                                                             "segments", "coreg", "value"},
                                     keep_default_na=False, encoding="utf-8", encoding_errors="replace"):
                chunk = chunk.loc[chunk["adsh"].isin(filings.index) & chunk["tag"].isin(CONCEPTS)
                                  & chunk["uom"].eq("USD") & chunk["qtrs"].isin(["0", "4"])
                                  & chunk["version"].str.startswith("us-gaap/") & chunk["coreg"].eq("")
                                  & chunk["value"].ne("")]
                if "segments" in chunk:
                    chunk = chunk.loc[chunk["segments"].eq("")]
                for row in chunk.itertuples(index=False):
                    filing = filings.loc[row.adsh]
                    end = pd.Timestamp(row.ddate)
                    # The data sets give an end date and quarter count, not a start date.
                    start = (end - pd.DateOffset(years=1) + pd.Timedelta(days=1)).date().isoformat() \
                        if row.qtrs == "4" else None
                    cik = int(filing["cik"])
                    records.append({
                        "ticker": ciks[cik], "cik": cik, "concept": row.tag, "start": start,
                        "end": end.date().isoformat(), "val": float(row.value), "form": filing["form"],
                        "fy": int(filing["fy"]) if filing["fy"].isdigit() else None,
                        "fp": filing["fp"] or None,
                        "filed": pd.Timestamp(filing["filed"]).date().isoformat(), "accn": row.adsh,
                    })
    return records


def run(zips_dir: Path, tickers_json: Path, output: Path,
        universe_path: Path = DATA_DIR / "asset_universe.csv") -> dict:
    zips = sorted((p for p in Path(zips_dir).expanduser().iterdir() if QUARTER_ZIP.match(p.name)),
                  key=lambda p: p.name)
    if not zips:
        raise ValueError("No YYYYqN.zip financial statement data sets found")
    universe = universe_rows(universe_path)
    ciks = stock_ciks(Path(tickers_json).expanduser(), universe)
    records, quarters = [], {}
    for path in zips:
        rows = quarter_facts(path, ciks)
        quarters[path.stem] = len(rows)
        records.extend(rows)
        print(f"{path.name}: {len(rows):,} facts", flush=True)
    # Guard against repeated rows; one value per accession, concept and period.
    unique = {(r["accn"], r["concept"], r["start"], r["end"]): r for r in records}
    records = sorted(unique.values(), key=lambda r: (r["ticker"], r["concept"], r["end"], r["filed"]))
    present = {int(m.group(1)) * 4 + int(m.group(2)) - 1 for m in (QUARTER_ZIP.match(p.name) for p in zips)}
    missing = [f"{q // 4}q{q % 4 + 1}" for q in range(min(present), max(present) + 1) if q not in present]
    stocks = [row["ticker"].upper() for row in universe if row["asset_type"] == "stock"]
    counts: dict[str, int] = {}
    for r in records:
        counts[r["ticker"]] = counts.get(r["ticker"], 0) + 1
    coverage = {t: ({"status": "collected", "facts": counts[t]} if t in counts else
                    {"status": "no_supported_facts" if t in ciks.values() else "failed",
                     **({} if t in ciks.values() else {"reason": "no_sec_ticker_mapping"})})
                for t in stocks}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "facts.jsonl", records)
    result = {"collected_at": utc_now(), "source": "sec_financial_statement_data_sets",
              "concepts": list(CONCEPTS), "quarters": quarters, "missing_quarters": missing,
              "tickers": coverage}
    atomic_write_json(output / "coverage.json", result)
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zips-dir", type=Path, required=True)
    parser.add_argument("--tickers-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run(args.zips_dir, args.tickers_json, args.output_dir)
    collected = sum(item["status"] == "collected" for item in result["tickers"].values())
    print(f"SEC financial statements: {collected}/{len(result['tickers'])} stocks; output: {args.output_dir}")
    if result["missing_quarters"]:
        print(f"Missing quarters: {', '.join(result['missing_quarters'])}")


if __name__ == "__main__":
    main()
