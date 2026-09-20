"""Load data/processed/asset_profiles.json into the MongoDB `assets` collection.

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
from app.db.mongo import create_client, ensure_indexes, get_database
from app.repositories.assets import AssetsRepository

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "asset_profiles.json"


async def main(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python data/build_asset_profiles.py` first.")
    assets = json.loads(path.read_text(encoding="utf-8"))
    if not assets:
        raise SystemExit(f"{path} contains no assets.")

    settings = get_settings()
    client = create_client(settings)
    try:
        db = get_database(client, settings)
        await ensure_indexes(db)  # makes sure the unique ticker index exists
        repo = AssetsRepository(db)
        inserted, updated = await repo.upsert_many(assets)
        print(f"Database '{settings.mongo_db_name}', collection 'assets'")
        print(f"  read {len(assets)} | inserted {inserted} | updated {updated} | total now {await repo.count()}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH))
