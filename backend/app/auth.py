"""JWT authentication and user management for MEMAR."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete

from .db import AsyncSessionLocal
from .models_db import RefreshToken, User, WsTicket


logger = logging.getLogger(__name__)


# WebSocket ticket: a short-lived, single-use nonce that authorizes ONE WS
# connection so the long-lived access JWT never rides the WS query string.
WS_TICKET_TTL_SECONDS = 30


# JWT Configuration
JWT_SECRET = os.getenv("MEMAR_JWT_SECRET")
if not JWT_SECRET:
    # In production a missing secret is fatal: an auto-generated per-process key
    # means every worker signs with a different key (random 401s) and every
    # restart invalidates all sessions. Refuse to boot. In dev/test we fall back
    # to a random key with a loud warning so local runs and the suite work.
    if os.getenv("MEMAR_ENV", "").lower() in ("production", "prod"):
        raise RuntimeError(
            "MEMAR_JWT_SECRET is required in production (MEMAR_ENV=production) "
            "but is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "and set it in the environment."
        )
    JWT_SECRET = secrets.token_hex(32)
    logger.warning(
        "MEMAR_JWT_SECRET not set — using an auto-generated key (dev/test only). "
        "Set MEMAR_JWT_SECRET to a fixed value in production; tokens otherwise "
        "invalidate on restart and break across multiple workers."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Seconds-granular TTL overrides (env). Production behaviour is UNCHANGED when
# these are unset — the defaults resolve to exactly 15 min / 30 days. They exist
# so e2e tests can express a 2-3s TTL (minutes/days can't) and drive GENUINE
# server-side token expiry rather than faking it with a bogus client token.
_ACCESS_TTL_SECONDS = int(
    os.getenv("MEMAR_ACCESS_TOKEN_EXPIRE_SECONDS", str(ACCESS_TOKEN_EXPIRE_MINUTES * 60))
)
_REFRESH_TTL_SECONDS = int(
    os.getenv("MEMAR_REFRESH_TOKEN_EXPIRE_SECONDS", str(REFRESH_TOKEN_EXPIRE_DAYS * 86400))
)

# Shipped default admin credential. When MEMAR_ADMIN_PASSWORD is not set, the app
# boots with admin/admin and FORCES a password change on first login (server-side
# enforced, not just UI). Setting MEMAR_ADMIN_PASSWORD opts out of the forced flow.
DEFAULT_ADMIN_PASSWORD = "admin"
MIN_PASSWORD_LENGTH = 8

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dummy hash for constant-time rejection of disabled/unknown users (prevents timing oracles)
_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.jf.JNi/EUvW.Tm"  # bcrypt of "dummy"


# Pydantic models
class LoginRequest(BaseModel):
    username: str = Field(max_length=255)
    password: str = Field(max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


# Password functions
def hash_password(password: str) -> str:
    """Hash a plain password with bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return pwd_context.verify(plain, hashed)


# JWT functions
def create_access_token(
    user_id: int, username: str, role: str, must_change_password: bool = False
) -> str:
    """Create an access token (15 min TTL).

    The must_change_password claim is the enforcement signal: deps.get_current_user
    refuses every protected route while it is true, so a token minted from the
    default admin/admin credential is inert until the password is actually changed.
    """
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "must_change_password": bool(must_change_password),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_ACCESS_TTL_SECONDS),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    return token


def create_refresh_token() -> str:
    """Create an opaque refresh token (stored as hash in DB)."""
    return secrets.token_urlsafe(48)


