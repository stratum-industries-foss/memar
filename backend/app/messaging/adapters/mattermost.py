"""Mattermost adapter — bidirectional via incoming webhooks + slash commands.

Outbound: HTTP POST to Mattermost incoming webhook URL
Inbound:  Slash command handler (MEMAR exposes /api/messaging/mattermost/command)

Env vars:
  MEMAR_MATTERMOST_URL         — Mattermost server URL, e.g. https://chat.example.com
  MEMAR_MATTERMOST_BOT_TOKEN   — Bot user token (Personal Access Token or Bot token)
  MEMAR_MATTERMOST_CHANNEL_ID  — Default channel ID for outbound messages
  MEMAR_MATTERMOST_WEBHOOK_URL — Incoming webhook URL (alternative outbound)
"""

from __future__ import annotations
from ...timeutil import utcnow as _utcnow

import asyncio
import logging
import os
from datetime import datetime

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_COLOR = {"info": "#3b82f6", "warning": "#f59e0b", "error": "#ef4444", "critical": "#7c2d12"}
_PRIORITY = {"info": "normal", "warning": "important", "error": "important", "critical": "important"}


class MattermostAdapter(MessagingAdapter):
    name = "mattermost"
    supports_commands = True

    def __init__(
        self,
        server_url: str,
        bot_token: str = "",
        channel_id: str = "",
        webhook_url: str = "",
    ):
        self._server_url = server_url.rstrip("/")
        self._bot_token = bot_token
        self._channel_id = channel_id
        self._webhook_url = webhook_url
        self._last_ok: str | None = None
        self._last_error: str | None = None

    @classmethod
    def from_env(cls) -> "MattermostAdapter | None":
        url = os.getenv("MEMAR_MATTERMOST_URL", "").strip()
        if not url:
            return None
        return cls(
            server_url=url,
            bot_token=os.getenv("MEMAR_MATTERMOST_BOT_TOKEN", "").strip(),
            channel_id=os.getenv("MEMAR_MATTERMOST_CHANNEL_ID", "").strip(),
            webhook_url=os.getenv("MEMAR_MATTERMOST_WEBHOOK_URL", "").strip(),
        )

    async def send(self, event: AlertEvent) -> bool:
        if self._bot_token and self._channel_id:
            return await self._send_via_api(event)
        if self._webhook_url:
            return await self._send_via_webhook(event)
        return False

    async def _send_via_api(self, event: AlertEvent) -> bool:
        import httpx

        attachment = {
            "color": _COLOR.get(event.severity, "#3b82f6"),
            "title": event.title,
            "text": event.body,
        }
        if event.device_id:
            attachment["fields"] = [{"title": "Device", "value": event.device_id, "short": True}]

        payload = {
            "channel_id": self._channel_id,
            "message": "",
            "props": {"attachments": [attachment]},
        }
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"{self._server_url}/api/v4/posts",
                    json=payload,
                    headers=headers,
                )
                r.raise_for_status()
                self._last_ok = _utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Mattermost API send failed: %s", exc)
            return False

    async def _send_via_webhook(self, event: AlertEvent) -> bool:
        import httpx

        payload = {
            "attachments": [{
                "color": _COLOR.get(event.severity, "#3b82f6"),
                "title": event.title,
                "text": event.body,
            }]
        }
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(self._webhook_url, json=payload)
                r.raise_for_status()
                self._last_ok = _utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Mattermost webhook send failed: %s", exc)
            return False

    async def reply(self, channel_id: str, text: str) -> None:
        """Send a reply to a specific channel — used by the slash command handler."""
        import httpx

        if not (self._bot_token and self._server_url):
            return
        headers = {"Authorization": f"Bearer {self._bot_token}", "Content-Type": "application/json"}
        payload = {"channel_id": channel_id, "message": text}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{self._server_url}/api/v4/posts", json=payload, headers=headers)
        except Exception as exc:
            logger.warning("Mattermost reply failed: %s", exc)
