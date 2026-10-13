"""Shared types for the MEMAR Unified Messaging Hub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AlertEvent:
    """A notification event fanned out to all configured adapters."""

    type: str            # "printer.error", "cnc.coolant_low", etc.
    title: str
    body: str
    severity: str        # info | warning | error | critical
    data: dict           # raw event payload (available in Jinja2 templates)
    device_id: str | None = None
    ts: datetime = field(default_factory=datetime.utcnow)


class MessagingAdapter(ABC):
    """Abstract base for all messaging adapters."""

    name: str = "unknown"
    supports_commands: bool = False

    # Set by MessagingHub before start() is called when supports_commands=True.
    _command_router: Any = None

    @classmethod
    @abstractmethod
    def from_env(cls) -> "MessagingAdapter | None":
        """Return a configured instance, or None if required env vars are absent."""

    @abstractmethod
    async def send(self, event: AlertEvent) -> bool:
        """Send a notification. Return True on success."""

    async def start(self) -> None:
        """Start any polling/socket/sync loop. Called once at app startup."""

    async def stop(self) -> None:
        """Tear down cleanly. Called once at app shutdown."""
