"""First-run setup: the owner creates the first admin account in the browser.

GET  /api/setup/status  - is this instance claimed, and is a setup code needed?
POST /api/setup/claim   - create the first admin (once), returns a token pair.

Policy lives in firstrun.py (MEMAR_SETUP_MODE auto|open|code).

Note: no `from __future__ import annotations` here. With postponed annotations
FastAPI 0.115 cannot resolve the `ClaimRequest` body model at the floor-pinned
versions and treats it as a missing query parameter (every claim returns 422).
"""

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import firstrun
from ._limiter import rate_limit
from .audit import client_ip, record_audit
from . import setup_failures
from .auth import TokenResponse, hash_password, is_claimed, issue_tokens
from .db import get_db
from .models_db import User

logger = logging.getLogger(__name__)

setup_router = APIRouter(prefix="/api/setup", tags=["setup"])

SETUP_MIN_PASSWORD = 10
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
_claim_lock = asyncio.Lock()


class ClaimRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=32)


def _where_is_the_code() -> list[str]:
    hints = ["The link printed at the end of the installer"]
    if firstrun.in_container():
        hints.insert(0, "Docker: run  docker logs memar  (or open the container's log in your NAS app)")
        hints.append("Or run: docker exec memar memar setup-link")
    else:
        hints.insert(0, "On the MEMAR computer, run:  sudo memar setup-link")
    return hints


@setup_router.get("/status")
async def setup_status(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    if await is_claimed(db):
        return {"claimed": True}
    mode = firstrun.setup_mode()
    # Tell this caller only what applies to them; the exact window remaining is
    # not published to unauthenticated clients.
    return {
        "claimed": False,
        "mode": mode,
        "code_required": firstrun.code_required(client_ip(request)),
        "window_seconds_left": (
            (firstrun.window_seconds_left() // 60) * 60 if mode == "auto" else None
        ),
        "where_is_the_code": _where_is_the_code(),
    }


@setup_router.post("/claim", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
@rate_limit("30/minute")
async def setup_claim(
    request: Request,
    body: ClaimRequest,
    db: AsyncSession = Depends(get_db),
):
    username = body.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3-64 characters: letters, numbers, and . _ @ -",
        )
    if len(body.password) < SETUP_MIN_PASSWORD:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {SETUP_MIN_PASSWORD} characters.",
        )
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Password must be at most 72 bytes (about 72 ASCII characters).")
    if body.password.strip().lower() in ("admin", "password", username.lower()):
        raise HTTPException(status_code=422, detail="Please choose a less guessable password.")

    key = client_ip(request) or "unknown"
    wait = setup_failures.check(key)
    if wait > 0:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(int(wait) + 1)},
            content={"detail": "too_many_attempts"},
        )

    async with _claim_lock:
        if await is_claimed(db):
            return JSONResponse(status_code=409, content={"detail": "already_claimed"})

        if body.code:
            # A code that was supplied must be right, even when none is required.
            if not firstrun.verify_setup_code(body.code):
                setup_failures.record_failure(key)
                return JSONResponse(status_code=403, content={"detail": "code_invalid"})
        elif firstrun.code_required(client_ip(request)):
            setup_failures.record_failure(key)
            return JSONResponse(status_code=403, content={"detail": "code_required"})

        user = User(
            username=username,
            password_hash=hash_password(body.password),
            role="admin",
            is_active=True,
            must_change_password=False,
            auth_provider="local",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        firstrun.clear_setup_code()

    tokens = await issue_tokens(db, user)
    await record_audit(
        db,
        action="setup.claim",
        user={"id": user.id, "username": user.username},
        resource="setup",
        detail={"mode": firstrun.setup_mode(), "with_code": bool(body.code)},
        request=request,
    )
    logger.info("Setup complete: admin account '%s' created", username)
    return tokens
