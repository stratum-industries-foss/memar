"""FastAPI dependency factories for authentication and authorization."""

import logging
import os
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from .auth import decode_access_token
from .config import get_config
from .db import get_db
from .license import get_license
from .models import ALPHA_PROTOCOLS
from .models_db import AlphaControlAck, User


logger = logging.getLogger(__name__)


# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)


async def get_current_user_allow_pwchange(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Validate Bearer token and return current user info, WITHOUT enforcing the
    forced-password-change gate. Only the few endpoints a user must reach while
    locked out (whoami, logout, change-password) depend on this directly; every
    other route uses get_current_user, which adds the gate on top.

    The MEMAR_NO_AUTH dev bypass returns a default admin for every request. It
    is double-gated so it can never engage by accident in production: BOTH
    MEMAR_NO_AUTH and MEMAR_ENV=dev must be set. If MEMAR_NO_AUTH is set while
    MEMAR_ENV is anything other than 'dev', we log a loud error and ignore it
    (fail secure) rather than open the whole API.
    """
    if os.getenv("MEMAR_NO_AUTH", "").lower() in ("1", "true", "yes"):
        if os.getenv("MEMAR_ENV", "").lower() == "dev":
            return {"id": 1, "username": "admin", "role": "admin", "must_change_password": False}
        logger.error(
            "MEMAR_NO_AUTH is set but MEMAR_ENV != 'dev' — refusing to bypass "
            "auth. Unset MEMAR_NO_AUTH in production. Proceeding with normal auth."
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get('sub')
    if not user_id:
        raise HTTPException(status_code=401, detail='Invalid token claims')
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail='Invalid token subject')

    # Load the live user row so a suspension or role downgrade takes effect
    # immediately, instead of lingering until the access token expires (~15 min
    # stale-access window). Role is sourced from the DB, not the token claim.
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail='User no longer exists')
    if not user.is_active:
        raise HTTPException(status_code=403, detail='Account suspended')

    return {
        "id": user_id,
        "username": user.username,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }


async def get_current_user(
    user: dict = Depends(get_current_user_allow_pwchange),
) -> dict:
    """
    Standard auth dependency for protected routes. Identical to
    get_current_user_allow_pwchange but additionally refuses the request (403)
    while the user still owes a forced password change. This is the server-side
    half of the forced-change flow — a UI modal alone would be bypassable, since
    the access token is already valid. The distinct detail code lets the frontend
    route the user to the change-password screen instead of logging them out.
    """
    if user.get("must_change_password"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_change_required",
        )
    return user


def require_role(*roles: str) -> Callable:
    """
    Dependency factory: returns a Depends that checks user role.

    Usage:
        @app.get("/admin-only")
        async def admin_route(_: dict = require_role("admin")):
            ...

        @app.get("/operator-or-admin")
        async def op_route(_: dict = require_role("admin", "operator")):
            ...
    """

    def _check(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(roles)}",
            )
        return current_user

    return _check


def require_feature(feature: str) -> Callable:
    """
    Dependency factory: returns a Depends that checks license feature.

    Usage:
        @app.get("/oee")
        async def oee_route(_: None = require_feature("oee")):
            ...
    """

    def _check():
        lic = get_license()
        # An expired or revoked key 402s here regardless of tier.
        if not lic.active:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Feature '{feature}' requires an active license.",
            )
        # Free tier no longer includes every feature (see
        # license._tier_to_features) — this is the actual per-feature gate.
        if feature not in lic.features:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Feature '{feature}' requires a paid plan.",
            )

    return _check


async def require_alpha_ack(
    device_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Gate for control routes (feed-rate, gcode, home, jog) targeting a device on
    an ALPHA_PROTOCOLS adapter — one that self-documents as unverified against
    real hardware. No-ops for every other device. The distinct detail code lets
    the frontend show the liability acknowledgment modal instead of a generic
    error, same handshake as get_current_user's password_change_required.

    Deliberately NOT applied to emergency_stop — gating a device's first-ever
    E-stop behind a confirmation modal is exactly the "throttled or delayed
    E-stop" the estop route's own docstring calls a safety bug. E-stop stays
    ungated and always dispatches; it surfaces the same unverified-hardware
    risk honestly in its response instead (see cnc_routes.cnc_emergency_stop).
    """
    cfg = get_config()
    printer = next((p for p in cfg.printers if p.id == device_id), None)
    if printer is None or printer.protocol not in ALPHA_PROTOCOLS:
        return current_user

    result = await db.execute(
        select(AlphaControlAck).where(
            AlphaControlAck.user_id == current_user["id"],
            AlphaControlAck.device_id == device_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="alpha_ack_required",
        )
    return current_user
