from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import Principal, get_assets_repo, get_current_principal
from app.repositories.assets import AssetsRepository
from app.schemas.profile import AssetSummary

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/search", response_model=list[AssetSummary])
async def search_assets(
    q: str = Query(min_length=1, max_length=50, description="Ticker prefix or part of the name"),
    limit: int = Query(8, ge=1, le=20),
    _: Principal = Depends(get_current_principal),
    assets: AssetsRepository = Depends(get_assets_repo),
) -> list[dict]:
    """Type-ahead for picking tickers to follow."""
    return await assets.search(q, limit)
