"""Password reset security tests.

Verifies the four invariants the advisor required:
  1. No user enumeration — same 200 whether username exists or not
  2. Token is SHA-256 hashed in DB, never stored plaintext
  3. Single-use + 15-min expiry enforced
  4. All refresh tokens revoked on successful reset
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth import hash_password
from app.db import AsyncSessionLocal
from app.models_db import PasswordResetToken, RefreshToken, User


# ── helpers ───────────────────────────────────────────────────────────────────

async def _create_user(username="resetuser", password="hunter2!"):
    async with AsyncSessionLocal() as db:
        u = User(username=username, password_hash=hash_password(password), role="viewer", is_active=True)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _plant_refresh_token(user_id: int):
    async with AsyncSessionLocal() as db:
        rt = RefreshToken(
            user_id=user_id,
            token_hash=hashlib.sha256(secrets.token_bytes(16)).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(rt)
        await db.commit()


async def _plant_reset_token(user_id: int, expired: bool = False):
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if expired:
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    async with AsyncSessionLocal() as db:
        db.add(PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
        await db.commit()
    return token


# ── 1. No user enumeration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forgot_password_same_response_for_missing_user(client):
    r = await client.post("/api/auth/forgot-password", json={"username": "no_such_user_xyz"})
    assert r.status_code == 200
    assert "reset link" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_forgot_password_same_response_for_existing_user(client):
    await _create_user(username="enumtest")
    r = await client.post("/api/auth/forgot-password", json={"username": "enumtest"})
    assert r.status_code == 200
    assert "reset link" in r.json().get("detail", "").lower()


# ── 2. Token hashed in DB ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forgot_password_stores_hash_not_plaintext(client, monkeypatch):
    user_id = await _create_user(username="hashtest")

    captured_url: list[str] = []

    async def fake_send(username, reset_url):
        captured_url.append(reset_url)
        return True

    import app.password_reset as pr_mod
    monkeypatch.setattr(pr_mod, "send_password_reset_email", fake_send)

    r = await client.post("/api/auth/forgot-password", json={"username": "hashtest"})
    assert r.status_code == 200
    assert len(captured_url) == 1

    # Extract plaintext token from the emailed URL
    token = captured_url[0].split("reset_token=")[1]
    expected_hash = hashlib.sha256(token.encode()).hexdigest()

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )).scalar_one_or_none()

    assert row is not None, "Token row must be written to DB"
    assert row.token_hash == expected_hash, "DB must store SHA-256 hash, not plaintext"
    assert token not in row.token_hash, "Plaintext token must NOT appear in token_hash"


# ── 3. Single-use enforced ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_token_single_use(client):
    user_id = await _create_user(username="singleuse")
    token = await _plant_reset_token(user_id)

    r1 = await client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "NewPass123!"})
    assert r1.status_code == 200

    # Second use of the same token must fail
    r2 = await client.post("/api/auth/reset-password",
                           json={"token": token, "new_password": "AnotherPass!1"})
    assert r2.status_code == 400


# ── 4. Expiry enforced ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_expired_token_rejected(client):
    user_id = await _create_user(username="expiredtest")
    token = await _plant_reset_token(user_id, expired=True)

    r = await client.post("/api/auth/reset-password",
                          json={"token": token, "new_password": "NewPass123!"})
    assert r.status_code == 400


# ── 5. Refresh tokens revoked on reset ────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_revokes_refresh_tokens(client):
    user_id = await _create_user(username="revoketest")
    await _plant_refresh_token(user_id)
    await _plant_refresh_token(user_id)
    token = await _plant_reset_token(user_id)

    r = await client.post("/api/auth/reset-password",
                          json={"token": token, "new_password": "NewPass123!"})
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        remaining = (await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        )).scalars().all()

    assert len(remaining) == 0, "All refresh tokens must be deleted on password reset"


# ── 6. Invalid / forged token rejected ────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_rejects_forged_token(client):
    r = await client.post("/api/auth/reset-password",
                          json={"token": "forgedtoken", "new_password": "NewPass123!"})
    assert r.status_code == 400


# ── 7. Short password rejected ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_rejects_short_password(client):
    user_id = await _create_user(username="shortpasstest")
    token = await _plant_reset_token(user_id)

    r = await client.post("/api/auth/reset-password",
                          json={"token": token, "new_password": "short"})
    # Pydantic min_length=8 on the model returns 422
    assert r.status_code == 422


# ── 8. Password reset recipient routing (BUG-HIGH-PWRESET-01) ────────────────

def test_reset_recipient_uses_admin_email_for_nonemail_username(monkeypatch):
    """BUG-HIGH-PWRESET-01: the default admin's username 'admin' isn't an email, so
    reset mail must route to MEMAR_ADMIN_EMAIL, not to 'admin'."""
    from app.email_service import _resolve_reset_recipient
    monkeypatch.setenv("MEMAR_ADMIN_EMAIL", "ops@example.com")
    assert _resolve_reset_recipient("admin") == "ops@example.com"


def test_reset_recipient_uses_username_when_email_shaped(monkeypatch):
    from app.email_service import _resolve_reset_recipient
    monkeypatch.setenv("MEMAR_ADMIN_EMAIL", "ops@example.com")
    assert _resolve_reset_recipient("alice@corp.io") == "alice@corp.io"


def test_reset_recipient_none_when_unresolvable(monkeypatch):
    from app.email_service import _resolve_reset_recipient
    monkeypatch.delenv("MEMAR_ADMIN_EMAIL", raising=False)
    assert _resolve_reset_recipient("admin") is None
