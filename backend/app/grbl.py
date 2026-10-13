"""GRBL HTTP/TCP adapter — budget CNC machines, K40 lasers, Sculpfun, etc.

GRBL responds to '?' with: <Idle|MPos:0.000,0.000,0.000|FS:0,0|Pn:XYZ>

Supported URL schemes:
  - http://host:port/ — HTTP bridge (default, assumes simple GET/POST API)
  - tcp://host:port — Direct TCP (uses Telnet-like protocol, default port 23)
  - serial://... — Not supported (requires external TCP bridge like ser2net)

HTTP bridge API (expected endpoints):
  - GET /status or /api/status → returns "status:<response>" line
  - GET /command?cmd=<gcode> or POST /api/command {gcode: "..."} → executes G-code
"""
from __future__ import annotations
import asyncio
import re
from typing import Optional
import httpx

from .cnc_adapter import CNCAdapterStatus
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus

_STATE_MAP = {
    "Idle": "ready", "Run": "printing", "Hold:0": "paused", "Hold:1": "paused",
    "Jog": "printing", "Alarm": "error", "Door:0": "paused", "Check": "ready",
    "Home": "printing", "Sleep": "offline",
}


class GRBLClient(CNCAdapter):
    """HTTP and TCP client for GRBL motion control firmware."""

    def __init__(self, config: PrinterConfig):
        """Initialize GRBL client. Supports http://, tcp://, and serial:// (not recommended).

        Args:
            config: PrinterConfig with base_url (e.g., "http://localhost:8080" or "tcp://192.168.1.100:23")
        """
        self.base_url = config.base_url
        self._http_client: Optional[httpx.AsyncClient] = None
        self._connection_error: Optional[str] = None

        if self.base_url.startswith("http://") or self.base_url.startswith("https://"):
            self._mode = "http"
            self._base_url_http = self.base_url.rstrip("/")
            # Create async HTTP client
            self._http_client = httpx.AsyncClient(
                timeout=8.0,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
        elif self.base_url.startswith("tcp://"):
            self._mode = "tcp"
            url = self.base_url[6:]
            host_port = url.split(":")
            self.host = host_port[0]
            self.port = int(host_port[1]) if len(host_port) > 1 else 23
        elif self.base_url.startswith("serial://"):
            self._mode = "serial"
            self._connection_error = (
                "serial:// base_url is not supported for GRBL — "
                "run ser2net on the host and use http://host:port or tcp://host:port instead"
            )
        else:
            # Default to HTTP if no scheme
            self._mode = "http"
            self._base_url_http = f"http://{self.base_url.rstrip('/')}"
            self._http_client = httpx.AsyncClient(
                timeout=8.0,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )

    async def connect(self) -> dict:
        """Test connection to GRBL machine.

        Returns:
            {"online": bool, "message": str, "state": str}
        """
        if self._connection_error:
            return {"online": False, "message": self._connection_error, "state": "offline"}

        try:
            status = await self.get_status()
            return {
                "online": status.get("online", False),
                "message": "Connected to GRBL" if status.get("online") else "Failed to connect",
                "state": status.get("state", "offline"),
            }
        except Exception as e:
            return {"online": False, "message": str(e), "state": "offline"}

    async def disconnect(self) -> dict:
        """Close GRBL connection.

        Returns:
            {"ok": bool}
        """
        try:
            if self._http_client:
                await self._http_client.aclose()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_status(self) -> dict:
        """Poll GRBL status via '?' command.

        Response format: <State|MPos:x,y,z|FS:f,s|Pn:pins|...>
        Example: <Idle|MPos:10.5,20.3,0.000|FS:100,0|Pn:X>

        Returns:
            {
                "online": bool,
                "state": str (ready|printing|paused|error|offline),
                "position_xyz": {"x": float, "y": float, "z": float},
                "feed_rate_mm_min": float | None,
                "spindle_rpm_current": int | None,
                "grbl_state_raw": str (Idle, Run, Hold:0, etc.)
            }
        """
        if self._connection_error:
            return {"online": False, "state": "offline"}

        try:
            raw = await self._send_command("?")
            return self._parse_status(raw)
        except Exception as e:
            return {"online": False, "state": "offline", "error": str(e)}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Get detailed machine state as the canonical CNCAdapterStatus.

        Conforms to the CNCAdapter contract (every other adapter returns a
        CNCAdapterStatus object). The CNC routes and metrics aggregator access
        fields by attribute (state.spindle_rpm_current, state.feed_rate_mm_min,
        ...) — returning a raw dict here used to raise AttributeError / 502.
        """
        status = await self.get_status()
        if not status.get("online"):
            return CNCAdapterStatus(online=False, state="offline")

        return CNCAdapterStatus(
            online=True,
            state=status.get("state") or "offline",
            position_xyz=status.get("position_xyz") or {"x": 0.0, "y": 0.0, "z": 0.0},
            feed_rate_mm_min=status.get("feed_rate_mm_min"),
            spindle_rpm_current=status.get("spindle_rpm_current"),
            tool_id=status.get("tool_id"),
            coolant_active=bool(status.get("coolant_active", False)),
        )

    async def send_gcode_command(self, gcode: str) -> dict:
        """Send a G-code command to GRBL.

        Args:
            gcode: G-code command (e.g., "G0 X10 Y20 Z5" or "M3 S1000")

        Returns:
            {
                "ok": bool,
                "response": str,
                "command": str,
                "error": str | None
            }
        """
        if self._connection_error:
            return {"ok": False, "response": "", "error": self._connection_error}

        try:
            response = await self._send_command(gcode)
            # GRBL typically responds with "ok" or error messages
            is_ok = "ok" in response.lower() or (response and not response.startswith("error"))
            return {
                "ok": is_ok,
                "response": response,
                "command": gcode,
                "error": None if is_ok else response,
            }
        except Exception as e:
            return {
                "ok": False,
                "response": "",
                "command": gcode,
                "error": str(e),
            }

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes (G28).

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "response": str, "homing": str}
        """
        if self._connection_error:
            return {"ok": False, "response": "", "homing": axes}

        try:
            # GRBL G28 homes all axes, but we can send individual axis commands
            # Standard: $H homes all homed axes
            response = await self._send_command("$H")
            is_ok = "ok" in response.lower() or response == ""
            return {
                "ok": is_ok,
                "response": response,
                "homing": axes,
            }
        except Exception as e:
            return {"ok": False, "response": str(e), "homing": axes}

    async def set_feed_rate(self, rate_mm_min: float) -> dict:
        """Set feed rate (sent as a G-code F-word).

        Note: GRBL has no absolute "set feed rate" command — feed rate is a
        modal G-code word (F) or a realtime override percentage (0x90-0x9D).
        This sends an F-word so the value sticks for subsequent moves.

        Returns:
            {"ok": bool, "new_rate_mm_min": float | None}
        """
        if rate_mm_min < 0:
            return {"ok": False, "new_rate_mm_min": None}

        if self._connection_error:
            return {"ok": False, "new_rate_mm_min": None}

        try:
            response = await self._send_command(f"F{rate_mm_min:g}")
            is_ok = "ok" in response.lower() or response == ""
            return {
                "ok": is_ok,
                "new_rate_mm_min": rate_mm_min if is_ok else None,
            }
        except Exception:
            return {"ok": False, "new_rate_mm_min": None}

    async def emergency_stop(self) -> dict:
        """Trigger emergency stop via GRBL soft-reset (Ctrl-X / 0x18).

        Returns:
            {"ok": bool, "state": str}
        """
        if self._connection_error:
            return {"ok": False, "state": "offline"}

        try:
            # 0x18 (Ctrl-X) is GRBL's realtime soft-reset / abort command.
            await self._send_command("\x18")
            return {"ok": True, "state": "error"}
        except Exception:
            return {"ok": False, "state": "unknown"}

    async def _send_command(self, cmd: str, timeout: float = 3.0) -> str:
        """Send command via HTTP or TCP, return response."""
        if self._mode == "http":
            return await self._send_http(cmd, timeout)
        elif self._mode == "tcp":
            return await self._send_tcp(cmd, timeout)
        else:
            raise ConnectionError(f"Unsupported mode: {self._mode}")

    async def _send_http(self, cmd: str, timeout: float = 3.0) -> str:
        """Send command via HTTP bridge."""
        if not self._http_client:
            raise ConnectionError("HTTP client not initialized")

        try:
            # Try POST first (more flexible)
            response = await self._http_client.post(
                f"{self._base_url_http}/api/command",
                json={"gcode": cmd},
                timeout=timeout,
            )

            if response.status_code == 404:
                # Fallback: try GET with query param
                response = await self._http_client.get(
                    f"{self._base_url_http}/command",
                    params={"cmd": cmd},
                    timeout=timeout,
                )

            if response.status_code == 200:
                return response.text.strip()
            else:
                raise ConnectionError(f"HTTP {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise ConnectionError(f"GRBL HTTP timeout ({self._base_url_http})")
        except Exception as e:
            raise ConnectionError(f"GRBL HTTP error ({self._base_url_http}): {e}")

    async def _send_tcp(self, cmd: str, timeout: float = 3.0) -> str:
        """Send command via TCP (Telnet-like protocol)."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout,
            )
            writer.write((cmd + "\n").encode())
            await writer.drain()
            response = await asyncio.wait_for(reader.read(256), timeout=timeout)
            return response.decode(errors="replace").strip()
        except asyncio.TimeoutError:
            raise ConnectionError(f"GRBL TCP timeout ({self.host}:{self.port})")
        except Exception as e:
            raise ConnectionError(f"GRBL TCP error ({self.host}:{self.port}): {e}")
        finally:
            # Close on ALL paths — a bridge that accepts but never replies would
            # otherwise leak an fd per poll (read() times out after the socket
            # is already open).
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    def _parse_status(self, raw: str) -> dict:
        """Parse GRBL status response.

        Format: <State|MPos:x,y,z|FS:f,s|Pn:pins|...>
        """
        if not raw:
            return {"online": False, "state": "offline"}

        # Try to parse GRBL status format
        m = re.search(
            r"<(\w+(?::\d+)?)\|MPos:([0-9.,\-]+)(?:\|FS:([0-9,]+))?",
            raw,
        )

        if not m:
            # Not a valid status response
            return {"online": False, "state": "offline", "raw": raw}

        grbl_state = m.group(1)
        mpos_str = m.group(2)
        fs_str = m.group(3) or "0,0"

        try:
            coords = [float(v) for v in mpos_str.split(",")]
            fs_vals = [float(v) for v in fs_str.split(",")]
        except ValueError:
            return {"online": False, "state": "offline", "parse_error": raw}

        state = _STATE_MAP.get(grbl_state, "offline")

        return {
            "online": True,
            "state": state,
            "grbl_state_raw": grbl_state,
            "position_xyz": {
                "x": coords[0] if len(coords) > 0 else 0.0,
                "y": coords[1] if len(coords) > 1 else 0.0,
                "z": coords[2] if len(coords) > 2 else 0.0,
            },
            "feed_rate_mm_min": fs_vals[0] if len(fs_vals) > 0 else None,
            "spindle_rpm_current": int(fs_vals[1]) if len(fs_vals) > 1 else None,
        }

    # Adapter protocol implementation
    async def send_gcode(self, gcode: str) -> dict:
        """CNCAdapter protocol: send G-code command."""
        return await self.send_gcode_command(gcode)

    # Legacy API compatibility
    async def run_gcode(self, cmd: str) -> dict:
        """Legacy method for compatibility."""
        return await self.send_gcode_command(cmd)

    async def list_files(self, path: str = "/") -> list:
        """GRBL has no filesystem."""
        return []
