from __future__ import annotations

from conftest import login, make_role, make_user


def test_permission_catalogue_and_options(client, admin):
    perms = client.get("/api/roles/permissions", headers=admin).json()
    keys = {p["key"] for p in perms}
    assert {"users:read", "roles:update"} <= keys
    assert all(p["group"] == p["key"].split(":")[0] for p in perms)
    assert {o["name"] for o in client.get("/api/roles/options", headers=admin).json()} >= {"admin", "user"}


def test_options_visible_to_user_managers_without_roles_read(client, admin):
    make_role(client, admin, "hr", ["users:create"])
    make_user(client, admin, "hr@example.com", role="hr")
    hr = login(client, "hr@example.com", "Passw0rd!x")
    assert client.get("/api/roles/options", headers=hr).status_code == 200
    assert client.get("/api/roles", headers=hr).status_code == 403


def test_role_crud(client, admin):
    role = make_role(client, admin, "analyst", ["users:read", "users:read"])
    assert role["permissions"] == ["users:read"] and role["is_system"] is False

    assert client.post("/api/roles", headers=admin, json={"name": "analyst"}).status_code == 409
    assert client.post("/api/roles", headers=admin, json={"name": "Bad Name!"}).status_code == 422
    assert client.post("/api/roles", headers=admin, json={"name": "ghost", "permissions": ["nope:read"]}).status_code == 422

    updated = client.patch(
        "/api/roles/analyst", headers=admin, json={"description": "Reads stuff", "permissions": ["users:read", "roles:read"]}
    ).json()
    assert updated["description"] == "Reads stuff" and updated["permissions"] == ["roles:read", "users:read"]

    assert client.delete("/api/roles/analyst", headers=admin).status_code == 204
    assert client.get("/api/roles/analyst", headers=admin).status_code == 404


def test_system_roles_are_protected(client, admin):
    assert client.delete("/api/roles/admin", headers=admin).status_code == 400
    assert client.delete("/api/roles/user", headers=admin).status_code == 400
    assert client.patch("/api/roles/admin", headers=admin, json={"permissions": []}).status_code == 400
    admin_role = client.get("/api/roles/admin", headers=admin).json()
    assert admin_role["permissions"] == sorted(p["key"] for p in client.get("/api/roles/permissions", headers=admin).json())


def test_cannot_delete_role_in_use_and_user_count(client, admin):
    make_role(client, admin, "support", [])
    make_user(client, admin, "s1@example.com", role="support")
    res = client.delete("/api/roles/support", headers=admin)
    assert res.status_code == 409 and "1 user" in res.json()["detail"]
    listed = {r["name"]: r for r in client.get("/api/roles", headers=admin).json()["items"]}
    assert listed["support"]["user_count"] == 1 and listed["admin"]["user_count"] == 1


def test_role_editor_cannot_remove_own_roles_update(client, admin):
    make_role(client, admin, "roleman", ["roles:read", "roles:update"])
    make_user(client, admin, "rm@example.com", role="roleman")
    rm = login(client, "rm@example.com", "Passw0rd!x")
    res = client.patch("/api/roles/roleman", headers=rm, json={"permissions": ["roles:read"]})
    assert res.status_code == 400
