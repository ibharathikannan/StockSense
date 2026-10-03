"""Load data/processed/asset_profiles.json into the PostgreSQL `assets` table.

Idempotent: assets are upserted by ticker, so re-running after refreshing the data
updates them in place. Run from the backend/ folder with the venv active:

    python -m scripts.import_assets                # default file
    python -m scripts.import_assets path/to/file.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.postgres import create_pool, ensure_schema
from app.repositories.assets import AssetsRepository

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "asset_profiles.json"


async def main(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python data/build_asset_profiles.py` first.")
    assets = json.loads(path.read_text(encoding="utf-8"))
    if not assets:
        raise SystemExit(f"{path} contains no assets.")

    settings = get_settings()
    pool = await create_pool(settings)
    try:
        await ensure_schema(pool)  # makes sure the assets table exists
        repo = AssetsRepository(pool)
        inserted, updated = await repo.upsert_many(assets)
        print(f"Database '{settings.postgres_db}' on {settings.postgres_host}, table 'assets'")
        print(f"  read {len(assets)} | inserted {inserted} | updated {updated} | total now {await repo.count()}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH))
