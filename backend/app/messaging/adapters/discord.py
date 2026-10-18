"""Discord adapter — outbound via webhook URL, bidirectional via bot token.

Env vars:
  MEMAR_DISCORD_WEBHOOK_URL  — Discord channel webhook URL (push-only)
  MEMAR_DISCORD_BOT_TOKEN    — Bot token for gateway + bidirectional
  MEMAR_DISCORD_CHANNEL_ID   — Channel ID for bot messages

If both are set, bot takes priority for outbound; Socket-mode-like gateway
handles commands. Webhook-URL-only mode is push-only (no commands).
"""

from __future__ import annotations
from ...timeutil import utcnow as _utcnow

import asyncio
import logging
import os
from datetime import datetime

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_COLOR_INT = {
    "info": 0x3B82F6,
    "warning": 0xF59E0B,
    "error": 0xEF4444,
    "critical": 0x7C2D12,
}


class DiscordAdapter(MessagingAdapter):
    name = "discord"
    supports_commands = False

    def __init__(
        self,
        webhook_url: str = "",
        bot_token: str = "",
        channel_id: str = "",
    ):
        self._webhook_url = webhook_url
        self._bot_token = bot_token
        self._channel_id = channel_id
        self._bot = None
        self._last_ok: str | None = None
        self._last_error: str | None = None

        if bot_token:
            self.supports_commands = True

    @classmethod
    def from_env(cls) -> "DiscordAdapter | None":
        webhook = os.getenv("MEMAR_DISCORD_WEBHOOK_URL", "").strip()
        bot = os.getenv("MEMAR_DISCORD_BOT_TOKEN", "").strip()
        channel = os.getenv("MEMAR_DISCORD_CHANNEL_ID", "").strip()
        if not (webhook or bot):
            return None
        return cls(webhook_url=webhook, bot_token=bot, channel_id=channel)

    async def send(self, event: AlertEvent) -> bool:
        if self._bot_token and self._channel_id:
            return await self._send_via_bot(event)
        if self._webhook_url:
            return await self._send_via_webhook(event)
        return False

    async def _send_via_webhook(self, event: AlertEvent) -> bool:
        import httpx

        embed = {
            "title": event.title,
            "description": event.body,
            "color": _COLOR_INT.get(event.severity, 0x3B82F6),
        }
        if event.device_id:
            embed["footer"] = {"text": f"Device: {event.device_id}"}

        payload = {"embeds": [embed], "username": "MEMAR"}

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(self._webhook_url, json=payload)
                r.raise_for_status()
                self._last_ok = _utcnow().isoformat() + "Z"
                self._last_error = None
                return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Discord webhook send failed: %s", exc)
            return False

    async def _send_via_bot(self, event: AlertEvent) -> bool:
        try:
            import discord
        except ImportError:
            logger.warning("discord.py not installed; falling back to webhook")
            return await self._send_via_webhook(event)

        if self._bot is None:
            return False

        try:
            channel = self._bot.get_channel(int(self._channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(self._channel_id))
            embed = discord.Embed(
                title=event.title,
                description=event.body,
                color=_COLOR_INT.get(event.severity, 0x3B82F6),
            )
            if event.device_id:
                embed.set_footer(text=f"Device: {event.device_id}")
            await channel.send(embed=embed)
            self._last_ok = _utcnow().isoformat() + "Z"
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Discord bot send failed: %s", exc)
            return False

    async def start(self) -> None:
        if not self._bot_token:
            return
        try:
            import discord
        except ImportError:
            logger.warning("discord.py not installed; Discord gateway disabled")
            return

        router = self._command_router

        intents = discord.Intents.default()
        intents.message_content = True

        class _Bot(discord.Client):
            pass

        bot = _Bot(intents=intents)
        self._bot = bot
        self._bot_task: asyncio.Task | None = None

        @bot.event
        async def on_message(message):
            if message.author == bot.user:
                return
            text = (message.content or "").strip()
            if not text.startswith("/"):
                return
            if router is None:
                return
            parts = text.split()
            cmd = parts[0].lstrip("/").lower()
            args = parts[1:]
            user_id = str(message.author.id)
            try:
                response = await router.dispatch(cmd, args, user_id, "discord")
            except Exception as exc:
                response = f"Error: {exc}"
            await message.channel.send(f"```\n{response}\n```")

        try:
            self._bot_task = asyncio.create_task(bot.start(self._bot_token))
            logger.info("Discord bot started")
        except Exception as exc:
            logger.error("Discord bot start failed: %s", exc)

    async def stop(self) -> None:
        if self._bot and not self._bot.is_closed():
            try:
                await self._bot.close()
            except Exception as exc:
                logger.warning("Discord close error: %s", exc)
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
        self._bot = None
        self._bot_task = None
