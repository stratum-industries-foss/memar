"""Slack adapter — wraps existing SlackIntegration for outbound webhook, adds
Socket Mode for bidirectional commands.

Env vars:
  MEMAR_SLACK_WEBHOOK_URL      — existing outbound webhook (kept for compat)
  MEMAR_SLACK_BOT_TOKEN        — xoxb- token (Socket Mode + blocks API)
  MEMAR_SLACK_APP_TOKEN        — xapp- token (Socket Mode handshake)
  MEMAR_SLACK_CHANNEL_ID       — target channel for bot messages
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_COLOR = {"info": "#3b82f6", "warning": "#f59e0b", "error": "#ef4444", "critical": "#7c2d12"}
_ICON = {"info": ":information_source:", "warning": ":warning:", "error": ":x:", "critical": ":rotating_light:"}


class SlackAdapter(MessagingAdapter):
    name = "slack"
    supports_commands = False  # upgraded to True when Socket Mode tokens are set

    def __init__(
        self,
        webhook_url: str = "",
        bot_token: str = "",
        app_token: str = "",
        channel_id: str = "",
    ):
        self._webhook_url = webhook_url
        self._bot_token = bot_token
        self._app_token = app_token
        self._channel_id = channel_id
        self._socket_client = None
        self._socket_task = None
        self._last_ok: str | None = None
        self._last_error: str | None = None

        if bot_token and app_token:
            self.supports_commands = True

    @classmethod
    def from_env(cls) -> "SlackAdapter | None":
        webhook = os.getenv("MEMAR_SLACK_WEBHOOK_URL", "").strip()
        bot = os.getenv("MEMAR_SLACK_BOT_TOKEN", "").strip()
        app_tok = os.getenv("MEMAR_SLACK_APP_TOKEN", "").strip()
        channel = os.getenv("MEMAR_SLACK_CHANNEL_ID", "").strip()
        if not (webhook or bot):
            return None
        return cls(webhook_url=webhook, bot_token=bot, app_token=app_tok, channel_id=channel)

    async def send(self, event: AlertEvent) -> bool:
        # Prefer bot API when available, fall back to incoming webhook
        if self._bot_token and self._channel_id:
            return await self._send_via_bot(event)
        if self._webhook_url:
            return await self._send_via_webhook(event)
        logger.warning("Slack: no delivery method configured")
        return False

    async def _send_via_webhook(self, event: AlertEvent) -> bool:
        import httpx

        payload = {
            "username": "MEMAR Fleet Monitor",
            "icon_emoji": ":factory:",
            "attachments": [{
                "color": _COLOR.get(event.severity, "#3b82f6"),
                "title": f"{_ICON.get(event.severity, ':bell:')} {event.title}",
                "text": event.body,
                "fields": [{"title": "Device", "value": event.device_id, "short": True}]
                if event.device_id else [],
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(self._webhook_url, json=payload)
                r.raise_for_status()
                self._last_ok = datetime.utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Slack webhook send failed: %s", exc)
            return False

    async def _send_via_bot(self, event: AlertEvent) -> bool:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            logger.warning("slack_sdk not installed; falling back to webhook")
            return await self._send_via_webhook(event)

        client = AsyncWebClient(token=self._bot_token)
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{event.title}*\n{event.body}",
                },
            }
        ]
        if event.device_id:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Device: `{event.device_id}`"}],
            })
        try:
            await client.chat_postMessage(channel=self._channel_id, blocks=blocks)
            self._last_ok = datetime.utcnow().isoformat() + "Z"
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Slack bot send failed: %s", exc)
            return False

    async def start(self) -> None:
        if not (self._bot_token and self._app_token):
            return
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            logger.warning("slack_sdk not installed; Slack Socket Mode disabled")
            return

        router = self._command_router
        if router is None:
            return

        web_client = AsyncWebClient(token=self._bot_token)
        self._socket_client = SocketModeClient(
            app_token=self._app_token,
            web_client=web_client,
        )

        async def _process(client, req):
            from slack_sdk.socket_mode.response import SocketModeResponse

            if req.type == "events_api":
                await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                event = req.payload.get("event", {})
                etype = event.get("type")
                if etype == "app_mention" or etype == "message":
                    text = (event.get("text") or "").strip()
                    user_id = event.get("user", "")
                    # Skip the bot's own messages / non-user events, else the bot
                    # replies to itself in an unbounded loop (mirrors discord.py
                    # `message.author == bot.user` and matrix.py `event.sender == self._user`).
                    if event.get("bot_id") or event.get("subtype") or not user_id:
                        return
                    # Plain channel chatter isn't a command — only auto-dispatch a
                    # `message` event when it looks like one; @-mentions always dispatch.
                    if etype == "message" and not text.startswith("/"):
                        return
                    parts = text.split()
                    cmd = parts[0].lstrip("/").split("@")[0].lower() if parts else ""
                    args = parts[1:] if len(parts) > 1 else []
                    try:
                        response = await router.dispatch(cmd, args, user_id, "slack")
                    except Exception as exc:
                        response = f"Error: {exc}"
                    channel = event.get("channel", self._channel_id)
                    if channel:
                        try:
                            await web_client.chat_postMessage(channel=channel, text=response)
                        except Exception as exc:
                            logger.warning("Slack reply failed: %s", exc)

            elif req.type == "slash_commands":
                await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                payload = req.payload
                cmd = payload.get("command", "").lstrip("/").lower()
                text = payload.get("text", "").strip()
                user_id = payload.get("user_id", "")
                args = text.split() if text else []
                try:
                    response = await router.dispatch(cmd, args, user_id, "slack")
                except Exception as exc:
                    response = f"Error: {exc}"
                channel = payload.get("channel_id", self._channel_id)
                if channel:
                    try:
                        await web_client.chat_postMessage(channel=channel, text=response)
                    except Exception as exc:
                        logger.warning("Slack slash response failed: %s", exc)

        self._socket_client.socket_mode_request_listeners.append(_process)
        await self._socket_client.connect()
        logger.info("Slack Socket Mode connected")

    async def stop(self) -> None:
        if self._socket_client:
            try:
                await self._socket_client.close()
            except Exception as exc:
                logger.warning("Slack socket close error: %s", exc)
            self._socket_client = None
