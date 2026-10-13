"""Authenticated forecast HTTP tests with no database lifespan or SQL calls."""
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("JWT_SECRET_KEY", "unit-tests-only-secret-not-production-123456789")

from app.api.deps import get_forecast_service, get_roles_repo, get_users_repo
from app.core.config import Settings
from app.core.security import create_access_token
from app.main import create_app
from app.repositories.forecasts import ForecastRepository
from app.services.forecasts import ForecastService


@pytest.fixture
def api(tmp_path):
    settings = Settings(jwt_secret_key="unit-tests-only-secret-not-production-123456789",
                        forecast_results_dir=tmp_path)
    user_id = uuid.uuid4()
    user = {"id": user_id, "role": "user", "is_active": True}

    class Users:
        async def get_by_id(self, selected):
            return user if str(selected) == str(user_id) else None

    class Roles:
        async def get(self, name):
            return {"name": name, "permissions": []}

    now = datetime.now(timezone.utc)
    row = {"Date": "2024-01-02", "ticker": "AAPL", "model": "Training-mean baseline",
           "predicted_return_10d": .01, "lower_return": -.05, "upper_return": .07,
           "uncertainty_width_pp": 12, "nominal_coverage": .9, "forecast_horizon_sessions": 10,
           "generated_at_utc": now.isoformat(), "calibration_latest_outcome": "2023-12-29"}
    with (tmp_path / "forecasts.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        writer.writeheader()
        writer.writerows([row, dict(row, ticker="MSFT")])
    (tmp_path / "report.json").write_text(json.dumps({
        "metadata": {"selected_model": row["model"], "as_of": "2024-01-02"},
        "calibration": {"coverage": .9, "latest_outcome": "2023-12-29"}}))
    app = create_app(settings)
    app.dependency_overrides[get_users_repo] = lambda: Users()
    app.dependency_overrides[get_roles_repo] = lambda: Roles()
    # Deliberately do not enter TestClient's context: database lifespan is not run.
    client = TestClient(app)
    token = create_access_token(str(user_id), settings)
    return client, {"Authorization": f"Bearer {token}"}, user, app


def test_signed_in_user_gets_only_selected_assets_and_missing_status(api):
    client, auth, _, _ = api
    response = client.get("/api/forecasts?tickers=AAPL,CEG", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert [item["ticker"] for item in body["forecasts"]] == ["AAPL"]
    assert body["unavailable_tickers"] == ["CEG"]
    assert body["forecasts"][0]["stale_snapshot"] is True
    assert response.headers["cache-control"] == "no-store"
    assert "source_provenance" not in body


def test_unauthenticated_and_inactive_requests_are_rejected(api):
    client, auth, user, _ = api
    assert client.get("/api/forecasts?tickers=AAPL").status_code == 401
    assert client.get("/api/forecasts?tickers=AAPL", headers={"Authorization": "Bearer invalid"}).status_code == 401
    user["is_active"] = False
    assert client.get("/api/forecasts?tickers=AAPL", headers=auth).status_code == 401


def test_missing_and_invalid_selection_do_not_return_entire_universe(api):
    client, auth, _, _ = api
    assert client.get("/api/forecasts", headers=auth).status_code == 422
    assert client.get("/api/forecasts?tickers=AAPL,AAPL", headers=auth).status_code == 400
    assert client.get("/api/forecasts?tickers=../../secret", headers=auth).status_code == 400


def test_unconfigured_export_returns_sanitized_503(api):
    client, auth, _, app = api
    app.dependency_overrides[get_forecast_service] = lambda: ForecastService(ForecastRepository(None))
    response = client.get("/api/forecasts?tickers=AAPL", headers=auth)
    assert response.status_code == 503
    assert "administrator" in response.json()["detail"]
    assert "joblib" not in response.text


def test_blank_directory_setting_is_disabled():
    settings = Settings(jwt_secret_key="unit-tests-only-secret-not-production-123456789",
                        forecast_results_dir="")
    assert settings.forecast_results_dir is None
