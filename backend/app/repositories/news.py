from __future__ import annotations

import json
from typing import Any

import asyncpg

# Shared data not migrated into this database (e.g. a local or test instance).
_MISSING = (asyncpg.InvalidSchemaNameError, asyncpg.UndefinedTableError)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class NewsRepository:
    """Read-only access to the news and news sentiment the offline pipeline stores in the shared
    data schema: articles in `rag_chunks` (frozen corpus + nightly Marketaux `extra_chunks`, which
    also carries each article's Marketaux sentiment) and the older Alpha Vantage aggregates in
    `prepared_sentiment_aggregates`. Nothing here collects or recalculates anything."""

    def __init__(self, pool: asyncpg.Pool, schema: str) -> None:
        self._pool = pool
        # Validated as a plain identifier in Settings, so it is safe to interpolate.
        self._schema = schema

    async def _has_marketaux_sentiment(self) -> bool:
        # The nightly embedder adds this column on its first run with sentiment persistence.
        return bool(await self._pool.fetchval(
            """SELECT 1 FROM information_schema.columns WHERE table_schema = $1
               AND table_name = 'extra_chunks' AND column_name = 'provider_sentiment'""",
            self._schema,
        ))

    async def latest_articles(self, ticker: str, limit: int) -> list[dict[str, Any]]:
        """The newest news articles for a ticker, one row per article, newest first."""
        s = self._schema
        try:
            sentiment = "x.provider_sentiment" if await self._has_marketaux_sentiment() else "NULL::jsonb"
            rows = await self._pool.fetch(
                f"""SELECT * FROM (
                        SELECT DISTINCT ON (r.document_id) r.document_id, r.title, r.source_url,
                               r.published_at, r.text, {sentiment} AS provider_sentiment
                        FROM "{s}".rag_chunks r
                        LEFT JOIN "{s}".extra_chunks x ON x.chunk_id = r.chunk_id
                        WHERE r.source_type = 'news' AND r.tickers @> ARRAY[$1]::text[]   -- uses the GIN index
                          AND r.published_at <= now()
                        ORDER BY r.document_id, r.published_at DESC
                    ) articles
                    ORDER BY published_at DESC LIMIT $2""",
                ticker.strip().upper(), limit,
            )
        except _MISSING:
            return []
        return [{**dict(r), "provider_sentiment": _json(r["provider_sentiment"])} for r in rows]

    async def marketaux_scores(self, ticker: str, limit: int = 200) -> list[dict[str, Any]]:
        """The ticker's own Marketaux sentiment per stored article, newest first."""
        try:
            if not await self._has_marketaux_sentiment():
                return []
            rows = await self._pool.fetch(
                f"""SELECT published_at, (provider_sentiment -> $1 ->> 'score')::float AS score
                    FROM "{self._schema}".extra_chunks
                    WHERE provider = 'marketaux' AND provider_sentiment ? $1
                      AND published_at <= now()
                    ORDER BY published_at DESC LIMIT $2""",
                ticker.strip().upper(), limit,
            )
        except _MISSING:
            return []
        return [dict(r) for r in rows if r["score"] is not None]

    async def alpha_vantage_aggregate(self, ticker: str) -> dict[str, Any] | None:
        try:
            raw = await self._pool.fetchval(
                f"""SELECT payload FROM "{self._schema}".prepared_sentiment_aggregates
                    WHERE UPPER(ticker) = UPPER($1) ORDER BY as_of DESC LIMIT 1""",
                ticker.strip(),
            )
        except _MISSING:
            return None
        return _json(raw) if raw is not None else None
