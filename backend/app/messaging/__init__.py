"""MEMAR Unified Messaging Hub.

Fans out AlertEvent notifications to all configured adapters concurrently.
Each adapter self-gates via from_env() — returns None if its required env vars
are absent. No adapter being configured is not an error; the hub simply no-ops.

Usage (lifespan):
    hub = MessagingHub.from_env()
    await hub.start()
    ...
    await hub.stop()

Usage (broadcast):
    from .messaging import get_hub, AlertEvent
    await get_hub().broadcast(AlertEvent(type="printer.error", ...))
"""

from __future__ import annotations
from ..timeutil import utcnow as _utcnow

import asyncio
import logging
from datetime import datetime
from typing import Callable

from .base import AlertEvent, MessagingAdapter  # noqa: F401 (re-exported)
from .commands import CommandRouter

logger = logging.getLogger(__name__)

# Process-level singleton. Set by MessagingHub.from_env() in lifespan.
_hub: "MessagingHub | None" = None


def get_hub() -> "MessagingHub":
    """Return the active MessagingHub singleton (always non-None after lifespan start)."""
    global _hub
    if _hub is None:
        _hub = MessagingHub(adapters=[])
    return _hub


class MessagingHub:
    """Fan-out notification bus + bidirectional command dispatcher."""

    def __init__(self, adapters: list[MessagingAdapter], db_factory: Callable | None = None):
        self._adapters = adapters
        self._db_factory = db_factory
        self._command_router: CommandRouter | None = (
            CommandRouter(db_factory) if db_factory is not None else None
        )
        self._bg_tasks: list[asyncio.Task] = []
        # adapter_name → {"ok": bool|None, "ts": str|None, "error": str|None}
        self._last_delivery: dict[str, dict] = {}

    @classmethod
    def from_env(cls, db_factory: Callable | None = None) -> "MessagingHub":
        """Instantiate all adapters from environment. Unconfigured adapters are skipped."""
        from .adapters.ntfy import NtfyAdapter
        from .adapters.webhook import GenericWebhookAdapter
        from .adapters.telegram import TelegramAdapter
        from .adapters.slack import SlackAdapter
        from .adapters.discord import DiscordAdapter
        from .adapters.mattermost import MattermostAdapter
        from .adapters.matrix import MatrixAdapter

        adapter_classes = [
            TelegramAdapter,
            NtfyAdapter,
            GenericWebhookAdapter,
            SlackAdapter,
            DiscordAdapter,
            MattermostAdapter,
            MatrixAdapter,
        ]

        adapters: list[MessagingAdapter] = []
        for cls_ in adapter_classes:
            try:
                inst = cls_.from_env()
                if inst is not None:
                    adapters.append(inst)
                    logger.info("MessagingHub: loaded adapter %s", inst.name)
            except Exception as exc:
                logger.warning("MessagingHub: failed to load %s: %s", cls_.__name__, exc)

        hub = cls(adapters=adapters, db_factory=db_factory)

        global _hub
        _hub = hub
        return hub

    async def start(self) -> None:
        """Wire command routers and start polling/socket loops for all adapters."""
        for adapter in self._adapters:
            if adapter.supports_commands and self._command_router is not None:
                adapter._command_router = self._command_router
            task = asyncio.create_task(self._safe_start(adapter), name=f"msg-{adapter.name}-start")
            self._bg_tasks.append(task)

    async def _safe_start(self, adapter: MessagingAdapter) -> None:
        try:
            await adapter.start()
        except Exception as exc:
            logger.error("Adapter %s start() failed: %s", adapter.name, exc)

    async def stop(self) -> None:
        for adapter in self._adapters:
            try:
                await adapter.stop()
            except Exception as exc:
                logger.warning("Adapter %s stop() error: %s", adapter.name, exc)
        for t in self._bg_tasks:
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()

    async def broadcast(self, event: AlertEvent) -> None:
        """Fan out event to all adapters concurrently. Never raises."""
        if not self._adapters:
            return
        tasks = [
            asyncio.create_task(self._safe_send(adapter, event))
            for adapter in self._adapters
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, adapter: MessagingAdapter, event: AlertEvent) -> None:
        ts = _utcnow().isoformat() + "Z"
        try:
            ok = await adapter.send(event)
            self._last_delivery[adapter.name] = {"ok": ok, "ts": ts, "error": None}
        except Exception as exc:
            logger.warning("Adapter %s send() failed: %s", adapter.name, exc)
            self._last_delivery[adapter.name] = {"ok": False, "ts": ts, "error": str(exc)}

    def adapter_status(self) -> list[dict]:
        """Return per-adapter health for the admin API."""
        return [
            {
                "name": a.name,
                "enabled": True,
                "bidirectional": a.supports_commands,
                **self._last_delivery.get(a.name, {"ok": None, "ts": None, "error": None}),
            }
            for a in self._adapters
        ]
