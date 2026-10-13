"""Slack integration for real-time alerts."""

import os
import json
import httpx
import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

SLACK_RETRY_ATTEMPTS = 3
SLACK_TIMEOUT_SEC = 10


def _get_webhook_url() -> str:
    """Read the Slack webhook URL at call time.

    Read here (not at import) so runtime configuration and test patching work,
    and so an unset URL reliably no-ops rather than capturing a stale value.
    """
    return os.getenv("MEMAR_SLACK_WEBHOOK_URL", "")


class SlackIntegration:
    """Send alerts to Slack."""

    @staticmethod
    async def send_alert(
        title: str,
        message: str,
        severity: str = "info",  # info, warning, error, critical
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> bool:
        """Send Slack message with retry logic.

        No-ops gracefully (returns False, never raises/blocks) when
        MEMAR_SLACK_WEBHOOK_URL is unset.
        """

        webhook_url = _get_webhook_url()
        if not webhook_url:
            logger.debug("MEMAR_SLACK_WEBHOOK_URL not configured; skipping Slack send")
            return False

        color_map = {
            "info": "#3b82f6",      # blue
            "warning": "#f59e0b",   # amber
            "error": "#ef4444",     # red
            "critical": "#7c2d12"   # dark red
        }

        icon_map = {
            "info": ":information_source:",
            "warning": ":warning:",
            "error": ":x:",
            "critical": ":rotating_light:"
        }

        attachment = {
            "color": color_map.get(severity, "#3b82f6"),
            "title": f"{icon_map.get(severity, ':bell:')} {title}",
            "text": message,
            "ts": int(datetime.utcnow().timestamp()),
            "fields": [
                {"title": "Timestamp", "value": datetime.utcnow().isoformat(), "short": True},
            ]
        }

        if device_name:
            attachment["fields"].append({"title": "Device", "value": device_name, "short": True})

        if metadata:
            for key, value in metadata.items():
                attachment["fields"].append({
                    "title": key.replace("_", " ").title(),
                    "value": str(value),
                    "short": True
                })

        payload = {
            "channel": "#memar-alerts",
            "username": "MEMAR Fleet Monitor",
            "icon_emoji": ":factory:",
            "attachments": [attachment]
        }

        for attempt in range(SLACK_RETRY_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=SLACK_TIMEOUT_SEC) as client:
                    response = await client.post(
                        webhook_url,
                        json=payload,
                    )

                    if response.status_code == 200:
                        logger.info(f"Slack alert sent: {title}")
                        return True

                    logger.warning(f"Slack response: {response.status_code}")

                    if attempt < SLACK_RETRY_ATTEMPTS - 1:
                        await asyncio.sleep(2 ** attempt)  # exponential backoff

            except Exception as e:
                logger.warning(f"Slack send error (attempt {attempt+1}): {e}")
                if attempt < SLACK_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)

        return False
