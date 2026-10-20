#!/usr/bin/env python3
"""Collect recent market news for offline StockSense research."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode

if __package__:
    from .collection_common import (
        atomic_write_json, fetch_json, load_environment, read_jsonl,
        stable_hash, utc_now, write_jsonl,
    )
else:
    from collection_common import (
        atomic_write_json, fetch_json, load_environment, read_jsonl,
        stable_hash, utc_now, write_jsonl,
    )


DATA_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = DATA_DIR / "artifacts" / "news"
ALPACA_URL = "https://data.alpaca.markets/v1beta1/news"
AV_URL = "https://www.alphavantage.co/query"
AV_DAILY_LIMIT = 25
MAX_RETRIES = 3
AV_QUOTA_PATH = DATA_DIR / ".cache" / "alpha_vantage_quota.sqlite3"


def reserve_av_request(account: str, day: str, known_used: int = 0) -> int:
    """Atomically reserve a request across output folders and collector processes."""
    AV_QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(AV_QUOTA_PATH, timeout=10) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS quota (account TEXT, day TEXT, used INTEGER, PRIMARY KEY(account, day))")
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT used FROM quota WHERE account=? AND day=?", (account, day)).fetchone()
        used = max(row[0] if row else 0, known_used)
        if used >= AV_DAILY_LIMIT:
            raise RuntimeError("Alpha Vantage daily request budget exhausted")
        connection.execute("INSERT OR REPLACE INTO quota VALUES (?, ?, ?)", (account, day, used + 1))
        return used + 1


def iso_utc(value: str | datetime) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str | datetime) -> datetime:
    return datetime.fromisoformat(iso_utc(value).replace("Z", "+00:00"))


def load_universe(path: Path = DATA_DIR / "asset_universe.csv") -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["ticker"] for row in csv.DictReader(handle) if row["ticker"] != "^VIX"}


def load_coverage(path: Path) -> dict:
    if not path.exists():
        return {"windows": {}, "quota": {}}
    import json
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    result.setdefault("windows", {})
    result.setdefault("quota", {})
    return result


def _safe_request(url: str, headers: dict[str, str] | None = None, *, quota: dict | None = None,
                  coverage_path: Path | None = None, coverage: dict | None = None,
                  quota_account: str | None = None, quota_day: str | None = None) -> dict:
    """Retry transient failures without recording credential-bearing exceptions."""
    for attempt in range(MAX_RETRIES):
        if quota is not None:
            if quota["used"] >= AV_DAILY_LIMIT:
                raise RuntimeError("Alpha Vantage daily request budget exhausted")
            quota["used"] = reserve_av_request(quota_account, quota_day, quota["used"])
            atomic_write_json(coverage_path, coverage)
        try:
            return fetch_json(url, headers=headers, timeout=30)
        except Exception as error:
            status = getattr(error, "status", getattr(error, "status_code", None))
            if status in (401, 403):
                raise RuntimeError(f"Provider rejected credentials or entitlement ({status})") from None
            if attempt == MAX_RETRIES - 1 or (status is not None and status not in (429, 500, 502, 503, 504)):
                raise RuntimeError("Provider request failed") from None
            delay = getattr(error, "retry_after", None)
            try:
                delay = min(max(float(delay), 0), 30) if delay is not None else 2 ** attempt
            except (TypeError, ValueError):
                delay = 2 ** attempt
            time.sleep(delay)
    raise RuntimeError("Provider request failed")


def _alpaca_record(article: dict, universe: set[str], fetched_at: str) -> dict | None:
    tickers = sorted(universe.intersection(article.get("symbols") or []))
    if not tickers:
        return None
    provider_id = str(article["id"])
    updated_at = iso_utc(article.get("updated_at") or article["created_at"])
    published_at = iso_utc(article["created_at"])
    text = article.get("content") or article.get("summary") or ""
    content_hash = stable_hash(text)
    return {
        "document_id": f"news:alpaca:{provider_id}:{stable_hash(updated_at + content_hash)[:12]}",
        "source_type": "news", "provider": "alpaca", "provider_id": provider_id,
        "tickers": tickers, "published_at": published_at,
        "available_at": fetched_at, "fetched_at": fetched_at,
        "updated_at": updated_at, "source_url": article.get("url") or "",
        "title": article.get("headline") or "", "text": text,
        "content_hash": content_hash, "content_available": bool(article.get("content")),
        "source": article.get("source") or "", "provider_sentiment": None,
    }


def _av_records(article: dict, universe: set[str], fetched_at: str) -> list[dict]:
    tagged = article.get("ticker_sentiment") or []
    tickers = sorted(universe.intersection(item.get("ticker") for item in tagged if item.get("ticker")))
    if not tickers:
        return []
    published = datetime.strptime(article["time_published"], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    text = article.get("summary") or ""
    source_url = article.get("url") or ""
    provider_id = stable_hash(source_url or (article.get("title", "") + article["time_published"]))
    content_hash = stable_hash(text)
    # Persist Alpha Vantage's original per-ticker sentiment, INCLUDING relevance_score.
    # The P1 attribution diagnostic showed relevance was being dropped here, which is the
    # one field needed for relevance-weighted aggregation (it cannot be recovered later).
    sentiments = {item["ticker"]: {"label": item.get("ticker_sentiment_label"),
                                     "score": item.get("ticker_sentiment_score"),
                                     "relevance": item.get("relevance_score")}
                  for item in tagged if item.get("ticker") in tickers}
    return [{
        "document_id": f"news:alpha_vantage:{provider_id}:{content_hash[:12]}",
        "source_type": "news", "provider": "alpha_vantage", "provider_id": provider_id,
        "tickers": tickers, "published_at": iso_utc(published),
        "available_at": fetched_at, "fetched_at": fetched_at,
        "updated_at": None, "source_url": source_url,
        "title": article.get("title") or "", "text": text,
        "content_hash": content_hash, "content_available": False,
        "source": article.get("source") or "", "provider_sentiment": sentiments,
    }]


def _save_documents(path: Path, incoming: list[dict]) -> None:
    existing = {record["document_id"]: record for record in read_jsonl(path)} if path.exists() else {}
    for record in incoming:
        if record["document_id"] not in existing:
            existing[record["document_id"]] = record
    write_jsonl(path, sorted(existing.values(), key=lambda item: (item["published_at"], item["document_id"])))


def collect_alpaca(*, start: datetime, end: datetime, output_dir: Path,
                   coverage: dict, universe: set[str], key: str, secret: str) -> None:
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    coverage_path = output_dir / "coverage.json"
    documents_path = output_dir / "documents.jsonl"
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=1), end)
        window_key = f"alpaca:{iso_utc(cursor)}:{iso_utc(window_end)}"
        if coverage["windows"].get(window_key, {}).get("status") in ("collected", "no_results"):
            cursor = window_end
            continue
        page_token = None
        seen_tokens: set[str] = set()
        window_records: list[dict] = []
        article_count = 0
        try:
            while True:
                params = {"start": iso_utc(cursor), "end": iso_utc(window_end),
                          "sort": "asc", "limit": 50, "include_content": "true"}
                if page_token:
                    params["page_token"] = page_token
                response = _safe_request(f"{ALPACA_URL}?{urlencode(params)}", headers)
                articles = response.get("news")
                if not isinstance(articles, list):
                    raise RuntimeError("Malformed Alpaca response")
                article_count += len(articles)
                fetched_at = iso_utc(utc_now())
                for article in articles:
                    record = _alpaca_record(article, universe, fetched_at)
                    if record:
                        window_records.append(record)
                page_token = response.get("next_page_token")
                if not page_token:
                    break
                if page_token in seen_tokens:
                    raise RuntimeError("Repeated Alpaca pagination token")
                seen_tokens.add(page_token)
            _save_documents(documents_path, window_records)
            coverage["windows"][window_key] = {
                "status": "collected" if window_records else "no_results",
                "provider_articles": article_count, "matched_documents": len(window_records),
                "completed_at": iso_utc(utc_now()),
            }
        except Exception:
            coverage["windows"][window_key] = {"status": "failed", "completed_at": iso_utc(utc_now())}
        atomic_write_json(coverage_path, coverage)
        cursor = window_end


def collect_alpha_vantage(*, start: datetime, end: datetime, output_dir: Path,
                          coverage: dict, universe: set[str], key: str) -> None:
    coverage_path = output_dir / "coverage.json"
    documents_path = output_dir / "documents.jsonl"
    cursor = start
    windows: list[tuple[datetime, datetime]] = []
    while cursor < end:
        window_end = min(cursor + timedelta(days=1), end)
        windows.append((cursor, window_end))
        cursor = window_end
    # Under the free daily budget, current context takes priority over backfill.
    for cursor, window_end in reversed(windows):
        window_key = f"alpha_vantage:{iso_utc(cursor)}:{iso_utc(window_end)}"
        if coverage["windows"].get(window_key, {}).get("status") in ("collected", "no_results"):
            continue
        quota_key = parse_time(utc_now()).date().isoformat()
        quota = coverage["quota"].setdefault(quota_key, {"used": 0})
        if quota["used"] >= AV_DAILY_LIMIT:
            coverage["windows"][window_key] = {"status": "unavailable", "reason": "daily_quota"}
            atomic_write_json(coverage_path, coverage)
            continue
        params = {"function": "NEWS_SENTIMENT",
                  "time_from": cursor.strftime("%Y%m%dT%H%M"),
                  "time_to": window_end.strftime("%Y%m%dT%H%M"),
                  "sort": "LATEST", "limit": 1000, "apikey": key}
        try:
            response = _safe_request(f"{AV_URL}?{urlencode(params)}", quota=quota,
                                     coverage_path=coverage_path, coverage=coverage,
                                     quota_account=stable_hash(key), quota_day=quota_key)
            if not isinstance(response.get("feed"), list):
                # Quota and entitlement notices arrive as HTTP 200. Stop this
                # run rather than spend the remaining budget repeating them.
                coverage["windows"][window_key] = {
                    "status": "unavailable", "reason": "provider_notice_or_entitlement",
                    "completed_at": iso_utc(utc_now()),
                }
                atomic_write_json(coverage_path, coverage)
                break
            fetched_at = iso_utc(utc_now())
            records = [record for article in response["feed"]
                       for record in _av_records(article, universe, fetched_at)]
            _save_documents(documents_path, records)
            reported = response.get("items")
            truncated = len(response["feed"]) >= 1000 or (str(reported).isdigit() and int(reported) > len(response["feed"]))
            coverage["windows"][window_key] = {
                "status": "partial" if truncated else ("collected" if records else "no_results"),
                "provider_articles": len(response["feed"]), "matched_documents": len(records),
                "truncated": truncated, "completed_at": fetched_at,
            }
        except Exception:
            coverage["windows"][window_key] = {"status": "failed", "completed_at": iso_utc(utc_now())}
        atomic_write_json(coverage_path, coverage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DATA_DIR / ".env")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", help="UTC timestamp; defaults to current UTC time")
    parser.add_argument("--days", type=int, default=30, help="UTC calendar days including the as-of day (1-30)")
    parser.add_argument("--provider", choices=("alpaca", "alpha_vantage", "both"), default="alpaca")
    args = parser.parse_args()
    if args.days < 1 or args.days > 30:
        parser.error("--days must be from 1 through 30")
    load_environment(args.env_file)
    now = parse_time(args.as_of) if args.as_of else parse_time(utc_now())
    cutoff = (now - timedelta(minutes=15)).replace(second=0, microsecond=0)
    start = datetime.combine(cutoff.date() - timedelta(days=args.days - 1),
                             datetime.min.time(), tzinfo=timezone.utc)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = load_coverage(output_dir / "coverage.json")
    universe = load_universe()
    if args.provider in ("alpaca", "both"):
        key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            parser.error("Alpaca key and secret are required for Alpaca collection")
        collect_alpaca(start=start, end=cutoff, output_dir=output_dir, coverage=coverage,
                       universe=universe, key=key, secret=secret)
    if args.provider in ("alpha_vantage", "both"):
        av_key = os.environ.get("ALPHA_VANTAGE_API_KEY") or os.environ.get("ALPHAVANTAGE_API_KEY")
        if not av_key:
            parser.error("ALPHA_VANTAGE_API_KEY is required for Alpha Vantage collection")
        collect_alpha_vantage(start=start, end=cutoff, output_dir=output_dir,
                              coverage=coverage, universe=universe, key=av_key)
    statuses: dict[str, int] = {}
    for result in coverage["windows"].values():
        statuses[result["status"]] = statuses.get(result["status"], 0) + 1
    documents = read_jsonl(output_dir / "documents.jsonl")
    coverage["requested_start"] = iso_utc(start)
    coverage["requested_end"] = iso_utc(cutoff)
    coverage["updated_at"] = iso_utc(utc_now())
    counts = {ticker: 0 for ticker in universe}
    for record in documents:
        if start <= parse_time(record["published_at"]) <= cutoff:
            for ticker in record["tickers"]:
                if ticker in counts:
                    counts[ticker] += 1
    coverage["tickers"] = {
        ticker: {"documents": count, "status": "collected" if count else "no_matching_documents",
                 "collection_incomplete": any(status not in {"collected", "no_results"} for status in statuses)}
        for ticker, count in sorted(counts.items())
    }
    atomic_write_json(output_dir / "coverage.json", coverage)
    print(f"News collection coverage: {statuses}")
    if statuses.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
