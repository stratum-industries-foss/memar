"""SSO login — OpenID Connect (OIDC) and LDAP.

Both are gated behind the `sso` feature (Farm+). OIDC needs only httpx +
python-jose (already deps). LDAP uses ldap3, imported lazily so the app runs
fine without it until LDAP is actually configured and the dependency installed.

OIDC env:
  MEMAR_OIDC_ISSUER          e.g. https://accounts.google.com
  MEMAR_OIDC_CLIENT_ID
  MEMAR_OIDC_CLIENT_SECRET
  MEMAR_OIDC_REDIRECT_URI    must equal this instance's /api/auth/sso/oidc/callback URL
LDAP env:
  MEMAR_LDAP_SERVER          e.g. ldap://ldap.example.com
  MEMAR_LDAP_USER_DN_TEMPLATE  e.g. uid={username},ou=people,dc=example,dc=com
  MEMAR_LDAP_DEFAULT_ROLE    role for LDAP users (default: viewer)
Common:
  MEMAR_PUBLIC_URL           SPA base URL to redirect back to after OIDC
  MEMAR_SSO_DEFAULT_ROLE     role for newly-provisioned SSO users (default: viewer)
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import (ALGORITHM, JWT_SECRET, REFRESH_TOKEN_EXPIRE_DAYS,
                   create_access_token, create_refresh_token, hash_password)
from ._limiter import rate_limit
from .db import get_db
from .deps import require_feature, require_role
from .license import get_license
from .models_db import RefreshToken, SSOSettings, User

logger = logging.getLogger(__name__)

sso_router = APIRouter(prefix="/api/auth/sso", tags=["sso"])
sso_admin_router = APIRouter(prefix="/api/admin/sso", tags=["sso-admin"])

_STATE_TTL_S = 300


async def _sso_settings(db: AsyncSession) -> SSOSettings | None:
    return (await db.execute(select(SSOSettings).where(SSOSettings.id == 1))).scalar_one_or_none()


def _resolve(db_value: str | None, env_key: str) -> str | None:
    """DB value wins when set (non-empty); otherwise fall back to the env var."""
    return db_value if db_value else os.getenv(env_key)


async def _oidc_settings(db: AsyncSession) -> dict:
    s = await _sso_settings(db)
    return {
        "issuer": _resolve(s.oidc_issuer if s else None, "MEMAR_OIDC_ISSUER"),
        "client_id": _resolve(s.oidc_client_id if s else None, "MEMAR_OIDC_CLIENT_ID"),
        "client_secret": _resolve(s.oidc_client_secret if s else None, "MEMAR_OIDC_CLIENT_SECRET"),
        "redirect_uri": _resolve(s.oidc_redirect_uri if s else None, "MEMAR_OIDC_REDIRECT_URI"),
    }


async def _ldap_settings(db: AsyncSession) -> dict:
    s = await _sso_settings(db)
    return {
        "server": _resolve(s.ldap_server if s else None, "MEMAR_LDAP_SERVER"),
        "dn_template": _resolve(s.ldap_user_dn_template if s else None, "MEMAR_LDAP_USER_DN_TEMPLATE"),
        "default_role": _resolve(s.ldap_default_role if s else None, "MEMAR_LDAP_DEFAULT_ROLE") or "viewer",
    }


@sso_router.get("/config")
async def sso_config(db: AsyncSession = Depends(get_db)) -> dict:
    """Public — which SSO methods this instance has configured AND licensed, so the
    login screen shows only the buttons that will actually work."""
    lic = get_license()
    licensed = lic.active and "sso" in lic.features
    oidc = await _oidc_settings(db)
    ldap = await _ldap_settings(db)
    return {
        "oidc": bool(licensed and oidc["issuer"] and oidc["client_id"]),
        "ldap": bool(licensed and ldap["server"] and ldap["dn_template"]),
    }


# ── Admin: DB-editable SSO settings (falls back to env vars when unset) ────────

class SSOSettingsUpdate(BaseModel):
    """All fields optional/partial-update. For a field: omit = leave unchanged,
    "" (empty string) = clear the DB override (revert to env var default),
    non-empty = set. Mirrors the printer api_key write-only "blank = keep,
    explicit clear" convention already used elsewhere in this app."""
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    ldap_server: str | None = None
    ldap_user_dn_template: str | None = None
    ldap_default_role: str | None = None
    sso_default_role: str | None = None


