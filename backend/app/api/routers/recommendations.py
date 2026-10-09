from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import Principal, get_current_principal, get_profiles_repo, get_recommendation_service
from app.repositories.profiles import ProfilesRepository
from app.schemas.recommendations import DiscoveryResponse, RecommendationSnapshot
from app.services.recommendations import RecommendationService

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


async def _require_profile(principal: Principal, profiles: ProfilesRepository) -> dict:
    """Recommendations are personalised, so the caller must have completed onboarding."""
    profile = await profiles.get(principal.user["id"])
    if not profile:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Complete onboarding to get personalised recommendations.")
    return profile


@router.get("", response_model=DiscoveryResponse)
async def discovery(
    principal: Principal = Depends(get_current_principal),
    service: RecommendationService = Depends(get_recommendation_service),
    profiles: ProfilesRepository = Depends(get_profiles_repo),
) -> DiscoveryResponse:
    """The personalised research set for the signed-in user, plus a diversification note."""
    profile = await _require_profile(principal, profiles)
    return await service.get_discovery(profile)


@router.get("/{ticker}", response_model=RecommendationSnapshot)
async def detail(
    ticker: str = Path(min_length=1, max_length=10),
    principal: Principal = Depends(get_current_principal),
    service: RecommendationService = Depends(get_recommendation_service),
    profiles: ProfilesRepository = Depends(get_profiles_repo),
) -> RecommendationSnapshot:
    """The full research snapshot for one asset at the user's risk tier (company detail page)."""
    profile = await _require_profile(principal, profiles)
    return await service.get_detail(ticker, profile)
