"""
Sinumerik (Siemens) CNC control system adapter.

Sinumerik is a family of CNC controls used in industrial machining centers.
Integration options:
1. SINUMERIK One (cloud-enabled) — REST API via Siemens IoT gateway
2. SINUMERIK 840D — PROFINET or S7-gateway (via SNAP7 or TCP bridge)
3. Automation Controller — OPC UA or HTTP REST API

This adapter assumes an HTTP REST bridge is available (most flexible).

State mapping:
  "IDLE" → "ready"
  "RUN" → "printing"
  "HOLD" → "paused"
  "ERROR" → "error"
  "OFFLINE" → "offline"
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus

_STATE_MAP = {
    "IDLE": "ready",
    "RUN": "printing",
    "HOLD": "paused",
    "PAUSE": "paused",
    "ERROR": "error",
    "OFFLINE": "offline",
    "ESTOP": "error",
    "HOMING": "printing",
    "RESETTING": "printing",
}


class SinumerikClient(CNCAdapter):
    """HTTP client for Siemens Sinumerik CNC systems."""

    def __init__(self, config: PrinterConfig):
        """Initialize Sinumerik client.

        Args:
            config: PrinterConfig with base_url (e.g., "http://sinumerik-gateway.local:8080" or "https://iot.siemens.com/api/...")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to Sinumerik system.

        Returns:
            {"ok": bool, "message": str, "state": str}
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/status",
                headers={"Accept": "application/json"},
                timeout=3,
            )
            if r.status_code == 200:
                return {"ok": True, "message": "Connected to Sinumerik", "state": "ready"}
            else:
                return {
                    "ok": False,
                    "message": f"HTTP {r.status_code} from {self.base_url}",
                    "state": "offline",
                }
        except Exception as e:
            return {"ok": False, "message": f"Connection failed: {e}", "state": "offline"}

    async def disconnect(self) -> dict:
        """Close Sinumerik connection.

        Returns:
            {"ok": bool, "message": str}
        """
        try:
            await self._client.aclose()
            return {"ok": True, "message": "Disconnected from Sinumerik"}
        except Exception as e:
            return {"ok": False, "message": f"Disconnect error: {e}"}

    async def get_status(self) -> dict:
        """Poll Sinumerik status.

        Returns:
            {
                "online": bool,
                "state": str,
                "position_xyz": dict,
                "feed_rate_mm_min": float | None,
                "spindle_rpm_current": int | None
            }
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/status",
                headers={"Accept": "application/json"},
                timeout=3,
            )
            if r.status_code != 200:
                return {"online": False, "state": "offline"}

            data = r.json()
            sinumerik_state = data.get("state", "OFFLINE")
            state = _STATE_MAP.get(sinumerik_state, "offline")

            # Expect response structure: {state, position: {x, y, z}, feed_rate, spindle_rpm}
            position = data.get("position", {})
            feed_rate = data.get("feed_rate") or data.get("feedrate")
            spindle_rpm = data.get("spindle_rpm") or data.get("spindle_speed")

            return {
                "online": True,
                "state": state,
                "position_xyz": {
                    "x": float(position.get("x", 0)) if isinstance(position, dict) else 0.0,
                    "y": float(position.get("y", 0)) if isinstance(position, dict) else 0.0,
                    "z": float(position.get("z", 0)) if isinstance(position, dict) else 0.0,
                },
                "feed_rate_mm_min": float(feed_rate) if feed_rate else None,
                "spindle_rpm_current": int(spindle_rpm) if spindle_rpm else None,
            }
        except Exception as e:
            return {"online": False, "state": "offline", "error": str(e)}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Get detailed Sinumerik machine state.

        Returns:
            CNCAdapterStatus with full machine snapshot
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/status",
                headers={"Accept": "application/json"},
                timeout=3,
            )
            if r.status_code != 200:
                return CNCAdapterStatus(online=False, state="offline")

            data = r.json()
            sinumerik_state = data.get("state", "OFFLINE")
            state = _STATE_MAP.get(sinumerik_state, "offline")

            position = data.get("position", {})
            feed_rate = data.get("feed_rate") or data.get("feedrate")
            spindle_rpm = data.get("spindle_rpm") or data.get("spindle_speed")
            coolant = data.get("coolant_active") or data.get("coolant")
            tool_id = data.get("tool_id") or data.get("tool_number")

            return CNCAdapterStatus(
                online=True,
                state=state,
                position_xyz={
                    "x": float(position.get("x", 0)) if isinstance(position, dict) else 0.0,
                    "y": float(position.get("y", 0)) if isinstance(position, dict) else 0.0,
                    "z": float(position.get("z", 0)) if isinstance(position, dict) else 0.0,
                },
                feed_rate_mm_min=float(feed_rate) if feed_rate else None,
                spindle_rpm_current=int(spindle_rpm) if spindle_rpm else None,
                tool_id=str(tool_id) if tool_id else None,
                coolant_active=bool(coolant) if coolant is not None else False,
            )
        except Exception:
            return CNCAdapterStatus(online=False, state="offline")

    async def send_gcode(self, gcode: str) -> dict:
        """Send G-code or ISO command to Sinumerik.

        Args:
            gcode: G-code or ISO command (e.g., "G0 X100 Y50 Z10")

        Returns:
            {"ok": bool, "response": str, "error": str | None}
        """
        if not gcode or not gcode.strip():
            return {"ok": False, "response": "", "error": "Empty G-code command"}

        if gcode.strip().startswith("-"):
            return {"ok": False, "response": "", "error": "G-code cannot start with '-'"}

        try:
            r = await self._client.post(
                f"{self.base_url}/api/v1/command",
                json={"command": gcode.strip()},
                headers={"Content-Type": "application/json"},
                timeout=5,
            )

            if r.status_code == 200:
                response = r.json()
                return {
                    "ok": True,
                    "response": response.get("result", "Command accepted"),
                    "error": None,
                }
            else:
                return {
                    "ok": False,
                    "response": "",
                    "error": f"HTTP {r.status_code}: {r.text[:200]}",
                }
        except Exception as e:
            return {"ok": False, "response": "", "error": str(e)}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "response": str}
        """
        try:
            r = await self._client.post(
                f"{self.base_url}/api/v1/home",
                json={"axes": axes},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            if r.status_code == 200:
                return {"ok": True, "response": f"Homing {axes}"}
            else:
                return {"ok": False, "response": f"Homing failed: HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "response": f"Homing error: {e}"}

    async def set_feed_rate(self, rate_mm_min: float) -> dict:
        """Set feed rate override.

        Args:
            rate_mm_min: Feed rate in mm/min (0.0 - 500.0)

        Returns:
            {"ok": bool, "new_rate_mm_min": float | None}
        """
        if rate_mm_min < 0:
            return {"ok": False, "new_rate_mm_min": None}

        try:
            r = await self._client.put(
                f"{self.base_url}/api/v1/feedrate",
                json={"feedrate_mm_min": rate_mm_min},
                headers={"Content-Type": "application/json"},
                timeout=3,
            )

            if r.status_code == 200:
                return {"ok": True, "new_rate_mm_min": rate_mm_min}
            else:
                return {"ok": False, "new_rate_mm_min": None}
        except Exception:
            return {"ok": False, "new_rate_mm_min": None}

    async def emergency_stop(self) -> dict:
        """Trigger emergency stop (ESTOP).

        Returns:
            {"ok": bool, "state": str}
        """
        try:
            r = await self._client.post(
                f"{self.base_url}/api/v1/estop",
                json={},
                headers={"Content-Type": "application/json"},
                timeout=2,
            )

            if r.status_code == 200:
                return {"ok": True, "state": "error"}
            else:
                return {"ok": False, "state": "unknown"}
        except Exception:
            return {"ok": False, "state": "unknown"}

    async def list_files(self, path: str = "/") -> list:
        """List G-code files from Sinumerik.

        Args:
            path: Directory path

        Returns:
            list of {"name": str, "path": str}
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/files",
                params={"path": path},
                headers={"Accept": "application/json"},
                timeout=3,
            )

            if r.status_code == 200:
                files = r.json().get("files", [])
                return [
                    {"name": f.get("name"), "path": f.get("path")}
                    for f in files
                    if isinstance(f, dict)
                ]
            return []
        except Exception:
            return []
