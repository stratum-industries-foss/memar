"""
CNC-specific webhook event detection and dispatch.

Monitors machine state for anomalies and triggers webhooks:
- Spindle overspeed: spindle_rpm > machine_max_rpm + threshold
- Coolant failure: coolant_active=True but no flow pressure
- Tool change: tool_id transition
- Feed rate warning: feed_rate > nominal + margin
- Production complete: machine cycle finished (transition Ready→Printing→Ready)

Integration: Call detect_cnc_anomalies() after polling machine state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from .models import PrinterConfig


class CNCEventTracker:
    """Track CNC machine state transitions to detect anomalies."""

    def __init__(self):
        """Initialize tracker."""
        # Keyed by printer.id — this tracker is a process-wide singleton shared
        # across all polled devices, so state must not be held as bare scalars
        # (that caused cross-device state corruption when polling 2+ CNC
        # machines concurrently).
        self.prev_state: dict[str, str | None] = {}
        self.prev_tool_id: dict[str, str | None] = {}
        self.prev_spindle_rpm: dict[str, float] = {}
        self.printing_start_time: dict[str, datetime | None] = {}
        # Edge-detection latches for level-triggered conditions — publish once
        # on the False→True transition, not every poll while the condition holds
        # (prevents alert storms). Reset when the condition clears.
        self.prev_overspeed: dict[str, bool] = {}
        self.prev_coolant_failure: dict[str, bool] = {}
        self.prev_feed_warning: dict[str, bool] = {}

    async def detect_anomalies(
        self,
        printer: PrinterConfig,
        current_state: dict,
        publish_event_func,
    ) -> list[dict]:
        """
        Detect and publish anomalies from current machine state.

        Args:
            printer: PrinterConfig with safety bounds
            current_state: Machine state dict with state, spindle_rpm_current, feed_rate_mm_min, tool_id, coolant_active, etc.
            publish_event_func: async callable to publish events (e.g., publish_event from webhooks.py)

        Returns:
            list of events detected
        """
        # Local per-invocation list — this tracker is a process-wide singleton
        # and detect_anomalies awaits mid-body, so a shared self.events_detected
        # would be raced/clobbered across concurrent device scans.
        events_detected: list[dict] = []
        device_id = printer.id
        state = current_state.get("state", "offline")
        spindle_rpm = current_state.get("spindle_rpm_current", 0) or 0
        feed_rate = current_state.get("feed_rate_mm_min", 0) or 0
        tool_id = current_state.get("tool_id")
        coolant_active = current_state.get("coolant_active", False)
        coolant_psi = current_state.get("coolant_psi")  # Optional: coolant pressure

        # ────────────────────────────────────────────────────────────────
        # 1. Spindle Overspeed Detection
        # ────────────────────────────────────────────────────────────────
        spindle_rpm_max = printer.spindle_rpm_max or 10000  # Default if not configured
        spindle_overspeed_threshold = spindle_rpm_max * 0.15  # 15% over max

        is_overspeed = spindle_rpm > (spindle_rpm_max + spindle_overspeed_threshold)
        if is_overspeed and not self.prev_overspeed.get(device_id):
            excess_pct = round(
                (spindle_rpm - spindle_rpm_max) / spindle_rpm_max * 100, 1
            )
            event = {
                "type": "cnc.spindle_overspeed",
                "severity": "warning" if excess_pct < 20 else "critical",
                "current_rpm": spindle_rpm,
                "max_rpm": spindle_rpm_max,
                "excess_pct": excess_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            events_detected.append(event)
            await publish_event_func("cnc.spindle_overspeed", printer.id, event)
        self.prev_overspeed[device_id] = is_overspeed

        # ────────────────────────────────────────────────────────────────
        # 2. Coolant Failure Detection
        # ────────────────────────────────────────────────────────────────
        # If coolant pressure is tracked and it's too low, trigger alert.
        is_coolant_failure = (
            coolant_active and coolant_psi is not None and coolant_psi < 5
        )
        if is_coolant_failure and not self.prev_coolant_failure.get(device_id):
            event = {
                "type": "cnc.coolant_failure",
                "severity": "critical",
                "coolant_active": True,
                "coolant_psi": coolant_psi,
                "expected_psi": 20,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            events_detected.append(event)
            await publish_event_func("cnc.coolant_failure", printer.id, event)
        self.prev_coolant_failure[device_id] = is_coolant_failure

        # ────────────────────────────────────────────────────────────────
        # 3. Tool Change Detection
        # ────────────────────────────────────────────────────────────────
        prev_tool_id = self.prev_tool_id.get(device_id)
        if tool_id and prev_tool_id and tool_id != prev_tool_id:
            event = {
                "type": "cnc.tool_change",
                "severity": "info",
                "prev_tool_id": prev_tool_id,
                "new_tool_id": tool_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            events_detected.append(event)
            await publish_event_func("cnc.tool_change", printer.id, event)

        self.prev_tool_id[device_id] = tool_id

        # ────────────────────────────────────────────────────────────────
        # 4. Feed Rate Warning
        # ────────────────────────────────────────────────────────────────
        # Assume nominal feed rate is 70% of max safe rate
        feed_rate_max = getattr(printer, "feed_rate_mm_min", 500) or 500
        feed_rate_nominal = feed_rate_max * 0.7
        feed_rate_warning_threshold = feed_rate_nominal * 1.2  # 20% above nominal

        is_feed_warning = feed_rate > feed_rate_warning_threshold
        if is_feed_warning and not self.prev_feed_warning.get(device_id):
            excess_pct = round((feed_rate - feed_rate_nominal) / feed_rate_nominal * 100, 1)
            event = {
                "type": "cnc.feed_rate_warning",
                "severity": "warning",
                "current_rate_mm_min": feed_rate,
                "nominal_rate_mm_min": feed_rate_nominal,
                "excess_pct": excess_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            events_detected.append(event)
            await publish_event_func("cnc.feed_rate_warning", printer.id, event)
        self.prev_feed_warning[device_id] = is_feed_warning

        # ────────────────────────────────────────────────────────────────
        # 5. Production Cycle Complete Detection
        # ────────────────────────────────────────────────────────────────
        # Detect: printing → ready (job finished)
        prev_state = self.prev_state.get(device_id)
        printing_start_time = self.printing_start_time.get(device_id)
        if prev_state == "printing" and state == "ready":
            duration = None
            if printing_start_time:
                duration = (datetime.now(timezone.utc) - printing_start_time).total_seconds() / 60
            event = {
                "type": "cnc.production_complete",
                "severity": "info",
                "duration_minutes": round(duration, 1) if duration else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            events_detected.append(event)
            await publish_event_func("cnc.production_complete", printer.id, event)
            self.printing_start_time[device_id] = None

        # Track printing start time
        if state == "printing" and prev_state != "printing":
            self.printing_start_time[device_id] = datetime.now(timezone.utc)

        self.prev_state[device_id] = state
        self.prev_spindle_rpm[device_id] = spindle_rpm

        return events_detected


# Singleton tracker (one per MEMAR session)
_event_tracker = CNCEventTracker()


async def detect_cnc_anomalies(
    printer: PrinterConfig,
    current_state: dict,
    publish_event_func,
) -> list[dict]:
    """
    Global function to detect CNC anomalies.

    Args:
        printer: PrinterConfig
        current_state: Machine state dict
        publish_event_func: async callable for event publishing

    Returns:
        list of events detected
    """
    global _event_tracker
    return await _event_tracker.detect_anomalies(printer, current_state, publish_event_func)
