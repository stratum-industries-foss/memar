"""SAML 2.0 routes: start login (redirect to the IdP) and the assertion consumer (ACS).

Mirrors the OIDC flow in sso.py: the same feature gate ("sso"), the same
account-provisioning path (provider="saml", so a SAML name can never sign in to
a local account), and the same token hand-off in the URL fragment.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import saml_service
from .db import get_db
from .deps import require_feature, require_role
from .models_db import SSOSettings
from .firstrun import public_base_url
from .sso import _provision_and_issue

logger = logging.getLogger(__name__)

saml_router = APIRouter(prefix="/api/auth/saml", tags=["sso"])
_LOGIN_FAILED = "SAML sign-in failed. Ask your administrator to check the identity provider settings."


async def _config(db: AsyncSession, request: Request) -> saml_service.SamlConfig:
    s = (await db.execute(select(SSOSettings).where(SSOSettings.id == 1))).scalar_one_or_none()
    if s is None or not (s.saml_idp_sso_url and s.saml_idp_cert_pem and s.saml_idp_entity_id):
        raise HTTPException(status_code=503, detail="SAML is not configured")
    # Same base as OIDC (firstrun.public_base_url): the address the browser really uses,
    # not the request's internal address, which is wrong behind a port mapping or proxy.
    base = public_base_url().rstrip("/")
    return saml_service.SamlConfig(
        idp_entity_id=s.saml_idp_entity_id,
        idp_sso_url=s.saml_idp_sso_url,
        idp_cert_pem=s.saml_idp_cert_pem,
        sp_entity_id=s.saml_sp_entity_id or f"{base}/api/auth/saml/metadata",
        sp_acs_url=f"{base}/api/auth/saml/acs",
    )


@saml_router.get("/login")
async def saml_login(request: Request, db: AsyncSession = Depends(get_db),
                     _: None = Depends(require_feature("sso"))) -> RedirectResponse:
    cfg = await _config(db, request)
    url, _req_id = saml_service.build_authn_request(cfg)
    return RedirectResponse(url, status_code=302)


@saml_router.post("/acs")
async def saml_acs(request: Request, SAMLResponse: str = Form(...), db: AsyncSession = Depends(get_db),
                   _: None = Depends(require_feature("sso"))) -> RedirectResponse:
    """Assertion consumer. Any failure returns the same generic message; the
    specific reason is logged on the server only."""
    cfg = await _config(db, request)
    try:
        identity = saml_service.process_response(cfg, SAMLResponse)
    except saml_service.SamlError as exc:
        logger.warning("SAML response rejected: %s", exc)
        raise HTTPException(status_code=401, detail=_LOGIN_FAILED)
    issued = await _provision_and_issue(db, username=identity["username"], provider="saml")
    base = public_base_url().rstrip("/")
    # Same fragment names as the OIDC callback (sso.py): the frontend reads sso_access / sso_refresh.
    frag = urlencode({"sso_access": issued["access_token"], "sso_refresh": issued["refresh_token"]})
    return RedirectResponse(f"{base}/#{frag}", status_code=302)


@saml_router.get("/metadata")
async def saml_metadata(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """The service-provider settings an administrator gives the IdP."""
    cfg = await _config(db, request)
    return {"entity_id": cfg.sp_entity_id, "acs_url": cfg.sp_acs_url, "binding": "HTTP-POST"}
