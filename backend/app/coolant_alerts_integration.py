"""
Coolant Alert Integration for CNC Routes

Wires the CNCMetricsLog table into coolant-pressure breach detection and
notification. See the "Clean entry points" section below for what's actually
called — evaluate_coolant_alerts_once() / start_coolant_alert_monitor(),
wired in main.py.
"""

from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_

from .coolant_alerts import AlertRouter
from .models_db import CNCMetricsLog
from .db import AsyncSessionLocal
from .config import get_config
from .slack_webhooks import SlackIntegration

logger = logging.getLogger(__name__)

# CNC-class machine types that have a coolant system worth monitoring.
# machine_type on PrinterConfig is a MachineType enum; we compare against .value.
CNC_MACHINE_TYPES: frozenset[str] = frozenset(
    {"cnc_mill", "cnc_lathe", "cnc_router", "wire_edm", "plasma", "waterjet", "laser"}
)

# Threshold logic. coolant_psi below LOW_PSI_THRESHOLD for at least
# MIN_SUSTAINED_MINUTES (measured from the span of the low samples in the
# lookback window) constitutes a breach. LOOKBACK is deliberately wider than
# MIN_SUSTAINED_MINUTES so a sample at the edge of the sustained window is still
# inside the query range.
LOW_PSI_THRESHOLD: float = 20.0
MIN_SUSTAINED_MINUTES: float = 5.0
LOOKBACK_MINUTES: int = 15

# Alert dedup: once a device's breach fires, suppress re-notification until this
# many minutes elapse (edge-triggered fire + periodic re-reminder), instead of
# re-firing every monitor tick. Cleared when the device recovers, so a fresh
# breach after recovery alerts immediately. This is the ONLY cross-poll state in
# this module; the breach decision itself (_evaluate_device) stays pure.
ALERT_REMINDER_MINUTES: float = 30.0
_last_alert_fired: dict[str, datetime] = {}


# ---------------------------------------------------------------------------
# Clean entry points
#
# These are the two functions the rest of the app wires up. The breach
# DECISION (_evaluate_device) is pure: it depends only on the DATA WINDOW —
# the timestamps and values of the CNCMetricsLog rows themselves — which keeps
# it deterministic and testable. The once-fn additionally consults a small
# cross-poll dedup latch (_last_alert_fired) to decide whether to *notify*, so
# a sustained breach edge-fires + re-reminds instead of storming every tick.
# ---------------------------------------------------------------------------


def _cnc_devices() -> list:
    """Enabled CNC-class printers from config (NOT a Device table — there is none)."""
    devices = []
    for p in get_config().printers:
        if not getattr(p, "enabled", True):
            continue
        mt = getattr(p, "machine_type", None)
        mt_value = getattr(mt, "value", mt)  # MachineType enum → str
        if mt_value in CNC_MACHINE_TYPES:
            devices.append(p)
    return devices


def _device_names() -> dict[str, str]:
    """Map device_id → display name from config (CNC devices only)."""
    return {p.id: p.name for p in _cnc_devices()}


