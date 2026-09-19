from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings


def create_client(settings: Settings) -> AsyncMongoClient:
    return AsyncMongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=5000)


def get_database(client: AsyncMongoClient, settings: Settings) -> AsyncDatabase:
    return client[settings.mongo_db_name]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Idempotent; run on every startup. Add new collections' indexes here."""
    await db["users"].create_index("email", unique=True)
    await db["roles"].create_index("name", unique=True)


def to_object_id(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None
