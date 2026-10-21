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

-- Immutable offline forecast uploads. A batch and all of its ticker rows are
-- inserted in one transaction so readers never observe a partial monthly run.
CREATE TABLE IF NOT EXISTS forecast_batches (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_sha256              TEXT NOT NULL UNIQUE CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    model                      TEXT NOT NULL,
    as_of                      DATE NOT NULL,
    generated_at               TIMESTAMPTZ NOT NULL,
    horizon_sessions           SMALLINT NOT NULL CHECK (horizon_sessions = 10),
    nominal_coverage           DOUBLE PRECISION NOT NULL CHECK (nominal_coverage > 0 AND nominal_coverage < 1),
    empirical_coverage         DOUBLE PRECISION CHECK (empirical_coverage >= 0 AND empirical_coverage <= 1),
    evaluation_mae_pp          DOUBLE PRECISION CHECK (evaluation_mae_pp >= 0),
    direction_accuracy_pct     DOUBLE PRECISION CHECK (direction_accuracy_pct >= 0 AND direction_accuracy_pct <= 100),
    always_up_accuracy_pct     DOUBLE PRECISION CHECK (always_up_accuracy_pct >= 0 AND always_up_accuracy_pct <= 100),
    calibration_latest_outcome DATE NOT NULL,
    imported_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model, generated_at)
);

CREATE TABLE IF NOT EXISTS forecast_results (
    batch_id                    UUID NOT NULL REFERENCES forecast_batches (id) ON DELETE CASCADE,
    ticker                      TEXT NOT NULL,
    forecast_origin             DATE NOT NULL,
    predicted_return_10d        DOUBLE PRECISION NOT NULL,
    lower_return                DOUBLE PRECISION NOT NULL,
    upper_return                DOUBLE PRECISION NOT NULL,
    uncertainty_width_pp        DOUBLE PRECISION NOT NULL CHECK (uncertainty_width_pp >= 0),
    PRIMARY KEY (batch_id, ticker),
    CHECK (lower_return <= predicted_return_10d AND predicted_return_10d <= upper_return)
);
CREATE INDEX IF NOT EXISTS forecast_batches_latest_idx
    ON forecast_batches (as_of DESC, generated_at DESC);
CREATE INDEX IF NOT EXISTS forecast_results_ticker_idx
    ON forecast_results (ticker, batch_id);
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
