from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.db.mongo import to_object_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UsersRepository:
    """Thin data-access layer over the ``users`` collection.

    ``create`` raises ``pymongo.errors.DuplicateKeyError`` if the email exists
    (unique index) — callers map that to a 409.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db["users"]

    @staticmethod
    def _search_filter(search: str | None) -> dict[str, Any]:
        if not search or not search.strip():
            return {}
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        return {"$or": [{"email": pattern}, {"full_name": pattern}]}

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        oid = to_object_id(user_id)
        return await self._col.find_one({"_id": oid}) if oid else None

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        return await self._col.find_one({"email": email.strip().lower()})

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        password_hash: str,
        role: str,
        is_active: bool = True,
    ) -> dict[str, Any]:
        now = _now()
        doc = {
            "email": email.strip().lower(),
            "full_name": full_name.strip(),
            "password_hash": password_hash,
            "role": role,
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }
        result = await self._col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def list(self, *, skip: int, limit: int, search: str | None = None) -> list[dict[str, Any]]:
        cursor = self._col.find(self._search_filter(search)).sort("created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self, search: str | None = None) -> int:
        return await self._col.count_documents(self._search_filter(search))

    async def update(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        oid = to_object_id(user_id)
        if oid is None:
            return None
        fields = {**fields, "updated_at": _now()}
        return await self._col.find_one_and_update({"_id": oid}, {"$set": fields}, return_document=ReturnDocument.AFTER)

    async def touch_last_login(self, user_id: Any) -> None:
        await self._col.update_one({"_id": user_id}, {"$set": {"last_login_at": _now()}})

    async def delete(self, user_id: str) -> bool:
        oid = to_object_id(user_id)
        if oid is None:
            return False
        return (await self._col.delete_one({"_id": oid})).deleted_count > 0

    async def count_total(self) -> int:
        return await self._col.count_documents({})

    async def count_active_with_role(self, role: str) -> int:
        return await self._col.count_documents({"role": role, "is_active": True})

    async def count_with_role(self, role: str) -> int:
        return await self._col.count_documents({"role": role})

    async def counts_by_role(self) -> dict[str, int]:
        rows = await self._col.aggregate([{"$group": {"_id": "$role", "n": {"$sum": 1}}}])
        return {row["_id"]: row["n"] async for row in rows}
