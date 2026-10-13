"""
MACH3 CNC control system adapter.

MACH3 is a Windows-based legacy CNC software. Integration via:
1. HTTP REST bridge (if available via Pokeys57CNC or similar middleware)
2. Direct socket communication (port 5000 default)

This adapter assumes an HTTP REST bridge is available.
State mapping:
  "Idle" → "ready"
  "Running" → "printing"
  "Paused" → "paused"
  "E-Stop" → "error"
  "Offline" → "offline"
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus

_STATE_MAP = {
    "Idle": "ready",
    "Running": "printing",
    "Paused": "paused",
    "E-Stop": "error",
    "Offline": "offline",
    "Reset": "ready",
    "Homing": "printing",
}


class MACH3Client(CNCAdapter):
    """HTTP client for MACH3 CNC control system."""

    def __init__(self, config: PrinterConfig):
        """Initialize MACH3 client.

        Args:
            config: PrinterConfig with base_url (e.g., "http://localhost:5000" or "http://cnc-machine.local:5000")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to MACH3 machine.

        Returns:
            {"ok": bool, "message": str, "state": str}
        """
        try:
            r = await self._client.get(f"{self.base_url}/api/status", timeout=3)
            if r.status_code == 200:
                return {"ok": True, "message": "Connected to MACH3", "state": "ready"}
            else:
                return {
                    "ok": False,
                    "message": f"HTTP {r.status_code} from {self.base_url}",
                    "state": "offline",
                }
        except Exception as e:
            return {"ok": False, "message": f"Connection failed: {e}", "state": "offline"}

    async def disconnect(self) -> dict:
        """Close MACH3 connection.

        Returns:
            {"ok": bool, "message": str}
        """
        try:
            await self._client.aclose()
            return {"ok": True, "message": "Disconnected from MACH3"}
        except Exception as e:
            return {"ok": False, "message": f"Disconnect error: {e}"}

    async def get_status(self) -> dict:
        """Poll MACH3 status.

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
            r = await self._client.get(f"{self.base_url}/api/status", timeout=3)
            if r.status_code != 200:
                return {"online": False, "state": "offline"}

            data = r.json()
            mach3_state = data.get("state", "Offline")
            state = _STATE_MAP.get(mach3_state, "offline")

            return {
                "online": True,
                "state": state,
                "position_xyz": {
                    "x": float(data.get("position_x", 0)),
                    "y": float(data.get("position_y", 0)),
                    "z": float(data.get("position_z", 0)),
                },
                "feed_rate_mm_min": float(data.get("feed_rate", 0)) or None,
                "spindle_rpm_current": int(data.get("spindle_rpm", 0)) or None,
            }
        except Exception as e:
            return {"online": False, "state": "offline", "error": str(e)}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Get detailed MACH3 machine state.

        Returns:
            CNCAdapterStatus with full machine snapshot
        """
        try:
            r = await self._client.get(f"{self.base_url}/api/status", timeout=3)
            if r.status_code != 200:
                return CNCAdapterStatus(online=False, state="offline")

            data = r.json()
            mach3_state = data.get("state", "Offline")
            state = _STATE_MAP.get(mach3_state, "offline")

            return CNCAdapterStatus(
                online=True,
                state=state,
                position_xyz={
                    "x": float(data.get("position_x", 0)),
                    "y": float(data.get("position_y", 0)),
                    "z": float(data.get("position_z", 0)),
                },
                feed_rate_mm_min=float(data.get("feed_rate", 0)) or None,
                spindle_rpm_current=int(data.get("spindle_rpm", 0)) or None,
                tool_id=str(data.get("tool_id", "")),
                coolant_active=bool(data.get("coolant_active", False)),
            )
        except Exception as e:
            return CNCAdapterStatus(online=False, state="error")

    async def send_gcode(self, gcode: str) -> dict:
        """Send G-code command to MACH3.

        Args:
            gcode: G-code string (e.g., "G0 X10 Y20 Z5")

        Returns:
            {"ok": bool, "response": str, "error": str | None}
        """
        if not gcode or not gcode.strip():
            return {"ok": False, "response": "", "error": "Empty G-code command"}

        if gcode.strip().startswith("-"):
            return {"ok": False, "response": "", "error": "G-code cannot start with '-'"}

        try:
            r = await self._client.post(
                f"{self.base_url}/api/command",
                json={"gcode": gcode.strip()},
                timeout=5,
            )

            if r.status_code == 200:
                return {"ok": True, "response": r.json().get("result", ""), "error": None}
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
                f"{self.base_url}/api/home",
                json={"axes": axes},
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
                f"{self.base_url}/api/feedrate",
                json={"feedrate_mm_min": rate_mm_min},
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
                f"{self.base_url}/api/estop",
                json={},
                timeout=2,
            )

            if r.status_code == 200:
                return {"ok": True, "state": "error"}
            else:
                return {"ok": False, "state": "unknown"}
        except Exception:
            return {"ok": False, "state": "unknown"}

    async def list_files(self, path: str = "/") -> list:
        """List G-code files from MACH3.

        Args:
            path: Directory path

        Returns:
            list of {"name": str, "path": str}
        """
        try:
            r = await self._client.get(
                f"{self.base_url}/api/files",
                params={"path": path},
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
