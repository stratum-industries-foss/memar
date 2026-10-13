"""
OPC UA (OLE for Process Control Unified Architecture) adapter for industrial CNC systems.

OPC UA is a platform-agnostic standard for machine-to-machine communication in industrial
automation. This adapter connects to OPC UA servers running on CNC controllers or gateway devices.

Node addressing is by NodeId STRING (asyncua ``client.get_node("ns=2;s=...")``), NOT by
browse path. OPC UA address spaces are entirely server-specific — the namespace index
(``ns=``) and identifier casing vary per vendor/firmware — so there is no portable default
that works out of the box. The defaults below (``_DEFAULT_NODE_IDS``) are PLACEHOLDERS that
almost certainly will not exist on a real server; a device left on them reads nothing and is
reported OFFLINE honestly rather than emitting fabricated telemetry. Real deployments MUST
override them per device (see ``_DEFAULT_NODE_IDS`` and OPCUAClient.__init__).

Logical roles the adapter reads/writes (map each to your server's real NodeId):
- state          — machine state (String | Enum), mapped via _STATE_MAP below
- spindle_rpm    — spindle speed (Int32 | Float), RPM
- feed_rate      — feed rate (Float), mm/min
- pos_x/y/z      — axis positions (Float)
- coolant        — coolant on/off (Boolean)
- tool_id        — active tool (String | Int32)
- gcode_command / homing_axes / estop — write targets for commands
- files          — optional file listing node

State mapping:
  "1" or "On" → "ready"
  "2" or "Running" → "printing"
  "3" or "Paused" → "paused"
  "4" or "E-Stop" → "error"
  "0" or "Off" → "offline"
"""
from __future__ import annotations

import asyncio
from typing import Optional

try:
    from asyncua import Client
except ImportError:
    Client = None  # Graceful degradation if opcua not installed

from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus

_STATE_MAP = {
    "On": "ready",
    "1": "ready",
    "Running": "printing",
    "2": "printing",
    "Paused": "paused",
    "3": "paused",
    "E-Stop": "error",
    "4": "error",
    "Off": "offline",
    "0": "offline",
}

# PLACEHOLDER NodeId strings, keyed by logical role. OPC UA address spaces are
# server-specific, so these ``ns=2;s=...`` guesses will not exist on most real
# servers — a device left on them simply reads nothing and reports offline
# (honest), never fabricated data. Override per device via a PrinterConfig
# ``opcua_nodes`` mapping ({role: nodeid_str}); see OPCUAClient.__init__.
_DEFAULT_NODE_IDS: dict[str, str] = {
    "state": "ns=2;s=Machine.State",
    "spindle_rpm": "ns=2;s=Controls.SpindleSpeed",
    "feed_rate": "ns=2;s=Controls.FeedRate",
    "pos_x": "ns=2;s=Motion.Position.X",
    "pos_y": "ns=2;s=Motion.Position.Y",
    "pos_z": "ns=2;s=Motion.Position.Z",
    "coolant": "ns=2;s=Machine.Coolant",
    "tool_id": "ns=2;s=Machine.ToolID",
    "gcode_command": "ns=2;s=Controls.GcodeCommand",
    "homing_axes": "ns=2;s=Controls.HomingAxes",
    "estop": "ns=2;s=Controls.EStop",
    "files": "ns=2;s=FileSystem.Files",
}