async def _fire_notifications(alert: dict, webhook_url: Optional[str]) -> None:
    """Fan out a coolant breach alert to the unified messaging hub.

    Falls back to direct Slack + webhook if the hub isn't initialised yet
    (e.g. during early startup before lifespan has run). Never raises.
    """
    try:
        from .messaging import get_hub, AlertEvent
        hub = get_hub()
        event = AlertEvent(
            type="cnc.coolant_low",
            title="Coolant Pressure Critical",
            body=alert["message"],
            severity="critical",
            device_id=alert["device_id"],
            data={
                "current_psi": alert["current_psi"],
                "threshold_psi": alert["threshold_psi"],
                "duration_minutes": alert["duration_minutes"],
                "device_name": alert["device_name"],
            },
        )
        await hub.broadcast(event)
        return
    except Exception as e:  # noqa: BLE001 - fallback path
        logger.debug("Hub broadcast unavailable (%s); using legacy direct notify", e)

    # Legacy fallback — keeps backward compat if hub not yet started
    try:
        await SlackIntegration.send_alert(
            title="Coolant Pressure Critical",
            message=alert["message"],
            severity="critical",
            device_id=alert["device_id"],
            device_name=alert["device_name"],
            metadata={
                "current_psi": f"{alert['current_psi']:.1f}",
                "threshold_psi": alert["threshold_psi"],
                "duration_minutes": alert["duration_minutes"],
            },
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Slack coolant alert failed for {alert['device_id']}: {e}")

    if webhook_url:
        router = AlertRouter(webhook_url=webhook_url)
        try:
            await router._send_webhook_alert(alert)
        except Exception as e:
            logger.error(f"Webhook coolant alert failed for {alert['device_id']}: {e}")


async def evaluate_coolant_alerts_once() -> list[dict]:
    """Evaluate every CNC device once against CNCMetricsLog and notify on breach.

    For each enabled CNC device:
      * Pull rows in the last LOOKBACK_MINUTES that have a non-NULL coolant_psi.
      * No such rows  -> no PSI data yet (the common case today) -> skip device.
      * All rows < LOW_PSI_THRESHOLD AND the low samples span >= MIN_SUSTAINED_MINUTES
        -> breach: fire notifications and record the alert.

    Returns the list of alert dicts raised this call. Notification failures are
    swallowed (logged) and never abort the sweep.
    """
    now = datetime.utcnow()  # naive UTC — consistent with stored timestamps
    cutoff = now - timedelta(minutes=LOOKBACK_MINUTES)
    webhook_url = os.getenv("MEMAR_COOLANT_WEBHOOK_URL") or os.getenv("WEBHOOK_URL")

    devices = _cnc_devices()
    if not devices:
        return []

    alerts: list[dict] = []

    async with AsyncSessionLocal() as db:
        for device in devices:
            stmt = (
                select(CNCMetricsLog)
                .where(
                    and_(
                        CNCMetricsLog.device_id == device.id,
                        CNCMetricsLog.timestamp >= cutoff,
                        CNCMetricsLog.coolant_psi.isnot(None),
                    )
                )
                .order_by(CNCMetricsLog.timestamp)
            )
            rows = (await db.execute(stmt)).scalars().all()

            alert = _evaluate_device(device.id, device.name, rows, now)
            if alert is None:
                # Recovered (or never breached) — clear the latch so the next
                # breach fires immediately rather than waiting out a stale cooldown.
                _last_alert_fired.pop(device.id, None)
                continue

            last = _last_alert_fired.get(device.id)
            if last is not None and (now - last).total_seconds() < ALERT_REMINDER_MINUTES * 60:
                # Still in an active, already-notified breach — suppress the
                # duplicate to avoid a per-tick alert storm.
                continue

            _last_alert_fired[device.id] = now
            alerts.append(alert)
            logger.warning(
                "COOLANT ALERT: %s - %.1f PSI sustained %d min",
                alert["device_name"],
                alert["current_psi"],
                alert["duration_minutes"],
            )
            await _fire_notifications(alert, webhook_url)

    return alerts


def _evaluate_device(
    device_id: str,
    device_name: str,
    rows: list,
    now: datetime,
) -> Optional[dict]:
    """Pure threshold logic for one device's lookback-window rows.

    `rows` are CNCMetricsLog rows (timestamp-ascending) already filtered to
    non-NULL coolant_psi within the window. Returns an alert dict on breach,
    else None. Robust to None / empty input.
    """
    if not rows:
        return None  # no PSI sample => skip device, do not crash

    psis = [r.coolant_psi for r in rows if r.coolant_psi is not None]
    if not psis:
        return None

    # Every sampled reading in the window must be below threshold.
    if not all(p < LOW_PSI_THRESHOLD for p in psis):
        return None

    earliest = rows[0].timestamp
    latest = rows[-1].timestamp
    span_minutes = (latest - earliest).total_seconds() / 60.0
    if span_minutes < MIN_SUSTAINED_MINUTES:
        return None  # low, but not yet sustained long enough

    current_psi = rows[-1].coolant_psi
    return {
        "device_id": device_id,
        "device_name": device_name,
        "current_psi": current_psi,
        "alert_start_time": earliest,
        "duration_minutes": int(span_minutes),
        "threshold_psi": int(LOW_PSI_THRESHOLD),
        "message": (
            f"Coolant pressure critical on {device_name}: "
            f"{current_psi:.1f} PSI (threshold: {int(LOW_PSI_THRESHOLD)} PSI) "
            f"sustained {int(span_minutes)} min"
        ),
    }


# Background monitor wired around the once-fn. Self-contained; safe to call once.
_monitor_task: Optional[asyncio.Task] = None


def start_coolant_alert_monitor(interval_seconds: int = 60) -> "asyncio.Task | None":
    """Start a background task that runs evaluate_coolant_alerts_once() every
    `interval_seconds`. Idempotent (guards double-start). Returns the task handle
    so the caller can cancel it on shutdown. Must be called from a running loop.
    """
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        return _monitor_task

    async def _loop() -> None:
        while True:
            try:
                await evaluate_coolant_alerts_once()
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"Coolant alert monitor iteration failed: {e}")
            await asyncio.sleep(interval_seconds)

    _monitor_task = asyncio.create_task(_loop())
    return _monitor_task
