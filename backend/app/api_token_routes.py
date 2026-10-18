"""Admin endpoints for personal API tokens.

POST   /api/admin/api-tokens          create; the plaintext token is returned once
GET    /api/admin/api-tokens          list (never includes the token value)
DELETE /api/admin/api-tokens/{id}     revoke

Admin only. A token acts as its owner, with the scope it was created with.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .api_tokens import create_token
from .db import get_db
from .deps import require_role
from .models_db import ApiToken, User

api_token_router = APIRouter(prefix="/api/admin/api-tokens", tags=["api-tokens"])


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["read", "full"] = "read"
    owner_user_id: int | None = None      # default: the admin creating it
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


def _public(row: ApiToken, owner: User | None) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "scope": row.scope,
        "owner": owner.username if owner else None,
        "owner_user_id": row.user_id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked": row.revoked,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@api_token_router.post("", status_code=201)
async def create_api_token(body: ApiTokenCreate, db: AsyncSession = Depends(get_db),
                           admin: dict = Depends(require_role("admin"))) -> dict:
    owner_id = body.owner_user_id or admin["id"]
    owner = (await db.execute(select(User).where(User.id == owner_id))).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="owner user not found")
    if not owner.is_active:
        raise HTTPException(status_code=400, detail="owner account is suspended")
    row, plaintext = await create_token(db, owner=owner, name=body.name, scope=body.scope,
                                        days=body.expires_in_days)
    await db.commit()
    out = _public(row, owner)
    out["token"] = plaintext  # shown once; it is not stored and cannot be retrieved again
    return out


@api_token_router.get("")
async def list_api_tokens(db: AsyncSession = Depends(get_db),
                          _: dict = Depends(require_role("admin"))) -> list[dict]:
    rows = (await db.execute(select(ApiToken).order_by(ApiToken.id.desc()))).scalars().all()
    owners = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
    return [_public(r, owners.get(r.user_id)) for r in rows]


@api_token_router.delete("/{token_id}")
async def revoke_api_token(token_id: int, db: AsyncSession = Depends(get_db),
                           _: dict = Depends(require_role("admin"))) -> dict:
    row = (await db.execute(select(ApiToken).where(ApiToken.id == token_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="token not found")
    row.revoked = True
    await db.commit()
    return {"id": row.id, "revoked": True}
