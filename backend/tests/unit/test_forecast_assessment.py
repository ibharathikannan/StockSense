"""Forecast-to-rule handoff uses explicit units and authenticated profile context."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.schemas.forecast import ForecastSnapshot
from app.services.forecast_assessment import ForecastAssessmentService
from app.services.errors import Conflict


def snapshot(stale=False):
    today=datetime.now(timezone.utc).date().isoformat()
    return ForecastSnapshot(model='XGBoost',as_of=today,generated_at=datetime.now(timezone.utc),
        nominal_coverage=.9,selected_tickers=['AAPL'],unavailable_tickers=[],
        forecasts=[dict(ticker='AAPL',date=today,predicted_return_10d=.025,
            lower_return=-.025,upper_return=.075,uncertainty_width_pp=10,
            nominal_coverage=.9,stale_snapshot=stale,data_age_calendar_days=20 if stale else 0,
            calibration_latest_outcome='2023-12-29')])

class Profiles:
    calls=[]
    value={'risk_level':'conservative'}
    async def get(self,user):
        self.calls.append(user)
        return self.value

class Assets:
    volatility=.18
    async def list_recommendable(self):
        return [{'ticker':'AAPL','risk':{'volatility_1y':self.volatility},
                 'as_of':datetime.now(timezone.utc).date()}]


def test_units_and_authenticated_profile_are_passed_to_engine(monkeypatch):
    calls=[]
    def engine(**kwargs):
        calls.append(kwargs)
        return {'stance':'MONITOR','decision_trace':['Measured example']}
    monkeypatch.setattr('app.services.forecast_assessment.evaluate_stock_stance',engine)
    profiles=Profiles();profiles.calls=[]
    user=uuid.uuid4();original=snapshot()
    result=asyncio.run(ForecastAssessmentService(profiles,Assets()).enrich(user,original))
    assert profiles.calls==[user]
    assert calls==[dict(forecast_return=2.5,volatility=.18,sentiment_score=None,
                       prediction_interval_width=10,forecast_lower_bound=-2.5,
                       user_risk_profile='conservative')]
    assert result.forecasts[0].stance=='MONITOR'
    assert result.forecasts[0].rule_inputs.forecast_return==2.5
    assert result.forecasts[0].rule_inputs.forecast_lower_bound==-2.5
    assert original.forecasts[0].stance is None


def test_real_engine_cautions_for_risk_mismatch_and_preserves_missing_sentiment():
    assets=Assets();assets.volatility=.4
    result=asyncio.run(ForecastAssessmentService(Profiles(),assets).enrich(uuid.uuid4(),snapshot()))
    item=result.forecasts[0]
    assert item.stance=='CAUTION'
    assert item.rule_inputs.sentiment_score is None
    assert any('Risk mismatch' in line for line in item.decision_trace)
    assert any('Sentiment is unavailable' in line for line in item.decision_trace)
    assert not any('defaulted to neutral' in line for line in item.decision_trace)


def test_real_engine_records_when_interval_includes_a_loss():
    item=asyncio.run(ForecastAssessmentService(Profiles(),Assets()).enrich(
        uuid.uuid4(),snapshot())).forecasts[0]
    assert item.stance=='MONITOR'
    assert any('Forecast range includes a loss' in line for line in item.decision_trace)


def test_missing_volatility_suppresses_stance_without_inventing_zero():
    assets=Assets();assets.volatility=None
    result=asyncio.run(ForecastAssessmentService(Profiles(),assets).enrich(uuid.uuid4(),snapshot()))
    assert result.forecasts[0].stance is None
    assert result.forecasts[0].assessment_status=='unavailable'
    assert result.forecasts[0].rule_inputs.volatility is None


def test_stale_assessment_is_explicitly_historical():
    result=asyncio.run(ForecastAssessmentService(Profiles(),Assets()).enrich(uuid.uuid4(),snapshot(stale=True)))
    assert result.forecasts[0].assessment_status=='historical'
    assert result.forecasts[0].decision_trace[0].startswith('Historical research')


def test_missing_profile_does_not_use_default_risk_level():
    profiles=Profiles();profiles.value=None
    with pytest.raises(Conflict):
        asyncio.run(ForecastAssessmentService(profiles,Assets()).enrich(uuid.uuid4(),snapshot()))
