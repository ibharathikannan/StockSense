"""Authenticated forecast inference for the caller's content-selected shortlist."""
from __future__ import annotations
import inspect
from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from app.api.deps import Principal, get_current_principal, get_forecast_service, get_recommendation_service, get_forecast_assessment_service
from app.core.config import Settings, get_settings
from app.schemas.forecast import ForecastSnapshot
from app.services.errors import Conflict, Forbidden
from app.services.recommendations import RecommendationService

router = APIRouter(prefix='/api/forecasts', tags=['forecasts'])

async def _predict(service, tickers):
    if inspect.iscoroutinefunction(service.get_snapshot):
        return await service.get_snapshot(tickers)
    return await run_in_threadpool(service.get_snapshot, tickers)

@router.get('/recommended', response_model=ForecastSnapshot)
async def recommended_forecasts(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
    recommender: RecommendationService = Depends(get_recommendation_service),
    service = Depends(get_forecast_service),
    assessment = Depends(get_forecast_assessment_service),
):
    recommendations = await recommender.for_user(principal.user['id'], settings.recommendations_limit)
    tickers = [item.ticker for item in recommendations]
    if not tickers:
        raise Conflict('No recommendations available for forecasting')
    response.headers['Cache-Control'] = 'no-store'
    snapshot = ForecastSnapshot.model_validate(await _predict(service,tickers))
    return await assessment.enrich(principal.user["id"],snapshot)

def get_selected_recommender(request: Request, settings: Settings = Depends(get_settings)):
    if not settings.forecast_model_dir:
        return None
    from app.repositories.profiles import ProfilesRepository
    from app.repositories.assets import AssetsRepository
    return RecommendationService(ProfilesRepository(request.app.state.db), AssetsRepository(request.app.state.db))

@router.get('', response_model=ForecastSnapshot)
async def selected_forecasts(
    response: Response,
    tickers: str = Query(min_length=1,max_length=1600),
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
    recommender = Depends(get_selected_recommender),
    service = Depends(get_forecast_service),
):
    selected = tickers.split(',')
    # Preserve legacy saved-result selection. Live inference is restricted on
    # the backend to recommendations for this authenticated user's profile.
    if settings.forecast_model_dir:
        recommendations = await recommender.for_user(principal.user['id'],settings.recommendations_limit)
        if not set(selected).issubset({item.ticker for item in recommendations}):
            raise Forbidden('Forecast only tickers selected by your recommendations')
    response.headers['Cache-Control'] = 'no-store'
    return await _predict(service,selected)
