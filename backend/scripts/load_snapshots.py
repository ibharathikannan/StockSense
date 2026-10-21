"""Load assembled recommendation snapshots into the application database.

Bridges the offline assembler's JSONL artifact (data/artifacts/snapshots/snapshots.jsonl) into
the `recommendation_snapshots` table the backend serves. Also upserts the asset universe from
`asset_profiles.json` so the snapshot foreign key is satisfied. Idempotent.

    python -m scripts.load_snapshots \
        --snapshots ../data/artifacts/snapshots/snapshots.jsonl \
        --profiles ../data/processed/asset_profiles.json

Connection comes from the backend settings (POSTGRES_* env / .env). Point it at a LOCAL
database — never run exploratory loads against production.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.db.postgres import create_pool, ensure_schema
from app.repositories.assets import AssetsRepository
from app.repositories.recommendations import RecommendationsRepository


def _snapshot_row(snap: dict) -> dict:
    sig = snap["signal"]
    return {
        "ticker": snap["ticker"],
        "risk_profile": sig["risk_profile"],
        "as_of": date.fromisoformat(snap["as_of"][:10]),
        "baseline_stance": sig["baseline_stance"],
        "news_aware_stance": sig["news_aware_stance"],
        "provisional": sig["provisional"],
        "forecast": snap["forecast"],
        "signal_detail": {"decision_trace": sig["decision_trace"], "news_signal": sig["news_signal"]},
        "evidence": snap["evidence"],
        "explanation": snap["explanation"],
    }


async def _run(args) -> None:
    settings = get_settings()
    pool = await create_pool(settings)
    try:
        await ensure_schema(pool)
        assets = json.loads(Path(args.profiles).read_text())
        inserted, updated = await AssetsRepository(pool).upsert_many(assets)
        rows = [_snapshot_row(json.loads(line)) for line in
                Path(args.snapshots).read_text().splitlines() if line.strip()]
        n = await RecommendationsRepository(pool).upsert_many(rows)
        print(f"Assets upserted: {inserted} new / {updated} updated. Snapshots loaded: {n}.")
    finally:
        await pool.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load recommendation snapshots into the app DB.")
    parser.add_argument("--snapshots", default="../data/artifacts/snapshots/snapshots.jsonl")
    parser.add_argument("--profiles", default="../data/processed/asset_profiles.json")
    args = parser.parse_args(argv)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
