from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Principal, get_current_principal, get_dashboard_service
from app.core.config import Settings, get_settings
from app.schemas.dashboard import DashboardOut
from app.services.dashboard import DashboardService

# Self-service: every signed-in user sees their own dashboard only.
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
async def get_dashboard(
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
    service: DashboardService = Depends(get_dashboard_service),
) -> dict:
    """The caller's profile summary, watchlist and suggestions, with the risk numbers the charts need."""
    return await service.for_user(principal.user["id"], settings.recommendations_limit)
