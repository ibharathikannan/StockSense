from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase


class AssetsRepository:
    """The recommendable stocks/ETFs (one document per ticker, loaded from data/asset_universe.csv)."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db["assets"]

    async def upsert_many(self, assets: list[dict[str, Any]]) -> tuple[int, int]:
        """Insert new tickers and update existing ones. Returns (inserted, updated); safe to re-run."""
        now = datetime.now(timezone.utc)
        operations = [
            UpdateOne(
                {"ticker": asset["ticker"]},
                {"$set": {**asset, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            for asset in assets
        ]
        result = await self._col.bulk_write(operations, ordered=False)
        return result.upserted_count, result.modified_count

    async def count(self) -> int:
        return await self._col.count_documents({})
