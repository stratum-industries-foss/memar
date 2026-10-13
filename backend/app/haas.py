"""
Haas CNC Machine adapter.

Haas industrial CNCs expose status via:
1. HTTP REST API (newer machines, port 80)
2. Modbus TCP (port 502) for legacy machines
3. Serial port RS-232 for oldest machines

This adapter targets the HTTP REST API (most common in modern shops).
Endpoints are rooted at /api/* on the machine's REST bridge.
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus


class HaasAdapter(CNCAdapter):
    """Haas industrial CNC machine adapter."""

    def __init__(self, config: PrinterConfig):
        """Initialize Haas client.

        Args:
            config: PrinterConfig with base_url (e.g., "http://192.168.1.100:80")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to Haas machine."""
        try:
            res = await self._client.get(f"{self.base_url}/api/version")
            if res.status_code == 200:
                data = res.json()
                return {
                    "ok": True,
                    "message": f"Connected to Haas {data.get('model', '?')}",
                    "state": "ready",
                }
            else:
                return {
                    "ok": False,
                    "message": f"Haas API returned {res.status_code}",
                    "state": "error",
                }
        except Exception as e:
            return {"ok": False, "message": str(e), "state": "offline"}

    async def disconnect(self) -> dict:
        """Close Haas connection."""
        try:
            await self._client.aclose()
        except Exception:
            pass
        return {"ok": True, "message": "Disconnected"}

    async def get_status(self) -> dict:
        """Poll Haas machine status (position, spindle, state)."""
        try:
            res = await self._client.get(f"{self.base_url}/api/status")
            if res.status_code != 200:
                return {"online": False, "state": "error"}

            data = res.json()
            return {
                "online": True,
                "state": data.get("state", "ready"),  # "ready", "running", "stopped", "alarm"
                "position_xyz": {
                    "x": float(data.get("position", {}).get("x", 0)),
                    "y": float(data.get("position", {}).get("y", 0)),
                    "z": float(data.get("position", {}).get("z", 0)),
                },
                "spindle_rpm_current": int(data.get("spindle_speed", 0)),
                "feed_rate_mm_min": float(data.get("feed_rate", 0)),
            }
        except Exception:
            return {"online": False, "state": "error"}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Detailed Haas machine state (position, spindle, coolant, tool)."""
        status = await self.get_status()
        tool_id = None
        coolant_active = False

        try:
            tool_res = await self._client.get(f"{self.base_url}/api/tool")
            if tool_res.status_code == 200:
                tool_data = tool_res.json()
                tool_id = str(tool_data.get("id", ""))

            coolant_res = await self._client.get(f"{self.base_url}/api/coolant")
            if coolant_res.status_code == 200:
                coolant_data = coolant_res.json()
                coolant_active = bool(coolant_data.get("active", False))
        except Exception:
            pass

        return CNCAdapterStatus(
            online=status.get("online", False),
            state=status.get("state", "offline"),
            position_xyz=status.get("position_xyz", {"x": 0, "y": 0, "z": 0}),
            spindle_rpm_current=status.get("spindle_rpm_current"),
            feed_rate_mm_min=status.get("feed_rate_mm_min"),
            tool_id=tool_id,
            coolant_active=coolant_active,
        )

    async def send_gcode(self, gcode: str) -> dict:
        """Send G-code to Haas (via MDI — Manual Data Input)."""
        if not gcode or not gcode.strip():
            return {"ok": False, "message": "Not connected or empty G-code"}

        try:
            res = await self._client.post(
                f"{self.base_url}/api/mdi",
                json={"gcode": gcode},
            )
            if res.status_code in (200, 201):
                return {
                    "ok": True,
                    "message": "G-code sent to Haas",
                    "result": res.json(),
                }
            else:
                return {"ok": False, "message": f"Haas returned {res.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes (X, Y, Z, A, B, C, or any combination).

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "message": str, "homing": str}
        """
        try:
            res = await self._client.post(
                f"{self.base_url}/api/home",
                json={"axis": axes.upper()},
            )
            return {
                "ok": res.status_code in (200, 201),
                "message": f"Homed {axes}",
                "homing": axes,
            }
        except Exception as e:
            return {"ok": False, "message": str(e), "homing": axes}

    async def set_feed_rate(self, feed_mm_min: float) -> dict:
        """Override feed rate.

        UNVERIFIED AGAINST REAL HARDWARE: this adapter targets a hypothetical
        REST bridge (see cnc_adapter.py's shared caveat), and it's unconfirmed
        whether the real endpoint takes an absolute mm/min setpoint (matching
        this method's parameter name and cnc_adapter.py's contract) or a
        percentage override. Currently treated as an already-computed
        percentage (0-200%), NOT divided by 100 — do not wire this to a live
        route without validating the real bridge's unit semantics first.
        """
        # HIGH-CNC-FEEDRATE-01: this bridge's feed-override endpoint takes a
        # 0-200% override, but the /feed-rate route validates and passes an
        # absolute mm/min setpoint. There is no safe mm/min->% conversion without
        # a per-machine baseline feed rate, which is not available here. Sending
        # the raw value inverts operator intent (e.g. 500 mm/min -> 200% override).
        # Refuse rather than send an ambiguous command to real hardware.
        return {
            "ok": False,
            "message": (
                "Feed-rate not supported on this adapter: the bridge expects a "
                "0-200% override, not the absolute mm/min the control route sends. "
                "Refused to avoid inverting operator intent on unverified hardware."
            ),
        }

    async def emergency_stop(self) -> dict:
        """Send emergency stop signal."""
        try:
            res = await self._client.post(f"{self.base_url}/api/stop")
            return {
                "ok": res.status_code in (200, 201),
                "message": "Emergency stop activated",
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def list_files(self, path: str = "/") -> list:
        """List G-code files on Haas machine (if available).

        Args:
            path: Directory path to list

        Returns:
            list of {"name": str, "path": str}
        """
        try:
            res = await self._client.get(
                f"{self.base_url}/api/files",
                params={"path": path},
            )
            if res.status_code == 200:
                files = res.json()
                return files if isinstance(files, list) else []
            return []
        except Exception:
            return []