@sso_admin_router.get("/settings")
async def get_sso_settings(db: AsyncSession = Depends(get_db),
                           _: dict = Depends(require_role("admin"))) -> dict:
    """Admin-only. Secret fields are never returned — only a *_set boolean."""
    s = await _sso_settings(db)
    return {
        "oidc_issuer": (s.oidc_issuer if s else None) or "",
        "oidc_client_id": (s.oidc_client_id if s else None) or "",
        "oidc_client_secret_set": bool(s and s.oidc_client_secret),
        "oidc_redirect_uri": (s.oidc_redirect_uri if s else None) or "",
        "ldap_server": (s.ldap_server if s else None) or "",
        "ldap_user_dn_template": (s.ldap_user_dn_template if s else None) or "",
        "ldap_default_role": (s.ldap_default_role if s else None) or "",
        "sso_default_role": (s.sso_default_role if s else None) or "",
        "env_defaults": {
            "oidc_issuer_set": bool(os.getenv("MEMAR_OIDC_ISSUER")),
            "oidc_client_id_set": bool(os.getenv("MEMAR_OIDC_CLIENT_ID")),
            "oidc_client_secret_set": bool(os.getenv("MEMAR_OIDC_CLIENT_SECRET")),
            "ldap_server_set": bool(os.getenv("MEMAR_LDAP_SERVER")),
            "ldap_user_dn_template_set": bool(os.getenv("MEMAR_LDAP_USER_DN_TEMPLATE")),
        },
    }


@sso_admin_router.put("/settings")
async def put_sso_settings(body: SSOSettingsUpdate, db: AsyncSession = Depends(get_db),
                           _: dict = Depends(require_role("admin"))) -> dict:
    s = await _sso_settings(db)
    if s is None:
        s = SSOSettings(id=1)
        db.add(s)

    def _apply(field: str, value: str | None) -> None:
        if value is None:
            return  # omitted — leave unchanged
        setattr(s, field, value or None)  # "" clears back to env fallback

    _apply("oidc_issuer", body.oidc_issuer)
    _apply("oidc_client_id", body.oidc_client_id)
    _apply("oidc_client_secret", body.oidc_client_secret)
    _apply("oidc_redirect_uri", body.oidc_redirect_uri)
    _apply("ldap_server", body.ldap_server)
    _apply("ldap_user_dn_template", body.ldap_user_dn_template)
    _apply("ldap_default_role", body.ldap_default_role)
    _apply("sso_default_role", body.sso_default_role)

    await db.commit()
    return await get_sso_settings(db=db, _=None)


async def _provision_and_issue(db: AsyncSession, *, username: str, provider: str, role: str | None = None) -> dict:
    """Find-or-create an SSO/LDAP user, then issue MEMAR access + refresh tokens.

    `provider` ("oidc" or "ldap") scopes the lookup: an SSO login only ever
    matches a user row provisioned by that SAME provider. Without this, an
    IdP-asserted or LDAP-bound identity whose username collides with a
    pre-existing LOCAL-password account (including admin) would log straight
    into that account — full takeover, no password. If the username exists
    under a different provider, this rejects rather than silently reusing it;
    there's no account-linking flow, so a collision needs a human to resolve.
    """
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing is not None and existing.auth_provider != provider:
        raise HTTPException(
            status_code=409,
            detail="An account with this username/email already exists via a different sign-in method. Contact an admin.",
        )
    user = existing
    if user is None:
        default_role = role
        if default_role is None:
            settings = await _sso_settings(db)
            default_role = _resolve(settings.sso_default_role if settings else None, "MEMAR_SSO_DEFAULT_ROLE") or "viewer"
        user = User(
            username=username,
            # SSO users authenticate via the IdP — store an unusable random hash.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=default_role,
            is_active=True,
            auth_provider=provider,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")

    access = create_access_token(user.id, user.username, user.role)
    refresh = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        revoked=False,
    ))
    await db.commit()
    return {"access_token": access, "refresh_token": refresh,
            "user": {"id": user.id, "username": user.username, "role": user.role}}


