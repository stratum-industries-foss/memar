"""WebAuthn/FIDO2 authentication API endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .deps import get_current_user
from ._limiter import rate_limit
from .webauthn_service import (
    RegistrationBeginRequest,
    RegistrationBeginResponse,
    RegistrationCompleteRequest,
    AuthenticationBeginResponse,
    AuthenticationCompleteRequest,
    begin_registration,
    complete_registration,
    begin_authentication,
    complete_authentication,
    list_credentials,
    delete_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/webauthn", tags=["webauthn"])


@router.post("/register-begin", response_model=RegistrationBeginResponse)
@rate_limit("10/hour")
async def register_begin(
    body: RegistrationBeginRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegistrationBeginResponse:
    """
    Start a WebAuthn passkey registration.

    Returns registration options (challenge + config) to send to the browser.
    """
    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(401, "Authentication required")

        return await begin_registration(
            db=db,
            user_id=user_id,
            username=current_user.get("username", ""),
            credential_name=body.credential_name,
        )
    except HTTPException:
        raise  # Let FastAPI handle it
    except Exception as e:
        logger.error(f"Registration begin failed: {e}")
        raise HTTPException(500, "Registration setup failed")


@router.post("/register-complete")
@rate_limit("10/hour")
async def register_complete(
    body: RegistrationCompleteRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Complete a WebAuthn passkey registration.

    Verifies the attestation response and stores the credential.
    """
    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(401, "Authentication required")

        # Extract credential name from the request (would be in request metadata)
        credential_name = getattr(body, "name", "My Passkey")

        return await complete_registration(
            db=db,
            user_id=user_id,
            credential_name=credential_name,
            registration_request=body,
        )
    except HTTPException:
        raise  # Let FastAPI handle it
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Registration complete failed: {e}")
        raise HTTPException(500, "Registration verification failed")


@router.post("/authenticate-begin", response_model=AuthenticationBeginResponse)
@rate_limit("20/hour")
async def authenticate_begin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthenticationBeginResponse:
    """
    Start a WebAuthn passkey authentication.

    Returns authentication options (challenge + config) to send to the browser.
    Public endpoint (no auth required).
    """
    try:
        return await begin_authentication(db=db)
    except HTTPException:
        raise  # Let FastAPI handle it
    except Exception as e:
        logger.error(f"Authentication begin failed: {e}")
        raise HTTPException(500, "Authentication setup failed")


@router.post("/authenticate")
@rate_limit("20/hour")
async def authenticate(
    body: AuthenticationCompleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Complete a WebAuthn passkey authentication.

    Verifies the assertion response and returns access tokens if successful.
    Public endpoint (no auth required).
    """
    try:
        user_info = await complete_authentication(db=db, auth_request=body)

        # Generate JWT tokens
        from .auth import create_access_token, create_refresh_token

        access_token = create_access_token(
            user_info["user_id"],
            user_info["username"],
            user_info["role"],
            must_change_password=user_info.get("must_change_password", False),
        )
        refresh_token = create_refresh_token()

        # Store refresh token
        from .models_db import RefreshToken
        from datetime import datetime, timedelta, timezone
        import hashlib

        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        db.add(RefreshToken(
            user_id=user_info["user_id"],
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    except HTTPException:
        raise  # Let FastAPI handle it
    except ValueError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(500, "Authentication failed")


@router.get("/credentials")
async def list_user_credentials(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all passkeys registered for the current user."""
    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(401, "Authentication required")

        return await list_credentials(db=db, user_id=user_id)
    except HTTPException:
        raise  # Let FastAPI handle it
    except Exception as e:
        logger.error(f"Failed to list credentials: {e}")
        raise HTTPException(500, "Failed to list credentials")


@router.delete("/credentials/{credential_id}")
async def delete_user_credential(
    credential_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a passkey."""
    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(401, "Authentication required")

        return await delete_credential(db=db, user_id=user_id, credential_id=credential_id)
    except HTTPException:
        raise  # Let FastAPI handle it
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Failed to delete credential: {e}")
        raise HTTPException(500, "Failed to delete credential")
