"""Admin API for the Unified Messaging Hub.

Routes:
  GET    /api/admin/messaging/status             — adapter health
  GET    /api/admin/messaging/identities         — list linked identities
  POST   /api/admin/messaging/identities         — link a platform user
  DELETE /api/admin/messaging/identities/{id}   — unlink
  POST   /api/admin/messaging/test               — send a test alert (admin)
  POST   /api/messaging/mattermost/command       — inbound slash command (verified via MEMAR_MATTERMOST_COMMAND_TOKEN)
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .deps import require_role
from .models_db import MessagingIdentity, User

logger = logging.getLogger(__name__)

messaging_admin_router = APIRouter(tags=["messaging-admin"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class IdentityCreate(BaseModel):
    platform: str           # telegram | slack | discord | mattermost | matrix
    platform_user_id: str
    username: str           # MEMAR username to link


class IdentityOut(BaseModel):
    id: int
    platform: str
    platform_user_id: str
    username: str | None
    memar_role: str | None
    created_at: str | None


# ---------------------------------------------------------------------------
# Adapter status
# ---------------------------------------------------------------------------


@messaging_admin_router.get("/api/admin/messaging/status")
async def messaging_status(_: dict = Depends(require_role("admin"))) -> dict:
    """Return per-adapter health: enabled, bidirectional, last delivery."""
    from .messaging import get_hub
    hub = get_hub()
    return {"adapters": hub.adapter_status()}


# ---------------------------------------------------------------------------
# Identity management
# ---------------------------------------------------------------------------


@messaging_admin_router.get("/api/admin/messaging/identities")
async def list_identities(
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[IdentityOut]:
    rows = (await db.execute(select(MessagingIdentity))).scalars().all()
    result = []
    for row in rows:
        user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
        result.append(IdentityOut(
            id=row.id,
            platform=row.platform,
            platform_user_id=row.platform_user_id,
            username=user.username if user else None,
            memar_role=user.role if user else None,
            created_at=row.created_at.isoformat() + "Z" if row.created_at else None,
        ))
    return result


@messaging_admin_router.post("/api/admin/messaging/identities", status_code=201)
async def create_identity(
    body: IdentityCreate,
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Link a platform user ID to a MEMAR user account."""
    valid_platforms = {"telegram", "slack", "discord", "mattermost", "matrix"}
    if body.platform not in valid_platforms:
        raise HTTPException(400, f"platform must be one of: {', '.join(sorted(valid_platforms))}")
    if not body.platform_user_id.strip():
        raise HTTPException(400, "platform_user_id must not be empty")

    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, f"MEMAR user '{body.username}' not found")

    existing = (
        await db.execute(
            select(MessagingIdentity).where(
                MessagingIdentity.platform == body.platform,
                MessagingIdentity.platform_user_id == body.platform_user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "This platform_user_id is already linked")

    identity = MessagingIdentity(
        user_id=user.id,
        platform=body.platform,
        platform_user_id=body.platform_user_id,
    )
    db.add(identity)
    await db.commit()
    await db.refresh(identity)
    return {
        "id": identity.id,
        "platform": identity.platform,
        "platform_user_id": identity.platform_user_id,
        "username": user.username,
        "memar_role": user.role,
    }


@messaging_admin_router.delete("/api/admin/messaging/identities/{identity_id}")
async def delete_identity(
    identity_id: int,
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(select(MessagingIdentity).where(MessagingIdentity.id == identity_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Identity not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Test broadcast (admin)
# ---------------------------------------------------------------------------


class TestAlertBody(BaseModel):
    title: str = "MEMAR test alert"
    body: str = "This is a test notification from MEMAR."
    severity: str = "info"


@messaging_admin_router.post("/api/admin/messaging/test")
async def test_broadcast(
    body: TestAlertBody,
    _: dict = Depends(require_role("admin")),
) -> dict:
    """Send a test AlertEvent to all configured adapters."""
    from .messaging import get_hub, AlertEvent
    event = AlertEvent(
        type="test.alert",
        title=body.title,
        body=body.body,
        severity=body.severity,
        data={},
    )
    hub = get_hub()
    await hub.broadcast(event)
    return {"ok": True, "adapters": len(hub._adapters)}


# ---------------------------------------------------------------------------
# Mattermost inbound slash command endpoint
# ---------------------------------------------------------------------------


class MattermostSlashPayload(BaseModel):
    command: str = ""
    text: str = ""
    user_id: str = ""
    channel_id: str = ""
    token: str = ""


@messaging_admin_router.post("/api/messaging/mattermost/command")
async def mattermost_slash_command(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a Mattermost slash command and return a response payload."""
    form = await request.form()
    cmd = str(form.get("command", "")).lstrip("/").lower()
    text = str(form.get("text", "")).strip()
    user_id = str(form.get("user_id", ""))
    channel_id = str(form.get("channel_id", ""))
    token = str(form.get("token", ""))

    expected_token = os.getenv("MEMAR_MATTERMOST_COMMAND_TOKEN", "").strip()
    if not expected_token or not hmac.compare_digest(token, expected_token):
        logger.warning("Rejected Mattermost slash command: missing/invalid token")
        raise HTTPException(status_code=403, detail="Invalid or unconfigured command token")

    from .messaging import get_hub
    hub = get_hub()

    # Find Mattermost adapter's command router
    router = hub._command_router
    if router is None:
        return {"response_type": "ephemeral", "text": "Messaging hub not initialized."}

    args = text.split() if text else []
    try:
        response_text = await router.dispatch(cmd, args, user_id, "mattermost")
    except Exception as exc:
        logger.exception("Mattermost command dispatch error")
        response_text = f"Error: {exc}"

    return {
        "response_type": "in_channel",
        "text": f"```\n{response_text}\n```",
    }