# ── OIDC ─────────────────────────────────────────────────────────────────────

async def _oidc_conf(db: AsyncSession) -> dict:
    resolved = await _oidc_settings(db)
    cfg = {
        "issuer": (resolved["issuer"] or "").rstrip("/"),
        "client_id": resolved["client_id"],
        "client_secret": resolved["client_secret"],
        "redirect_uri": resolved["redirect_uri"],
    }
    if not all(cfg.values()):
        raise HTTPException(status_code=503, detail="OIDC is not configured on this instance")
    return cfg


async def _oidc_discover(issuer: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{issuer}/.well-known/openid-configuration")
        r.raise_for_status()
        return r.json()


async def _oidc_jwks(jwks_uri: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(jwks_uri)
        r.raise_for_status()
        return r.json()


async def _oidc_token(disc: dict, conf: dict, code: str) -> dict:
    """Exchange the authorization code for tokens at the provider token endpoint."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(disc["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": conf["redirect_uri"],
            "client_id": conf["client_id"],
            "client_secret": conf["client_secret"],
        })
        r.raise_for_status()
        return r.json()


def _make_state() -> tuple[str, str]:
    nonce = secrets.token_urlsafe(16)
    state = jwt.encode(
        {"nonce": nonce,
         "exp": datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_S)},
        JWT_SECRET, algorithm=ALGORITHM)
    return state, nonce


def _check_state(state: str) -> str:
    """Verify state JWT and return the embedded nonce."""
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[ALGORITHM])
        return payload["nonce"]
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired SSO state")


@sso_router.get("/oidc/login")
async def oidc_login(db: AsyncSession = Depends(get_db),
                     _: None = Depends(require_feature("sso"))) -> RedirectResponse:
    conf = await _oidc_conf(db)
    disc = await _oidc_discover(conf["issuer"])
    state, nonce = _make_state()
    params = {
        "client_id": conf["client_id"],
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": conf["redirect_uri"],
        "state": state,
        "nonce": nonce,
    }
    return RedirectResponse(disc["authorization_endpoint"] + "?" + urlencode(params), status_code=302)


@sso_router.get("/oidc/callback")
async def oidc_callback(code: str, state: str, db: AsyncSession = Depends(get_db),
                        _: None = Depends(require_feature("sso"))) -> RedirectResponse:
    nonce = _check_state(state)
    conf = await _oidc_conf(db)
    disc = await _oidc_discover(conf["issuer"])
    id_token = (await _oidc_token(disc, conf, code)).get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="OIDC provider returned no id_token")
    jwks_uri = disc.get("jwks_uri")
    if not jwks_uri:
        raise HTTPException(status_code=503, detail="OIDC provider does not advertise a JWKS URI")
    jwks_data = await _oidc_jwks(jwks_uri)
    # Select key by kid if present, else use first available key
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    keys = jwks_data.get("keys", [])
    key_data = next((k for k in keys if k.get("kid") == kid), None) if kid else (keys[0] if keys else None)
    if not key_data:
        raise HTTPException(status_code=400, detail="OIDC JWKS: no matching key for id_token")
    try:
        claims = jwt.decode(
            id_token,
            key_data,
            algorithms=["RS256", "ES256", "PS256"],
            audience=conf["client_id"],
            issuer=conf["issuer"],
        )
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=f"OIDC id_token verification failed: {exc}")
    if not claims.get("nonce") or claims["nonce"] != nonce:
        raise HTTPException(status_code=400, detail="OIDC nonce mismatch")
    # Only trust the email claim as an identity if the IdP marked it verified —
    # a misconfigured or self-signup IdP can otherwise let an attacker assert
    # an arbitrary (including an existing local user's) email address. This is
    # belt-and-suspenders on top of the provider-scoped lookup in
    # _provision_and_issue: even a verified email can never match a
    # different-provider account, but an unverified one shouldn't even try.
    email_verified = claims.get("email_verified") is True or claims.get("email_verified") == "true"
    email = claims.get("email") if email_verified else None
    username = email or (f"oidc:{claims['sub']}" if claims.get("sub") else None)
    if not username:
        raise HTTPException(status_code=400, detail="OIDC token missing a verified email or sub claim")
    issued = await _provision_and_issue(db, username=username, provider="oidc")
    base = os.getenv("MEMAR_PUBLIC_URL", "http://localhost:9000").rstrip("/")
    frag = urlencode({"sso_access": issued["access_token"], "sso_refresh": issued["refresh_token"]})
    return RedirectResponse(f"{base}/#{frag}", status_code=302)


# ── LDAP ─────────────────────────────────────────────────────────────────────

class LdapLoginRequest(BaseModel):
    username: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=1024)


def _escape_ldap_dn_value(value: str) -> str:
    """RFC 4514 DN-value escaping for untrusted input used to build a bind DN.

    ldap3 does not escape values passed via `user=`; without this, a username
    containing `,`/`+`/`"`/`\\`/`<`/`>`/`;` (or a leading `#`/space) can alter
    the RDN sequence the server actually sees.
    """
    out = []
    for i, ch in enumerate(value):
        if ch in ',+"\\<>;':
            out.append("\\" + ch)
        elif ch == "#" and i == 0:
            out.append("\\#")
        elif ch == " " and (i == 0 or i == len(value) - 1):
            out.append("\\ ")
        elif ch == "\x00":
            out.append("\\00")
        else:
            out.append(ch)
    return "".join(out)


@sso_router.post("/ldap/login")
@rate_limit("10/minute")
async def ldap_login(body: LdapLoginRequest, request: Request, db: AsyncSession = Depends(get_db),
                     _: None = Depends(require_feature("sso"))) -> dict:
    ldap_cfg = await _ldap_settings(db)
    server_url = ldap_cfg["server"]
    dn_template = ldap_cfg["dn_template"]
    if not server_url or not dn_template:
        raise HTTPException(status_code=503, detail="LDAP is not configured on this instance")
    # RFC 4513 "unauthenticated bind": a SIMPLE bind with a zero-length
    # password authenticates NOTHING but some directories (older OpenLDAP,
    # misconfigured AD) still return success for it. ldap3 has no client-side
    # guard against this, so reject empty/whitespace passwords ourselves
    # before ever constructing the Connection — do not rely on the directory
    # to have unauthenticated-bind disabled.
    if not body.password.strip():
        raise HTTPException(status_code=401, detail="Invalid LDAP credentials")
    try:
        import ldap3
    except ImportError:
        raise HTTPException(status_code=503, detail="LDAP support is not installed (ldap3)")

    user_dn = dn_template.format(username=_escape_ldap_dn_value(body.username))
    try:
        server = ldap3.Server(server_url, get_info=ldap3.NONE)
        conn = ldap3.Connection(server, user=user_dn, password=body.password, auto_bind=True)
        conn.unbind()
    except Exception as e:  # noqa: BLE001 — any bind failure = invalid credentials
        logger.info("LDAP bind failed for %s: %s", body.username, e)
        raise HTTPException(status_code=401, detail="Invalid LDAP credentials")

    issued = await _provision_and_issue(db, username=body.username, provider="ldap",
                                        role=ldap_cfg["default_role"])
    return {"access_token": issued["access_token"], "refresh_token": issued["refresh_token"],
            "token_type": "bearer"}
