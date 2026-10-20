"""Map forecast units and caller context into deterministic research rules."""
from __future__ import annotations
from datetime import date, datetime, timezone
import math
import uuid

from app.rule_engine.rule_based_engine import evaluate_stock_stance, normalize_risk_profile, VOLATILITY_LIMITS
from app.schemas.forecast import ForecastSnapshot, RuleInputs
from app.services.errors import Conflict
from app.services.recommendations import PROFILE_REQUIRED


class ForecastAssessmentService:
    def __init__(self, profiles, assets):
        self.profiles, self.assets = profiles, assets

    async def enrich(self, user_id: uuid.UUID, snapshot: ForecastSnapshot) -> ForecastSnapshot:
        result = snapshot.model_copy(deep=True)
        if not result.forecasts:
            return result
        profile = await self.profiles.get(user_id)
        if not profile:
            raise Conflict(PROFILE_REQUIRED)
        catalogue = {a['ticker']: a for a in await self.assets.list_recommendable()}
        risk_level = profile.get('risk_level')
        valid_risk = isinstance(risk_level,str) and normalize_risk_profile(risk_level) in VOLATILITY_LIMITS
        today = datetime.now(timezone.utc).date()
        for item in result.forecasts:
            asset = catalogue.get(item.ticker,{})
            risk_data = asset.get('risk')
            raw_vol = risk_data.get('volatility_1y') if isinstance(risk_data,dict) else None
            try:
                volatility = float(raw_vol) if raw_vol is not None and not isinstance(raw_vol,bool) else None
                if volatility is not None and (not math.isfinite(volatility) or volatility<0):
                    volatility = None
            except (TypeError,ValueError):
                volatility = None
            try:
                raw_date = asset.get('as_of')
                volatility_as_of = date.fromisoformat(raw_date) if isinstance(raw_date,str) else raw_date
                if not isinstance(volatility_as_of,date) or volatility_as_of>today:
                    volatility_as_of = None
            except ValueError:
                volatility_as_of = None
            # No dated runtime sentiment source is connected. Missing stays None;
            # it must not masquerade as measured neutral sentiment.
            item.rule_inputs = RuleInputs(
                forecast_return=item.predicted_return_10d*100,
                prediction_interval_width=item.uncertainty_width_pp,
                volatility=volatility,volatility_as_of=volatility_as_of,
                sentiment_score=None,user_risk_profile=risk_level if valid_risk else None)
            if volatility is None or not valid_risk:
                item.assessment_status='unavailable'
                item.stance=None
                item.decision_trace=['Research assessment unavailable: valid one-year volatility and a saved risk profile are required.']
                continue
            decision = evaluate_stock_stance(
                forecast_return=item.rule_inputs.forecast_return,
                volatility=volatility,sentiment_score=None,
                prediction_interval_width=item.rule_inputs.prediction_interval_width,
                user_risk_profile=risk_level)
            item.stance=decision['stance']
            item.decision_trace=list(decision['decision_trace'])
            historical = item.stale_snapshot or (volatility_as_of is not None and (today-volatility_as_of).days>7)
            item.assessment_status='historical' if historical else 'evaluated'
            if historical:
                item.decision_trace.insert(0,'Historical research assessment: inputs are dated snapshots, not a current-market assessment.')
            if volatility_as_of is None:
                item.decision_trace.append('The one-year volatility measurement date is unavailable.')
        return result
