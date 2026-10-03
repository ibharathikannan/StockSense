from __future__ import annotations

import json
import uuid

import asyncpg

from app.core.config import Settings

# Idempotent DDL, run on every startup. Add new tables here (CREATE ... IF NOT EXISTS),
# and keep changes additive: there is no migration tool, so existing tables are never altered.
SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    name        TEXT PRIMARY KEY,
    description TEXT,
    permissions TEXT[] NOT NULL DEFAULT '{}',
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL REFERENCES roles (name),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);

CREATE TABLE IF NOT EXISTS assets (
    ticker                  TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    asset_type              TEXT NOT NULL,
    category                TEXT,
    sector                  TEXT NOT NULL,
    themes                  TEXT[] NOT NULL DEFAULT '{}',
    recommendation_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    forecast_eligible       BOOLEAN NOT NULL DEFAULT FALSE,
    history_note            TEXT,
    as_of                   DATE,
    risk                    JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- At most one investor profile per user; it goes away with the user.
CREATE TABLE IF NOT EXISTS profiles (
    user_id          UUID PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    risk_level       TEXT NOT NULL,
    interests        TEXT[] NOT NULL,
    asset_types      TEXT NOT NULL,
    followed_tickers TEXT[] NOT NULL,
    completed_at     TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL
);
"""

# Arbitrary constant: serialises schema creation when several processes start at once
# (concurrent CREATE ... IF NOT EXISTS can otherwise fail with a unique violation).
_SCHEMA_LOCK_KEY = 0x5354_4F43


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password or None,
        ssl=settings.postgres_sslmode,
        timeout=10,
        init=_init_connection,
    )


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(SCHEMA)


def like_pattern(text: str) -> str:
    """Substring pattern for (I)LIKE, with the user's own wildcards escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def to_uuid(value: object) -> uuid.UUID | None:
    """Parse an id from a URL or token; None if it isn't a valid UUID (callers treat that as 'not found')."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
