"""Integration tests run against a real PostgreSQL server (default: postgres@localhost:5432,
override with the TEST_POSTGRES_* variables below) using a throw-away database that is
dropped and recreated around every test. Never point these at a server where a database
named ``stocksense_test`` holds anything you want to keep.
"""

from __future__ import annotations

import asyncio
import os

# Must be set before app.main is imported (it builds an app at import time).
TEST_DB = "stocksense_test"
TEST_PG = {
    "host": os.environ.get("TEST_POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("TEST_POSTGRES_PORT", "5432")),
    "user": os.environ.get("TEST_POSTGRES_USER", "postgres"),
    "password": os.environ.get("TEST_POSTGRES_PASSWORD", ""),
    "ssl": os.environ.get("TEST_POSTGRES_SSLMODE", "prefer"),
}
os.environ.update(
    {
        "POSTGRES_HOST": TEST_PG["host"],
        "POSTGRES_PORT": str(TEST_PG["port"]),
        "POSTGRES_USER": TEST_PG["user"],
        "POSTGRES_PASSWORD": TEST_PG["password"],
        "POSTGRES_SSLMODE": TEST_PG["ssl"],
        "POSTGRES_DB": TEST_DB,
        "JWT_SECRET_KEY": "test-secret-test-secret-test-secret-1234",
        "FIRST_ADMIN_EMAIL": "admin@example.com",
        "FIRST_ADMIN_PASSWORD": "AdminPass123!",
        "ENVIRONMENT": "development",
    }
)

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "AdminPass123!"


async def _sql(database: str, query: str, *args):
    conn = await asyncpg.connect(database=database, timeout=5, **TEST_PG)
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


def run_sql(query: str, *args) -> list:
    """Run a statement directly against the test database (for arranging or inspecting state)."""
    return asyncio.run(_sql(TEST_DB, query, *args))


def _drop_db() -> None:
    # FORCE ends connections a previous test may have left open (PostgreSQL 13+).
    asyncio.run(_sql("postgres", f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))


def _create_db() -> None:
    asyncio.run(_sql("postgres", f'CREATE DATABASE "{TEST_DB}"'))


@pytest.fixture
def client():
    _drop_db()
    _create_db()
    with TestClient(create_app(Settings())) as c:  # runs lifespan: schema + seed
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
