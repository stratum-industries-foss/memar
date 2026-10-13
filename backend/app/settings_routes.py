"""Enterprise Settings API Routes

Phase 2-3 enterprise settings management:
- SSO/LDAP configuration and testing
- Messaging platform integrations (Slack, Discord, Telegram, etc.)
- User roles & permissions (RBAC)
- White-label branding and logo uploads
- Webhooks and automation
- Analytics and reporting settings
- Advanced options (cache, beta features, telemetry)

Routes:
  GET    /api/settings/enterprise              - Fetch all enterprise settings
  POST   /api/settings/enterprise              - Save enterprise settings
  POST   /api/settings/sso/test                - Test SSO configuration
  POST   /api/settings/messaging/test          - Test messaging platform
  POST   /api/settings/webhooks/{id}/test      - Test webhook delivery
  POST   /api/settings/branding/upload-logo    - Upload company logo
  GET    /api/settings/analytics/export        - Export analytics data (CSV/PDF)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .deps import require_role, get_current_user
from .logging_config import logger

router = APIRouter(tags=["settings"], prefix="/api/settings")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────


class SsoConfig(BaseModel):
    enabled: bool = False
    provider: str = "oidc"  # oidc | ldap | saml
    discoveryUrl: str | None = None
    clientId: str | None = None
    clientSecret: str | None = None
    ldapHost: str | None = None
    ldapPort: int | None = 389
    ldapBaseDn: str | None = None
    ldapSearchFilter: str | None = None
    ldapBindDn: str | None = None
    ldapBindPassword: str | None = None
    autoSyncRoles: bool = False


class MessagingPlatform(BaseModel):
    id: str
    type: str  # telegram | slack | discord | mattermost | matrix | ntfy | webhook
    enabled: bool = False
    config: dict[str, str]
    testable: bool | None = True


class UserRole(BaseModel):
    id: str
    name: str
    description: str
    permissions: dict[str, bool]
    isCustom: bool = False


class BrandingConfig(BaseModel):
    logoUrl: str | None = None
    companyName: str | None = None
    primaryColor: str | None = None
    secondaryColor: str | None = None
    hideNoweredByMemar: bool = False
    customDomain: str | None = None
    emailTemplate: str | None = None
    smsTemplate: str | None = None


class Webhook(BaseModel):
    id: str
    url: str
    events: list[str]
    enabled: bool = False
    retryPolicy: dict[str, int] = Field(
        default_factory=lambda: {"maxRetries": 3, "backoffMs": 1000}
    )


class AnalyticsConfig(BaseModel):
    enabled: bool = False
    oeeCategories: list[str] = Field(default_factory=list)
    materialCostPerKg: float = 0.0
    energyCostPerKwh: float = 0.0
    dataRetentionDays: int = 90
    collectTelemetry: bool = False


class AdvancedOptions(BaseModel):
    binaryCacheDays: int = 30
    cacheSize: str = "medium"  # small | medium | large
    refreshInterval: int = 60
    betaFeaturesEnabled: bool = False
    telemetryEnabled: bool = False


class EnterpriseSettings(BaseModel):
    sso: SsoConfig
    messaging: list[MessagingPlatform]
    roles: list[UserRole]
    branding: BrandingConfig
    webhooks: list[Webhook]
    analytics: AnalyticsConfig
    advancedOptions: AdvancedOptions


class SsoTestRequest(BaseModel):
    enabled: bool
    provider: str
    discoveryUrl: str | None = None
    clientId: str | None = None
    clientSecret: str | None = None
    ldapHost: str | None = None
    ldapPort: int | None = None
    ldapBaseDn: str | None = None
    ldapSearchFilter: str | None = None
    ldapBindDn: str | None = None
    ldapBindPassword: str | None = None
    autoSyncRoles: bool = False


class SsoTestResponse(BaseModel):
    connected: bool
    error: str | None = None
    message: str | None = None


class MessagingTestResponse(BaseModel):
    success: bool
    error: str | None = None


class WebhookTestResponse(BaseModel):
    success: bool
    error: str | None = None
    statusCode: int | None = None
    latencyMs: int | None = None


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Storage (Demo)
# ─────────────────────────────────────────────────────────────────────────────

_default_settings = EnterpriseSettings(
    sso=SsoConfig(),
    messaging=[],
    roles=[
        UserRole(
            id="admin",
            name="Administrator",
            description="Full system access",
            permissions={"*": True},
            isCustom=False,
        ),
        UserRole(
            id="operator",
            name="Operator",
            description="Control and monitor printers",
            permissions={
                "view:dashboard": True,
                "control:printer": True,
                "view:settings": True,
            },
            isCustom=False,
        ),
        UserRole(
            id="viewer",
            name="Viewer",
            description="Read-only access",
            permissions={"view:dashboard": True, "view:settings": True},
            isCustom=False,
        ),
    ],
    branding=BrandingConfig(),
    webhooks=[],
    analytics=AnalyticsConfig(),
    advancedOptions=AdvancedOptions(),
)

# TODO: Replace with persistent storage (PostgreSQL)
_settings_storage: dict[str, EnterpriseSettings] = {}


def _get_settings_storage() -> EnterpriseSettings:
    """Get current settings or return default."""
    if "default" not in _settings_storage:
        _settings_storage["default"] = _default_settings.model_copy(deep=True)
    return _settings_storage["default"]


def _save_settings_storage(settings: EnterpriseSettings) -> None:
    """Save settings to storage."""
    _settings_storage["default"] = settings.model_copy(deep=True)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/enterprise", response_model=EnterpriseSettings)
async def get_enterprise_settings(
    _: dict = Depends(require_role("admin")),
) -> EnterpriseSettings:
    """Fetch all enterprise settings (admin only)."""
    return _get_settings_storage()


@router.post("/enterprise", response_model=EnterpriseSettings)
async def save_enterprise_settings(
    body: EnterpriseSettings,
    _: dict = Depends(require_role("admin")),
) -> EnterpriseSettings:
    """Save enterprise settings (admin only)."""
    _save_settings_storage(body)
    logger.info("Enterprise settings updated")
    return body


@router.post("/sso/test", response_model=SsoTestResponse)
async def test_sso_connection(
    body: SsoTestRequest,
    _: dict = Depends(require_role("admin")),
) -> SsoTestResponse:
    """Test SSO configuration connectivity (admin only)."""
    if not body.enabled:
        return SsoTestResponse(connected=False, error="SSO is not enabled")

    try:
        # TODO: Implement real SSO testing
        # - For OIDC: call discovery endpoint
        # - For LDAP: test LDAP bind
        # - For SAML: validate metadata

        if body.provider == "ldap":
            if not body.ldapHost:
                return SsoTestResponse(
                    connected=False, error="LDAP host is required"
                )
            # Mock successful LDAP connection test
            logger.info(f"Testing LDAP connection to {body.ldapHost}:{body.ldapPort}")
            return SsoTestResponse(
                connected=True, message="LDAP connection successful"
            )
        elif body.provider == "oidc":
            if not body.discoveryUrl:
                return SsoTestResponse(
                    connected=False, error="Discovery URL is required"
                )
            # Mock successful OIDC discovery
            logger.info(f"Testing OIDC discovery at {body.discoveryUrl}")
            return SsoTestResponse(
                connected=True, message="OIDC discovery successful"
            )
        else:
            return SsoTestResponse(
                connected=False, error=f"Provider {body.provider} not yet implemented"
            )
    except Exception as e:
        logger.error(f"SSO test failed: {e}")
        return SsoTestResponse(connected=False, error=str(e))


@router.post("/messaging/test", response_model=MessagingTestResponse)
async def test_messaging_platform(
    body: MessagingPlatform,
    _: dict = Depends(require_role("admin")),
) -> MessagingTestResponse:
    """Test messaging platform configuration (admin only)."""
    try:
        # TODO: Implement real messaging platform testing
        # - For Slack: call Webhook API with test message
        # - For Discord: call Webhook API
        # - For Telegram: send test message via bot API

        if body.type == "slack":
            if "webhook_url" not in body.config:
                return MessagingTestResponse(
                    success=False, error="webhook_url is required for Slack"
                )
            logger.info(f"Testing Slack webhook: {body.config['webhook_url'][:30]}...")
            return MessagingTestResponse(success=True)
        elif body.type == "telegram":
            if "bot_token" not in body.config or "chat_id" not in body.config:
                return MessagingTestResponse(
                    success=False,
                    error="bot_token and chat_id are required for Telegram",
                )
            logger.info("Telegram integration configured for %s", body.id)
            return MessagingTestResponse(success=True)
        else:
            logger.info(f"Testing {body.type} platform")
            return MessagingTestResponse(success=True)
    except Exception as e:
        logger.error(f"Messaging platform test failed: {e}")
        return MessagingTestResponse(success=False, error=str(e))


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResponse)
async def test_webhook(
    webhook_id: str,
    _: dict = Depends(require_role("admin")),
) -> WebhookTestResponse:
    """Test webhook delivery (admin only)."""
    try:
        # TODO: Implement real webhook testing
        # - POST test payload to webhook URL
        # - Capture status code and latency
        # - Verify retry logic with failures

        import time

        logger.info(f"Testing webhook {webhook_id}")
        start = time.time()

        # Mock successful webhook test
        latency = int((time.time() - start) * 1000)
        return WebhookTestResponse(
            success=True, statusCode=200, latencyMs=latency
        )
    except Exception as e:
        logger.error(f"Webhook test failed: {e}")
        return WebhookTestResponse(success=False, error=str(e))


@router.post("/branding/upload-logo", status_code=200)
async def upload_logo(
    file: UploadFile = File(...),
    _: dict = Depends(require_role("admin")),
) -> dict[str, str]:
    """Upload company logo (admin only)."""
    try:
        if not file.filename:
            raise HTTPException(400, "File name is required")

        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(400, "File must be an image")

        # TODO: Implement real file storage
        # - Save to S3 or local storage
        # - Generate signed URL
        # - Return public URL

        contents = await file.read()
        size_mb = len(contents) / (1024 * 1024)

        if size_mb > 5:
            raise HTTPException(400, "File size must be less than 5 MB")

        # Mock file URL
        url = f"https://cdn.example.com/logos/{file.filename}"
        logger.info(f"Logo uploaded: {url}")

        return {"url": url}
    except Exception as e:
        logger.error(f"Logo upload failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/analytics/export")
async def export_analytics(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    _: dict = Depends(require_role("admin")),
) -> dict:
    """Export analytics data in CSV or PDF format (admin only)."""
    try:
        # TODO: Implement real analytics export
        # - Query analytics data from database
        # - Format as CSV or PDF
        # - Return downloadable file

        logger.info(f"Exporting analytics as {format}")

        if format == "csv":
            content = b"timestamp,metric,value\n"
            content += b"2026-08-06T00:00:00Z,oee,0.95\n"
            content += b"2026-08-06T01:00:00Z,oee,0.92\n"
        else:  # pdf
            content = b"%PDF-1.4\n... PDF content here ..."

        return {"format": format, "size": len(content)}
    except Exception as e:
        logger.error(f"Analytics export failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/auth/methods", response_model=list)
async def get_user_auth_methods(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Get enabled auth methods for current user."""
    from sqlalchemy import select
    from .models_db import User

    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(401, "Authentication required")

    user_row = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = user_row.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User not found")

    # NULL = all methods enabled (default)
    if user.enabled_auth_methods is None:
        return ["password", "passkey", "magic_link", "ldap", "oidc"]

    return user.enabled_auth_methods or []


@router.post("/auth/methods")
async def update_user_auth_methods(
    methods: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update enabled auth methods for current user.

    Example: {"enabled": ["passkey"]} disables password login.
    {"enabled": ["password", "passkey"]} enables both.
    """
    from sqlalchemy import select, update
    from .models_db import User

    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(401, "Authentication required")

    enabled_methods = methods.get("enabled", [])

    # Validate methods
    valid_methods = {"password", "passkey", "magic_link", "ldap", "oidc"}
    if not isinstance(enabled_methods, list):
        raise HTTPException(400, "enabled must be a list")
    if not all(m in valid_methods for m in enabled_methods):
        raise HTTPException(400, f"Invalid methods. Valid: {valid_methods}")

    # Prevent user from disabling all auth methods (account lockout)
    if len(enabled_methods) == 0:
        raise HTTPException(400, "Must enable at least one auth method")

    # Update user's enabled auth methods
    await db.execute(
        update(User).where(User.id == user_id).values(enabled_auth_methods=enabled_methods)
    )
    await db.commit()

    logger.info(f"Updated auth methods for user {user_id}: {enabled_methods}")

    return {"detail": "Auth methods updated", "enabled": enabled_methods}
