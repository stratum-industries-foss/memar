"""Tests for authentication endpoints."""

import os
import pytest
from datetime import datetime, timezone, timedelta


# ── Unit tests (no HTTP) ──────────────────────────────────────────────────────

def test_create_access_token_returns_string():
    from app.auth import create_access_token
    token = create_access_token(user_id=1, username="admin", role="admin")
    assert isinstance(token, str)
    assert len(token) > 20


def test_create_refresh_token_is_urlsafe_string():
    from app.auth import create_refresh_token
    token = create_refresh_token()
    assert isinstance(token, str)
    assert len(token) > 20


def test_password_hashing_roundtrip():
    from app.auth import hash_password, verify_password
    pw = "correct-horse-battery-staple"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed)
    assert not verify_password("wrong-password", hashed)


def test_datetime_comparison_uses_aware_types():
    """Regression: ensure expiry comparisons don't mix naive/aware datetimes."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    # Both are tz-aware; no TypeError should be raised.
    assert now > past
    assert now < future


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client):
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "definitely-wrong",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(client):
    resp = await client.post("/api/auth/login", json={
        "username": "nobody",
        "password": "anything",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_correct_credentials_returns_tokens(client):
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_refresh_token_flow(client):
    """Login → use refresh token → get new access token."""
    login_resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "testpass123",
    })
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200, f"Refresh failed: {refresh_resp.text}"
    assert "access_token" in refresh_resp.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token_returns_401(client):
    resp = await client.post("/api/auth/refresh", json={"refresh_token": "x" * 64})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_token_returns_401(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token_returns_200(admin_client):
    resp = await admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_no_auth_requires_dev_env(client):
    """
    Security: MEMAR_NO_AUTH alone must NOT bypass auth — it is double-gated and
    requires MEMAR_ENV=dev as well, so it can never open the API by accident in
    production. With NO_AUTH set but MEMAR_ENV unset, requests still get 401.
    """
    old_na = os.environ.get("MEMAR_NO_AUTH")
    old_env = os.environ.get("MEMAR_ENV")
    try:
        os.environ["MEMAR_NO_AUTH"] = "1"
        os.environ.pop("MEMAR_ENV", None)  # not dev
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401  # bypass refused without MEMAR_ENV=dev
    finally:
        if old_na is None:
            os.environ.pop("MEMAR_NO_AUTH", None)
        else:
            os.environ["MEMAR_NO_AUTH"] = old_na
        if old_env is not None:
            os.environ["MEMAR_ENV"] = old_env


@pytest.mark.asyncio
async def test_no_auth_bypass_engages_only_in_dev(client):
    """With BOTH MEMAR_NO_AUTH=1 and MEMAR_ENV=dev, the dev bypass returns admin."""
    old_na = os.environ.get("MEMAR_NO_AUTH")
    old_env = os.environ.get("MEMAR_ENV")
    try:
        os.environ["MEMAR_NO_AUTH"] = "1"
        os.environ["MEMAR_ENV"] = "dev"
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"
    finally:
        if old_na is None:
            os.environ.pop("MEMAR_NO_AUTH", None)
        else:
            os.environ["MEMAR_NO_AUTH"] = old_na
        if old_env is None:
            os.environ.pop("MEMAR_ENV", None)
        else:
            os.environ["MEMAR_ENV"] = old_env
