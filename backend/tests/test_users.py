from __future__ import annotations

from conftest import login, make_role, make_user


def test_default_role_user_has_no_permissions(client, admin):
    make_user(client, admin, "dave@example.com")
    dave = login(client, "dave@example.com", "Passw0rd!x")
    assert client.get("/api/auth/me", headers=dave).json()["permissions"] == []
    assert client.get("/api/users", headers=dave).status_code == 403
    assert client.post("/api/users", headers=dave, json={}).status_code == 403


def test_permission_grants_are_enforced_per_action(client, admin):
    make_role(client, admin, "viewer", ["users:read"])
    make_user(client, admin, "erin@example.com", role="viewer")
    erin = login(client, "erin@example.com", "Passw0rd!x")

    assert client.get("/api/users", headers=erin).status_code == 200
    body = {"email": "x@example.com", "full_name": "X", "password": "Passw0rd!x"}
    assert client.post("/api/users", headers=erin, json=body).status_code == 403
    assert client.get("/api/roles", headers=erin).status_code == 403


def test_role_edit_takes_effect_on_existing_token(client, admin):
    make_role(client, admin, "viewer", [])
    make_user(client, admin, "erin@example.com", role="viewer")
    erin = login(client, "erin@example.com", "Passw0rd!x")
    assert client.get("/api/users", headers=erin).status_code == 403

    client.patch("/api/roles/viewer", headers=admin, json={"permissions": ["users:read"]})
    assert client.get("/api/users", headers=erin).status_code == 200


def test_user_crud_and_pagination_search(client, admin):
    for i in range(12):
        make_user(client, admin, f"user{i:02d}@example.com")
    page1 = client.get("/api/users?page=1&page_size=5", headers=admin).json()
    assert page1["total"] == 13 and page1["total_pages"] == 3 and len(page1["items"]) == 5
    assert all("password" not in u and "password_hash" not in u for u in page1["items"])

    found = client.get("/api/users?q=user07", headers=admin).json()
    assert found["total"] == 1 and found["items"][0]["email"] == "user07@example.com"

    uid = found["items"][0]["id"]
    patched = client.patch(f"/api/users/{uid}", headers=admin, json={"full_name": "Renamed"}).json()
    assert patched["full_name"] == "Renamed"
    assert client.delete(f"/api/users/{uid}", headers=admin).status_code == 204
    assert client.get(f"/api/users/{uid}", headers=admin).status_code == 404
    assert client.get("/api/users/not-an-object-id", headers=admin).status_code == 404


def test_duplicate_email_and_unknown_role(client, admin):
    make_user(client, admin, "dup@example.com")
    body = {"email": "DUP@example.com", "full_name": "D", "password": "Passw0rd!x"}
    assert client.post("/api/users", headers=admin, json=body).status_code == 409
    body = {"email": "new@example.com", "full_name": "N", "password": "Passw0rd!x", "role": "nope"}
    assert client.post("/api/users", headers=admin, json=body).status_code == 400


def test_admin_can_reset_password(client, admin):
    user = make_user(client, admin, "frank@example.com")
    client.patch(f"/api/users/{user['id']}", headers=admin, json={"password": "BrandNewPass1"})
    login(client, "frank@example.com", "BrandNewPass1")


def test_cannot_lock_yourself_or_the_last_admin_out(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.delete(f"/api/users/{me['id']}", headers=admin).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"role": "user"}).status_code == 400

    # A second admin may demote/delete the first, but never the last one standing.
    second = make_user(client, admin, "second@example.com", role="admin")
    second_h = login(client, "second@example.com", "Passw0rd!x")
    assert client.delete(f"/api/users/{me['id']}", headers=second_h).status_code == 204
    assert client.delete(f"/api/users/{second['id']}", headers=second_h).status_code == 400


def test_non_admin_cannot_escalate_to_admin(client, admin):
    make_role(client, admin, "hr", ["users:read", "users:create", "users:update", "users:delete"])
    hr_user = make_user(client, admin, "hr@example.com", role="hr")
    hr = login(client, "hr@example.com", "Passw0rd!x")
    victim = make_user(client, admin, "vic@example.com")
    admin_me = client.get("/api/auth/me", headers=admin).json()

    body = {"email": "sneaky@example.com", "full_name": "S", "password": "Passw0rd!x", "role": "admin"}
    assert client.post("/api/users", headers=hr, json=body).status_code == 403
    assert client.patch(f"/api/users/{victim['id']}", headers=hr, json={"role": "admin"}).status_code == 403
    assert client.patch(f"/api/users/{admin_me['id']}", headers=hr, json={"password": "TakeOver1234"}).status_code == 403
    assert client.delete(f"/api/users/{admin_me['id']}", headers=hr).status_code == 403
    assert client.patch(f"/api/users/{victim['id']}", headers=hr, json={"full_name": "ok"}).status_code == 200
    assert hr_user["role"] == "hr"
