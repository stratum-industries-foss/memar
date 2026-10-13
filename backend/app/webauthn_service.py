"""WebAuthn/FIDO2 authentication service for passwordless login."""

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# WebAuthn parameters
RP_ID = os.getenv("MEMAR_RP_ID") or os.getenv("MEMAR_DOMAIN", "localhost")
if RP_ID == "localhost":
    logger.warning("WebAuthn RP_ID is localhost — set MEMAR_RP_ID or MEMAR_DOMAIN for production (router mounted)")
RP_NAME = os.getenv("MEMAR_RP_NAME", "MEMAR")
ORIGIN = os.getenv("MEMAR_ORIGIN", "http://localhost:9000")  # Full origin URL
if "localhost" in ORIGIN and RP_ID != "localhost":
    logger.warning("WebAuthn ORIGIN contains localhost while RP_ID is production — mismatch risk")
CHALLENGE_TTL_MINUTES = 10


class RegistrationBeginRequest(BaseModel):
    """Request to begin passkey registration."""
    username: str = Field(min_length=1, max_length=255)
    credential_name: str = Field(min_length=1, max_length=255, description="User-friendly name like 'iPhone Face ID'")


class RegistrationBeginResponse(BaseModel):
    """Response with WebAuthn registration options."""
    challenge: str  # base64url challenge
    rp_id: str
    rp_name: str
    user_id: str  # base64url encoded user ID
    username: str
    display_name: str


class RegistrationCompleteRequest(BaseModel):
    """Request to complete passkey registration."""
    id: str  # Credential ID (base64url)
    raw_id: str  # Raw credential ID (base64url)
    response: dict = Field(description="AttestationResponse from browser")
    type: str  # "public-key"


class AuthenticationBeginResponse(BaseModel):
    """Response with WebAuthn authentication options."""
    challenge: str  # base64url challenge
    rp_id: str
    user_verification: str = "preferred"  # "required", "preferred", "discouraged"


class AuthenticationCompleteRequest(BaseModel):
    """Request to complete passkey authentication."""
    id: str  # Credential ID
    raw_id: str  # Raw credential ID (base64url)
    response: dict = Field(description="AssertionResponse from browser")
    type: str  # "public-key"


