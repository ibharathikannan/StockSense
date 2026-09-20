from __future__ import annotations

import re
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

    async def count_matching(self, sectors: list[str], themes: list[str]) -> int:
        """Recommendable assets whose sector is in `sectors` or that carry any of `themes`."""
        conditions: list[dict[str, Any]] = []
        if sectors:
            conditions.append({"sector": {"$in": sectors}})
        if themes:
            conditions.append({"themes": {"$in": themes}})
        if not conditions:
            return 0
        return await self._col.count_documents({"recommendation_eligible": True, "$or": conditions})

    async def eligible_tickers(self, tickers: list[str]) -> set[str]:
        """Which of `tickers` exist and may be recommended/followed."""
        cursor = self._col.find({"ticker": {"$in": tickers}, "recommendation_eligible": True}, {"ticker": 1})
        return {doc["ticker"] async for doc in cursor}

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Type-ahead: ticker prefix or name substring, case-insensitive."""
        pattern = re.escape(query.strip())
        cursor = (
            self._col.find(
                {
                    "recommendation_eligible": True,
                    "$or": [
                        {"ticker": {"$regex": f"^{pattern}", "$options": "i"}},
                        {"name": {"$regex": pattern, "$options": "i"}},
                    ],
                },
                {"_id": 0, "ticker": 1, "name": 1, "asset_type": 1, "sector": 1},
            )
            .sort("ticker", 1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)
