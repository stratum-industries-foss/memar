"""Webhook event bus, background dispatcher, and CRUD endpoints."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db, AsyncSessionLocal
from .deps import get_current_user, require_feature, require_role
from .models_db import Webhook, SpoolLog, WebhookDeliveryLog
from .ssrf import (
    PinnedResolveTransport,
    resolve_public_ip as _resolve_public_ip,
    _is_unsafe_ip as _is_unsafe_webhook_ip,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts/webhooks", tags=["webhooks"])

# Module-level state
_event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
_prev_states: dict[str, str] = {}  # printer_id → last known state string
_prev_states_lock = asyncio.Lock()
_detect_task: asyncio.Task | None = None  # T127: single in-flight detect_state_changes

# R3 BUG FIX: Strong references to fire-and-forget tasks. Without these, asyncio.create_task
# tasks can be GC'd mid-flight before completing, silently losing the work (email alerts,
# job records, spool deductions). Mirrored from fleet.py's _pending_close_tasks pattern.
_pending_webhook_tasks: set[asyncio.Task] = set()


# --- SSRF Guard ---
#
# Webhook targets are user-supplied and dispatched to server-side, so a
# malicious or compromised user could point a webhook at cloud metadata
# endpoints (169.254.169.254) or internal-only services. The SSRF protection
# code (PinnedResolveTransport, _is_unsafe_webhook_ip, _resolve_public_ip) is
# now centralized in app/ssrf.py for reuse across the codebase.
#
# DNS-rebinding note: a standalone "validate the URL, then httpx.post(url)"
# pattern is NOT rebinding-safe, because httpx re-resolves the hostname at
# connect time. PinnedResolveTransport resolves each request's host EXACTLY
# ONCE, validates that IP is public, and connects to that pinned IP (no second
# lookup) while preserving the original hostname for the Host header, TLS SNI,
# and certificate verification. `_validate_webhook_url` is kept only as an
# early, user-facing fast-fail (clear 400 at create time / before the first
# attempt); it is defense-in-depth, not the load-bearing control.


async def _validate_webhook_url(url: str) -> None:
    """Early fast-fail: raise HTTPException(400) if `url`'s host is missing or
    resolves to a disallowed IP. Runs the blocking lookup in the default executor
    so it can't stall the event loop.

    This is NOT the anti-rebinding control (see module note) — it resolves
    independently of the eventual connection. `PinnedResolveTransport` is the
    authoritative single-resolve-and-pin guard used for the actual dispatch.
    """
    host = httpx.URL(url).host
    if not host:
        raise HTTPException(status_code=400, detail="Webhook URL must have a host")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _resolve_public_ip, host)


# --- Event Publishing ---


async def publish_event(event_type: str, printer_id: str, data: dict) -> None:
    """
    Publish an event to the webhook queue.
    Non-blocking; silently drops events if queue is full.
    """
    try:
        _event_queue.put_nowait(
            {"type": event_type, "printer_id": printer_id, "data": data}
        )
    except asyncio.QueueFull:
        logger.warning(f"Webhook queue full, dropping event: {event_type}")
        pass


# --- Email alerts on equipment state changes (Maker+ tier) ---
_last_email_alert: dict[str, datetime] = {}
_EMAIL_ALERT_DEBOUNCE_S = 15 * 60  # one email per device per 15 min


async def _email_alert(printer_id: str, event_type: str, state: str) -> None:
    """Email the configured recipients when a device goes error/offline.

    Gated by the email_alerts feature (Maker+) and MEMAR_ALERT_EMAILS; debounced
    per device so a flapping device can't spam the inbox. Fire-and-forget.
    """
    from . import email_service
    from .license import get_license

    lic = get_license()
    if not (lic.active and "email_alerts" in lic.features):
        return
    now = datetime.now(timezone.utc)
    last = _last_email_alert.get(printer_id)
    if last and (now - last).total_seconds() < _EMAIL_ALERT_DEBOUNCE_S:
        return
    _last_email_alert[printer_id] = now
    company = "MEMAR"
    if "custom_branding" in lic.features:  # only branded tiers need the DB lookup
        try:  # white-label the alert; cosmetic, never blocks the alert itself
            from .branding import get_effective_branding
            from .db import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                company = (await get_effective_branding(db)).get("company_name") or "MEMAR"
        except Exception:  # noqa: BLE001
            pass
    subject = f"⚠️ {company} alert: {printer_id} is {state}"
    body = (f"Device {printer_id} transitioned to '{state}' ({event_type}) "
            f"at {now.isoformat()}.\n\n— {company}")
    try:
        await email_service.send_alert(subject, body, device_id=printer_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("email alert failed for %s: %s", printer_id, e)


async def detect_state_changes(printers: list) -> None:
    """
    Detect state changes in printer list and publish events.
    Called each WebSocket cycle.

    Args:
        printers: List of FleetPrinter objects from fetch_fleet()
    """
    # T127: Keep only one in-flight detect_state_changes task
    global _detect_task
    if _detect_task and not _detect_task.done():
        return  # Skip, prior still running
    _detect_task = asyncio.current_task()
    try:
        async with _prev_states_lock:
            for p in printers:
                prev = _prev_states.get(p.id)
                # Determine current state
                cur = p.job.state if p.job else ("offline" if not p.online else "idle")

                # Detect transitions and publish events
                if prev is not None and prev != cur:
                    job_name = p.job.filename if (p.job and getattr(p.job, "filename", None)) else None
                    if cur == "error":
                        await publish_event("printer.error", p.id, {"state": cur})
                        task = asyncio.create_task(_email_alert(p.id, "printer.error", cur))
                        _pending_webhook_tasks.add(task)
                        task.add_done_callback(_pending_webhook_tasks.discard)
                        _record_job(p.id, job_name, "failed", failure_reason="printer error")
                    elif cur == "complete" or (
                        prev == "printing" and cur in ("idle", "ready")
                    ):
                        await publish_event("printer.complete", p.id, {"state": cur})
                        # Auto-deduct spool on job completion (fire-and-forget)
                        task = asyncio.create_task(_deduct_spool_on_complete(p))
                        _pending_webhook_tasks.add(task)
                        task.add_done_callback(_pending_webhook_tasks.discard)
                        _record_job(p.id, job_name, "completed")
                    elif cur == "offline":
                        await publish_event("printer.offline", p.id, {"state": cur})
                        task = asyncio.create_task(_email_alert(p.id, "printer.offline", cur))
                        _pending_webhook_tasks.add(task)
                        task.add_done_callback(_pending_webhook_tasks.discard)

                _prev_states[p.id] = cur
    finally:
        _detect_task = None


def _record_job(device_id: str, job_name, status: str, failure_reason: str | None = None) -> None:
    """Fire-and-forget JobLog write for analytics (OEE / error-rate)."""
    from .telemetry import record_job_completion
    asyncio.create_task(
        record_job_completion(device_id, job_name, status, failure_reason=failure_reason)
    )


async def _deduct_spool_on_complete(printer) -> None:
    """
    Compute filament/resin/wire consumption for a completed job and deduct
    from spool_remaining_g.  Writes a SpoolLog row for audit history.
    Supports all machine types with a mass model; silently skips others.

    H1 BUG FIX: Idempotency guard — if a SpoolLog entry already exists for this
    job_name on this printer (within the last 5 minutes), skip the deduction.
    This prevents double-deduction when the printer flaps between printing and idle
    (e.g., pause → resume → complete), or when detect_state_changes is called
    concurrently from the WebSocket loop and the telemetry sampler.
    """
    from .spool_deduction import compute_consumption
    from .config import get_config, update_printer_fields
    from datetime import timedelta

    try:
        # Gather consumption inputs from the printer's last job state
        job = printer.job
        cap = printer.capability if hasattr(printer, "capability") else None
        # MachineType is a (str, Enum), so str(MachineType.FDM) is "MachineType.FDM",
        # NOT "fdm". Every downstream .lower() comparison here — and
        # compute_consumption's own dispatch — then falls through to
        # "not_applicable", so grams_used comes back None and the spool is never
        # deducted. Unwrap to the enum's value once, the way fleet.py already does.
        _machine_type_raw = (cap.machine_type if cap else None) or "fdm"
        machine_type = str(getattr(_machine_type_raw, "value", _machine_type_raw) or "fdm")
        material = (cap.current_material if cap else None)
        filament_used_mm = float(job.filament_used_mm or 0) if job else 0.0

        # Look up live PrinterConfig for static overrides (filament_diameter, wire config)
        cfg = get_config()
        printer_cfg = next((pc for pc in cfg.printers if pc.id == printer.id), None)
        if printer_cfg is None:
            return

        job_name = job.filename if job else None

        # H1 FIX: Idempotency guard — check if this job was already deducted recently
        # This check has its own try/except: a failure *here* (DB hiccup, session
        # issue, etc.) must never silently abort the entire deduction below it.
        # Previously any exception from this block was caught by the outer
        # `except Exception` wrapping the whole function, which meant a transient
        # or unrelated failure in the dedup lookup silently skipped deducting the
        # spool at all (not just the idempotency check) — exactly the kind of
        # silent no-op this function's docstring warns against.
        try:
            async with AsyncSessionLocal() as db:
                # Look for any SpoolLog entry for this job on this printer in the last 5 minutes
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
                result = await db.execute(
                    select(SpoolLog).where(
                        SpoolLog.printer_id == printer.id,
                        SpoolLog.job_name == job_name,
                        SpoolLog.created_at >= cutoff,
                    )
                )
                if result.scalar_one_or_none() is not None:
                    # Job already deducted recently — skip to avoid double-deduction
                    logger.debug(f"[spool] {printer.id}/{job_name} already deducted recently, skipping")
                    return
        except Exception as guard_err:
            logger.warning(
                f"[spool] idempotency guard failed for {printer.id}/{job_name}, "
                f"proceeding with deduction anyway: {guard_err}"
            )

        # Filament diameter: config field > default 1.75mm
        filament_diameter_mm: float = printer_cfg.filament_diameter_mm or 1.75

        # Wire EDM: use config-level wire_used_mm_per_job (no Moonraker equivalent)
        wire_used_mm = printer_cfg.wire_used_mm_per_job if str(machine_type).lower() == "wire_edm" else None

        # SLA: layer_height from job object; if missing, fetch from Moonraker file metadata
        layer_count = getattr(job, "total_layer", None)
        layer_height_mm: float | None = None
        build_x = build_y = None
        if cap and cap.build_volume:
            build_x = cap.build_volume.get("x")
            build_y = cap.build_volume.get("y")

        if str(machine_type).lower() in ("sla", "msla", "dlp", "lcd") and job and job.filename:
            try:
                from .fleet import _get_client, _safe_float
                client = await _get_client(printer_cfg)
                from .moonraker import MoonrakerClient
                if isinstance(client, MoonrakerClient):
                    raw_meta = await client.file_metadata(job.filename)
                    if layer_height_mm is None:
                        layer_height_mm = _safe_float(raw_meta.get("layer_height"))
                    if layer_count is None:
                        layer_count = raw_meta.get("layer_count") or raw_meta.get("layers")
            except Exception as _meta_err:
                logger.debug(f"[spool] SLA metadata fetch failed for {printer.id}: {_meta_err}")

        grams_used, method = compute_consumption(
            str(machine_type),
            filament_used_mm=filament_used_mm if filament_used_mm > 0 else None,
            filament_diameter_mm=filament_diameter_mm,
            material=material,
            layer_count=int(layer_count) if layer_count else None,
            layer_height_mm=layer_height_mm,
            build_x_mm=build_x,
            build_y_mm=build_y,
            wire_used_mm=wire_used_mm,
        )

        spool_before = printer_cfg.spool_remaining_g
        spool_after: float | None = None

        if grams_used is not None and spool_before is not None:
            spool_after = max(0.0, round(spool_before - grams_used, 1))
            await update_printer_fields(printer.id, {"spool_remaining_g": spool_after})
            logger.info(
                f"[spool] {printer.id}: -{grams_used}g ({method}) "
                f"→ {spool_before}g → {spool_after}g"
            )

        # Write SpoolLog row regardless (logs even when spool_before is unknown)
        async with AsyncSessionLocal() as db:
            row = SpoolLog(
                printer_id=printer.id,
                job_name=job_name,
                filament_used_mm=int(filament_used_mm) if filament_used_mm else None,
                filament_used_g=round(grams_used) if grams_used is not None else None,
                spool_before_g=round(spool_before) if spool_before is not None else None,
                spool_after_g=round(spool_after) if spool_after is not None else None,
                material=material,
                source="auto",
                note=method,
            )
            db.add(row)
            await db.commit()

    except Exception as exc:
        logger.warning(f"[spool] deduction failed for {printer.id}: {exc}")


# --- Background Dispatcher ---


async def _dispatch_loop() -> None:
    """
    Background loop that reads events from the queue and dispatches them
    to all active webhooks via HTTP POST with HMAC signing and retry.

    Runs indefinitely; swallows HTTP errors gracefully.
    """
    # PinnedResolveTransport resolves-once-and-pins each request to a validated
    # public IP (closes DNS-rebinding). follow_redirects stays False so a 3xx to
    # an internal host can't be chased past the guard.
    async with httpx.AsyncClient(
        timeout=5.0,
        transport=PinnedResolveTransport(),
        follow_redirects=False,
    ) as client:
        while True:
            try:
                event = await _event_queue.get()

                # Fan event out to messaging hub (Telegram, Slack, ntfy, etc.)
                try:
                    from .messaging import get_hub, AlertEvent as _AE
                    _hub = get_hub()
                    _sev = "error" if "error" in event["type"] else (
                        "warning" if "offline" in event["type"] else "info"
                    )
                    task = asyncio.create_task(_hub.broadcast(_AE(
                        type=event["type"],
                        title=event["type"].replace(".", " ").replace("_", " ").title(),
                        body=f"Device {event.get('printer_id', 'unknown')}: {event['type']}",
                        severity=_sev,
                        device_id=event.get("printer_id"),
                        data=event.get("data", {}),
                    )))
                    _pending_webhook_tasks.add(task)
                    task.add_done_callback(_pending_webhook_tasks.discard)
                except Exception:
                    pass  # hub not ready or import failed — never block HTTP dispatch

                # Fetch all active webhooks from database
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Webhook).where(Webhook.active == True)
                    )
                    hooks = result.scalars().all()

                # Dispatch to each matching webhook
                for hook in hooks:
                    try:
                        events = (
                            json.loads(hook.events)
                            if isinstance(hook.events, str)
                            else hook.events
                        )
                    except json.JSONDecodeError:
                        continue
                    if event["type"] in events:
                        asyncio.create_task(_dispatch_with_retry(client, hook, event))
            except Exception as e:
                logger.error(f"dispatch loop error: {e}")
                continue


async def _dispatch_with_retry(client: httpx.AsyncClient, hook: Webhook, event: dict) -> None:
    """
    Dispatch event to webhook with retry (max 3 attempts, exponential backoff).
    Log each attempt for debugging.
    """
    max_attempts = 3
    # Serialize the body ONCE. The HMAC must be computed over the exact bytes we
    # transmit, so we send `content=payload_bytes` (not json=event, which would
    # let httpx re-serialize with different whitespace/key order and break the
    # receiver's signature check).
    payload_bytes = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    secret = (hook.secret or "").encode()
    sig = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-MEMAR-Signature": f"sha256={sig}",
        "X-MEMAR-Event": str(event.get("type", "")),
    }
    for attempt in range(1, max_attempts + 1):
        try:
            # SSRF is enforced by PinnedResolveTransport on the dispatch client
            # (resolve-once-and-pin at connect). No pre-check here: it would
            # re-resolve independently and, on an unresolvable host, abort before
            # the transport runs. _validate_webhook_url still fast-fails at
            # webhook create time (see the create/update endpoints).
            response = await client.post(hook.url, content=payload_bytes, headers=headers)

            # Log success
            async with AsyncSessionLocal() as db:
                log = WebhookDeliveryLog(
                    webhook_id=hook.id,
                    event_type=event["type"],
                    attempt=attempt,
                    status_code=response.status_code,
                    delivered_at=datetime.now(timezone.utc) if response.status_code < 400 else None,
                )
                db.add(log)
                await db.commit()

            if response.status_code < 400:
                logger.info(f"Webhook {hook.id} delivered: {response.status_code}")
                return
            else:
                logger.warning(
                    f"Webhook {hook.id} attempt {attempt}: {response.status_code}"
                )
                if attempt < max_attempts:
                    # Same exponential backoff as the exception path below — a
                    # receiver returning 4xx/5xx was retried with NO delay,
                    # hammering it 3x back-to-back instead of backing off.
                    backoff = 2 ** (attempt - 1)
                    await asyncio.sleep(backoff)
        except Exception as e:
            # Log failure
            async with AsyncSessionLocal() as db:
                log = WebhookDeliveryLog(
                    webhook_id=hook.id,
                    event_type=event["type"],
                    attempt=attempt,
                    error=str(e),
                )
                db.add(log)
                await db.commit()

            logger.warning(f"Webhook {hook.id} attempt {attempt} failed: {e}")

            if attempt < max_attempts:
                # Exponential backoff: 1s, 2s, 4s
                backoff = 2 ** (attempt - 1)
                await asyncio.sleep(backoff)


def start_dispatcher() -> asyncio.Task:
    """Start the background webhook dispatcher task and return it so the caller
    can track/cancel it (asyncio holds only a weak ref — an untracked task can be
    garbage-collected mid-run, silently killing all webhook alerting)."""
    return asyncio.create_task(_dispatch_loop())


# --- Pydantic Models ---


class WebhookCreateRequest(BaseModel):
    """Request body for creating a webhook."""

    url: HttpUrl
    events: list[str] = Field(min_length=1, max_length=20)  # e.g. ["printer.error", "printer.complete", "printer.offline"]


class WebhookResponse(BaseModel):
    """Response for webhook GET/POST operations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    events: list[str]
    active: bool
    created_by: int
    created_at: str


