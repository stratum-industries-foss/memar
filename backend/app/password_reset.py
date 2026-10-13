"""Password reset endpoints — forgot-password and reset-password flows."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ._limiter import rate_limit
from .auth import hash_password
from .db import get_db
from .email_service import send_password_reset_email
from .models_db import PasswordResetToken, RefreshToken, User

password_reset_router = APIRouter(prefix="/api/auth", tags=["auth"])

_DEV_ENVS = frozenset({"dev", "development", "test"})
_TOKEN_TTL_MINUTES = 15


class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=1024)


@password_reset_router.post("/forgot-password")
@rate_limit("5/hour")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link.

    Always returns 200 — never reveals whether the username exists.
    The rate limit (5/hour) prevents email bombing.

    If SMTP is not configured, returns the reset link directly in the response
    (for local/dev deployments). Production should always use email delivery.
    """
    result = await db.execute(
        select(User).where(User.username == body.username, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    email_sent = False
    reset_url = None

    if user is not None:
        # Prune any existing tokens for this user (one active reset at a time)
        await db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_TTL_MINUTES)
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
        await db.commit()

        public_url = os.getenv("MEMAR_PUBLIC_URL", "http://localhost:9000").rstrip("/")
        reset_url = f"{public_url}/?reset_token={token}"

        # Try to send email; if it fails (SMTP not configured), fallback to direct link
        email_sent = await send_password_reset_email(username=user.username, reset_url=reset_url)

    # Security: always say email was sent (no user enumeration)
    # But if email SMTP is not configured, return the link directly for local dev use
    response = {"detail": "If the account exists, a reset link has been sent"}

    # Fallback for dev/local deployments where SMTP is not configured
    if not email_sent and reset_url and os.getenv("MEMAR_ENV", "").lower() in _DEV_ENVS:
        response["reset_link"] = reset_url
        response["detail"] = "SMTP not configured. Reset link is provided below. (This link will only appear in development mode.)"

    return response


@password_reset_router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid reset token for a new password.

    - Single-use: token is marked used on success.
    - All existing refresh tokens are revoked so old sessions cannot persist.
    - Returns the same 400 for expired vs invalid tokens to prevent oracle attacks.
    """
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    _invalid = HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Atomic token consumption: SELECT + mark used in single UPDATE to prevent races
    result = await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,  # noqa: E712
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
        .values(used=True)
        .returning(PasswordResetToken.user_id)
    )
    row = result.first()
    if row is None:
        raise _invalid
    user_id = row[0]

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise _invalid
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False

    # Revoke all refresh tokens so existing sessions are invalidated
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))

    await db.commit()
    return {"detail": "Password reset successfully"}
