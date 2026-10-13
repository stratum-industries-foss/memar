"""
Coolant Pressure Alert Handler

`AlertRouter` (webhook path only) is the sole survivor of this module — it's
the legacy fallback used by `coolant_alerts_integration.py::_fire_notifications`
when the unified messaging hub hasn't finished initializing yet. Everything
else (CoolantAlertTracker, AlertRouter.route_alert/_send_email_alert/
_create_incident, and the debounce/email/incident machinery those methods
depended on) was the pre-messaging-hub alerting path, fully superseded by
`coolant_alerts_integration.py`'s "clean" entry points (evaluate_coolant_alerts_once
/ start_coolant_alert_monitor, wired in main.py) and removed as dead code.
"""

from __future__ import annotations

from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AlertRouter:
    """Legacy webhook-only alert sender — used as a fallback when the
    messaging hub broadcast fails or hasn't started yet."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url

    async def _send_webhook_alert(self, alert: dict):
        """Send webhook notification (Slack, Discord, etc.)."""
        if not self.webhook_url:
            return

        import httpx

        payload = {
            "device_id": alert["device_id"],
            "device_name": alert["device_name"],
            "current_psi": alert["current_psi"],
            "threshold_psi": alert["threshold_psi"],
            "duration_minutes": alert["duration_minutes"],
            "timestamp": alert["alert_start_time"].isoformat(),
            "message": alert["message"],
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.webhook_url, json=payload)
            if resp.status_code not in (200, 201, 202):
                raise Exception(f"Webhook returned {resp.status_code}")
