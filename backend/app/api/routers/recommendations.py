from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from app.api.deps import Principal, get_current_principal, get_recommendation_service
from app.core.config import MAX_RECOMMENDATIONS, Settings, get_settings
from app.schemas.recommendation import RecommendationOut
from app.services.recommendations import RecommendationService

# Self-service: every signed-in user gets suggestions for their own profile only.
router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("", response_model=list[RecommendationOut])
async def list_recommendations(
    limit: int | None = Query(
        None, ge=1, le=MAX_RECOMMENDATIONS, description="How many to return; defaults to the RECOMMENDATIONS_LIMIT setting"
    ),
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
    service: RecommendationService = Depends(get_recommendation_service),
) -> list[dict]:
    """Assets that match the caller's interests, followed tickers and risk level, best first, with reasons."""
    count = limit if limit is not None else settings.recommendations_limit
    return [asdict(r) for r in await service.for_user(principal.user["id"], count)]
