"""Persist and read immutable offline forecast batches in PostgreSQL."""
from __future__ import annotations

import uuid

import asyncpg

from app.schemas.forecast import ForecastSnapshot


class DatabaseForecastRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def import_snapshot(self, snapshot: ForecastSnapshot, *, source_sha256: str) -> tuple[uuid.UUID, bool]:
        """Insert one complete batch, returning ``(batch_id, inserted)``.

        Re-importing the exact source is idempotent. A conflicting batch identity
        with different bytes is rejected instead of silently replacing history.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id, source_sha256 FROM forecast_batches WHERE model = $1 AND generated_at = $2",
                snapshot.model,
                snapshot.generated_at,
            )
            if existing:
                if existing["source_sha256"] != source_sha256:
                    raise ValueError("Forecast batch identity already exists with different source bytes")
                count = await conn.fetchval(
                    "SELECT count(*) FROM forecast_results WHERE batch_id = $1", existing["id"]
                )
                if count != len(snapshot.forecasts):
                    raise ValueError("Existing forecast batch is incomplete")
                return existing["id"], False

            batch_id = await conn.fetchval(
                """
                INSERT INTO forecast_batches (
                    source_sha256, model, as_of, generated_at, horizon_sessions,
                    nominal_coverage, empirical_coverage, evaluation_mae_pp,
                    direction_accuracy_pct, always_up_accuracy_pct,
                    calibration_latest_outcome
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                RETURNING id
                """,
                source_sha256,
                snapshot.model,
                snapshot.as_of,
                snapshot.generated_at,
                snapshot.horizon_sessions,
                snapshot.nominal_coverage,
                snapshot.empirical_coverage,
                snapshot.evaluation_mae_pp,
                snapshot.direction_accuracy_pct,
                snapshot.always_up_accuracy_pct,
                snapshot.forecasts[0].calibration_latest_outcome,
            )
            await conn.executemany(
                """
                INSERT INTO forecast_results (
                    batch_id, ticker, forecast_origin, predicted_return_10d,
                    lower_return, upper_return, uncertainty_width_pp
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                [
                    (
                        batch_id,
                        item.ticker,
                        item.date,
                        item.predicted_return_10d,
                        item.lower_return,
                        item.upper_return,
                        item.uncertainty_width_pp,
                    )
                    for item in snapshot.forecasts
                ],
            )
            return batch_id, True

    async def read_latest(self, tickers: list[str]) -> tuple[dict, list[dict]] | None:
        async with self._pool.acquire() as conn:
            batch = await conn.fetchrow(
                """
                SELECT id, model, as_of, generated_at, horizon_sessions,
                       nominal_coverage, empirical_coverage, evaluation_mae_pp,
                       direction_accuracy_pct, always_up_accuracy_pct,
                       calibration_latest_outcome
                FROM forecast_batches
                ORDER BY as_of DESC, generated_at DESC
                LIMIT 1
                """
            )
            if batch is None:
                return None
            rows = await conn.fetch(
                """
                SELECT ticker, forecast_origin, predicted_return_10d,
                       lower_return, upper_return, uncertainty_width_pp
                FROM forecast_results
                WHERE batch_id = $1 AND ticker = ANY($2::text[])
                """,
                batch["id"],
                tickers,
            )
        return dict(batch), [dict(row) for row in rows]