def decode_access_token(token: str) -> dict:
    """Decode and verify an access token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise JWTError("Invalid token type")
        return payload
    except JWTError as e:
        logger.debug(f"Token decode error: {e}")
        raise


async def create_ws_ticket(db: AsyncSession, user: dict) -> str:
    """Mint a single-use WS ticket bound to `user`, valid for WS_TICKET_TTL_SECONDS.

    Returns the opaque nonce the client connects with (`?ticket=<nonce>`). Also
    opportunistically prunes expired rows so the table stays small without a
    dedicated cleanup job.
    """
    now = datetime.now(timezone.utc)
    # Opportunistic GC of expired/abandoned tickets.
    await db.execute(delete(WsTicket).where(WsTicket.expires_at < now))

    nonce = secrets.token_urlsafe(32)
    db.add(WsTicket(
        nonce=nonce,
        user_id=int(user["id"]),
        username=user["username"],
        role=user["role"],
        expires_at=now + timedelta(seconds=WS_TICKET_TTL_SECONDS),
    ))
    await db.commit()
    return nonce


async def consume_ws_ticket(nonce: str) -> dict | None:
    """Validate + atomically consume a WS ticket. Returns the bound user or None.

    Single-use is enforced by DELETE ... RETURNING in one round-trip: only the
    caller whose delete actually removed the (still-valid) row gets the user
    back, so a replayed or expired nonce yields None. Opens its own short-lived
    session (the WS handler holds no request-scoped db) rather than pinning a
    connection for the lifetime of the socket.
    """
    if not nonce:
        return None
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(WsTicket)
            .where(WsTicket.nonce == nonce, WsTicket.expires_at > now)
            .returning(WsTicket.user_id, WsTicket.username, WsTicket.role)
        )
        row = result.first()
        await db.commit()
    if row is None:
        return None
    return {"id": int(row[0]), "username": row[1], "role": row[2]}


async def ensure_admin_user(db: AsyncSession) -> None:
    """
    Create a default admin user if none exists.
    Called at startup.
    """
    # Check if admin user already exists
    result = await db.execute(select(User).where(User.role == "admin"))
    existing_admin = result.scalars().first()
    if existing_admin:
        logger.info("Admin user already exists")
        return

    # Get credentials from env, else ship with a known default that must be changed.
    username = os.getenv("MEMAR_ADMIN_USER", "admin")
    password = os.getenv("MEMAR_ADMIN_PASSWORD")
    env = os.getenv("MEMAR_ENV", "").lower()

    if password:
        # Operator chose the password explicitly — trust it, no forced change.
        must_change = False
    elif env in ("production", "prod"):
        # Production MUST have an explicit password — no default admin/admin.
        raise RuntimeError(
            "MEMAR_ADMIN_PASSWORD is required in production (MEMAR_ENV=production). "
            "Set it to a strong password before starting the server."
        )
    else:
        # Dev/test: boot with the documented default and FORCE a change on first login.
        password = DEFAULT_ADMIN_PASSWORD
        must_change = True
        logger.warning(
            "MEMAR_ADMIN_PASSWORD not set — created admin user '%s' with the default "
            "password '%s'. You will be required to change it on first login. Set "
            "MEMAR_ADMIN_PASSWORD in the environment to skip the default entirely.",
            username,
            DEFAULT_ADMIN_PASSWORD,
        )

    # Hash and create user
    password_hash = hash_password(password)
    admin_user = User(
        username=username,
        password_hash=password_hash,
        role="admin",
        is_active=True,
        must_change_password=must_change,
        auth_provider="local",
    )

    db.add(admin_user)
    await db.commit()
    logger.info(f"Created admin user: {username}")


# Route handlers (these will be integrated into main.py in Step 5)
async def login(db: AsyncSession, request: LoginRequest) -> TokenResponse:
    """
    Authenticate user and return access + refresh tokens.
    """
    # Find user
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        # Constant-time rejection: always verify to prevent timing oracle
        pwd_context.verify("dummy", _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Check if password auth is enabled for this user
    # enabled_auth_methods is NULL (default) = all methods enabled
    # enabled_auth_methods is a list = only those methods are allowed
    if user.enabled_auth_methods is not None and "password" not in user.enabled_auth_methods:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password login is disabled for this account. Please use an alternative auth method.",
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Create tokens
    access_token = create_access_token(
        user.id, user.username, user.role, user.must_change_password
    )
    refresh_token = create_refresh_token()

    # Hash and store refresh token
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_REFRESH_TTL_SECONDS)

    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(refresh_token_obj)
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        must_change_password=user.must_change_password,
    )


async def change_password(
    db: AsyncSession, user_id: int, request: ChangePasswordRequest
) -> TokenResponse:
    """
    Change the authenticated user's password and clear must_change_password.

    Verifies the current password, enforces a minimum length, refuses re-use of
    the current password or the shipped default, then rotates ALL refresh tokens
    so any session minted from the default credential is killed. Returns a fresh
    token pair (flag cleared) so the client stays signed in seamlessly.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    new_password = request.new_password
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if new_password == DEFAULT_ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must not be the default password",
        )
    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password",
        )

    # Update password, clear the forced-change flag
    user.password_hash = hash_password(new_password)
    user.must_change_password = False

    # Rotate refresh tokens: kill every existing session (incl. the default-cred one)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    for token in result.scalars().all():
        await db.delete(token)

    # Issue a fresh pair so the client stays signed in
    access_token = create_access_token(user.id, user.username, user.role, False)
    refresh_token = create_refresh_token()
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_REFRESH_TTL_SECONDS)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    ))
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        must_change_password=False,
    )


async def refresh_access_token(db: AsyncSession, request: RefreshRequest) -> TokenResponse:
    """
    Refresh access token using a valid refresh token.

    M4 BUG FIX: Single-statement atomicity. The original code had a TOCTOU window:
    read token → validate → delete old → create new. Two concurrent requests for the
    same token could both pass validation and both create new tokens. Fixed by using
    DELETE...WHERE with multiple conditions (not revoked, not expired, same hash) and
    RETURNING to get the user_id in a single atomic operation. Only the request whose
    DELETE actually removes the row succeeds; replayed tokens get 401.
    """
    # M4 FIX: Atomic delete-and-return. Only the request whose DELETE removes the
    # token gets a user_id back; all concurrent replays and retries get None → 401.
    token_hash = hashlib.sha256(request.refresh_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        delete(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > now,
        ).returning(RefreshToken.user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    user_id = row

    # Load user and create new tokens
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        # Token was valid but user is now gone/suspended — don't issue a replacement
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    access_token = create_access_token(
        user.id, user.username, user.role, user.must_change_password
    )
    new_refresh_token = create_refresh_token()

    new_token_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
    new_expires_at = now + timedelta(seconds=_REFRESH_TTL_SECONDS)

    new_refresh_token_obj = RefreshToken(
        user_id=user.id,
        token_hash=new_token_hash,
        expires_at=new_expires_at,
        revoked=False,
    )
    db.add(new_refresh_token_obj)
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        must_change_password=user.must_change_password,
    )


async def logout(db: AsyncSession, user_id: int) -> dict:
    """
    Revoke all refresh tokens for a user (logout all sessions).
    """
    # Delete all refresh tokens for this user
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    tokens = result.scalars().all()

    for token in tokens:
        await db.delete(token)

    await db.commit()
    return {"message": "Logged out"}
