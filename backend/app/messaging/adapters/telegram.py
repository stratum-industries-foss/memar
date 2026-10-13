"""Telegram adapter — bidirectional via polling (no public URL needed).

Requires: python-telegram-bot>=21.0,<22 (runtime-tested manually; not covered by CI suite)
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


def _html(text: str) -> str:
    return html.escape(str(text))


class TelegramAdapter(MessagingAdapter):
    name = "telegram"
    supports_commands = True

    def __init__(self, token: str, chat_ids: list[str]):
        self._token = token
        self._chat_ids = chat_ids
        self._app = None
        self._last_ok: str | None = None
        self._last_error: str | None = None

    @classmethod
    def from_env(cls) -> "TelegramAdapter | None":
        token = os.getenv("MEMAR_TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return None
        try:
            import telegram  # noqa: F401
        except ImportError:
            logger.warning("python-telegram-bot not installed; Telegram adapter disabled")
            return None
        raw = os.getenv("MEMAR_TELEGRAM_CHAT_ID", "").strip()
        chat_ids = [c.strip() for c in raw.split(",") if c.strip()]
        return cls(token=token, chat_ids=chat_ids)

    async def send(self, event: AlertEvent) -> bool:
        try:
            from telegram import Bot
        except ImportError:
            return False

        emoji = _SEVERITY_EMOJI.get(event.severity, "🔔")
        text = f"{emoji} <b>{_html(event.title)}</b>\n{_html(event.body)}"
        if event.device_id:
            text += f"\n<i>Device: {_html(event.device_id)}</i>"

        ok = False
        async with Bot(token=self._token) as bot:
            for chat_id in self._chat_ids:
                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                    ok = True
                except Exception as exc:
                    logger.warning("Telegram send to %s failed: %s", chat_id, exc)
                    self._last_error = str(exc)

        if ok:
            self._last_ok = datetime.utcnow().isoformat() + "Z"
            self._last_error = None
        return ok

    async def start(self) -> None:
        try:
            from telegram.ext import Application, CommandHandler, ContextTypes
            from telegram import Update
        except ImportError:
            logger.warning("python-telegram-bot not installed; Telegram polling disabled")
            return

        router = self._command_router
        if router is None:
            logger.warning("TelegramAdapter has no command router; bidirectional disabled")
            return

        app = Application.builder().token(self._token).build()
        self._app = app

        async def _dispatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.effective_user or not update.message:
                return
            sender_id = str(update.effective_user.id)
            text = (update.message.text or "").strip()
            parts = text.split()
            if not parts:
                return
            cmd = parts[0].lstrip("/").split("@")[0].lower()
            args = parts[1:]
            try:
                response = await router.dispatch(cmd, args, sender_id, "telegram")
            except Exception as exc:
                response = f"Error: {exc}"
            await update.message.reply_text(response)

        for cmd_name in ["status", "machines", "machine", "jobs", "alerts", "ack", "help"]:
            from telegram.ext import CommandHandler as CmdH
            app.add_handler(CmdH(cmd_name, _dispatch))

        await app.initialize()
        await app.start()
        if app.updater:
            await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()
        except Exception as exc:
            logger.warning("Telegram shutdown error: %s", exc)
        self._app = None
