from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Principal, get_assets_repo, get_current_principal
from app.repositories.assets import AssetsRepository
from app.rule_engine.rule_based_engine import evaluate_stock_stance
from app.schemas.profile import AssetSummary, AssetEvaluationRequest, AssetStanceResponse

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

@router.post("/{ticker}/evaluate", response_model=AssetStanceResponse)
async def evaluate_asset_stance(
    ticker: str,
    payload: AssetEvaluationRequest,
    _: Principal = Depends(get_current_principal),
    assets: AssetsRepository = Depends(get_assets_repo),
) -> AssetStanceResponse:
    """
    Evaluates an asset stance (EXPLORE, MONITOR, CAUTION) using the deterministic rule engine.
    If volatility is omitted in the request, it falls back to the asset's stored profile metric.
    """
    clean_ticker = ticker.strip().upper()
    asset = await assets.get_by_ticker(clean_ticker)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset with ticker '{clean_ticker}' not found."
        )

    effective_volatility = payload.volatility
    if effective_volatility is None:
        effective_volatility = (asset.get("risk") or {}).get("volatility_1y")
    if effective_volatility is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No volatility available for '{clean_ticker}'. Provide it in the request.",
        )
    
    try:
        evaluation = evaluate_stock_stance(
            forecast_return=payload.forecast_return,
            volatility=effective_volatility,
            sentiment_score=payload.sentiment_score,
            prediction_interval_width=payload.prediction_interval_width,
            user_risk_profile=payload.user_risk_profile or "moderate",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return AssetStanceResponse(
        ticker=clean_ticker,
        stance=evaluation["stance"],
        decision_trace=evaluation["decision_trace"],
    )
