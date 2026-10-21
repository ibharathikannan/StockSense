"""Validate and atomically import an offline forecast export into PostgreSQL.

Run from ``backend/`` with its environment configured:

    python -m scripts.import_forecasts \
      ../data/artifacts/forecasting/walkforward-xgboost-2026-09-18

The directory must contain the matching ``forecasts.csv`` and ``report.json``.
No model file is loaded, no market data is downloaded, and prior batches remain
available for audit. Re-importing identical source files is a safe no-op.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.db.postgres import create_pool, ensure_schema
from app.repositories.database_forecasts import DatabaseForecastRepository
from app.repositories.forecasts import ForecastRepository
from app.services.forecasts import ForecastService


def source_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in ("forecasts.csv", "report.json"):
        payload = (directory / name).read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def load_snapshot(directory: Path):
    rows, _ = ForecastRepository(directory).read()
    tickers = [row["ticker"] for row in rows]
    return ForecastService(
        ForecastRepository(directory), now=lambda: datetime.now(timezone.utc)
    ).get_snapshot(tickers)


async def import_directory(directory: Path) -> tuple[int, bool]:
    directory = directory.expanduser().resolve()
    snapshot = load_snapshot(directory)
    digest = source_digest(directory)
    settings = get_settings()
    pool = await create_pool(settings)
    try:
        await ensure_schema(pool)
        _, inserted = await DatabaseForecastRepository(pool).import_snapshot(
            snapshot, source_sha256=digest
        )
    finally:
        await pool.close()
    return len(snapshot.forecasts), inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("forecast_dir", type=Path)
    args = parser.parse_args()
    try:
        count, inserted = asyncio.run(import_directory(args.forecast_dir))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Forecast import failed: {exc}") from None
    action = "imported" if inserted else "already present"
    print(f"Forecast batch {action}: {count} ticker rows")


if __name__ == "__main__":
    main()
