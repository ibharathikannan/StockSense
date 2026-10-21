"""Database-backed forecast service and importer helpers, without a live DB."""
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.database_forecasts import DatabaseForecastService
from app.services.errors import BadRequest
from app.services.forecasts import ForecastUnavailable
from app.api.deps import get_forecast_service


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


class Repository:
    result = None

    async def read_latest(self, tickers):
        self.tickers = tickers
        return self.result


def batch(**changes):
    value = {
        "model": "XGBoost grid=3 rounds=150",
        "as_of": date(2026, 9, 18),
        "generated_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
        "horizon_sessions": 10,
        "nominal_coverage": 0.9,
        "empirical_coverage": 0.8693,
        "evaluation_mae_pp": 5.789,
        "direction_accuracy_pct": 52.67,
        "always_up_accuracy_pct": 52.67,
        "calibration_latest_outcome": date(2025, 12, 31),
    }
    value.update(changes)
    return value


def row(ticker="AAPL", **changes):
    value = {
        "ticker": ticker,
        "forecast_origin": date(2026, 9, 18),
        "predicted_return_10d": 0.0048,
        "lower_return": -0.066,
        "upper_return": 0.0756,
        "uncertainty_width_pp": 14.16,
    }
    value.update(changes)
    return value


def test_latest_database_batch_preserves_requested_order_and_missing_tickers():
    repository = Repository()
    repository.result = batch(), [row("AAPL"), row("MSFT")]
    service = DatabaseForecastService(repository, now=lambda: NOW)
    result = asyncio.run(service.get_snapshot(["MSFT", "GEV", "AAPL"]))
    assert repository.tickers == ["MSFT", "GEV", "AAPL"]
    assert [item.ticker for item in result.forecasts] == ["MSFT", "AAPL"]
    assert result.unavailable_tickers == ["GEV"]
    assert result.forecasts[0].stale_snapshot is True
    assert result.forecasts[0].data_age_calendar_days == 33
    assert result.empirical_coverage == 0.8693
    assert result.source_mode == "saved_results"


def test_missing_or_invalid_database_batch_fails_closed():
    repository = Repository()
    service = DatabaseForecastService(repository, now=lambda: NOW)
    with pytest.raises(ForecastUnavailable):
        asyncio.run(service.get_snapshot(["AAPL"]))
    repository.result = batch(generated_at=datetime(2026, 10, 22, tzinfo=timezone.utc)), [row()]
    with pytest.raises(ForecastUnavailable):
        asyncio.run(service.get_snapshot(["AAPL"]))
    repository.result = batch(), [row(uncertainty_width_pp=1)]
    with pytest.raises(ForecastUnavailable):
        asyncio.run(service.get_snapshot(["AAPL"]))


def test_database_service_rejects_invalid_ticker_selections():
    service = DatabaseForecastService(Repository(), now=lambda: NOW)
    for tickers in ([], ["AAPL", "AAPL"], ["aapl"], ["AAPL;DROP"]):
        with pytest.raises(BadRequest):
            asyncio.run(service.get_snapshot(tickers))


def test_dependency_defaults_to_database_when_local_overrides_are_unset():
    pool = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=pool)))
    settings = SimpleNamespace(forecast_model_dir=None, forecast_results_dir=None)
    service = get_forecast_service(request, settings)
    assert isinstance(service, DatabaseForecastService)
    assert service._repository._pool is pool
