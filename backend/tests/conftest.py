"""Integration tests run against a real MongoDB (default: mongodb://localhost:27017,
override with TEST_MONGO_URI) using a throw-away database that is dropped around
every test. Point TEST_MONGO_URI at your MongoDB (see README).
"""

from __future__ import annotations

import os

# Must be set before app.main is imported (it builds an app at import time).
TEST_DB = "stocksense_test"
TEST_MONGO_URI = os.environ.get("TEST_MONGO_URI", "mongodb://localhost:27017")
os.environ.update(
    {
        "MONGO_URI": TEST_MONGO_URI,
        "MONGO_DB_NAME": TEST_DB,
        "JWT_SECRET_KEY": "test-secret-test-secret-test-secret-1234",
        "FIRST_ADMIN_EMAIL": "admin@example.com",
        "FIRST_ADMIN_PASSWORD": "AdminPass123!",
        "ENVIRONMENT": "development",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "AdminPass123!"


def _drop_db() -> None:
    with MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=3000) as c:
        c.drop_database(TEST_DB)


@pytest.fixture
def client():
    _drop_db()
    with TestClient(create_app(Settings())) as c:  # runs lifespan: indexes + seed
        yield c
    _drop_db()


def login(client: TestClient, email: str, password: str) -> dict:
    """Signs in and returns Authorization headers (the session cookie is also set)."""
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def make_user(client, admin_headers, email, role="user", password="Passw0rd!x", **extra):
    res = client.post(
        "/api/users",
        headers=admin_headers,
        json={"email": email, "full_name": email.split("@")[0], "password": password, "role": role, **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()


def make_role(client, admin_headers, name, permissions):
    res = client.post("/api/roles", headers=admin_headers, json={"name": name, "permissions": permissions})
    assert res.status_code == 201, res.text
    return res.json()
