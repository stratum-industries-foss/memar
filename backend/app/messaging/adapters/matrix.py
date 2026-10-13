"""Matrix/Element adapter — bidirectional via matrix-nio sync loop.

Requires: matrix-nio>=0.20

Env vars:
  MEMAR_MATRIX_HOMESERVER  — e.g. https://matrix.org
  MEMAR_MATRIX_USER        — full user ID, e.g. @memar-bot:matrix.org
  MEMAR_MATRIX_PASSWORD    — bot account password
  MEMAR_MATRIX_ROOM_ID     — room to send alerts to, e.g. !abc123:matrix.org
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from ..base import AlertEvent, MessagingAdapter

logger = logging.getLogger(__name__)

_SEVERITY_PREFIX = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


class MatrixAdapter(MessagingAdapter):
    name = "matrix"
    supports_commands = True

    def __init__(
        self,
        homeserver: str,
        user: str,
        password: str,
        room_id: str,
    ):
        self._homeserver = homeserver
        self._user = user
        self._password = password
        self._room_id = room_id
        self._client = None
        self._sync_task = None
        self._last_ok: str | None = None
        self._last_error: str | None = None

    @classmethod
    def from_env(cls) -> "MatrixAdapter | None":
        hs = os.getenv("MEMAR_MATRIX_HOMESERVER", "").strip()
        if not hs:
            return None
        try:
            import nio  # noqa: F401
        except ImportError:
            logger.warning("matrix-nio not installed; Matrix adapter disabled")
            return None
        return cls(
            homeserver=hs,
            user=os.getenv("MEMAR_MATRIX_USER", "").strip(),
            password=os.getenv("MEMAR_MATRIX_PASSWORD", "").strip(),
            room_id=os.getenv("MEMAR_MATRIX_ROOM_ID", "").strip(),
        )

    async def _get_client(self):
        if self._client is not None:
            return self._client
        from nio import AsyncClient

        client = AsyncClient(self._homeserver, self._user)
        resp = await client.login(self._password)
        from nio import LoginError
        if isinstance(resp, LoginError):
            logger.error("Matrix login failed: %s", resp)
            await client.close()
            return None
        self._client = client
        return client

    async def send(self, event: AlertEvent) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        prefix = _SEVERITY_PREFIX.get(event.severity, "🔔")
        body = f"{prefix} **{event.title}**\n{event.body}"
        if event.device_id:
            body += f"\n_Device: {event.device_id}_"
        try:
            from nio import RoomSendResponse
            resp = await client.room_send(
                room_id=self._room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": body,
                    "format": "org.matrix.custom.html",
                    "formatted_body": body.replace("\n", "<br>"),
                },
            )
            # matrix-nio returns a RoomSendError (NOT an exception) when the bot
            # isn't in the room / lacks permission — treating that as success made
            # an undelivered critical alert report "delivered". Only a genuine
            # RoomSendResponse counts as delivered.
            if not isinstance(resp, RoomSendResponse):
                self._last_error = f"Matrix send not accepted: {resp}"
                logger.warning("Matrix send not accepted: %s", resp)
                return False
            self._last_ok = datetime.utcnow().isoformat() + "Z"
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Matrix send failed: %s", exc)
            return False

    async def start(self) -> None:
        client = await self._get_client()
        if client is None:
            return

        router = self._command_router

        # Ignore messages that predate this process start, so a restart doesn't
        # replay stale /commands the initial sync delivers from room history
        # (BUG-HIGH-MATRIX-02). server_timestamp is ms since the unix epoch (UTC);
        # time.time() shares that clock, so this compares directly.
        import time
        _start_ms = time.time() * 1000

        if router is not None:
            from nio import RoomMessageText, MatrixRoom

            async def _on_message(room: MatrixRoom, event: RoomMessageText) -> None:
                if event.sender == self._user:
                    return
                if getattr(event, "server_timestamp", 0) < _start_ms:
                    return
                text = (event.body or "").strip()
                if not text.startswith("/"):
                    return
                parts = text.split()
                cmd = parts[0].lstrip("/").lower()
                args = parts[1:]
                try:
                    response = await router.dispatch(cmd, args, event.sender, "matrix")
                except Exception as exc:
                    response = f"Error: {exc}"
                await client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": response},
                )

            client.add_event_callback(_on_message, RoomMessageText)

        async def _sync_loop():
            # MATRIX-SYNC-BACKOFF-01: sync_forever previously ran once — any
            # exception escaping it (transient network blip, homeserver hiccup)
            # killed command handling for the rest of the process's life, since
            # nothing here ever called it again. Retry with capped exponential
            # backoff instead of dying silently on the first fatal error.
            attempt = 0
            while True:
                try:
                    await client.sync_forever(timeout=30000, full_state=False)
                    return  # stopped cleanly (e.g. client.close() during shutdown)
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    attempt += 1
                    delay = min(2 ** attempt, 60)
                    logger.error(
                        "Matrix sync loop error (retry #%d in %ds): %s", attempt, delay, exc
                    )
                    await asyncio.sleep(delay)

        self._sync_task = asyncio.create_task(_sync_loop())
        logger.info("Matrix sync loop started")

    async def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None
        if self._client:
            try:
                await self._client.close()
            except Exception as exc:
                logger.warning("Matrix client close error: %s", exc)
            self._client = None
