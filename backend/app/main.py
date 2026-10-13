# NOTE: no `from __future__ import annotations` here — slowapi's functools.wraps
# wrapper makes FastAPI resolve deferred annotations against slowapi's module
# globals, silently turning the request body into a query param (422 on login).

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging

_start_time = time.monotonic()

from .logging_config import logger

from fastapi import Body, FastAPI, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles

from starlette.websockets import WebSocketState

try:
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    _slowapi_available = True
except ImportError:
    import logging as _logging
    _logging.getLogger(__name__).warning("slowapi not installed; rate limiting disabled")
    _slowapi_available = False

from ._limiter import limiter as _shared_limiter, rate_limit as _rate_limit_decorator
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_config, get_version, reload_config_cache, update_printer_fields
from .db import get_db, init_db, AsyncSessionLocal
from .auth import (
    ensure_admin_user, login, refresh_access_token, logout, change_password,
    LoginRequest, RefreshRequest, TokenResponse, ChangePasswordRequest,
    create_ws_ticket, consume_ws_ticket, WS_TICKET_TTL_SECONDS,
)
from .moonraker_db import MoonrakerDBWriter
from .validation import SettingsValidator
from .firmware import FirmwareManager
from .license import get_license, load_license_from_env, warn_device_count, apply_license, load_license_from_db
from .deps import (
    get_current_user,
    get_current_user_allow_pwchange,
    require_feature,
    require_role,
    security as _bearer_security,
)
from .billing import billing_router
from .fleet import _clear_client_cache
from .stripe_webhook import stripe_router
from .oee import router as oee_router
from .floorplan import router as floorplan_router
from .webhooks import router as webhooks_router, start_dispatcher, detect_state_changes
from .print_monitor import start_monitor, get_monitor_state, _sse_queue, register_anomaly_callback
from .admin import admin_router
from .audit import audit_router, record_audit, record_audit_batch
from .sso import sso_admin_router, sso_router
from .branding import branding_router
from .cnc_routes import router as cnc_router
from .pa_routes import router as pa_router
from .motion_routes import router as motion_router
from .webauthn_routes import router as webauthn_router
from .messaging_admin import messaging_admin_router
from .password_reset import password_reset_router
from .onboarding_routes import router as onboarding_router
from .settings_routes import router as settings_router
try:
    # analytics_routes is committed, but the import stays guarded so the app
    # remains importable on a fresh checkout / partial deploy if the module or
    # one of its optional deps is ever absent.
    from .analytics_routes import router as analytics_router
except ImportError as _analytics_err:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "analytics_routes unavailable, skipping router: %s", _analytics_err
    )
    analytics_router = None
from .fleet import (
    dispatch_upload,
    fetch_current_file,
    fetch_file_detail,
    dispatch_dry_run,
    dry_run_batch_action,
    fetch_file_browser,
    fetch_fleet,
    fetch_fleet_metrics,
    fetch_fleet_settings,
    fetch_history,
    fetch_macros,
    fetch_printer_diagnostics,
    fetch_printer_settings,
    fetch_timelapses,
    fetch_webcam_snapshot,
    fetch_webcams,
    motion_check,
    jog,
    run_batch_action,
    run_macro,
    save_fleet_settings,
    save_printer_settings,
    set_nozzle_diameter,
    set_temperatures,
    start_print,
    upload_gcode,
)
from .models import (
    AppVersion,
    BatchActionRequest,
    DispatchDryRunRequest,
    DryRunRequest,
    FleetSettingsUpdateRequest,
    JogRequest,
    MacroRunRequest,
    MotionCheckRequest,
    NozzleUpdateRequest,
    PrinterSettingsUpdateRequest,
    StartPrintRequest,
    TemperatureSetRequest,
)
from .validation import SettingsValidator
from pydantic import BaseModel, Field
from .models_db import IssuedLicense, SpoolLog
from sqlalchemy import select


class LicenseActivateRequest(BaseModel):
    license_key: str


class AddPrinterRequest(BaseModel):
    id: str
    name: str
    protocol: str
    base_url: str
    enabled: bool = True
    serial: str | None = Field(default=None, max_length=128)   # Bambu MQTT topic/identity
    api_key: str | None = Field(default=None, max_length=512)  # secret (e.g. Bambu LAN access code)
    mqtt_topic: str | None = Field(default=None, max_length=512)  # generic MQTT status topic
    mqtt_field_mapping: dict[str, str] | None = None             # generic MQTT field map


class AddPrinterResponse(BaseModel):
    success: bool
    message: str
    printer_id: str | None = None


class CoolantReadingRequest(BaseModel):
    psi: float
    coolant_active: bool | None = None


ALLOWED_ACTIONS = {"home", "motors_off", "cooldown", "emergency_stop", "pause", "resume", "cancel", "firmware_restart"}
DRY_RUN_ACTIONS = ALLOWED_ACTIONS | {"macro", "temperature"}


