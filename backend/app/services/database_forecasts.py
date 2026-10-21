"""Serve the latest atomically imported PostgreSQL forecast batch."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Callable

from app.schemas.forecast import ForecastItem, ForecastSnapshot
from app.services.errors import BadRequest
from app.services.forecasts import ForecastUnavailable


class DatabaseForecastService:
    def __init__(self, repository, *, now: Callable[[], datetime] | None = None):
        self._repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def get_snapshot(self, tickers: list[str]) -> ForecastSnapshot:
        if (
            not isinstance(tickers, list)
            or not 1 <= len(tickers) <= 90
            or len(set(tickers)) != len(tickers)
            or any(
                not isinstance(ticker, str)
                or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,15}", ticker)
                for ticker in tickers
            )
        ):
            raise BadRequest("Provide 1 to 90 distinct valid selected tickers")

        result = await self._repository.read_latest(tickers)
        if result is None:
            raise ForecastUnavailable()
        batch, rows = result
        now = self._now().astimezone(timezone.utc)
        if batch["generated_at"].tzinfo is None or batch["generated_at"] > now:
            raise ForecastUnavailable()

        available = {}
        try:
            for row in rows:
                age = (now.date() - row["forecast_origin"]).days
                if age < 0:
                    raise ValueError("Forecast origin is in the future")
                item = ForecastItem(
                    ticker=row["ticker"],
                    date=row["forecast_origin"],
                    predicted_return_10d=row["predicted_return_10d"],
                    lower_return=row["lower_return"],
                    upper_return=row["upper_return"],
                    uncertainty_width_pp=row["uncertainty_width_pp"],
                    nominal_coverage=batch["nominal_coverage"],
                    stale_snapshot=age > 7,
                    data_age_calendar_days=age,
                    calibration_latest_outcome=batch["calibration_latest_outcome"],
                )
                available[item.ticker] = item
            return ForecastSnapshot(
                model=batch["model"],
                as_of=batch["as_of"],
                generated_at=batch["generated_at"],
                horizon_sessions=batch["horizon_sessions"],
                nominal_coverage=batch["nominal_coverage"],
                empirical_coverage=batch["empirical_coverage"],
                evaluation_mae_pp=batch["evaluation_mae_pp"],
                direction_accuracy_pct=batch["direction_accuracy_pct"],
                always_up_accuracy_pct=batch["always_up_accuracy_pct"],
                forecasts=[available[ticker] for ticker in tickers if ticker in available],
                selected_tickers=tickers,
                unavailable_tickers=[ticker for ticker in tickers if ticker not in available],
                status="experimental_offline_snapshot",
                source_mode="saved_results",
            )
        except (KeyError, TypeError, ValueError):
            raise ForecastUnavailable() from None
