from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase


class ProfilesRepository:
    """Investor profiles: at most one document per user (unique index on ``user_id``)."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db["profiles"]

    async def get(self, user_id: ObjectId) -> dict[str, Any] | None:
        return await self._col.find_one({"user_id": user_id})

    async def upsert(self, user_id: ObjectId, data: dict[str, Any]) -> dict[str, Any]:
        """Create the profile, or replace its answers. ``completed_at`` is set once, on first save."""
        now = datetime.now(timezone.utc)
        return await self._col.find_one_and_update(
            {"user_id": user_id},
            {"$set": {**data, "updated_at": now}, "$setOnInsert": {"created_at": now, "completed_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    async def delete_for_user(self, user_id: ObjectId) -> None:
        await self._col.delete_one({"user_id": user_id})