async def _watch_config() -> None:
    """Poll config file for changes and hot-reload on mtime change."""
    from .config import get_config_path
    config_path = get_config_path()
    try:
        last_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
    except OSError:
        last_mtime = 0.0
    while True:
        await asyncio.sleep(30)
        try:
            mtime = config_path.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                reload_config_cache()
                _clear_client_cache()
                cfg = get_config()
                logger.info(
                    "Config file changed — reloaded %d printers",
                    len([p for p in cfg.printers if p.enabled]),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Config watcher error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_admin_user(db)
        load_license_from_env()
        await load_license_from_db(db)
    cfg = get_config()
    warn_device_count(len([p for p in cfg.printers if p.enabled]))
    _dispatcher_task = start_dispatcher()
    from .webhooks import publish_event as _pub
    async def _on_anomaly(pid: str, result: dict):
        await _pub("printer.anomaly", pid, result)
    register_anomaly_callback(_on_anomaly)
    _monitor_task = start_monitor(get_config)
    # Track long-running background tasks so they're cancelled on shutdown —
    # otherwise the event loop never drains and systemd SIGKILLs us at stop
    # timeout (and the sampler can't release its DB lease cleanly).
    bg_tasks: list[asyncio.Task] = []
    # Alert dispatcher + CV monitor were started above; track them too so they
    # aren't garbage-collected mid-run (asyncio keeps only a weak ref).
    bg_tasks.append(_dispatcher_task)
    bg_tasks.append(_monitor_task)
    bg_tasks.append(asyncio.create_task(_watch_config()))
    # Telemetry sampler: persists fleet status / CNC metrics time-series that the
    # analytics + coolant dashboards read. Without it those tables stay empty.
    # (Self-elects a single active sampler across multiple workers via a DB lease.)
    from .telemetry import start_telemetry_sampler, backfill_job_history
    bg_tasks.append(start_telemetry_sampler())
    # One-time/incremental import of Moonraker job history into JobLog so the
    # DB-backed analytics (throughput / error-rate / OEE trend) reflect real past
    # jobs immediately instead of reading 0 until live jobs accrue. Idempotent.
    bg_tasks.append(asyncio.create_task(backfill_job_history()))
    # Converge license state across workers for the runtime-activation flow.
    from .license import license_reload_loop, license_heartbeat_loop, renewal_warning_loop
    bg_tasks.append(asyncio.create_task(license_reload_loop()))
    bg_tasks.append(asyncio.create_task(license_heartbeat_loop()))
    bg_tasks.append(asyncio.create_task(renewal_warning_loop()))
    # Unified Messaging Hub — fans alert events to Telegram, Slack, ntfy, Discord,
    # Mattermost, Matrix, and generic webhooks. Bidirectional adapters also handle
    # incoming slash commands with MEMAR role-gated authorization.
    from .messaging import MessagingHub
    _msg_hub = MessagingHub.from_env(db_factory=AsyncSessionLocal)
    await _msg_hub.start()

    # Coolant alert monitor: evaluates CNCMetricsLog for low/declining coolant
    # pressure and fires notifications via the hub.
    try:
        from .coolant_alerts_integration import start_coolant_alert_monitor
        _ct = start_coolant_alert_monitor()
        if _ct is not None:
            bg_tasks.append(_ct)
    except Exception as _ca_err:  # noqa: BLE001
        logger.warning("coolant alert monitor unavailable: %s", _ca_err)

    # Initialize WebSocket connections to Moonraker instances
    from .ws_client import ws_manager
    from .fleet import auto_load_bed_mesh
    for printer in cfg.printers:
        if printer.enabled and printer.protocol == "moonraker":
            try:
                port = int(printer.base_url.split(":")[-1])
                _printer_ref = printer  # capture for closure
                async def _bed_mesh_ready(p=_printer_ref):
                    await auto_load_bed_mesh(p)
                bg_tasks.append(asyncio.create_task(
                    ws_manager.connect_printer(
                        port, printer.id,
                        base_url=printer.base_url,
                        on_klippy_ready=_bed_mesh_ready,
                    )
                ))
            except Exception as e:
                logger.error(f"Failed to start WS for {printer.id}: {e}")

    yield

    # Graceful shutdown: cancel background loops so the process exits promptly on
    # SIGTERM (no systemd stop-timeout SIGKILL), then close WebSockets.
    for _t in bg_tasks:
        _t.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    await _msg_hub.stop()
    await ws_manager.disconnect_all()


# Disable Swagger/OpenAPI in production (fingerprinting mitigation)
_docs_url = None if os.getenv("MEMAR_ENV") == "production" else "/docs"
_redoc_url = None if os.getenv("MEMAR_ENV") == "production" else "/redoc"
_openapi_url = None if os.getenv("MEMAR_ENV") == "production" else "/openapi.json"

app = FastAPI(
    title="MEMAR API",
    version=get_version()[0],
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Writer guard for mutating/control routes. The public demo (and any 'viewer'
# token) can read the dashboard but must NOT drive hardware or change config —
# applied per-route via `dependencies=[_WRITER]` on every POST/PUT/DELETE that
# actuates a printer or persists settings. (Closes the demo-token control hole
# and the spoolman_url SSRF, which is only reachable through the settings write.)
_WRITER = Depends(require_role("admin", "operator"))
if _slowapi_available and _shared_limiter is not None:
    limiter = _shared_limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(NotImplementedError)
async def _not_implemented_handler(request: Request, exc: NotImplementedError) -> _JSONResponse:
    return _JSONResponse(status_code=501, content={"detail": "Not implemented"})

import os as _os
_cors_origins_raw = _os.getenv("MEMAR_CORS_ORIGINS", "http://localhost:5173,http://localhost:8080,http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


class _SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (b"strict-transport-security", b"max-age=63072000; includeSubDomains; preload"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"),
                ])
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(_SecurityHeadersMiddleware)


def _get_printer_or_404(printer_id: str):
    cfg = get_config()
    printer = next((item for item in cfg.printers if item.id == printer_id and item.enabled), None)
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return printer


_rate_limit = _rate_limit_decorator


@app.post("/api/auth/login")
@_rate_limit("10/minute")
async def auth_login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        resp = await login(db, body)
    except HTTPException:
        await record_audit(db, action="login_failed", user={"username": body.username}, request=request)
        raise
    await record_audit(db, action="login", user={"username": body.username}, request=request)
    return resp


@app.post("/api/auth/refresh")
@_rate_limit("30/minute")
async def auth_refresh(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    return await refresh_access_token(db, body)


@app.post("/api/auth/logout")
async def auth_logout(_user: dict = Depends(get_current_user_allow_pwchange), db: AsyncSession = Depends(get_db)) -> dict:
    return await logout(db, _user["id"])


@app.get("/api/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user_allow_pwchange)) -> dict:
    # Reachable while a forced password change is pending so the UI can detect the
    # must_change_password flag and route the user to the change screen.
    return current_user


@app.post("/api/auth/change-password")
@_rate_limit("10/minute")
async def auth_change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user_allow_pwchange),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    resp = await change_password(db, current_user["id"], body)
    await record_audit(db, action="password_changed", user=current_user, request=request)
    return resp


# NOTE: /api/auth/demo was removed. It minted a token for user_id=999, a row
# that never exists in the DB, so any authenticated request made with that
# token failed user lookup. The route now simply doesn't exist and the SPA
# fallback returns a real 404 for /api/* (see spa_fallback below), which is
# exactly what the frontend's demo probe already handles by falling through to
# the login screen. MEMAR_DEMO_MODE is still honoured by
# backend/scripts/seed_cnc_demo.py and reported by scripts/preflight.py.


@app.get("/api/license/status")
async def license_status(_: dict = Depends(get_current_user)) -> dict:
    lic = get_license()
    days_remaining = None
    if lic.expires_at:
        from datetime import date
        delta = date.fromisoformat(lic.expires_at) - date.today()
        days_remaining = delta.days
    return {
        "tier": lic.tier, "device_limit": lic.device_limit, "expiry": lic.expires_at,
        "days_remaining": days_remaining, "features": lic.features,
        "active": lic.active, "warning": lic.warning,
    }


@app.get("/api/license/renewal-warning")
async def license_renewal_warning(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns a warning if the active license expires within 30 days.
    """
    from datetime import datetime, timezone, timedelta
    try:
        # Find soonest-expiring active (not-yet-expired) license. expires_at's
        # tz-awareness isn't guaranteed at the DB layer (SQLite stores it
        # naive), so filtering "not yet expired" in SQL risks a naive/aware
        # comparison mismatch — fetch activated licenses ordered soonest-first
        # and pick the first one that's actually still valid in Python,
        # normalizing tzinfo the same way this endpoint already does below.
        # Without this, an old expired row (e.g. from a prior tier change)
        # permanently wins "soonest expiring" and the banner never clears.
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.activated == True)
            .order_by(IssuedLicense.expires_at.asc())
        )
        now = datetime.now(timezone.utc)
        lic = None
        expires = None
        for candidate in result.scalars():
            candidate_expires = candidate.expires_at
            if candidate_expires.tzinfo is None:
                candidate_expires = candidate_expires.replace(tzinfo=timezone.utc)
            if candidate_expires > now:
                lic, expires = candidate, candidate_expires
                break
        if not lic:
            return {"warning": False}

        days_remaining = (expires - now).days
        if days_remaining > 30:
            return {"warning": False}

        return {
            "warning": True,
            "days_remaining": max(days_remaining, 0),
            "tier": lic.tier,
            "message": f"Your {lic.tier.title()} license expires in {max(days_remaining, 0)} days. Renew to avoid service interruption.",
        }
    except Exception as e:
        logger.warning(f"renewal-warning check failed: {e}")
        return {"warning": False}


@app.get("/api/license/upgrade-hint")
async def license_upgrade_hint(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns an upgrade hint if the device count is approaching the tier limit.
    Triggers at 90% of device limit.
    """
    from .billing import DEVICE_LIMITS, TIER_PRICES

    lic = get_license()
    if not lic.device_limit:
        return {"show": False}

    # Count configured (enabled) devices — canonical device-count definition,
    # identical to warn_device_count() and the device-limit enforcement in add_printer().
    # Devices live in config (devices.yaml), not a DB table; an offline-but-enabled
    # device still consumes a seat.
    cfg = get_config()
    enabled_count = len([p for p in cfg.printers if p.enabled])

    # Check if at 90% of limit
    threshold = int(lic.device_limit * 0.9)
    if enabled_count < threshold:
        return {"show": False}

    # Map current tier to next tier
    tier_progression = {"free": "maker", "maker": "pro", "pro": "farm", "farm": "scale", "scale": None}
    next_tier = tier_progression.get(lic.tier)
    if not next_tier:
        return {"show": False}

    next_limit = DEVICE_LIMITS.get(next_tier, 0)
    next_price = TIER_PRICES.get(next_tier, 0)

    return {
        "show": True,
        "current": enabled_count,
        "limit": lic.device_limit,
        "next_tier": next_tier,
        "next_limit": next_limit,
        "next_price_monthly": next_price,
    }


@app.post("/api/license/activate")
async def license_activate(
    request: LicenseActivateRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Activate a license key at runtime (admin only).

    Changing the whole instance's license tier is an administrative action, so
    this is gated to admins — a viewer/operator must not be able to swap it
    (the key is signature-bound, but tier changes are still admin scope).

    On success we also persist the key as an activated IssuedLicense row (if not
    already present) so load_license_from_db re-applies it after a restart — this
    is what makes the account-portal / API key-application flow durable.
    """
    ok = apply_license(request.license_key)
    if not ok:
        raise HTTPException(400, "Invalid or expired license key")

    lic = get_license()

    # Persist for restart durability. Mark any matching stored row activated;
    # if none exists (e.g. key delivered by email, not via our DB), insert one.
    try:
        existing = await db.execute(
            select(IssuedLicense).where(IssuedLicense.license_key == request.license_key)
        )
        row = existing.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is not None:
            row.activated = True
            row.activated_at = now
        else:
            db.add(IssuedLicense(
                stripe_customer_id=lic.customer_id or "manual",
                email="manual-activation@local",
                tier=lic.tier,
                device_limit=lic.device_limit,
                license_key=request.license_key,
                stripe_session_id=f"manual_{int(now.timestamp())}",
                expires_at=(
                    datetime.fromisoformat(lic.expires_at).replace(tzinfo=timezone.utc)
                    if lic.expires_at else now + timedelta(days=3650)
                ),
                activated=True,
                activated_at=now,
            ))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        # In-memory activation already succeeded; persistence is best-effort.
        logger.warning("License activated in memory but DB persist failed: %s", exc)
        await db.rollback()

    await record_audit(db, action="license_activate", user=current_user,
                       resource="license", detail={"tier": lic.tier, "device_limit": lic.device_limit})
    return {
        "activated": True,
        "tier": lic.tier,
        "device_limit": lic.device_limit,
        "expires_at": lic.expires_at,
        "features": lic.features,
    }


@app.post("/api/admin/reload-config")
async def admin_reload_config(_: dict = Depends(require_role("admin"))) -> dict:
    """Hot-reload printer configuration without restart. Admin only."""
    reload_config_cache()
    _clear_client_cache()
    cfg = get_config()
    enabled = len([p for p in cfg.printers if p.enabled])
    logger.info("Admin triggered config reload: %d printers enabled", enabled)
    return {"ok": True, "printer_count": enabled}


@app.post("/api/admin/backfill-jobs")
async def admin_backfill_jobs(_: dict = Depends(require_role("admin"))) -> dict:
    """Import Moonraker job history into JobLog (idempotent) so DB-backed analytics
    reflect real past jobs. Safe to re-run. Admin only."""
    from .telemetry import backfill_job_history
    inserted = await backfill_job_history()
    logger.info("Admin triggered job-history backfill: %d rows imported", inserted)
    return {"ok": True, "imported": inserted}


@app.get("/api/healthz")
async def healthz(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_security),
) -> dict:
    """Liveness probe. Unauthenticated callers get status + uptime only;
    version/build/db/license/stripe details are fingerprinting fodder, so they
    require a valid Bearer token (same validation path as every other route)."""
    uptime_s = int(time.monotonic() - _start_time)

    payload: dict = {
        "status": "ok",
        "uptime_s": uptime_s,
    }

    try:
        await get_current_user_allow_pwchange(credentials, db)
    except HTTPException:
        return payload

    from sqlalchemy import text
    version_value, build_id = get_version()
    lic = get_license()
    cfg = get_config()

    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    adapters_configured = len([p for p in cfg.printers if p.enabled])
    stripe_configured = bool(os.getenv("MEMAR_STRIPE_SECRET_KEY", "").strip())

    payload.update({
        "version": version_value,
        "build_id": build_id,
        "db": "connected" if db_ok else "error",
        "stripe_configured": stripe_configured,
        "license_tier": lic.tier,
        "license_active": lic.active,
        "license_expires": lic.expires_at,
        "devices_licensed": lic.device_limit,
        "adapters_configured": adapters_configured,
    })
    return payload


@app.get("/api/readyz")
async def readyz() -> dict[str, str]:
    cfg = get_config()
    return {"status": "ok", "printers": str(len([p for p in cfg.printers if p.enabled]))}


@app.get("/api/version")
async def version() -> AppVersion:
    version_value, build_id = get_version()
    return AppVersion(version=version_value, build_id=build_id)


@app.get("/api/support-info")
async def support_info(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> dict:
    """Diagnostic dump — admin only. Paste output into support tickets.

    Returns tailed ERROR log lines (stack traces, internal paths, upstream
    failure detail) plus version/license/fleet info, so it is gated to admins.
    """
    from sqlalchemy import text
    version_value, build_id = get_version()
    lic = get_license()
    cfg = get_config()

    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    enabled = [p for p in cfg.printers if p.enabled]
    by_protocol: dict[str, int] = {}
    for p in enabled:
        key = p.protocol.value if hasattr(p.protocol, "value") else str(p.protocol)
        by_protocol[key] = by_protocol.get(key, 0) + 1

    recent_errors: list[str] = []
    try:
        log_path = Path(__file__).parent.parent.parent / "logs" / "backend.log"
        if log_path.exists():
            with log_path.open("rb") as f:
                f.seek(0, 2)
                chunk = min(50_000, f.tell())
                f.seek(-chunk, 2)
                tail = f.read().decode("utf-8", errors="replace")
            recent_errors = [ln for ln in tail.splitlines() if " ERROR " in ln][-5:]
    except Exception:
        pass

    return {
        "memar_version": version_value,
        "build_id": build_id,
        "uptime_seconds": int(time.monotonic() - _start_time),
        "license": {
            "tier": lic.tier,
            "active": lic.active,
            "expires": lic.expires_at,
            "device_limit": lic.device_limit,
        },
        "fleet": {
            "total": len(enabled),
            "by_protocol": by_protocol,
        },
        "database": "connected" if db_ok else "error",
        "stripe_connected": bool(os.getenv("MEMAR_STRIPE_SECRET_KEY", "").strip()),
        "recent_errors": recent_errors,
    }


@app.get("/api/settings/fleet")
async def get_fleet_settings_route(_: dict = Depends(get_current_user)) -> dict[str, object]:
    cfg = get_config()
    payload = await fetch_fleet_settings(cfg.printers)
    return payload.model_dump()


@app.post("/api/settings/fleet", dependencies=[_WRITER])
async def post_fleet_settings_route(request: FleetSettingsUpdateRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    payload = await save_fleet_settings(request)
    return payload.model_dump()


def _redact_printer(printer: dict) -> dict:
    """Strip the secret ``api_key`` from a serialized PrinterConfig before it
    leaves the API, replacing it with a boolean ``api_key_set`` so the UI can show
    "configured" without revealing the credential. The access code is write-only:
    accepted on update, never returned. DENYLIST — any future secret field added
    to PrinterConfig must be stripped here too.
    """
    printer["api_key_set"] = bool(printer.pop("api_key", None))
    return printer


@app.get("/api/printers/{printer_id}/settings")
async def get_printer_settings_route(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    payload = await fetch_printer_settings(printer)
    return _redact_printer(payload.model_dump())


@app.post("/api/printers/{printer_id}/settings", dependencies=[_WRITER])
async def post_printer_settings_route(printer_id: str, request: PrinterSettingsUpdateRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    # Validate printer settings before saving
    valid, errors = SettingsValidator.validate_printer_settings_request(request)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Validation failed: {'; '.join(errors)}")
    try:
        payload = await save_printer_settings(printer, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = payload.model_dump()
    if isinstance(data.get("printer"), dict):
        _redact_printer(data["printer"])
    return data


@app.put("/api/printers/{printer_id}/spool", dependencies=[_WRITER])
async def update_spool(printer_id: str, body: dict = Body(...), _: dict = Depends(get_current_user)) -> dict:
    """Quick update for spool remaining weight (g)."""
    _get_printer_or_404(printer_id)
    remaining_g = body.get("remaining_g")
    if remaining_g is None:
        raise HTTPException(400, "remaining_g required")
    try:
        remaining_g = float(remaining_g)
    except (TypeError, ValueError):
        raise HTTPException(400, "remaining_g must be a number")
    if not (0 <= remaining_g <= 20000):
        raise HTTPException(400, "remaining_g out of range (0-20000)")
    await update_printer_fields(printer_id, {"spool_remaining_g": remaining_g})
    return {"ok": True, "spool_remaining_g": remaining_g}


@app.post("/api/printers/{printer_id}/spool/estimate", dependencies=[_WRITER])
async def estimate_spool_from_image(
    printer_id: str,
    file: UploadFile = File(...),
    full_spool_g: float = Form(1000.0),
    _: dict = Depends(get_current_user),
) -> dict:
    """Estimate spool remaining weight from an uploaded image.

    Priority chain:
    1. Rust CV binary (spool-cv) — local, ~5ms, no network, no model
    2. LiteLLM vision model (MEMAR_VISION_MODEL env, default 'vision' = groq llama-4-scout)
    3. LiteLLM fallback model ('gemma3' local ollama)

    CV result is used if confidence != 'low'. Otherwise falls through to LLM.
    """
    import base64
    import os
    import re
    import shutil
    import subprocess
    import tempfile
    import urllib.request as _urllib

    _get_printer_or_404(printer_id)

    image_bytes = await _read_upload_capped(file, 10 * 1024 * 1024)

    mime = file.content_type or "image/jpeg"

    # ── Tier 1: Rust CV binary ──────────────────────────────────────────────
    cv_bin = os.environ.get(
        "MEMAR_SPOOL_CV_BIN",
        str(Path(__file__).parent.parent.parent / "tools" / "spool-cv" / "target" / "release" / "spool-cv"),
    )

    cv_result = None
    if shutil.which(cv_bin) or os.path.isfile(cv_bin):
        suffix = ".jpg" if "jpeg" in mime else ".png"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            try:
                loop = asyncio.get_running_loop()
                def _run_cv():
                    proc = subprocess.run(
                        [cv_bin, tmp_path, "--full-g", str(full_spool_g)],
                        capture_output=True, text=True, timeout=10,
                    )
                    return proc
                proc = await loop.run_in_executor(None, _run_cv)

                if proc.returncode == 0 and proc.stdout.strip():
                    cv_result = json.loads(proc.stdout.strip())
                    logger.info(f"spool-cv result: {cv_result}")
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            logger.warning(f"spool-cv failed: {e}")
            cv_result = None

    if (
        cv_result
        and cv_result.get("confidence") != "low"
        and cv_result.get("fill_pct") is not None
        and cv_result.get("estimated_g") is not None
    ):
        return {
            "ok": True,
            "fill_pct": round(float(cv_result["fill_pct"]), 3),
            "estimated_g": int(cv_result["estimated_g"]),
            "confidence": cv_result.get("confidence", "medium"),
            "reasoning": cv_result.get("reasoning", ""),
            "model_used": "spool-cv (local)",
        }

    # ── Tier 2 & 3: Vision LLM fallback ────────────────────────────────────
    img_b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        "This is a photo of a 3D printer filament spool. "
        "Estimate how much filament remains by looking at the visible width of the "
        "filament wound between the center hub and the outer spool flange. "
        f"Assume a full spool weighs {full_spool_g:.0f}g. "
        "Respond ONLY with a valid JSON object and nothing else: "
        '{"fill_pct": 0.5, "estimated_g": 500, "confidence": "high", "reasoning": "brief note"}'
    )

    vision_model = os.environ.get("MEMAR_VISION_MODEL", "vision")
    fallback_model = "gemma3"

    async def _call_vision(model: str) -> dict:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            ]}],
            "max_tokens": 200,
            "temperature": 0.1,
        }).encode()
        req = _urllib.Request(
            os.getenv("MEMAR_VISION_LLM_URL", "http://localhost:4002") + "/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer memar"},
        )
        loop = asyncio.get_running_loop()
        def _do_request():
            with _urllib.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        result = await loop.run_in_executor(None, _do_request)
        if 'error' in result or not result.get('choices'):
            raise ValueError(f"LLM error: {result}")
        content = result["choices"][0]["message"]["content"]
        content = re.sub(r"^```[a-z]*\n?", "", content.strip())
        content = re.sub(r"\n?```$", "", content.strip())
        return json.loads(content)

    last_err = None
    for model in [vision_model, fallback_model]:
        try:
            data = await _call_vision(model)
            fill_pct = float(data.get("fill_pct", 0.5))
            fill_pct = max(0.0, min(1.0, fill_pct))
            estimated_g = data.get("estimated_g") or round(fill_pct * full_spool_g)
            cv_note = f" (cv:{cv_result['confidence']} confidence, used llm)" if cv_result else ""
            return {
                "ok": True,
                "fill_pct": round(fill_pct, 3),
                "estimated_g": round(float(estimated_g)),
                "confidence": data.get("confidence", "medium"),
                "reasoning": data.get("reasoning", "") + cv_note,
                "model_used": model,
            }
        except Exception as e:
            last_err = e
            logger.warning(f"Vision model {model!r} failed for spool estimate: {e}")
            continue

    raise HTTPException(502, f"All vision models failed: {last_err}")


@app.put("/api/printers/{printer_id}/name", dependencies=[_WRITER])
async def update_printer_name(printer_id: str, body: dict = Body(...), _: dict = Depends(get_current_user)) -> dict:
    """Update printer display name."""
    _get_printer_or_404(printer_id)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required and cannot be empty")
    if len(name) > 100:
        raise HTTPException(400, "name must be 100 characters or less")
    await update_printer_fields(printer_id, {"name": name})
    return {"ok": True, "id": printer_id, "name": name}


@app.get("/api/printers")
async def list_printers(_: dict = Depends(get_current_user)) -> dict[str, object]:
    cfg = get_config()
    printers = await fetch_fleet(cfg.printers)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "printers": [printer.model_dump() for printer in printers]}


@app.post("/api/printers/add")
async def add_printer(
    request: AddPrinterRequest,
    current_user: dict = Depends(require_role("admin")),
) -> AddPrinterResponse:
    """
    Add a new device to the fleet (admin only).

    The license device-limit check and the config append are performed
    atomically inside add_printer_to_config() under a single lock, so two
    concurrent adds can't both slip past the limit (TOCTOU). The new entry is
    built from a full PrinterConfig so every schema field gets its default —
    a partial dict would later crash code that reads those fields.
    """
    from .config import add_printer_to_config, DeviceLimitReached, DuplicateDeviceId
    from .models import PrinterConfig
    from pydantic import ValidationError

    lic = get_license()

    # Build a schema-complete, validated device entry (43 fields, defaults filled).
    try:
        printer_model = PrinterConfig(
            id=request.id,
            name=request.name,
            base_url=request.base_url,
            protocol=request.protocol,
            enabled=request.enabled,
            serial=request.serial,
            api_key=request.api_key,
            mqtt_topic=request.mqtt_topic,
            mqtt_field_mapping=request.mqtt_field_mapping,
        )
    except ValidationError as e:
        return AddPrinterResponse(success=False, message=f"Invalid device config: {e}")

    printer_dict = printer_model.model_dump(mode="json")

    try:
        new_count = await add_printer_to_config(printer_dict, lic.device_limit)
    except DeviceLimitReached as e:
        return AddPrinterResponse(
            success=False,
            message=(
                f"Device limit reached ({e.enabled_count}/{e.device_limit}). "
                "Upgrade your license to add more devices."
            ),
        )
    except DuplicateDeviceId as e:
        return AddPrinterResponse(success=False, message=f"Device id already exists: {e.device_id}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to add device: {e}")
        return AddPrinterResponse(success=False, message=f"Failed to add device: {e}")

    logger.info("Device %s added (%d/%d seats used)", request.id, new_count, lic.device_limit)
    return AddPrinterResponse(
        success=True,
        message=f"Device {request.id} added successfully ({new_count}/{lic.device_limit} seats used)",
        printer_id=request.id,
    )


@app.post("/api/devices/{device_id}/coolant-psi", dependencies=[_WRITER])
async def ingest_coolant_psi(
    device_id: str,
    request: CoolantReadingRequest,
    _: dict = Depends(get_current_user),
) -> dict:
    """
    Ingest a coolant pressure reading from an external sensor.

    Coolant pressure is almost always a separate sensor, not something the CNC
    controller exposes — so an IoT pressure sensor (or a gateway script) POSTs
    readings here. Each reading is persisted to CNCMetricsLog, which feeds the
    coolant-depletion analytics and alerts. This is the real data source that
    makes the coolant-PSI dashboards functional.
    """
    from .models_db import CNCMetricsLog

    _get_printer_or_404(device_id)  # 404 if the device isn't in the fleet config
    if request.psi < 0:
        raise HTTPException(400, "psi must be non-negative")

    async with AsyncSessionLocal() as db:
        db.add(CNCMetricsLog(
            device_id=device_id,
            coolant_psi=request.psi,
            coolant_active=request.coolant_active,
        ))
        await db.commit()
    return {"ok": True, "device_id": device_id, "psi": request.psi}


@app.post("/api/printers/{printer_id}/anomalies/ack", dependencies=[_WRITER])
async def ack_anomaly(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Acknowledge (suppress) a specific anomaly code for a device.

    Upserts one AnomalyAck(device_id, code) row. The ack suppresses that code
    until the condition clears — fleet._apply_anomaly_acks auto-prunes the row
    once the code drops out of the live anomaly set, so a recurrence re-alerts.
    """
    from sqlalchemy import select
    from .models_db import AnomalyAck

    _get_printer_or_404(printer_id)  # 404 if the device isn't in the fleet config
    code = body.get("code")
    if not isinstance(code, str) or not code.strip():
        raise HTTPException(422, "code must be a non-empty string")
    code = code.strip()

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(AnomalyAck).where(
                AnomalyAck.device_id == printer_id,
                AnomalyAck.code == code,
            )
        )).scalar_one_or_none()
        if existing is None:
            db.add(AnomalyAck(device_id=printer_id, code=code))
            await db.commit()
    return {"ok": True}


@app.get("/api/metrics")
async def metrics(history_limit: int = 50, _: dict = Depends(get_current_user)) -> dict[str, object]:
    cfg = get_config()
    payload = await fetch_fleet_metrics(cfg.printers, history_limit=max(5, min(history_limit, 200)))
    return payload.model_dump()


@app.get("/api/printers/{printer_id}/diagnostics")
async def get_printer_diagnostics(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    diagnostics = await fetch_printer_diagnostics(printer)
    return diagnostics.model_dump()


@app.get("/api/printers/{printer_id}/klipper-config")
async def get_printer_klipper_config(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    """Return the parsed printer.cfg hardware spec for this printer.

    Reads the config_file path reported by Klippy (via /printer/info) and
    parses it locally. The printer must be online for the config path to be
    available; if offline the last-known path from a full diagnostics fetch
    is used when possible.
    """
    from pathlib import Path as _Path
    from .config_discovery import parse_printer_cfg as _parse_cfg
    from .models import KlipperConfig

    printer = _get_printer_or_404(printer_id)
    # Try to get cfg path from a lightweight printer_info call
    try:
        from .moonraker import MoonrakerClient
        from .fleet import _get_client
        client = await _get_client(printer)
        if isinstance(client, MoonrakerClient):
            info = await client.printer_info()
            cfg_file = info.get("config_file")
        else:
            cfg_file = None
    except Exception:
        cfg_file = None

    if not cfg_file:
        # Fall back to guessing path from standard directory layout
        try:
            num = int(printer_id.replace("printer-", ""))
            cfg_file = str(_Path.home() / f"printer_{num}_data" / "config" / "printer.cfg")
        except (ValueError, Exception):
            return {"error": "Could not determine config file path", "klipper_config": None}

    from .fleet import _allowed_klipper_file
    safe_cfg = _allowed_klipper_file(cfg_file)
    if safe_cfg is None:
        # cfg_file is supplied by the untrusted remote printer via /printer/info
        # (or guessed from printer_id); only read it when it resolves within an
        # operator-allowlisted root (MEMAR_KLIPPER_FILE_ROOTS, default deny-all).
        # Closes the same arbitrary-file-read vector as BUG-HIGH-FLEET-03.
        return {"config_file": cfg_file, "error": "config file path not permitted", "klipper_config": None}
    try:
        kc = KlipperConfig(**_parse_cfg(safe_cfg))
        return {"config_file": str(safe_cfg), "klipper_config": kc.model_dump()}
    except Exception as e:
        return {"config_file": str(safe_cfg), "error": str(e), "klipper_config": None}


@app.get("/api/printers/{printer_id}/history")
async def get_printer_history(printer_id: str, limit: int = 15, _: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    history = await fetch_history(printer, db=db, limit=max(1, min(limit, 100)))
    return history.model_dump()


@app.get("/api/printers/{printer_id}/files")
async def get_printer_files(printer_id: str, path: str = "gcodes", _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    browser = await fetch_file_browser(printer, path=path)
    return browser.model_dump()


@app.get("/api/printers/{printer_id}/files/detail")
async def get_printer_file_detail(printer_id: str, filename: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    detail = await fetch_file_detail(printer, filename)
    return detail.model_dump()


def _normalize_job_name(name: str | None) -> str:
    """Reduce a JobLog.job_name to the gcodes-relative form the file browser uses
    as a file's identity, so counts join to browsed files.

    JobLog stores the gcodes-relative path already (telemetry.backfill writes
    Moonraker `history.filename`, webhooks writes `print_stats.filename` — neither
    is prefixed), while FileEntry.path IS prefixed (`fleet._join_path("gcodes", ...)`).
    The frontend strips the prefix before looking a file up; stripping it here too
    keeps the join correct for any adapter that happens to store the long form.
    NULL job_name (CNC machines that report no program name) collapses to the same
    'Unknown file' label fetch_history already uses — it can never match a real
    browsed file, it just rides along as its own bucket.
    """
    if not name or not name.strip():
        return "Unknown file"
    cleaned = name.strip().lstrip("/")
    if cleaned.startswith("gcodes/"):
        cleaned = cleaned[len("gcodes/"):]
    return cleaned or "Unknown file"


@app.get("/api/printers/{printer_id}/files/print-counts")
async def get_printer_file_print_counts(
    printer_id: str,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """How many times each file has been run on THIS device, from JobLog.

    Honest scope: this counts every terminal job MEMAR recorded — completed,
    failed AND cancelled (deliberately unfiltered: a cancelled run still consumed
    the machine). It only covers MEMAR's own observation window plus the 30-day
    Moonraker backfill, so it under-reports against a printer's native history
    (Fluidd/Mainsail keep theirs indefinitely). The UI states this in a tooltip.
    """
    from sqlalchemy import func

    from .models_db import JobLog

    printer = _get_printer_or_404(printer_id)
    rows = (await db.execute(
        select(JobLog.job_name, func.count().label("count"))
        .where(JobLog.device_id == printer.id)
        .group_by(JobLog.job_name)
        .order_by(JobLog.job_name)
    )).all()
    # Group in SQL (cheap, indexed on device_id), then re-merge in Python: two
    # rows that differ only by a 'gcodes/' prefix are the same file and must sum
    # into one bucket rather than emit a duplicate key the frontend Map would drop.
    merged: dict[str, int] = {}
    for job_name, count in rows:
        merged[_normalize_job_name(job_name)] = merged.get(_normalize_job_name(job_name), 0) + int(count or 0)
    return [{"job_name": name, "count": count} for name, count in sorted(merged.items())]


@app.get("/api/printers/{printer_id}/current-file")
async def get_printer_current_file(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    detail = await fetch_current_file(printer)
    return detail.model_dump()


MAX_GCODE_UPLOAD_BYTES = 256 * 1024 * 1024


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an UploadFile in chunks, aborting with 413 if it exceeds max_bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // (1024 * 1024)}MB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/printers/{printer_id}/files/upload", dependencies=[_WRITER])
async def upload_printer_file(
    printer_id: str,
    file: UploadFile = File(...),
    relative_path: str | None = Form(default=None),
    auto_print: bool = Form(default=False),
    _: dict = Depends(get_current_user),
) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    content = await _read_upload_capped(file, MAX_GCODE_UPLOAD_BYTES)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    uploaded = await upload_gcode(printer, filename=file.filename, content=content, relative_path=relative_path, auto_print=auto_print)
    return uploaded.model_dump()


@app.post("/api/files/upload", dependencies=[_WRITER])
async def upload_from_dashboard(
    printer_ids: list[str] = Form(...),
    file: UploadFile = File(...),
    relative_path: str | None = Form(default=None),
    auto_print: bool = Form(default=False),
    _: dict = Depends(get_current_user),
) -> dict[str, object]:
    cfg = get_config()
    content = await _read_upload_capped(file, MAX_GCODE_UPLOAD_BYTES)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if not printer_ids:
        raise HTTPException(status_code=400, detail="At least one printer must be selected")
    dispatched = await dispatch_upload(
        cfg.printers,
        printer_ids=printer_ids,
        filename=file.filename,
        content=content,
        relative_path=relative_path,
        auto_print=auto_print,
    )
    return dispatched.model_dump()


@app.post("/api/printers/{printer_id}/files/print", dependencies=[_WRITER])
async def print_printer_file(printer_id: str, request: StartPrintRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    result = await start_print(printer, request.filename)
    return result.model_dump()


@app.get("/api/printers/{printer_id}/macros")
async def get_printer_macros(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    macros = await fetch_macros(printer)
    return {"printer_id": printer_id, "macros": [item.model_dump() for item in macros]}


@app.post("/api/printers/{printer_id}/macros/{macro_name:path}", dependencies=[_WRITER])
async def post_printer_macro(
    printer_id: str,
    macro_name: str,
    body: MacroRunRequest | None = None,
    _: dict = Depends(get_current_user),
) -> dict[str, object]:
    # `body` MUST stay optional: the plain no-args macro button posts with no
    # body at all, and a required model would 422 every one of those calls.
    printer = _get_printer_or_404(printer_id)
    try:
        result = await run_macro(printer, macro_name, body.params if body else None)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Printer communication error: {type(exc).__name__}") from exc
    return result.model_dump()


@app.post("/api/printers/{printer_id}/temperature", dependencies=[_WRITER])
async def post_printer_temperature(
    printer_id: str,
    body: TemperatureSetRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    try:
        # Validate temperature request before sending — inside the try so a
        # rejected unsafe-temperature attempt still hits the finally's audit
        # call below, matching jog_printer's audit-even-on-rejection pattern.
        valid, errors = SettingsValidator.validate_temperature_set_request(body)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Validation failed: {'; '.join(errors)}")
        result = await set_temperatures(printer, body)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Printer communication error: {type(exc).__name__}") from exc
    finally:
        await record_audit(
            db,
            action="fdm_set_temperature",
            user=current_user,
            resource=f"printer:{printer_id}",
            detail=body.model_dump(exclude_none=True),
            request=request,
        )
    return result.model_dump()

@app.post("/api/printers/{printer_id}/settings/nozzle", dependencies=[_WRITER])
async def post_printer_nozzle(printer_id: str, request: NozzleUpdateRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    # Validate nozzle diameter before changing
    valid, msg = SettingsValidator.validate_nozzle_diameter(request.nozzle_diameter_mm)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    try:
        result = await set_nozzle_diameter(printer, request.nozzle_diameter_mm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump()


@app.post("/api/printers/{printer_id}/jog", dependencies=[_WRITER])
async def jog_printer(
    printer_id: str,
    body: JogRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    try:
        result = await jog(printer, body)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Printer communication error: {type(exc).__name__}") from exc
    finally:
        await record_audit(
            db,
            action="fdm_jog",
            user=current_user,
            resource=f"printer:{printer_id}",
            detail=body.model_dump(),
            request=request,
        )
    return result.model_dump()

@app.get("/api/printers/{printer_id}/webcams")
async def get_printer_webcams(printer_id: str, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    webcams = await fetch_webcams(printer)
    return webcams.model_dump()


@app.get("/api/printers/{printer_id}/webcams/default/snapshot")
async def get_printer_default_webcam_snapshot(printer_id: str, _: dict = Depends(get_current_user)) -> Response:
    printer = _get_printer_or_404(printer_id)
    content, content_type = await fetch_webcam_snapshot(printer, None)
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    return Response(content=content, media_type=content_type, headers=headers)


@app.get("/api/printers/{printer_id}/webcams/{uid}/snapshot")
async def get_printer_webcam_snapshot_route(printer_id: str, uid: str, _: dict = Depends(get_current_user)) -> Response:
    printer = _get_printer_or_404(printer_id)
    content, content_type = await fetch_webcam_snapshot(printer, uid)
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    return Response(content=content, media_type=content_type, headers=headers)


@app.get("/api/printers/{printer_id}/timelapse")
async def get_printer_timelapse(printer_id: str, limit: int = 12, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    payload = await fetch_timelapses(printer, limit=max(1, min(limit, 50)))
    return payload.model_dump()


@app.get("/api/printers/{printer_id}/timelapse/{name}")
async def get_timelapse_file_route(printer_id: str, name: str, _: dict = Depends(get_current_user)) -> FileResponse:
    """Serve one timelapse file for playback/download.

    FOUND BY REVIEW: the list route existed but this one didn't — every
    <video src> and download link in the timelapse tab 404'd (the SPA
    catch-all swallows any api/* path with no matching route).
    """
    printer = _get_printer_or_404(printer_id)
    if not printer.timelapse_dir:
        raise HTTPException(status_code=404, detail="No timelapse directory configured")
    directory = Path(printer.timelapse_dir).expanduser().resolve()
    requested = (directory / name).resolve()
    if not requested.is_relative_to(directory) or not requested.is_file():
        raise HTTPException(status_code=404, detail="Timelapse file not found")
    return FileResponse(requested)


@app.get("/api/printers/{printer_id}/temperature-history")
async def get_printer_temperature_history(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Get temperature history for a printer."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_temperature_history
    return await fetch_temperature_history(printer)


@app.post("/api/printers/{printer_id}/gcode", dependencies=[_WRITER])
async def run_gcode_console_route(
    printer_id: str,
    request: Request,
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a raw G-code command on a printer."""
    printer = _get_printer_or_404(printer_id)
    from .gcode_allowlist import validate_console_script
    from .fleet import run_gcode_console
    script = body.get("script") or ""
    try:
        try:
            script = validate_console_script(script)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return await run_gcode_console(printer, script)
    finally:
        await record_audit(
            db,
            action="fdm_gcode",
            user=current_user,
            resource=f"printer:{printer_id}",
            detail={"script": script},
            request=request,
        )


@app.get("/api/printers/{printer_id}/gcode/history")
async def get_gcode_history_route(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Fetch G-code command history."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_gcode_history
    return await fetch_gcode_history(printer)


@app.get("/api/printers/{printer_id}/bed-mesh")
async def get_bed_mesh_route(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Fetch bed mesh data for visualization."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_bed_mesh
    return await fetch_bed_mesh(printer)


@app.get("/api/printers/{printer_id}/exclude-objects")
async def get_exclude_objects_route(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Fetch list of objects that can be excluded from the current print."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_exclude_objects
    return await fetch_exclude_objects(printer)


@app.post("/api/printers/{printer_id}/exclude-objects/{name:path}", dependencies=[_WRITER])
async def exclude_object_route(
    printer_id: str,
    name: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Exclude a named object from the current print."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import exclude_object
    return await exclude_object(printer, name)


@app.get("/api/printers/{printer_id}/webcams/{uid}/stream")
async def get_webcam_stream_route(
    printer_id: str,
    uid: str,
    ticket: str | None = None,
):
    """Proxy MJPEG webcam stream from printer.

    Auth via single-use ticket (see POST /api/ws/ticket), not Bearer — an
    <img src> can't carry an Authorization header, same reasoning as
    /ws/fleet's ticket-only auth.
    """
    user = await consume_ws_ticket(ticket)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired ticket")
    printer = _get_printer_or_404(printer_id)
    from .fleet import stream_webcam
    return await stream_webcam(printer, uid)


@app.get("/api/printers/{printer_id}/host-stats")
async def get_host_stats(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Get host system stats (CPU, memory, network) for a printer's Moonraker instance."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_host_stats
    return await fetch_host_stats(printer)


@app.get("/api/printers/{printer_id}/queue")
async def get_print_queue(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Get print queue status for a printer."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_print_queue
    return await fetch_print_queue(printer)


@app.post("/api/printers/{printer_id}/queue/start", dependencies=[_WRITER])
async def start_print_queue(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Start the print queue."""
    printer = _get_printer_or_404(printer_id)
    try:
        from .fleet import _get_client
        from .moonraker import MoonrakerClient
        client = await _get_client(printer)
        if isinstance(client, MoonrakerClient):
            await client._request("POST", "/server/job_queue/start")
            return {"ok": True}
        return {"ok": False}
    except Exception as e:
        logger.error(f"Failed to start queue for {printer.id}: {e}")
        raise HTTPException(500, f"Failed to start queue: {e}")


@app.post("/api/printers/{printer_id}/queue/pause", dependencies=[_WRITER])
async def pause_print_queue(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Pause the print queue."""
    printer = _get_printer_or_404(printer_id)
    try:
        from .fleet import _get_client
        from .moonraker import MoonrakerClient
        client = await _get_client(printer)
        if isinstance(client, MoonrakerClient):
            await client._request("POST", "/server/job_queue/pause")
            return {"ok": True}
        return {"ok": False}
    except Exception as e:
        logger.error(f"Failed to pause queue for {printer.id}: {e}")
        raise HTTPException(500, f"Failed to pause queue: {e}")


@app.get("/api/printers/{printer_id}/updates")
async def get_update_status(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Get update status for a printer's Klipper and Moonraker."""
    printer = _get_printer_or_404(printer_id)
    from .fleet import fetch_update_status
    return await fetch_update_status(printer)


@app.post("/api/printers/actions/{action}", dependencies=[_WRITER])
async def batch_action(
    action: str,
    body: BatchActionRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cfg = get_config()
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown action")
    result = await run_batch_action(cfg.printers, body, action)
    # One audit row per printer (not one per batch) — run_batch_action already
    # isolates per-printer adapter exceptions into a "error" BatchActionResult
    # rather than raising, so this always sees real per-printer outcomes,
    # including failures. Mirrors cnc_routes' record-even-on-failure pattern,
    # scoped to each device rather than the whole batch call.
    await record_audit_batch(db, [
        {
            "action": f"fdm_{action}",
            "user": current_user,
            "resource": f"printer:{r.printer_id}",
            "detail": {"status": r.status, "allowed": r.allowed, "message": r.message},
            "request": request,
        }
        for r in result.results
    ])
    return result.model_dump()


@app.post("/api/dry-run/actions/{action}")
async def batch_action_dry_run(action: str, request: DryRunRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    cfg = get_config()
    if action not in DRY_RUN_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown dry-run action")
    result = await dry_run_batch_action(cfg.printers, request, action)
    return result.model_dump()


@app.post("/api/printers/{printer_id}/motion-check", dependencies=[_WRITER])
async def motion_check_route(printer_id: str, request: MotionCheckRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    printer = _get_printer_or_404(printer_id)
    result = await motion_check(printer, request)
    return result.model_dump()


@app.post("/api/dispatch/dry-run")
async def dispatch_dry_run_route(request: DispatchDryRunRequest, _: dict = Depends(get_current_user)) -> dict[str, object]:
    cfg = get_config()
    result = await dispatch_dry_run(cfg.printers, request)
    return result.model_dump()


@app.post("/api/printers/{printer_id}/actions/{action}", dependencies=[_WRITER])
async def single_printer_action(
    printer_id: str,
    action: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown action")
    body = BatchActionRequest(printer_ids=[printer_id], mode="standard")
    return await batch_action(action, body, request, current_user, db)


# ============================================================================
# WRITE-BACK ENDPOINTS (Bidirectional Sync)
# ============================================================================

@app.get("/api/printers/{printer_id}/spool/log")
async def get_spool_log(
    printer_id: str,
    limit: int = 50,
    _: dict = Depends(get_current_user),
) -> dict:
    """Return spool depletion history for a printer (newest first)."""
    _get_printer_or_404(printer_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SpoolLog)
            .where(SpoolLog.printer_id == printer_id)
            .order_by(SpoolLog.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        rows = result.scalars().all()
    return {
        "printer_id": printer_id,
        "entries": [
            {
                "id": r.id,
                "job_name": r.job_name,
                "filament_used_mm": r.filament_used_mm,
                "filament_used_g": r.filament_used_g,
                "spool_before_g": r.spool_before_g,
                "spool_after_g": r.spool_after_g,
                "material": r.material,
                "source": r.source,
                "note": r.note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@app.post("/api/printers/{printer_id}/spool/log", dependencies=[_WRITER])
async def add_spool_log_entry(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Manually append a spool log entry (spool swap, correction, etc.)."""
    _get_printer_or_404(printer_id)
    remaining_g = body.get("remaining_g")
    note = body.get("note", "manual")
    material = body.get("material")

    # Optionally update spool_remaining_g in config if provided
    if remaining_g is not None:
        cfg = get_config()
        pc = next((p for p in cfg.printers if p.id == printer_id), None)
        spool_before = pc.spool_remaining_g if pc else None
        await update_printer_fields(printer_id, {"spool_remaining_g": float(remaining_g)})
        if material:
            await update_printer_fields(printer_id, {"current_material": material})
    else:
        spool_before = None

    async with AsyncSessionLocal() as db:
        row = SpoolLog(
            printer_id=printer_id,
            job_name=None,
            filament_used_mm=None,
            filament_used_g=None,
            spool_before_g=round(spool_before) if spool_before is not None else None,
            spool_after_g=round(float(remaining_g)) if remaining_g is not None else None,
            material=material,
            source="manual",
            note=note,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return {"ok": True, "id": row.id}


@app.post("/api/printers/{printer_id}/speed-factor", dependencies=[_WRITER])
async def set_speed_factor(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Set live speed factor (M220) and persist to DB."""
    from .moonraker_db import MoonrakerDBWriter

    printer = _get_printer_or_404(printer_id)

    try:
        factor = body.get("factor", 1.0)
        if not (0.1 <= factor <= 2.0):
            raise HTTPException(400, "factor must be 0.1-2.0")

        writer = MoonrakerDBWriter(printer.base_url)
        await writer.set_speed_factor(factor)
        return {"ok": True, "factor": factor}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set speed factor for {printer_id}: {e}")
        raise HTTPException(500, f"Speed factor update failed: {e}")


@app.post("/api/printers/{printer_id}/extrude-factor", dependencies=[_WRITER])
async def set_extrude_factor(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Set live extrude/flow factor (M221) and persist to DB."""
    from .moonraker_db import MoonrakerDBWriter

    printer = _get_printer_or_404(printer_id)

    try:
        factor = body.get("factor", 1.0)
        if not (0.5 <= factor <= 1.5):
            raise HTTPException(400, "factor must be 0.5-1.5")

        writer = MoonrakerDBWriter(printer.base_url)
        await writer.set_extrude_factor(factor)
        return {"ok": True, "factor": factor}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set extrude factor for {printer_id}: {e}")
        raise HTTPException(500, f"Extrude factor update failed: {e}")


@app.post("/api/printers/{printer_id}/maintenance/complete", dependencies=[_WRITER])
async def record_maintenance_complete(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Record maintenance completion — updates last_service_at, clears maintenance_due, optionally sets next_service_due."""
    from .config import update_printer_fields

    printer = _get_printer_or_404(printer_id)

    try:
        maintenance_type = body.get("type", "service")  # nozzle_change, rebuild, service
        notes = body.get("notes", "")
        now_iso = datetime.now(timezone.utc).date().isoformat()  # YYYY-MM-DD

        # Compute next_service_due if interval_hours provided
        interval_hours = printer.maintenance_interval_hours
        next_due: str | None = None
        if interval_hours and interval_hours > 0:
            from datetime import timedelta
            next_dt = datetime.now(timezone.utc) + timedelta(hours=interval_hours)
            next_due = next_dt.date().isoformat()

        # Persist to devices.yaml
        fields_to_update: dict = {
            "last_service_at": now_iso,
            "maintenance_due": False,
            "maintenance_state": None,
        }
        if next_due:
            fields_to_update["next_service_due"] = next_due
        if notes:
            # Append note rather than replacing; read current notes first
            current_notes = list(printer.maintenance_notes or [])
            current_notes.append(f"{now_iso}: [{maintenance_type}] {notes}")
            fields_to_update["maintenance_notes"] = current_notes

        await update_printer_fields(printer_id, fields_to_update)

        logger.info(
            f"[maintenance] {printer_id}: completed '{maintenance_type}' on {now_iso}"
            + (f", next due {next_due}" if next_due else "")
        )
        return {
            "ok": True,
            "type": maintenance_type,
            "last_service_at": now_iso,
            "next_service_due": next_due,
            "maintenance_due": False,
        }
    except Exception as e:
        logger.error(f"Failed to record maintenance for {printer_id}: {e}")
        raise HTTPException(500, f"Maintenance record failed: {e}")


@app.post("/api/printers/{printer_id}/queue/resume", dependencies=[_WRITER])
async def resume_print_queue(
    printer_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Resume paused print queue."""
    from .fleet import _get_client

    printer = _get_printer_or_404(printer_id)

    try:
        client = await _get_client(printer)
        response = await client._request('POST', '/server/job_queue/start', json={})
        return {"ok": True}
    except Exception as e:
        logger.error(f"Failed to resume queue for {printer_id}: {e}")
        raise HTTPException(500, f"Queue resume failed: {e}")


@app.delete("/api/printers/{printer_id}/queue/{job_id}", dependencies=[_WRITER])
async def remove_from_queue(
    printer_id: str,
    job_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Remove job from queue."""
    from .fleet import _get_client

    printer = _get_printer_or_404(printer_id)

    try:
        client = await _get_client(printer)
        response = await client._request('POST', '/server/job_queue/delete', json={"job_ids": [job_id]})
        return {"ok": True}
    except Exception as e:
        logger.error(f"Failed to remove {job_id} from queue for {printer_id}: {e}")
        raise HTTPException(500, f"Queue removal failed: {e}")


@app.post("/api/printers/{printer_id}/queue/add", dependencies=[_WRITER])
async def add_to_queue(
    printer_id: str,
    body: dict = Body(...),
    _: dict = Depends(get_current_user),
) -> dict:
    """Add file to print queue."""
    from .fleet import _get_client

    printer = _get_printer_or_404(printer_id)

    try:
        filename = body.get("filename")
        if not filename:
            raise HTTPException(400, "filename required")

        client = await _get_client(printer)
        response = await client._request('POST', '/server/job_queue/job', json={"filenames": [filename]})
        return {"ok": True, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add {body.get('filename')} to queue for {printer_id}: {e}")
        raise HTTPException(500, f"Queue add failed: {e}")


# ============================================================================
# FIRMWARE MANAGEMENT (Phase 1: Read-Only)
# ============================================================================
# NOTE: Firmware endpoints are intentionally free-tier (no require_feature gate).
# Rationale: firmware version visibility is a basic operational need, not a
# premium analytics feature. Letting free-tier users see when updates are
# available keeps their fleet secure without requiring a paid plan.

@app.get("/api/fleet/firmware")
async def get_fleet_firmware_summary(
    _: dict = Depends(get_current_user),
) -> dict:
    """Get firmware summary for all printers in fleet."""
    from .firmware import FirmwareManager

    cfg = get_config()

    summary = {
        "printers": [],
        "update_needed": [],
        "total_printers": len([p for p in cfg.printers if p.enabled]),
    }

    for printer in cfg.printers:
        if not printer.enabled:
            continue

        try:
            async with FirmwareManager(printer.base_url) as manager:
                state = await manager.get_firmware_state()

            updates_needed = [
                c["name"] for c in state.get("components", [])
                if c.get("commits_behind", 0) > 0
            ]

            summary["printers"].append({
                "id": printer.id,
                "name": printer.name,
                "update_available": state.get("update_available", False),
                "components": state.get("components", []),
            })

            if updates_needed:
                summary["update_needed"].append({
                    "id": printer.id,
                    "name": printer.name,
                    "components": updates_needed,
                })
        except Exception as e:
            logger.warning(f"Could not fetch firmware for {printer.id}: {e}")

    return summary


@app.post("/api/ws/ticket")
async def create_ws_ticket_route(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mint a short-lived, single-use ticket for opening one WebSocket.

    Bearer-authed (so the JWT stays in the Authorization header, never a URL).
    The client connects with `?ticket=<nonce>`; the nonce expires in ~30s and is
    consumed on first use. Reconnects must request a fresh ticket.
    """
    nonce = await create_ws_ticket(db, current_user)
    return {"ticket": nonce, "expires_in": WS_TICKET_TTL_SECONDS}


@app.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket) -> None:
    # Auth via single-use ticket (see POST /api/ws/ticket). The long-lived access
    # token is deliberately NOT accepted here — putting it in the WS query string
    # leaked it into proxy/access logs.
    ticket = websocket.query_params.get("ticket")
    user = await consume_ws_ticket(ticket)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await websocket.accept()
    try:
        while True:
            cfg = get_config()
            printers = await fetch_fleet(cfg.printers)
            asyncio.create_task(detect_state_changes(printers))
            payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "printers": [printer.model_dump() for printer in printers]}
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                return


@app.get("/api/monitor/events")
async def monitor_sse(request: Request, _: dict = Depends(get_current_user)):
    """SSE stream for real-time CV anomaly events."""
    from starlette.responses import StreamingResponse
    from .print_monitor import _sse_queue as _mon_queue

    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = _mon_queue.get_nowait()
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.QueueEmpty:
                await asyncio.sleep(1)
                yield ": ping\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/monitor/state")
async def get_monitor_state_endpoint(_: dict = Depends(get_current_user)) -> dict:
    """Return current CV anomaly state for all printers."""
    from .print_monitor import get_monitor_state as _get_state
    return {"ok": True, "anomalies": _get_state()}


app.include_router(oee_router)
app.include_router(floorplan_router)
app.include_router(webhooks_router)
app.include_router(billing_router, prefix="/api")
app.include_router(stripe_router)
app.include_router(admin_router)
app.include_router(audit_router)
app.include_router(sso_router)
app.include_router(sso_admin_router)
app.include_router(branding_router)
app.include_router(settings_router)
app.include_router(cnc_router)
app.include_router(pa_router)
app.include_router(motion_router)
# SECURITY: WebAuthn router unmounted until assertions are cryptographically verified.
# See https://github.com/stratum-industries-foss/memar/issues/XXX
# app.include_router(webauthn_router)
app.include_router(messaging_admin_router)
app.include_router(password_reset_router)
app.include_router(onboarding_router)
if analytics_router is not None:
    app.include_router(analytics_router)

_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend_dist"
_INDEX_HTML = _DIST_DIR / "index.html"
if (_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
async def spa_root() -> Response:
    if not _INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="frontend not built")
    _NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}
    # Read file fresh each time to avoid any caching issues
    content = _INDEX_HTML.read_text(encoding='utf-8')
    logger.info(f"spa_root: serving index.html from {_INDEX_HTML}, contains: {'BoWdH3bI' if 'BoWdH3bI' in content else 'Dhijqeok'}")
    return Response(content=content, media_type="text/html; charset=utf-8", headers=_NO_CACHE)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> Response:
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        raise HTTPException(status_code=404, detail="Not found")
    if not _INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="frontend not built")
    # Serve static files from dist root (e.g. manifest.json, favicon.ico) before SPA fallback
    static_file = _DIST_DIR / full_path
    if static_file.is_file() and static_file.resolve().is_relative_to(_DIST_DIR.resolve()):
        return FileResponse(static_file)
    _NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}
    # Read file fresh each time to avoid any caching issues
    content = _INDEX_HTML.read_text(encoding='utf-8')
    return Response(content=content, media_type="text/html; charset=utf-8", headers=_NO_CACHE)
