#!/usr/bin/env python3
"""Collect a bounded, resumable SEC filing corpus for StockSense issuers."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time as clock_time, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

if __package__:
    from .collection_common import (
        atomic_write_json, fetch_json, fetch_text, load_environment,
        read_jsonl, stable_hash, utc_now, write_jsonl,
    )
else:
    from collection_common import (
        atomic_write_json, fetch_json, fetch_text, load_environment,
        read_jsonl, stable_hash, utc_now, write_jsonl,
    )


DATA_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = DATA_DIR / "artifacts" / "sec"
EASTERN = ZoneInfo("America/New_York")
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
TICKER_FILE = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SHARD = "https://data.sec.gov/submissions/{name}"
MIN_INTERVAL = 0.5  # Two requests per second, below SEC's ten-per-second ceiling.
NORMALIZATION_VERSION = 2


class FilingText(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BLOCK_TAGS = {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table"}
    HIDDEN_TAGS = {"head", "script", "style", "noscript", "template", "ix:header", "ix:hidden"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []

    @property
    def ignored(self) -> bool:
        return bool(self.stack and self.stack[-1][1])

    def separator(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        style = re.sub(r"/\*.*?\*/", "", attributes.get("style") or "", flags=re.S)
        hidden_style = re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!\s*important\s*)?(?:;|$)", style, re.I)
        hidden = self.ignored or tag in self.HIDDEN_TAGS or "hidden" in attributes or bool(hidden_style)
        if not hidden:
            self.separator(tag)
        # Void elements never consume a closing tag; treating them as containers
        # would suppress all following text after e.g. a hidden input element.
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                hidden = self.stack[index][1]
                del self.stack[index:]
                if not hidden:
                    self.separator(tag)
                break

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def normalize_filing(raw: str) -> str:
    parser = FilingText()
    parser.feed(raw)
    text = "".join(parser.parts)
    return "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    )


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetched_at() -> str:
    value = utc_now()
    return iso_utc(value) if isinstance(value, datetime) else value


def acceptance_time(row: dict) -> datetime:
    """EDGAR acceptanceDateTime has no offset; it is Eastern local time."""
    raw = row.get("acceptanceDateTime")
    if raw:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return value.replace(tzinfo=EASTERN) if value.tzinfo is None else value
    # A missing acceptance time must never make a filing prematurely available.
    filed = date.fromisoformat(row["filingDate"])
    return datetime.combine(filed, clock_time.max, EASTERN)


def filing_rows(table: dict) -> list[dict]:
    if not isinstance(table, dict):
        return []
    columns = ["accessionNumber", "form", "filingDate", "reportDate", "acceptanceDateTime", "primaryDocument"]
    count = len(table.get("accessionNumber", []))
    return [{key: (table.get(key, [None] * count)[i] if i < len(table.get(key, [])) else None) for key in columns} for i in range(count)]


def select_filings(rows: list[dict], as_of: datetime) -> list[dict]:
    eligible = []
    for row in rows:
        if row.get("form") not in {"10-K", "10-Q", "20-F", "40-F", "8-K", "6-K"}:
            continue
        try:
            accepted = acceptance_time(row)
            if accepted.astimezone(timezone.utc) <= as_of and ACCESSION.fullmatch(str(row.get("accessionNumber", ""))):
                eligible.append((accepted, row))
        except (TypeError, ValueError):
            continue
    eligible.sort(key=lambda item: item[0], reverse=True)
    annual_forms = [row["form"] for _, row in eligible if row["form"] in {"10-K", "20-F", "40-F"}]
    foreign = bool(annual_forms and annual_forms[0] in {"20-F", "40-F"})
    annual = annual_forms[0] if foreign else "10-K"
    quarterly = "6-K" if foreign else "10-Q"
    current = "6-K" if foreign else "8-K"
    selected: list[dict] = []
    for form, maximum, cutoff in (
        (annual, 2, None),
        (quarterly, 4 if not foreign else 0, None),
        (current, None, as_of - timedelta(days=90)),
    ):
        matches = [row for accepted, row in eligible if row["form"] == form and (cutoff is None or accepted.astimezone(timezone.utc) >= cutoff)]
        selected.extend(matches[:maximum] if maximum is not None else matches)
    return list({row["accessionNumber"]: row for row in selected}.values())


def validate_identity(value: str | None) -> str:
    value = (value or "").strip()
    if not value or "@" not in value or any(c in value for c in "\r\n"):
        raise ValueError("SEC_USER_AGENT must identify your organization and contact email")
    organization, _, contact = value.rpartition(" ")
    if not organization or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact):
        raise ValueError("SEC_USER_AGENT must identify your organization and contact email")
    return value


class SecClient:
    def __init__(self, user_agent: str, cache: Path, *, pause=time.sleep, monotonic=time.monotonic):
        self.headers = {"User-Agent": validate_identity(user_agent)}
        self.cache = cache
        self.pause = pause
        self.monotonic = monotonic
        self.last_request: float | None = None
        self.refreshed: set[str] = set()

    def _request(self, url: str, parser, suffix: str):
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / f"{stable_hash(url)}.{suffix}"
        # Submission inventories change; refresh once per run. Accession HTML is
        # immutable and can be reused across runs.
        if path.exists() and (suffix == "html" or url in self.refreshed):
            content = path.read_text(encoding="utf-8")
            return json.loads(content) if suffix == "json" else content
        for attempt in range(4):
            if self.last_request is not None:
                self.pause(max(0.0, MIN_INTERVAL - (self.monotonic() - self.last_request)))
            self.last_request = self.monotonic()
            try:
                result = parser(url, headers=self.headers)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache, prefix=".sec-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(json.dumps(result) if suffix == "json" else result)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                self.refreshed.add(url)
                return result
            except Exception as error:
                status = getattr(error, "status", None)
                if status not in {None, 408, 429, 500, 502, 503, 504} or attempt == 3:
                    raise
                retry_after = getattr(error, "retry_after", None)
                try:
                    wait = max(float(retry_after), 2 ** attempt) if retry_after is not None else 2 ** attempt
                except (TypeError, ValueError):
                    wait = 2 ** attempt
                self.pause(min(wait, 60))
        raise RuntimeError("SEC request attempts exhausted")

    def json(self, url: str):
        return self._request(url, fetch_json, "json")

    def text(self, url: str):
        return self._request(url, fetch_text, "html")


def issuer_mapping(client: SecClient) -> dict[str, dict]:
    raw = client.json(TICKER_FILE)
    mapped: dict[str, dict] = {}
    for entry in raw.values() if isinstance(raw, dict) else raw:
        ticker = str(entry.get("ticker", "")).upper()
        if ticker in mapped and mapped[ticker]["cik_str"] != entry["cik_str"]:
            raise ValueError(f"SEC ticker mapping is ambiguous for {ticker}")
        mapped[ticker] = entry
    return mapped


def all_submissions(client: SecClient, cik: int, as_of: datetime) -> tuple[dict, list[dict]]:
    submission = client.json(SUBMISSIONS.format(cik=cik))
    rows = filing_rows(submission.get("filings", {}).get("recent", {}))
    # Older shards are needed for an issuer with sparse recent forms.
    for shard in submission.get("filings", {}).get("files", []):
        known = [r for r in rows if r.get("form") in {"10-K", "20-F", "40-F", "10-Q"} and r.get("filingDate") and acceptance_time(r).astimezone(timezone.utc) <= as_of]
        foreign = bool(known and next((r["form"] for r in known if r["form"] in {"10-K", "20-F", "40-F"}), None) in {"20-F", "40-F"})
        annual = next(r["form"] for r in known if r["form"] in {"20-F", "40-F"}) if foreign else "10-K"
        if sum(r["form"] == annual for r in known) >= 2 and (foreign or sum(r["form"] == "10-Q" for r in known) >= 4):
            break
        name = str(shard.get("name", ""))
        if not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
            continue
        rows.extend(filing_rows(client.json(SHARD.format(name=name))))
    return submission, list({r.get("accessionNumber"): r for r in rows if r.get("accessionNumber")}.values())


def filing_url(cik: int, row: dict) -> str:
    document = str(row.get("primaryDocument") or "")
    if not document or document in {".", ".."} or "/" in document or "\\" in document:
        raise ValueError("SEC filing has an unsafe primary document name")
    accession = row["accessionNumber"]
    if not ACCESSION.fullmatch(accession):
        raise ValueError("SEC filing has an invalid accession")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{quote(document)}"


def document_record(ticker: str, cik: int, issuer: str, row: dict, html: str, as_of: datetime) -> dict:
    text = normalize_filing(html)
    accepted = acceptance_time(row)
    stamp = iso_utc(accepted)
    return {
        "document_id": f"sec:{cik}:{row['accessionNumber']}",
        "source_type": "sec", "provider": "SEC EDGAR", "tickers": [ticker],
        "published_at": stamp, "available_at": stamp, "fetched_at": fetched_at(),
        "source_url": filing_url(cik, row), "title": f"{issuer} {row['form']} ({row.get('filingDate')})",
        "text": text, "content_hash": stable_hash(text), "cik": cik,
        "normalization_version": NORMALIZATION_VERSION,
        "issuer_name": issuer, "accession": row["accessionNumber"], "form": row["form"],
        "report_period": row.get("reportDate") or None,
        "filing_date": row.get("filingDate"), "accepted_at": stamp,
        "as_of": iso_utc(as_of),
    }


def universe_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def collect(output: Path, as_of: datetime, tickers: list[str], universe: list[dict], client: SecClient) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    existing = {row["document_id"]: row for row in read_jsonl(output / "documents.jsonl")} if (output / "documents.jsonl").exists() else {}
    previous_coverage = {}
    if (output / "coverage.json").exists():
        previous = json.loads((output / "coverage.json").read_text())
        previous_as_of = datetime.fromisoformat(previous["as_of"].replace("Z", "+00:00"))
        if previous_as_of > as_of:
            raise ValueError("SEC output directory contains later filings; choose a new --output-dir for an earlier --as-of")
        previous_coverage = previous.get("tickers", {})
    coverage = dict(previous_coverage)
    by_ticker = {row["ticker"].upper(): row for row in universe}
    stocks = [t for t in tickers if t in by_ticker and by_ticker[t]["asset_type"] == "stock"]
    try:
        mapping = issuer_mapping(client) if stocks else {}
    except Exception as error:
        for ticker in tickers:
            coverage[ticker] = (
                {"status": "failed", "reason": f"issuer_mapping_{type(error).__name__}"}
                if ticker in stocks else
                {"status": "not-applicable", "reason": "No corporate issuer filing corpus"}
            )
        result = {"as_of": iso_utc(as_of), "tickers": coverage}
        atomic_write_json(output / "coverage.json", result)
        return result
    for ticker in tickers:
        asset = by_ticker.get(ticker)
        if asset is None:
            coverage[ticker] = {"status": "unavailable", "reason": "not in StockSense universe"}
            continue
        if asset["asset_type"] != "stock":
            coverage[ticker] = {"status": "not-applicable", "reason": "ETF/index has no corporate issuer filing corpus"}
            continue
        match = mapping.get(ticker)
        if not match:
            coverage[ticker] = {"status": "unavailable", "reason": "ticker missing from SEC issuer mapping"}
            continue
        cik = int(match["cik_str"])
        try:
            submission, rows = all_submissions(client, cik, as_of)
            listed = {str(t).upper() for t in submission.get("tickers", [])}
            if ticker not in listed:
                coverage[ticker] = {"status": "unavailable", "reason": "SEC submission ticker does not match issuer mapping", "cik": cik}
                continue
            selected = select_filings(rows, as_of)
            added = 0
            for row in selected:
                document_id = f"sec:{cik}:{row['accessionNumber']}"
                if document_id in existing:
                    record = existing[document_id]
                    if record.get("normalization_version") != NORMALIZATION_VERSION:
                        # Accession HTML is cached independently of normalized
                        # text. Updating the parser does not change fetched_at.
                        text = normalize_filing(client.text(filing_url(cik, row)))
                        if not text:
                            raise ValueError("SEC primary filing has no extractable text")
                        record.update(text=text, content_hash=stable_hash(text), normalization_version=NORMALIZATION_VERSION)
                    record["tickers"] = sorted(set(record["tickers"]) | {ticker})
                    added += 1
                    continue
                url = filing_url(cik, row)
                html = client.text(url)
                record = document_record(ticker, cik, submission.get("name") or match.get("title") or ticker, row, html, as_of)
                if not record["text"]:
                    raise ValueError("SEC primary filing has no extractable text")
                existing[document_id] = record
                added += 1
                write_jsonl(output / "documents.jsonl", sorted(existing.values(), key=lambda r: r["document_id"]))
            coverage[ticker] = {
                "status": "collected" if added else "no-results", "cik": cik,
                "issuer_name": submission.get("name"), "filings_selected": len(selected),
                "filings_collected": added, "forms": sorted({r["form"] for r in selected}),
            }
        except Exception as error:
            coverage[ticker] = {"status": "failed", "cik": cik, "reason": type(error).__name__}
        atomic_write_json(output / "coverage.json", {"as_of": iso_utc(as_of), "tickers": coverage})
    write_jsonl(output / "documents.jsonl", sorted(existing.values(), key=lambda r: r["document_id"]))
    result = {"as_of": iso_utc(as_of), "tickers": coverage}
    atomic_write_json(output / "coverage.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DATA_DIR / ".env")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", help="UTC ISO date or datetime; defaults to now")
    parser.add_argument("--pilot", type=int, metavar="N", help="Collect first N stock tickers")
    parser.add_argument("--tickers", help="Comma-separated StockSense tickers")
    args = parser.parse_args()
    load_environment(args.env_file)
    try:
        identity = validate_identity(os.getenv("SEC_USER_AGENT"))
    except ValueError as error:
        parser.error(str(error))
    if args.pilot is not None and args.pilot <= 0:
        parser.error("--pilot must be positive")
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.fromisoformat(utc_now().replace("Z", "+00:00"))
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    if len(args.as_of or "") == 10:
        as_of = datetime.combine(as_of.date(), clock_time.max, timezone.utc)
    as_of = as_of.astimezone(timezone.utc)
    universe = universe_rows(DATA_DIR / "asset_universe.csv")
    names = [row["ticker"].upper() for row in universe]
    if args.tickers:
        names = list(dict.fromkeys(t.strip().upper() for t in args.tickers.split(",") if t.strip()))
    if args.pilot is not None:
        stocks = {row["ticker"].upper() for row in universe if row["asset_type"] == "stock"}
        names = [name for name in names if name in stocks][:args.pilot]
    result = collect(args.output_dir, as_of, names, universe, SecClient(identity, args.output_dir / "raw"))
    counts = {status: sum(item["status"] == status for item in result["tickers"].values()) for status in {item["status"] for item in result["tickers"].values()}}
    print(f"SEC coverage: {counts}; output: {args.output_dir}")
    if counts.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
