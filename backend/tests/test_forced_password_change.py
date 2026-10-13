"""Forced first-login password change — server-side enforcement.

The app ships with a default admin/admin credential (when MEMAR_ADMIN_PASSWORD is
unset) and a must_change_password flag. The whole point is that the flag is
enforced at the API layer, not just in the UI: a token minted from the default
credential must be inert on every protected route until the password is changed.
"""

import os

import pytest
import pytest_asyncio

from app.auth import hash_password
from app.db import AsyncSessionLocal
from app.models_db import User


PROTECTED_ROUTE = "/api/printers"  # depends on get_current_user (enforced)


@pytest_asyncio.fixture()
async def forced_user(client):
    """Create an admin that still owes a forced password change (default cred)."""
    async with AsyncSessionLocal() as db:
        db.add(User(
            username="forced",
            password_hash=hash_password("admin"),
            role="admin",
            is_active=True,
            must_change_password=True,
        ))
        await db.commit()
    return "forced", "admin"


@pytest.mark.asyncio
async def test_login_surfaces_flag(client, forced_user):
    username, password = forced_user
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_default_cred_token_is_inert_on_protected_route(client, forced_user):
    """The discriminating test: a valid login token must NOT open a protected
    route while the forced change is pending. If this passes, the feature is real;
    if the route returns 200, the UI modal would be pure theater."""
    username, password = forced_user
    token = (await client.post("/api/auth/login", json={"username": username, "password": password})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # /me is reachable (so the UI can detect the flag)...
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    # ...but a real protected route is refused with the routing code.
    blocked = await client.get(PROTECTED_ROUTE, headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "password_change_required"


@pytest.mark.asyncio
async def test_change_password_unlocks_and_rotates(client, forced_user):
    username, password = forced_user
    token = (await client.post("/api/auth/login", json={"username": username, "password": password})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Change the password; receive a fresh token pair with the flag cleared.
    changed = await client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "admin",
        "new_password": "n3w-strong-pass",
    })
    assert changed.status_code == 200
    body = changed.json()
    assert body["must_change_password"] is False
    new_headers = {"Authorization": f"Bearer {body['access_token']}"}

    # The fresh token now opens the previously-blocked route.
    assert (await client.get(PROTECTED_ROUTE, headers=new_headers)).status_code == 200

    # The old default credential no longer works at all.
    relogin = await client.post("/api/auth/login", json={"username": username, "password": "admin"})
    assert relogin.status_code == 401

    # The new credential logs in cleanly with the flag off.
    relogin_new = await client.post("/api/auth/login", json={"username": username, "password": "n3w-strong-pass"})
    assert relogin_new.status_code == 200
    assert relogin_new.json()["must_change_password"] is False


@pytest.mark.asyncio
async def test_change_password_rejects_weak_and_default(client, forced_user):
    username, password = forced_user
    token = (await client.post("/api/auth/login", json={"username": username, "password": password})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Too short
    short = await client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "admin", "new_password": "short",
    })
    assert short.status_code == 400

    # Re-using the default password is refused
    same = await client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "admin", "new_password": "admin",
    })
    assert same.status_code == 400

    # Wrong current password is refused
    wrong = await client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "not-it", "new_password": "n3w-strong-pass",
    })
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_env_password_admin_has_no_forced_flag(admin_client):
    """The conftest admin is created WITH MEMAR_ADMIN_PASSWORD set, so it must NOT
    be forced to change and must reach protected routes immediately."""
    me = await admin_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json().get("must_change_password") is False
    assert (await admin_client.get(PROTECTED_ROUTE)).status_code == 200
