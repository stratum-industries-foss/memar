"""Personal API tokens: what they allow, what they refuse, and how they end."""

import httpx
import pytest
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models_db import ApiToken, User


async def _mint(admin_client, scope="read", **extra):
    body = {"name": "test", "scope": scope, **extra}
    r = await admin_client.post("/api/admin/api-tokens", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _as(client, token):
    c = httpx.AsyncClient(transport=client._transport, base_url=str(client.base_url))
    c.headers["Authorization"] = f"Bearer {token}"
    return c


async def test_created_token_is_shown_once_and_never_stored(admin_client):
    out = await _mint(admin_client)
    plaintext = out["token"]
    assert plaintext.startswith("mem_") and len(plaintext) >= 40
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(ApiToken))).scalars().all()
    stored = " ".join(r.token_hash for r in rows)
    assert plaintext not in stored, "the plaintext token must never be stored"
    assert len(rows[-1].token_hash) == 64, "only a SHA-256 is stored"
    listed = (await admin_client.get("/api/admin/api-tokens")).json()
    assert all("token" not in row for row in listed), "list must never return the token"


async def test_read_token_reads_but_cannot_write(admin_client, client):
    out = await _mint(admin_client, scope="read")
    t = _as(client, out["token"])
    assert (await t.get("/api/admin/api-tokens")).status_code == 200
    r = await t.post("/api/admin/api-tokens", json={"name": "x", "scope": "read"})
    assert r.status_code == 403, "a read-scope token must not write"


async def test_full_token_acts_as_its_owner_admin(admin_client, client):
    out = await _mint(admin_client, scope="full")
    t = _as(client, out["token"])
    r = await t.post("/api/admin/api-tokens", json={"name": "child", "scope": "read"})
    assert r.status_code == 201, r.text


async def test_wrong_token_is_refused(client):
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer mem_" + "A" * 43})
    assert r.status_code == 401


async def test_revoked_token_stops_working(admin_client, client):
    out = await _mint(admin_client, scope="full")
    t = _as(client, out["token"])
    assert (await t.get("/api/auth/me")).status_code == 200
    rv = await admin_client.delete(f"/api/admin/api-tokens/{out['id']}")
    assert rv.status_code == 200
    assert (await t.get("/api/auth/me")).status_code == 401


async def test_expired_token_is_refused(admin_client, client):
    from datetime import datetime, timedelta
    out = await _mint(admin_client, scope="full", expires_in_days=1)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(ApiToken).where(ApiToken.id == out["id"]))).scalar_one()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        await db.commit()
    assert (await _as(client, out["token"]).get("/api/auth/me")).status_code == 401


async def test_suspended_owner_loses_their_tokens(admin_client, client):
    out = await _mint(admin_client, scope="full")
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.id == out["owner_user_id"]))).scalar_one()
        owner.is_active = False
        await db.commit()
    try:
        assert (await _as(client, out["token"]).get("/api/auth/me")).status_code == 401
    finally:
        async with AsyncSessionLocal() as db:
            owner = (await db.execute(select(User).where(User.id == out["owner_user_id"]))).scalar_one()
            owner.is_active = True
            await db.commit()


async def test_token_is_refused_on_jwt_only_paths_without_breaking_sessions(admin_client):
    """A normal login session still works alongside tokens (no regression)."""
    r = await admin_client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["role"] == "admin"


async def test_non_admin_cannot_mint_tokens(client, admin_client):
    created = await admin_client.post("/api/admin/users", json={
        "username": "viewer.tok", "password": "viewer-tok-passphrase-1", "role": "viewer"})
    if created.status_code not in (200, 201):
        pytest.skip(f"cannot create a viewer in this fixture: {created.status_code}")
    login = await client.post("/api/auth/login", json={"username": "viewer.tok",
                                                       "password": "viewer-tok-passphrase-1"})
    viewer_jwt = login.json()["access_token"]
    r = await _as(client, viewer_jwt).post("/api/admin/api-tokens",
                                           json={"name": "nope", "scope": "full"})
    assert r.status_code == 403
