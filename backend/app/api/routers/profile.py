from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Principal, get_current_principal, get_profile_service
from app.schemas.profile import ProfileIn, ProfileOptions, ProfileOut
from app.services.profiles import ProfileService

# Self-service: every signed-in user manages their own profile, so no admin permission is needed.
router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/options", response_model=ProfileOptions)
async def profile_options(
    _: Principal = Depends(get_current_principal),
    service: ProfileService = Depends(get_profile_service),
) -> dict:
    """Choices for the onboarding form (risk levels, interests with asset counts, asset types)."""
    return await service.options()


@router.get("", response_model=ProfileOut | None)
async def get_profile(
    principal: Principal = Depends(get_current_principal),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileOut | None:
    """The caller's profile, or null if they haven't completed onboarding yet."""
    doc = await service.get(principal.user["_id"])
    return ProfileOut.from_doc(doc) if doc else None


@router.put("", response_model=ProfileOut)
async def save_profile(
    payload: ProfileIn,
    principal: Principal = Depends(get_current_principal),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileOut:
    """Create the profile (completing onboarding) or replace its answers."""
    doc = await service.save(
        principal.user["_id"],
        risk_level=payload.risk_level,
        interests=payload.interests,
        asset_types=payload.asset_types,
        followed_tickers=payload.followed_tickers,
    )
    return ProfileOut.from_doc(doc)