class WebhookCreateResponse(WebhookResponse):
    """Create response — includes the signing secret ONCE (never returned again)."""

    secret: str


# --- CRUD Routes ---


@router.post("/")
async def create_webhook(
    request: WebhookCreateRequest,
    current_user: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin")),
    _: None = Depends(require_feature("webhooks")),
    db: AsyncSession = Depends(get_db),
) -> WebhookCreateResponse:
    """
    Create a new webhook.
    Requires: authenticated admin + webhooks feature enabled. A webhook receives
    every fleet event regardless of creator, so creation is an admin capability.

    The response includes a freshly generated signing `secret`. This is the ONLY
    time the secret is returned — store it; the receiver uses it to verify the
    X-MEMAR-Signature HMAC-SHA256 over the raw request body.
    """
    await _validate_webhook_url(str(request.url))

    secret = secrets.token_hex(32)
    webhook = Webhook(
        url=str(request.url),
        events=json.dumps(request.events),
        active=True,
        secret=secret,
        created_by=current_user["id"],
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    return WebhookCreateResponse(
        id=webhook.id,
        url=webhook.url,
        events=json.loads(webhook.events),
        active=webhook.active,
        created_by=webhook.created_by,
        created_at=webhook.created_at.isoformat(),
        secret=secret,
    )


@router.get("/")
async def list_webhooks(
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_feature("webhooks")),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookResponse]:
    """
    List webhooks.
    - Admin: sees all webhooks
    - Others: sees only their own (created_by == user_id)
    """
    is_admin = current_user["role"] == "admin"

    if is_admin:
        result = await db.execute(select(Webhook))
    else:
        result = await db.execute(
            select(Webhook).where(Webhook.created_by == current_user["id"])
        )

    webhooks = result.scalars().all()

    return [
        WebhookResponse(
            id=w.id,
            url=w.url,
            events=json.loads(w.events) if isinstance(w.events, str) else w.events,
            active=w.active,
            created_by=w.created_by,
            created_at=w.created_at.isoformat(),
        )
        for w in webhooks
    ]


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    current_user: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin")),
    _: None = Depends(require_feature("webhooks")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Delete a webhook. Admin-only capability (webhook management is admin-gated).
    The residual owner check below is now belt-and-suspenders since only admins
    reach this handler.
    """
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    # Check authorization
    is_admin = current_user["role"] == "admin"
    is_owner = webhook.created_by == current_user["id"]

    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this webhook",
        )

    await db.delete(webhook)
    await db.commit()

    return {"message": "Webhook deleted"}


class WebhookDeliveryLogResponse(BaseModel):
    """Response for webhook delivery log entries."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    webhook_id: int
    event_type: str
    attempt: int
    status_code: int | None
    error: str | None
    delivered_at: str | None
    created_at: str


@router.get("/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    webhook_id: int,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_feature("webhooks")),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookDeliveryLogResponse]:
    """
    List delivery attempts for a webhook.
    - Admin: sees all deliveries
    - Others: sees only deliveries for webhooks they created (403 if not owner)
    """
    # Check webhook exists and user is authorized
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    is_admin = current_user["role"] == "admin"
    is_owner = webhook.created_by == current_user["id"]

    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this webhook's deliveries",
        )

    # Fetch delivery logs (most recent first, limit 100)
    result = await db.execute(
        select(WebhookDeliveryLog)
        .where(WebhookDeliveryLog.webhook_id == webhook_id)
        .order_by(WebhookDeliveryLog.created_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()

    return [
        WebhookDeliveryLogResponse(
            id=log.id,
            webhook_id=log.webhook_id,
            event_type=log.event_type,
            attempt=log.attempt,
            status_code=log.status_code,
            error=log.error,
            delivered_at=log.delivered_at.isoformat() if log.delivered_at else None,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]
