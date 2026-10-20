"""Recommended saved-model HTTP contracts with no model, provider or database."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("JWT_SECRET_KEY", "unit-tests-only-secret-not-production-123456789")

from app.api.deps import get_current_principal, get_forecast_service, get_recommendation_service, get_forecast_assessment_service, get_users_repo, get_roles_repo, Principal
from app.api.routers.forecasts import get_selected_recommender
from app.core.config import Settings
from app.main import create_app
from app.services.errors import Conflict
from app.schemas.forecast import ForecastItem, ForecastSnapshot


@pytest.fixture
def inference_api(tmp_path):
    settings = Settings(jwt_secret_key="unit-tests-only-secret-not-production-123456789",
                        forecast_model_dir=tmp_path)
    user_id = uuid.uuid4()
    principal = Principal(user={"id": user_id, "role": "user", "is_active": True}, permissions=set())

    class Recommendations:
        calls = []
        tickers = ["MSFT", "AAPL"]
        failure = None

        async def for_user(self, selected_user, limit):
            self.calls.append((selected_user, limit))
            if self.failure:
                raise self.failure
            return [SimpleNamespace(ticker=ticker) for ticker in self.tickers]

    class Engine:
        calls = []

        async def get_snapshot(self, tickers):
            self.calls.append(tickers)
            return ForecastSnapshot(model="XGBoost", as_of="2026-10-12", generated_at="2026-10-13T00:00:00Z",
                        nominal_coverage=.9, forecasts=[], selected_tickers=tickers,
                        unavailable_tickers=tickers)

    class Assessment:
        def __init__(self):
            self.calls = []

        async def enrich(self, selected_user, snapshot):
            self.calls.append((selected_user, snapshot))
            for item in snapshot.forecasts:
                item.stance = "MONITOR"
                item.decision_trace = ["Fixture assessment using the new forecast"]
                item.assessment_status = "evaluated"
            return snapshot

    recommender, engine = Recommendations(), Engine()
    engine.assessment = Assessment()
    app = create_app(settings)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_recommendation_service] = lambda: recommender
    app.dependency_overrides[get_forecast_service] = lambda: engine
    app.dependency_overrides[get_forecast_assessment_service] = lambda: engine.assessment
    app.dependency_overrides[get_selected_recommender] = lambda: recommender
    app.dependency_overrides[get_users_repo] = lambda: object()
    app.dependency_overrides[get_roles_repo] = lambda: object()
    # No TestClient context: application database lifespan is never entered.
    return TestClient(app), app, recommender, engine, user_id, settings


def test_recommended_route_uses_authenticated_users_exact_shortlist(inference_api):
    client, _, recommender, engine, user_id, settings = inference_api
    # Query contents must not let the caller expand the generated shortlist.
    response = client.get("/api/forecasts/recommended?tickers=NVDA")
    assert response.status_code == 200
    assert recommender.calls == [(user_id, settings.recommendations_limit)]
    assert engine.calls == [["MSFT", "AAPL"]]
    assert response.json()["selected_tickers"] == ["MSFT", "AAPL"]
    assert response.headers["cache-control"] == "no-store"


def test_selected_inference_cannot_bypass_recommendations(inference_api):
    client, _, _, engine, _, _ = inference_api
    response = client.get("/api/forecasts?tickers=AAPL,NVDA")
    assert response.status_code == 403
    assert engine.calls == []
    assert engine.assessment.calls == []
    response = client.get("/api/forecasts?tickers=AAPL")
    assert response.status_code == 200
    assert engine.calls == [["AAPL"]]


@pytest.mark.parametrize("failure", ["missing_profile", "empty_catalogue"])
def test_recommendation_preconditions_do_not_run_inference(inference_api, failure):
    client, _, recommender, engine, _, _ = inference_api
    if failure == "missing_profile":
        recommender.failure = Conflict("Complete your investor profile to get suggestions")
    else:
        recommender.tickers = []
    assert client.get("/api/forecasts/recommended").status_code == 409
    assert engine.calls == []
    assert engine.assessment.calls == []


def test_recommended_route_requires_authentication(inference_api):
    client, app, recommender, engine, _, _ = inference_api
    del app.dependency_overrides[get_current_principal]
    # Authentication rejects before any recommendation repository/model call.
    response = client.get("/api/forecasts/recommended")
    assert response.status_code == 401
    assert recommender.calls == []
    assert engine.calls == []
    assert engine.assessment.calls == []


def test_recommended_forecast_rule_handoff_preserves_caller_and_new_prediction(inference_api):
    client, _, _, engine, user_id, _ = inference_api
    async def populated_snapshot(tickers):
        engine.calls.append(tickers)
        item = ForecastItem(ticker="AAPL", date="2026-10-12", predicted_return_10d=.025,
                            lower_return=-.025, upper_return=.075, uncertainty_width_pp=10,
                            nominal_coverage=.9, stale_snapshot=False, data_age_calendar_days=1,
                            calibration_latest_outcome="2026-09-30")
        return ForecastSnapshot(model="XGBoost", as_of="2026-10-12", generated_at="2026-10-13T00:00:00Z",
                                nominal_coverage=.9, forecasts=[item], selected_tickers=tickers,
                                unavailable_tickers=["MSFT"])
    engine.get_snapshot = populated_snapshot
    response = client.get("/api/forecasts/recommended")
    assert response.status_code == 200
    body = response.json()
    assert body["forecasts"][0]["stance"] == "MONITOR"
    assert body["forecasts"][0]["assessment_status"] == "evaluated"
    assert body["forecasts"][0]["decision_trace"] == ["Fixture assessment using the new forecast"]
    assert len(engine.assessment.calls) == 1
    selected_user, assessed_snapshot = engine.assessment.calls[0]
    assert selected_user == user_id
    assert assessed_snapshot.forecasts[0].predicted_return_10d == .025
    assert assessed_snapshot.forecasts[0].uncertainty_width_pp == 10
    assert assessed_snapshot.selected_tickers == ["MSFT", "AAPL"]
