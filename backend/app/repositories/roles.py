from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RolesRepository:
    """Roles are identified by their unique, immutable ``name``.

    ``create`` raises ``pymongo.errors.DuplicateKeyError`` on a name clash.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db["roles"]

    async def get(self, name: str) -> dict[str, Any] | None:
        return await self._col.find_one({"name": name})

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self._col.find().sort([("is_system", -1), ("name", 1)]).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self) -> int:
        return await self._col.count_documents({})

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        permissions: list[str],
        is_system: bool = False,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        doc = {
            "name": name,
            "description": description,
            "permissions": sorted(set(permissions)),
            "is_system": is_system,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        result = await self._col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def update(self, name: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        if "permissions" in fields:
            fields = {**fields, "permissions": sorted(set(fields["permissions"]))}
        fields = {**fields, "updated_at": _now()}
        return await self._col.find_one_and_update({"name": name}, {"$set": fields}, return_document=ReturnDocument.AFTER)

    async def delete(self, name: str) -> bool:
        return (await self._col.delete_one({"name": name})).deleted_count > 0