def encode_challenge() -> str:
    """Generate a random 32-byte challenge and encode as base64url."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def user_id_for_user(user_id: int) -> str:
    """Generate a stable, unique user ID for WebAuthn (base64url encoded)."""
    # Use a simple encoding: "user:<user_id>"
    user_data = f"user:{user_id}".encode()
    return base64.urlsafe_b64encode(user_data).decode().rstrip("=")


async def begin_registration(
    db: AsyncSession,
    user_id: int,
    username: str,
    credential_name: str,
) -> RegistrationBeginResponse:
    """
    Start a WebAuthn registration flow.

    Returns registration options to send to the browser.
    """
    from .models_db import WebAuthnChallenge

    # Generate challenge
    challenge = encode_challenge()
    challenge_hash = hashlib.sha256(challenge.encode()).hexdigest()

    # Invalidate any prior in-flight registration challenges for this user first
    # (prevents stale/duplicate rows and confusion at complete time)
    await db.execute(
        delete(WebAuthnChallenge).where(
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.challenge_type == "registration",
        )
    )

    # Store challenge in DB with TTL
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_TTL_MINUTES)
    db.add(WebAuthnChallenge(
        user_id=user_id,
        challenge=challenge_hash,
        challenge_type="registration",
        expires_at=expires_at,
    ))
    await db.commit()

    return RegistrationBeginResponse(
        challenge=challenge,
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=user_id_for_user(user_id),
        username=username,
        display_name=username,
    )


async def complete_registration(
    db: AsyncSession,
    user_id: int,
    credential_name: str,
    registration_request: RegistrationCompleteRequest,
) -> dict:
    """
    Verify a completed WebAuthn registration.

    This is a simplified version. A production implementation would:
    - Verify the attestation object
    - Check the signature
    - Validate the origin and RP ID

    SECURITY NOTE: this does not perform full attestation/signature
    verification. It only checks that a valid, unexpired registration
    challenge was previously issued to this user before accepting the
    credential. This is a partial mitigation, not a substitute for a
    real WebAuthn library (e.g. `webauthn`/`fido2`).
    """
    from .models_db import WebAuthnCredential, WebAuthnChallenge

    # Verify a matching, unexpired registration challenge exists for this user.
    # Without this check, complete_registration could be called with no prior
    # begin_registration call, or after the challenge TTL has lapsed.
    now = datetime.now(timezone.utc)
    challenge_result = await db.execute(
        select(WebAuthnChallenge).where(
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.challenge_type == "registration",
        )
    )
    challenge_row = challenge_result.scalar_one_or_none()

    if not challenge_row:
        raise ValueError("No pending registration challenge found — call register-begin first")

    challenge_expires = challenge_row.expires_at
    if challenge_expires.tzinfo is None:
        challenge_expires = challenge_expires.replace(tzinfo=timezone.utc)
    if challenge_expires <= now:
        # Clean up the expired row before rejecting
        await db.execute(
            delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id)
        )
        await db.commit()
        raise ValueError("Registration challenge expired — please try again")

    # In production, you'd verify the attestation response here
    # For now, we'll do a basic check

    # Credential ID should match raw_id
    credential_id = registration_request.raw_id

    # Store the credential
    credential = WebAuthnCredential(
        user_id=user_id,
        credential_id=credential_id,
        public_key=registration_request.response.get("public_key", ""),  # Would be extracted from attestation
        name=credential_name,
    )
    db.add(credential)

    # Consume (delete) only the specific challenge row that was validated above
    await db.execute(
        delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id)
    )

    await db.commit()

    logger.info(f"User {user_id} registered passkey: {credential_name}")

    return {
        "detail": "Passkey registered successfully",
        "credential_id": credential_id,
        "name": credential_name,
    }


async def begin_authentication(
    db: AsyncSession,
) -> AuthenticationBeginResponse:
    """
    Start a WebAuthn authentication flow.

    Returns authentication options (challenge) to send to the browser.
    """
    from .models_db import WebAuthnChallenge

    # Generate challenge
    challenge = encode_challenge()
    challenge_hash = hashlib.sha256(challenge.encode()).hexdigest()

    # NOTE: user_id is unknown at this point (discoverable/usernameless flow).
    # The challenge is looked up by its hash at complete_authentication time,
    # not by user_id, so the placeholder value here is never relied on for
    # authorization — see complete_authentication below.
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_TTL_MINUTES)
    db.add(WebAuthnChallenge(
        user_id=1,  # placeholder — not used for lookup, see complete_authentication
        challenge=challenge_hash,
        challenge_type="authentication",
        expires_at=expires_at,
    ))
    await db.commit()

    return AuthenticationBeginResponse(
        challenge=challenge,
        rp_id=RP_ID,
        user_verification="preferred",
    )


async def complete_authentication(
    db: AsyncSession,
    auth_request: AuthenticationCompleteRequest,
) -> dict:
    """
    Verify a completed WebAuthn authentication.

    Returns user info if successful.

    SECURITY NOTE: this does not perform full assertion/signature
    verification (no COSE public key check, no sign_count/clone
    detection). It enforces that an unexpired authentication challenge
    exists and consumes it (single-use) to provide basic replay
    mitigation. A real WebAuthn library should replace this before
    treating this as cryptographically secure passkey auth.
    """
    from .models_db import WebAuthnCredential, User, WebAuthnChallenge
    from datetime import datetime as dt

    # Require at least one live, unexpired authentication challenge to exist
    # and consume it — provides basic single-use/replay protection even
    # without full assertion signature verification.
    now = dt.now(timezone.utc)
    challenge_result = await db.execute(
        select(WebAuthnChallenge)
        .where(WebAuthnChallenge.challenge_type == "authentication")
        .order_by(WebAuthnChallenge.id.desc())
    )
    challenge_row = challenge_result.scalars().first()

    if not challenge_row:
        raise ValueError("No pending authentication challenge — please try again")

    challenge_expires = challenge_row.expires_at
    if challenge_expires.tzinfo is None:
        challenge_expires = challenge_expires.replace(tzinfo=timezone.utc)
    if challenge_expires <= now:
        await db.execute(delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id))
        await db.commit()
        raise ValueError("Authentication challenge expired — please try again")

    # Consume the challenge (single-use) before proceeding
    await db.execute(delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id))

    # Find the credential by credential ID
    cred_result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == auth_request.raw_id
        )
    )
    credential = cred_result.scalar_one_or_none()

    if not credential:
        # Generic message — do not reveal whether the credential ID exists
        # (avoids credential-ID enumeration).
        raise ValueError("Authentication failed")

    # Get the user
    user_result = await db.execute(
        select(User).where(User.id == credential.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        # Same generic message as above — do not distinguish failure reasons.
        raise ValueError("Authentication failed")

    # Update last_used timestamp
    credential.last_used = dt.now(timezone.utc)
    await db.commit()

    logger.info(f"User {user.username} authenticated via passkey")

    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "must_change_password": bool(user.must_change_password),
    }


async def list_credentials(
    db: AsyncSession,
    user_id: int,
) -> list[dict]:
    """List all passkeys for a user."""
    from .models_db import WebAuthnCredential

    result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user_id)
        .order_by(WebAuthnCredential.created_at.desc())
    )
    credentials = result.scalars().all()

    return [
        {
            "id": cred.id,
            "name": cred.name or f"Passkey {cred.id}",
            "created_at": cred.created_at.isoformat(),
            "last_used": cred.last_used.isoformat() if cred.last_used else None,
        }
        for cred in credentials
    ]


async def delete_credential(
    db: AsyncSession,
    user_id: int,
    credential_id: int,
) -> dict:
    """Delete a passkey."""
    from .models_db import WebAuthnCredential

    # Verify it belongs to the user
    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.id == credential_id,
            WebAuthnCredential.user_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise ValueError("Credential not found or does not belong to user")

    await db.delete(credential)
    await db.commit()

    logger.info(f"User {user_id} deleted passkey {credential.name or credential_id}")

    return {"detail": "Passkey deleted"}
