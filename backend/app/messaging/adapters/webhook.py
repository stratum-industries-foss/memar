"""Generic HTTP POST webhook adapter with optional Jinja2 payload template.

Covers: Zapier, Make, PagerDuty, OpsGenie, HomeAssistant, n8n, and any custom
HTTP endpoint. Signing uses the same HMAC-SHA256 scheme as MEMAR's outbound
webhooks (X-MEMAR-Signature header).

Backward-compat: also reads legacy MEMAR_COOLANT_WEBHOOK_URL if
MEMAR_NOTIFY_WEBHOOK_URL is unset (with deprecation warning).
"""

from __future__ import annotations
from ...timeutil import utcnow as _utcnow

import hashlib
import hmac
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)


def _default_payload(event: AlertEvent) -> dict:
    return {
        "type": event.type,
        "title": event.title,
        "body": event.body,
        "severity": event.severity,
        "device_id": event.device_id,
        "ts": event.ts.isoformat() + "Z",
        "data": event.data,
    }


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class GenericWebhookAdapter(MessagingAdapter):
    name = "webhook"
    supports_commands = False

    def __init__(
        self,
        url: str,
        template_path: str = "",
        secret: str = "",
        extra_headers: dict[str, str] | None = None,
        event_filter: set[str] | None = None,
    ):
        self._url = url
        self._template_path = template_path
        self._secret = secret
        self._extra_headers = extra_headers or {}
        self._event_filter = event_filter  # None = all events
        self._template = None
        self._last_ok: str | None = None
        self._last_error: str | None = None

    @classmethod
    def from_env(cls) -> "GenericWebhookAdapter | None":
        url = os.getenv("MEMAR_NOTIFY_WEBHOOK_URL", "").strip()
        if not url:
            legacy = os.getenv("MEMAR_COOLANT_WEBHOOK_URL", "").strip() or os.getenv("WEBHOOK_URL", "").strip()
            if legacy:
                logger.warning(
                    "MEMAR_COOLANT_WEBHOOK_URL / WEBHOOK_URL is deprecated; "
                    "set MEMAR_NOTIFY_WEBHOOK_URL instead."
                )
                url = legacy
        if not url:
            return None

        raw_headers = os.getenv("MEMAR_NOTIFY_WEBHOOK_HEADERS", "").strip()
        extra_headers: dict[str, str] = {}
        if raw_headers:
            try:
                extra_headers = json.loads(raw_headers)
            except Exception:
                logger.warning("MEMAR_NOTIFY_WEBHOOK_HEADERS is not valid JSON; ignoring")

        raw_events = os.getenv("MEMAR_NOTIFY_WEBHOOK_EVENTS", "").strip()
        event_filter: set[str] | None = None
        if raw_events:
            event_filter = {e.strip() for e in raw_events.split(",") if e.strip()}

        return cls(
            url=url,
            template_path=os.getenv("MEMAR_NOTIFY_WEBHOOK_TEMPLATE", "").strip(),
            secret=os.getenv("MEMAR_NOTIFY_WEBHOOK_SECRET", "").strip(),
            extra_headers=extra_headers,
            event_filter=event_filter,
        )

    def _load_template(self):
        if self._template is not None:
            return self._template
        if not self._template_path:
            return None
        try:
            from jinja2 import Template
            self._template = Template(Path(self._template_path).read_text())
        except Exception as exc:
            logger.error("Failed to load webhook template %s: %s", self._template_path, exc)
            self._template = False  # mark as failed so we don't retry on every send
        return self._template

    async def send(self, event: AlertEvent) -> bool:
        if self._event_filter and event.type not in self._event_filter:
            return True  # filtered out — not an error

        tmpl = self._load_template()
        if tmpl:
            try:
                rendered = tmpl.render(
                    type=event.type,
                    title=event.title,
                    body=event.body,
                    severity=event.severity,
                    device_id=event.device_id,
                    ts=event.ts.isoformat() + "Z",
                    data=event.data,
                )
                raw = rendered.encode()
            except Exception as exc:
                logger.error("Webhook template render failed: %s", exc)
                raw = json.dumps(_default_payload(event)).encode()
        else:
            raw = json.dumps(_default_payload(event)).encode()

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        if self._secret:
            headers["X-MEMAR-Signature"] = _sign(self._secret, raw)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._url, content=raw, headers=headers)
                resp.raise_for_status()
                self._last_ok = _utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Webhook send failed: %s", exc)
            return False
