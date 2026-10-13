"""Moonraker WebSocket client for real-time printer state subscriptions."""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

import websockets

from .device_url import assert_safe_device_url

logger = logging.getLogger(__name__)

_CACHE_TTL = 20.0  # Seconds before cached state is considered stale


class MoonrakerWSClient:
    """WebSocket client for Moonraker printer objects subscription."""

    def __init__(self, port: int, printer_id: str, base_url: str | None = None):
        self.port = port
        self.printer_id = printer_id
        # Use base_url host if provided, else default to 127.0.0.1
        if base_url:
            # Validate base_url for SSRF before extracting host
            assert_safe_device_url(base_url)  # LAN device: block metadata/link-local, allow RFC1918
            import re
            m = re.match(r"https?://([^:/]+)", base_url)
            host = m.group(1) if m else "127.0.0.1"
        else:
            host = "127.0.0.1"
        self.url = f"ws://{host}:{port}/websocket"
        self.ws = None
        self.message_id = 0
        self.cached_state: dict = {}
        self.last_update_ts: float = 0.0
        self.is_connected = False
        self._task = None
        self._shutdown = False
        # Optional async callback invoked when Klippy transitions to ready
        self._on_klippy_ready: Callable[[], Coroutine] | None = None

    def set_on_klippy_ready(self, callback: Callable[[], Coroutine]) -> None:
        """Register an async callback to run when notify_klippy_ready fires."""
        self._on_klippy_ready = callback

    async def connect(self):
        """Connect and subscribe to printer objects."""
        try:
            self.ws = await websockets.connect(self.url, ping_interval=20)
            self.is_connected = True
            logger.info(f"Connected to Moonraker WS at {self.url}")
            await self._subscribe_to_objects()
            self._task = asyncio.create_task(self._pump_messages())
        except Exception as e:
            logger.warning(f"Failed to connect to {self.url}: {e}")
            self.is_connected = False

    async def _subscribe_to_objects(self):
        """Send subscription request for all printer objects."""
        request = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {
                "objects": {
                    "webhooks": ["state", "state_message"],
                    "print_stats": ["filename", "state", "print_duration", "total_duration", "message", "filament_used", "info"],
                    "virtual_sdcard": ["progress"],
                    "extruder": ["temperature", "target"],
                    "heater_bed": ["temperature", "target"],
                    "toolhead": None,
                    "idle_timeout": ["state", "printing_time"],
                    "gcode_move": ["speed_factor", "extrude_factor"],
                    "temperature_sensor mcu_temp": ["temperature"],
                }
            },
            "id": 1,
        }
        await self.ws.send(json.dumps(request))
        logger.debug(f"{self.printer_id}: Sent subscription request")

    async def _pump_messages(self):
        """Receive and process WebSocket messages."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    method = data.get("method")
                    if method == "notify_status_update":
                        self._update_cached_state(data.get("params", [{}])[0])
                    elif method == "notify_klippy_shutdown":
                        logger.info(f"{self.printer_id}: Klippy shutdown — clearing cached state")
                        self.cached_state = {}
                        self.last_update_ts = 0.0
                    elif method == "notify_klippy_ready":
                        logger.info(f"{self.printer_id}: Klippy ready — re-subscribing")
                        try:
                            await self._subscribe_to_objects()
                        except Exception as e:
                            logger.warning(f"{self.printer_id}: Re-subscribe failed: {e}")
                        if self._on_klippy_ready:
                            try:
                                await self._on_klippy_ready()
                            except Exception as e:
                                logger.warning(f"{self.printer_id}: on_klippy_ready callback failed: {e}")
                except json.JSONDecodeError:
                    logger.debug(f"{self.printer_id}: Could not decode message: {message}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"{self.printer_id}: Message pump error: {e}")
        finally:
            self.is_connected = False
            self.cached_state = {}  # Invalidate stale cache on disconnect
            self.last_update_ts = 0.0
            if not self._shutdown:
                asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        """Reconnect with exponential backoff until success or shutdown."""
        backoff = 2
        while not self.is_connected and not self._shutdown:
            logger.info(f"{self.printer_id}: Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            try:
                await self.connect()
            except Exception as e:
                logger.warning(f"{self.printer_id}: Reconnect failed: {e}")
            # connect() swallows its own exceptions and returns normally on
            # failure, so key the backoff on the actual connection outcome — not
            # on an exception that never propagates. Otherwise a down printer
            # would retry every 2s forever (thundering herd).
            if not self.is_connected:
                backoff = min(backoff * 2, 30)

    def _update_cached_state(self, update: dict):
        """Merge status update into cached state."""
        for key, value in update.items():
            if key in self.cached_state and isinstance(self.cached_state[key], dict):
                self.cached_state[key].update(value)
            else:
                self.cached_state[key] = value
        self.last_update_ts = time.monotonic()

    def get_cached_state(self) -> dict:
        """Get the latest cached printer state."""
        return self.cached_state

    async def disconnect(self):
        """Close the WebSocket connection."""
        self._shutdown = True
        if self._task:
            self._task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.is_connected = False


class MoonrakerWSManager:
    """Manages WebSocket connections to multiple Moonraker instances."""

    def __init__(self):
        self.clients: dict[str, MoonrakerWSClient] = {}

    async def connect_printer(self, port: int, printer_id: str, base_url: str | None = None,
                              on_klippy_ready: Callable[[], Coroutine] | None = None):
        """Connect to a printer's Moonraker WebSocket."""
        # Tear down any prior client for this printer first — overwriting the
        # dict entry without disconnecting leaks its pump/reconnect tasks and
        # socket (they'd keep running against the replaced instance).
        old = self.clients.get(printer_id)
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                pass
        client = MoonrakerWSClient(port, printer_id, base_url=base_url)
        if on_klippy_ready:
            client.set_on_klippy_ready(on_klippy_ready)
        await client.connect()
        self.clients[printer_id] = client
        logger.info(f"Registered WS client for {printer_id}")
        # If Klippy is already ready at connection time, fire the callback immediately
        if on_klippy_ready and client.is_connected:
            asyncio.create_task(on_klippy_ready())

    def set_on_klippy_ready(self, printer_id: str, callback: Callable[[], Coroutine]) -> None:
        """Register a ready callback on an existing client."""
        client = self.clients.get(printer_id)
        if client:
            client.set_on_klippy_ready(callback)

    async def disconnect_all(self):
        """Disconnect all WebSocket clients."""
        for client in self.clients.values():
            await client.disconnect()
        self.clients.clear()

    def get_cached_state(self, printer_id: str) -> Optional[dict]:
        """Get cached state for a printer, or None if not connected or cache is stale."""
        client = self.clients.get(printer_id)
        if not client or not client.is_connected:
            return None
        if client.last_update_ts and (time.monotonic() - client.last_update_ts) > _CACHE_TTL:
            logger.debug(f"{printer_id}: Cached state expired, falling back to HTTP")
            return None
        return client.get_cached_state() or None


# Global WS manager instance
ws_manager = MoonrakerWSManager()
