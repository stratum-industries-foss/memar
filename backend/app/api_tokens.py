"""Personal API tokens (mem_...): create, look up, revoke.

A token is "mem_" + 32 random bytes (base64url). The database stores only its
SHA-256. The plaintext is returned once, at creation, and never again.

Scope:
  read  -> GET, HEAD, OPTIONS only (any other method is refused with 403)
  full  -> the owner's role, as with a logged-in session

The owner is checked on every call (suspended or deleted owners lose access at
once), and an expired or revoked token is refused.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models_db import ApiToken, User

PREFIX = "mem_"
SCOPES = ("read", "full")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_api_token(value: str) -> bool:
    return value.startswith(PREFIX) and 40 <= len(value) <= 80


async def create_token(db: AsyncSession, *, owner: User, name: str, scope: str,
                       days: int | None) -> tuple[ApiToken, str]:
    """Return (row, plaintext). The plaintext is not stored and cannot be recovered."""
    if scope not in SCOPES:
        raise ValueError("scope must be 'read' or 'full'")
    plaintext = PREFIX + secrets.token_urlsafe(32)
    expires = None
    if days:
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
    row = ApiToken(user_id=owner.id, name=name.strip()[:100], token_hash=_hash(plaintext),
                   scope=scope, expires_at=expires, revoked=False)
    db.add(row)
    await db.flush()
    return row, plaintext


async def resolve(db: AsyncSession, value: str, method: str) -> dict | None:
    """Return the owner's identity if the token is valid for this request, else None.

    Returns a dict shaped like a session identity so routes treat it the same way.
    Raises PermissionError when the token exists but its scope forbids this method.
    """
    if not looks_like_api_token(value):
        return None
    row = (await db.execute(select(ApiToken).where(ApiToken.token_hash == _hash(value)))).scalar_one_or_none()
    if row is None or row.revoked:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row.expires_at is not None and now >= row.expires_at:
        return None
    owner = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if owner is None or not owner.is_active:
        return None
    if row.scope == "read" and method.upper() not in READ_METHODS:
        raise PermissionError("this token is read-only")
    row.last_used_at = now
    return {
        "id": owner.id,
        "username": owner.username,
        "role": owner.role,
        "must_change_password": False,  # API tokens are not interactive sessions
        "token_id": row.id,
        "token_scope": row.scope,
    }
