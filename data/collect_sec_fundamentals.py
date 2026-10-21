#!/usr/bin/env python3
"""Collect point-in-time SEC XBRL fundamentals for StockSense stocks.

Offline and explicit. Reads SEC company facts (https://data.sec.gov/api/xbrl/)
for stock tickers only (ETFs and indices have no issuer fundamentals) and keeps
the small set of concepts used by data/rag/fundamentals_signal.py. Every value
retains its filing date and accession so the signal can use only facts that
were public at its as-of time. Writes under the ignored data/artifacts/.

    python -m data.collect_sec_fundamentals --env-file data/.env
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from data.collect_sec_filings import SecClient, issuer_mapping, universe_rows, validate_identity
from data.collection_common import atomic_write_json, load_environment, utc_now, write_jsonl

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = DATA_DIR / "artifacts" / "sec_fundamentals"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}

# Concepts read by the signal, in us-gaap. Alternatives for one metric are
# resolved there; collecting all of them keeps that choice out of collection.
CONCEPTS = (
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax", "RegulatedAndUnregulatedOperatingRevenue",
    "SalesRevenueNet", "RevenuesNetOfInterestExpense", "OperatingIncomeLoss",
    "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
    "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent",
    "StockholdersEquity", "AssetsCurrent", "LiabilitiesCurrent",
)


def fact_records(ticker: str, cik: int, facts: dict) -> list[dict]:
    """Flatten company facts into one record per reported USD value."""
    records = []
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for concept in CONCEPTS:
        for row in ((gaap.get(concept) or {}).get("units") or {}).get("USD", []):
            if row.get("form") not in FORMS or not row.get("end") or not row.get("filed"):
                continue
            records.append({
                "ticker": ticker, "cik": cik, "concept": concept,
                "start": row.get("start"), "end": row["end"], "val": row["val"],
                "form": row["form"], "fy": row.get("fy"), "fp": row.get("fp"),
                "filed": row["filed"], "accn": row.get("accn"),
            })
    return records


def collect(output: Path, tickers: list[str], client: SecClient) -> dict:
    mapping = issuer_mapping(client)
    records, coverage = [], {}
    for ticker in tickers:
        entry = mapping.get(ticker)
        if entry is None:
            coverage[ticker] = {"status": "failed", "reason": "no_sec_ticker_mapping"}
            continue
        cik = int(entry["cik_str"])
        try:
            rows = fact_records(ticker, cik, client.json(COMPANY_FACTS.format(cik=cik)))
        except Exception as error:
            # Provider errors can embed request details; keep only the error type.
            coverage[ticker] = {"status": "failed", "reason": type(error).__name__}
            continue
        coverage[ticker] = {"status": "collected" if rows else "no_supported_facts",
                            "cik": cik, "facts": len(rows)}
        records.extend(rows)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "facts.jsonl", records)
    result = {"collected_at": utc_now(), "source": "sec_xbrl_companyfacts",
              "concepts": list(CONCEPTS), "tickers": coverage}
    atomic_write_json(output / "coverage.json", result)
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", type=Path, default=DATA_DIR / ".env")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tickers", help="Comma-separated stock tickers; defaults to all universe stocks")
    args = parser.parse_args(argv)
    load_environment(args.env_file)
    try:
        identity = validate_identity(os.getenv("SEC_USER_AGENT"))
    except ValueError as error:
        parser.error(str(error))
    stocks = [row["ticker"].upper() for row in universe_rows(DATA_DIR / "asset_universe.csv")
              if row["asset_type"] == "stock"]
    if args.tickers:
        requested = list(dict.fromkeys(t.strip().upper() for t in args.tickers.split(",") if t.strip()))
        stocks = [t for t in requested if t in set(stocks)]
    result = collect(args.output_dir, stocks, SecClient(identity, args.output_dir / "raw"))
    failed = [t for t, item in result["tickers"].items() if item["status"] == "failed"]
    print(f"SEC fundamentals: {len(result['tickers']) - len(failed)}/{len(result['tickers'])} tickers; "
          f"output: {args.output_dir}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