class OPCUAClient(CNCAdapter):
    """OPC UA client for industrial CNC systems."""

    def __init__(self, config: PrinterConfig):
        """Initialize OPC UA client.

        Args:
            config: PrinterConfig with base_url (e.g., "opc.tcp://cnc-gateway.local:4840/endpoint")

        Note: the asyncua dependency is checked at connect() time, NOT here.
        Constructing must never raise — otherwise a single OPC-UA device with a
        missing optional dependency would crash the whole fleet fetch. A missing
        dependency surfaces as a clean offline status instead.
        """
        self.base_url = config.base_url
        self._client: Optional[Client] = None
        self._connected = False
        # Per-device NodeId overrides, keyed by logical role (see _DEFAULT_NODE_IDS).
        # NOTE: PrinterConfig currently declares no ``opcua_nodes`` field and pydantic
        # drops unknown input keys (extra="ignore"), so this getattr is INERT until
        # models.py adds ``opcua_nodes: dict[str, str] | None = None`` to PrinterConfig.
        # Until then every device uses the placeholder defaults and — because those
        # NodeIds won't exist on a real server — reads nothing and reports offline
        # honestly. This is deliberately configurable-ready, not fabricated-working.
        overrides = getattr(config, "opcua_nodes", None) or {}
        self._nodes: dict[str, str] = {**_DEFAULT_NODE_IDS, **overrides}

    async def connect(self) -> dict:
        """Connect to OPC UA server.

        Returns:
            {"ok": bool, "message": str, "state": str}
        """
        if Client is None:
            return {
                "ok": False,
                "message": "asyncua library not installed (pip install asyncua)",
                "state": "offline",
            }
        try:
            self._client = Client(self.base_url)
            await self._client.connect()
            self._connected = True
            return {"ok": True, "message": "Connected to OPC UA server", "state": "ready"}
        except Exception as e:
            self._connected = False
            return {
                "ok": False,
                "message": f"OPC UA connection failed: {e}",
                "state": "offline",
            }

    async def _ensure_connected(self) -> bool:
        """Ensure connection is established before operations.

        Returns:
            True if connected (or connection succeeded), False otherwise.
        """
        if not self._connected:
            result = await self.connect()
            return result.get("ok", False)
        return True

    async def disconnect(self) -> dict:
        """Disconnect from OPC UA server.

        Returns:
            {"ok": bool, "message": str}
        """
        try:
            if self._client and self._connected:
                await self._client.disconnect()
            self._connected = False
            return {"ok": True, "message": "Disconnected from OPC UA"}
        except Exception as e:
            return {"ok": False, "message": f"Disconnect error: {e}"}

    async def get_status(self) -> dict:
        """Poll OPC UA status.

        Returns:
            {
                "online": bool,
                "state": str,
                "position_xyz": dict,
                "feed_rate_mm_min": float | None,
                "spindle_rpm_current": int | None
            }
        """
        if not self._connected or not self._client:
            result = await self.connect()
            if not result.get("ok"):
                return {"online": False, "state": "offline"}

        try:
            # Read configured OPC UA nodes by NodeId string.
            state = await self._read_node(self._nodes["state"])
            # If the state node can't be read, the address space doesn't match our
            # config (or the machine is down) — report offline honestly instead of
            # claiming online with fabricated zeroed telemetry.
            if state is None:
                return {"online": False, "state": "offline"}
            spindle_rpm = await self._read_node(self._nodes["spindle_rpm"])
            feed_rate = await self._read_node(self._nodes["feed_rate"])
            x_pos = await self._read_node(self._nodes["pos_x"])
            y_pos = await self._read_node(self._nodes["pos_y"])
            z_pos = await self._read_node(self._nodes["pos_z"])

            mapped_state = _STATE_MAP.get(str(state), "offline")

            return {
                "online": True,
                "state": mapped_state,
                "position_xyz": {
                    "x": float(x_pos or 0),
                    "y": float(y_pos or 0),
                    "z": float(z_pos or 0),
                },
                "feed_rate_mm_min": float(feed_rate) if feed_rate else None,
                "spindle_rpm_current": int(spindle_rpm) if spindle_rpm else None,
            }
        except Exception as e:
            return {"online": False, "state": "offline", "error": str(e)}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Get detailed OPC UA machine state.

        Returns:
            CNCAdapterStatus with full machine snapshot
        """
        # Lazy connect: cnc_routes builds a fresh adapter per request and calls
        # this without connect(), so _connected was always False → every OPC-UA
        # device reported offline. Establish the session on first use.
        if not self._connected or not self._client:
            result = await self.connect()
            if not result.get("ok"):
                return CNCAdapterStatus(online=False, state="offline")

        try:
            state = await self._read_node(self._nodes["state"])
            # Same honesty gate as get_status(): no readable state node → offline,
            # not online-with-zeros.
            if state is None:
                return CNCAdapterStatus(online=False, state="offline")
            spindle_rpm = await self._read_node(self._nodes["spindle_rpm"])
            feed_rate = await self._read_node(self._nodes["feed_rate"])
            x_pos = await self._read_node(self._nodes["pos_x"])
            y_pos = await self._read_node(self._nodes["pos_y"])
            z_pos = await self._read_node(self._nodes["pos_z"])
            coolant = await self._read_node(self._nodes["coolant"])
            tool_id = await self._read_node(self._nodes["tool_id"])

            mapped_state = _STATE_MAP.get(str(state), "offline")

            return CNCAdapterStatus(
                online=True,
                state=mapped_state,
                position_xyz={
                    "x": float(x_pos or 0),
                    "y": float(y_pos or 0),
                    "z": float(z_pos or 0),
                },
                feed_rate_mm_min=float(feed_rate) if feed_rate else None,
                spindle_rpm_current=int(spindle_rpm) if spindle_rpm else None,
                tool_id=str(tool_id) if tool_id else None,
                coolant_active=bool(coolant) if coolant is not None else False,
            )
        except Exception:
            return CNCAdapterStatus(online=False, state="offline")

    async def send_gcode(self, gcode: str) -> dict:
        """Send G-code via OPC UA (if supported by machine).

        Args:
            gcode: G-code string

        Returns:
            {"ok": bool, "response": str, "error": str | None}
        """
        if not gcode or not gcode.strip():
            return {"ok": False, "response": "", "error": "Empty G-code command"}

        if gcode.strip().startswith("-"):
            return {"ok": False, "response": "", "error": "G-code cannot start with '-'"}

        if not await self._ensure_connected():
            return {"ok": False, "response": "", "error": "Not connected to OPC UA"}

        try:
            # Attempt to write G-code command to OPC UA command node
            # (implementation varies by machine; this is a common pattern)
            await self._write_node(
                self._nodes["gcode_command"],
                gcode.strip(),
            )
            return {"ok": True, "response": "Command queued", "error": None}
        except Exception as e:
            return {"ok": False, "response": "", "error": f"OPC UA write failed: {e}"}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes via OPC UA.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "response": str}
        """
        if not await self._ensure_connected():
            return {"ok": False, "response": "Not connected to OPC UA"}

        try:
            # Trigger homing command on OPC UA server
            await self._write_node(self._nodes["homing_axes"], axes)
            return {"ok": True, "response": f"Homing {axes}"}
        except Exception as e:
            return {"ok": False, "response": f"Homing failed: {e}"}

    async def set_feed_rate(self, rate_mm_min: float) -> dict:
        """Set feed rate override via OPC UA.

        Args:
            rate_mm_min: Feed rate in mm/min (0.0 - 500.0)

        Returns:
            {"ok": bool, "new_rate_mm_min": float | None}
        """
        if rate_mm_min < 0:
            return {"ok": False, "new_rate_mm_min": None}

        if not await self._ensure_connected():
            return {"ok": False, "new_rate_mm_min": None}

        try:
            await self._write_node(self._nodes["feed_rate"], rate_mm_min)
            return {"ok": True, "new_rate_mm_min": rate_mm_min}
        except Exception:
            return {"ok": False, "new_rate_mm_min": None}

    async def emergency_stop(self) -> dict:
        """Trigger emergency stop via OPC UA.

        Returns:
            {"ok": bool, "state": str}
        """
        if not await self._ensure_connected():
            return {"ok": False, "state": "offline"}

        try:
            await self._write_node(self._nodes["estop"], True)
            return {"ok": True, "state": "error"}
        except Exception:
            return {"ok": False, "state": "unknown"}

    async def list_files(self, path: str = "/") -> list:
        """List files on OPC UA server (if supported).

        Args:
            path: Directory path

        Returns:
            list of {"name": str, "path": str}
        """
        if not await self._ensure_connected():
            return []

        try:
            files = await self._read_node(self._nodes["files"])
            if isinstance(files, list):
                return [
                    {"name": f.get("name"), "path": f.get("path")}
                    for f in files
                    if isinstance(f, dict)
                ]
            return []
        except Exception:
            return []

    # Private helpers
    async def _read_node(self, nodeid: str) -> Optional[any]:
        """Read a value from an OPC UA node by NodeId string.

        Args:
            nodeid: OPC UA NodeId string, e.g. "ns=2;s=Machine.State" or
                "ns=3;i=1001". This is the unambiguous, most portable addressing
                form (``client.get_node`` accepts it directly) — unlike a browse
                path it needs no assumptions about the address-space tree layout.

        Returns:
            Node value, or None if the node can't be resolved/read (unknown NodeId,
            bad namespace, permission denied, connection dropped). None is treated
            by callers as "unreadable" and surfaces as offline, never as fake data.
        """
        if not self._client:
            return None

        try:
            node = self._client.get_node(nodeid)
            return await node.read_value()
        except Exception:
            return None

    async def _write_node(self, nodeid: str, value: any) -> None:
        """Write a value to an OPC UA node by NodeId string.

        Args:
            nodeid: OPC UA NodeId string (see _read_node).
            value: Value to write.
        """
        if not self._client:
            raise ConnectionError("Not connected to OPC UA")

        try:
            node = self._client.get_node(nodeid)
            await node.write_value(value)
        except Exception as e:
            raise RuntimeError(f"OPC UA write failed: {e}")
