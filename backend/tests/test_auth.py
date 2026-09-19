from __future__ import annotations

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, login, make_user


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_seed_creates_admin_and_system_roles(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert me["email"] == ADMIN_EMAIL and me["role"] == "admin"
    assert "users:delete" in me["permissions"]
    names = [r["name"] for r in client.get("/api/roles", headers=admin).json()["items"]]
    assert {"admin", "user"} <= set(names)


def test_login_sets_httponly_cookie_and_cookie_authenticates(client):
    res = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert res.status_code == 200
    set_cookie = res.headers["set-cookie"].lower()
    assert "access_token=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    # No Authorization header: the TestClient replays the cookie.
    assert client.get("/api/auth/me").status_code == 200


def test_logout_clears_cookie(client):
    client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_bad_credentials_uniformly(client):
    wrong_pw = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "nope"})
    no_user = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_disabled_user_cannot_login_and_existing_token_dies(client, admin):
    user = make_user(client, admin, "bob@example.com")
    bob = login(client, "bob@example.com", "Passw0rd!x")
    assert client.patch(f"/api/users/{user['id']}", headers=admin, json={"is_active": False}).status_code == 200

    assert client.get("/api/auth/me", headers=bob).status_code == 401  # deactivation is immediate
    res = client.post("/api/auth/login", json={"email": "bob@example.com", "password": "Passw0rd!x"})
    assert res.status_code == 403


def test_protected_routes_require_a_valid_token(client):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_change_password(client, admin):
    make_user(client, admin, "carol@example.com")
    carol = login(client, "carol@example.com", "Passw0rd!x")

    bad = client.post("/api/auth/change-password", headers=carol, json={"current_password": "wrong", "new_password": "NewPassw0rd!"})
    assert bad.status_code == 400
    same = client.post("/api/auth/change-password", headers=carol, json={"current_password": "Passw0rd!x", "new_password": "Passw0rd!x"})
    assert same.status_code == 400
    short = client.post("/api/auth/change-password", headers=carol, json={"current_password": "Passw0rd!x", "new_password": "short"})
    assert short.status_code == 422

    ok = client.post("/api/auth/change-password", headers=carol, json={"current_password": "Passw0rd!x", "new_password": "NewPassw0rd!"})
    assert ok.status_code == 204
    assert client.post("/api/auth/login", json={"email": "carol@example.com", "password": "Passw0rd!x"}).status_code == 401
    login(client, "carol@example.com", "NewPassw0rd!")
