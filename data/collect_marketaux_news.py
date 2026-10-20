#!/usr/bin/env python3
"""Collect current market news + per-entity sentiment from Marketaux (free tier).

Why Marketaux: after the P1 attribution diagnostic (docs/ai/SENTIMENT_ATTRIBUTION.md) we do
NOT trust sentiment we attribute ourselves. Alpha Vantage and Finnhub both moved sentiment
to premium. Marketaux's free `/v1/news/all` returns, per article, an `entities[]` array where
each entity carries its own `sentiment_score` (-1..1) and `match_score` (relevance strength).
We use that provider-side attribution directly — no regex, no FinBERT on it — which is exactly
what avoids the Alpha-Vantage attribution mistake: AAPL's sentiment comes from AAPL's entity,
never from a sentence we guessed was about AAPL.

Each collected record matches the shared news schema so `data.rag.news_sentiment` can consume
it: `provider="marketaux"`, `provider_sentiment={ticker: {score, relevance, label, match_score}}`.
`relevance` is `match_score` normalised to [0,1] (match_score / 100, clamped); the raw value is
kept for transparency. Only universe tickers are kept.

Free-tier limits: 100 requests/day, 3 articles per request. We query per symbol and cap the run.
A User-Agent header is required (Marketaux's edge returns Cloudflare 1010 without one).

    python -m data.collect_marketaux_news --env-file data/.env --days 3

Secrets (MARKETAUX_SECRET_KEY) load from the environment or the env file and are never printed.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
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
DEFAULT_OUTPUT = DATA_DIR / "artifacts" / "marketaux"
MARKETAUX_URL = "https://api.marketaux.com/v1/news/all"
USER_AGENT = "StockSense/1.0 (offline research collector)"
FREE_DAILY_LIMIT = 100
MATCH_SCORE_MAX = 100.0  # Marketaux match_score is a 0..~100 strength; normalise to [0,1].


def iso_utc(value: str | datetime) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_universe(path: Path = DATA_DIR / "asset_universe.csv") -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["ticker"] for row in csv.DictReader(handle)
                if row["ticker"] != "^VIX" and row.get("asset_type") != "index"}


def _label(score: float) -> str:
    if score <= -0.15:
        return "Bearish"
    if score >= 0.15:
        return "Bullish"
    return "Neutral"


def _record(article: dict, universe: set[str], fetched_at: str) -> dict | None:
    """Normalise one Marketaux article, keeping only universe entities' own sentiment."""
    provider_sentiment: dict[str, dict] = {}
    for entity in article.get("entities") or []:
        symbol = entity.get("symbol")
        if symbol not in universe:
            continue
        score, match = entity.get("sentiment_score"), entity.get("match_score")
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        try:
            relevance = max(0.0, min(float(match) / MATCH_SCORE_MAX, 1.0))
        except (TypeError, ValueError):
            relevance = None
        provider_sentiment[symbol] = {
            "score": score, "relevance": relevance,
            "label": _label(score), "match_score": match,
        }
    if not provider_sentiment:
        return None

    uuid = article.get("uuid") or stable_hash((article.get("url") or "") + (article.get("published_at") or ""))
    text = article.get("description") or article.get("snippet") or ""
    content_hash = stable_hash(text)
    return {
        "document_id": f"news:marketaux:{uuid}",
        "source_type": "news", "provider": "marketaux", "provider_id": uuid,
        "tickers": sorted(provider_sentiment.keys()),
        "published_at": iso_utc(article["published_at"]),
        "available_at": fetched_at, "fetched_at": fetched_at, "updated_at": None,
        "source_url": article.get("url") or "", "title": article.get("title") or "",
        "text": text, "content_hash": content_hash, "content_available": bool(text),
        "source": article.get("source") or "", "provider_sentiment": provider_sentiment,
    }


def _save_documents(path: Path, incoming: list[dict]) -> int:
    existing = {rec["document_id"]: rec for rec in read_jsonl(path)} if path.exists() else {}
    added = 0
    for rec in incoming:
        if rec["document_id"] not in existing:
            existing[rec["document_id"]] = rec
            added += 1
    write_jsonl(path, sorted(existing.values(), key=lambda r: (r["published_at"], r["document_id"])))
    return added


def collect(*, symbols: list[str], published_after: datetime, output_dir: Path, key: str,
            limit: int, max_requests: int, pause: float) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents_path = output_dir / "documents.jsonl"
    coverage_path = output_dir / "coverage.json"
    coverage = {"provider": "marketaux", "symbols": {}, "requests": 0,
                "published_after": iso_utc(published_after), "updated_at": None}
    universe = set(symbols)
    for index, symbol in enumerate(symbols):
        if coverage["requests"] >= max_requests:
            coverage["symbols"][symbol] = {"status": "skipped_budget"}
            continue
        params = {"symbols": symbol, "filter_entities": "true", "language": "en",
                  "published_after": published_after.strftime("%Y-%m-%dT%H:%M"),
                  "limit": str(limit), "api_token": key}
        try:
            response = fetch_json(f"{MARKETAUX_URL}?{urlencode(params)}",
                                  headers={"User-Agent": USER_AGENT}, timeout=30)
            coverage["requests"] += 1
            articles = response.get("data") or []
            records = [r for r in (_record(a, universe, iso_utc(utc_now())) for a in articles) if r]
            added = _save_documents(documents_path, records)
            coverage["symbols"][symbol] = {
                "status": "collected" if records else "no_results",
                "articles": len(articles), "matched": len(records), "added": added,
            }
        except Exception:
            coverage["requests"] += 1  # a failed call still consumes budget
            coverage["symbols"][symbol] = {"status": "failed"}
        coverage["updated_at"] = iso_utc(utc_now())
        atomic_write_json(coverage_path, coverage)
        if pause and index < len(symbols) - 1:
            time.sleep(pause)
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DATA_DIR / ".env")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--days", type=int, default=3, help="Look back this many days for news")
    parser.add_argument("--limit", type=int, default=3, help="Articles per request (free tier max 3)")
    parser.add_argument("--max-requests", type=int, default=FREE_DAILY_LIMIT - 5,
                        help="Stop after this many requests to stay under the daily budget")
    parser.add_argument("--pause", type=float, default=1.0, help="Seconds between requests")
    parser.add_argument("--symbols", help="Comma-separated subset; default is the whole universe")
    args = parser.parse_args(argv)

    load_environment(args.env_file)
    key = os.environ.get("MARKETAUX_SECRET_KEY") or os.environ.get("MARKETAUX_API_KEY")
    if not key:
        parser.error("MARKETAUX_SECRET_KEY is required for Marketaux collection")

    universe = load_universe()
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else sorted(universe))
    published_after = datetime.now(timezone.utc) - timedelta(days=args.days)

    coverage = collect(symbols=symbols, published_after=published_after, output_dir=args.output_dir,
                       key=key, limit=args.limit, max_requests=args.max_requests, pause=args.pause)
    statuses: dict[str, int] = {}
    for info in coverage["symbols"].values():
        statuses[info["status"]] = statuses.get(info["status"], 0) + 1
    total_docs = len(read_jsonl(args.output_dir / "documents.jsonl"))
    print(f"Marketaux collection: {statuses}; {coverage['requests']} requests; "
          f"{total_docs} total documents.")
    return 1 if statuses.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
