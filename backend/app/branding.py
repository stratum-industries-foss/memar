"""White-label branding (Scale+ tier).

Stores a single branding row (company name / logo / colour / support email) and
exposes it. Branding is applied ONLY when the license carries `custom_branding`;
otherwise everything falls back to MEMAR defaults — so a downgrade can never
leave a half-rebranded instance, and the public GET is always safe to call.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .deps import require_feature, require_role
from .license import get_license
from .models_db import Branding

logger = logging.getLogger(__name__)

DEFAULT_BRANDING = {
    "company_name": "MEMAR",
    "logo_url": None,
    "primary_color": "#00a046",
    "support_email": None,
    "custom": False,
}


async def get_effective_branding(db: AsyncSession) -> dict:
    """Active branding: stored values if custom_branding is licensed AND a row
    exists, else MEMAR defaults. Always safe (never raises)."""
    lic = get_license()
    if not (lic.active and "custom_branding" in lic.features):
        return dict(DEFAULT_BRANDING)
    row = (await db.execute(select(Branding).where(Branding.id == 1))).scalar_one_or_none()
    if row is None:
        return dict(DEFAULT_BRANDING)
    return {
        "company_name": row.company_name or DEFAULT_BRANDING["company_name"],
        "logo_url": row.logo_url,
        "primary_color": row.primary_color or DEFAULT_BRANDING["primary_color"],
        "support_email": row.support_email,
        "custom": True,
    }


branding_router = APIRouter(tags=["branding"])


@branding_router.get("/api/branding")
async def get_branding(db: AsyncSession = Depends(get_db)) -> dict:
    """Public — the UI reads this to render the instance's brand."""
    return await get_effective_branding(db)


class BrandingUpdate(BaseModel):
    company_name: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None, max_length=2048)
    primary_color: str | None = Field(default=None, max_length=32)
    support_email: str | None = Field(default=None, max_length=255)


@branding_router.put("/api/admin/branding")
async def update_branding(
    body: BrandingUpdate,
    _: dict = Depends(require_role("admin")),
    __: None = Depends(require_feature("custom_branding")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set branding (admin + custom_branding tier). Only provided fields change."""
    # T60: logo_url must use HTTPS only
    if body.logo_url and not body.logo_url.startswith("https://"):
        raise HTTPException(400, "logo_url must use HTTPS")
    row = (await db.execute(select(Branding).where(Branding.id == 1))).scalar_one_or_none()
    if row is None:
        row = Branding(id=1)
        db.add(row)
    for field in ("company_name", "logo_url", "primary_color", "support_email"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await db.commit()
    return await get_effective_branding(db)
