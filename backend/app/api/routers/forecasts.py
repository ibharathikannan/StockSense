"""Forecast results for an explicit content-selected ticker shortlist."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Principal, get_current_principal, get_forecast_service
from app.schemas.forecast import ForecastSnapshot
from app.services.forecasts import ForecastService

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


@router.get("", response_model=ForecastSnapshot)
def selected_forecasts(
    response: Response,
    tickers: str = Query(min_length=1, max_length=1600,
                         description="Comma-separated tickers selected by the content recommender"),
    _: Principal = Depends(get_current_principal),
    service: ForecastService = Depends(get_forecast_service),
) -> ForecastSnapshot:
    # A synchronous route runs file reading/validation in FastAPI's threadpool.
    # The authenticated browser explicitly supplies a shortlist; there is no
    # endpoint that silently returns the entire forecasting universe.
    response.headers["Cache-Control"] = "no-store"
    return service.get_snapshot(tickers.split(","))
