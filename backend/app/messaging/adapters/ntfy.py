"""ntfy.sh push adapter — push-only, no commands."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_SEVERITY_PRIORITY = {
    "info": "default",
    "warning": "high",
    "error": "high",
    "critical": "urgent",
}

_SEVERITY_TAGS = {
    "info": "information_source",
    "warning": "warning",
    "error": "x",
    "critical": "rotating_light",
}


class NtfyAdapter(MessagingAdapter):
    name = "ntfy"
    supports_commands = False

    def __init__(self, url: str, token: str = "", priority_override: str = ""):
        self._url = url.rstrip("/")
        self._token = token
        self._priority_override = priority_override
        self._last_ok: str | None = None
        self._last_error: str | None = None

    @classmethod
    def from_env(cls) -> "NtfyAdapter | None":
        url = os.getenv("MEMAR_NTFY_URL", "").strip()
        if not url:
            return None
        return cls(
            url=url,
            token=os.getenv("MEMAR_NTFY_TOKEN", ""),
            priority_override=os.getenv("MEMAR_NTFY_PRIORITY", ""),
        )

    async def send(self, event: AlertEvent) -> bool:
        priority = self._priority_override or _SEVERITY_PRIORITY.get(event.severity, "default")
        headers: dict[str, str] = {
            "Title": event.title[:250],
            "Priority": priority,
            "Tags": _SEVERITY_TAGS.get(event.severity, "bell"),
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._url, content=event.body.encode(), headers=headers)
                resp.raise_for_status()
                self._last_ok = datetime.utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("ntfy send failed: %s", exc)
            return False
