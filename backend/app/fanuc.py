"""
FANUC CNC Machine adapter.

FANUC industrial CNCs expose status via:
1. FOCAS API (native FANUC SDK) — HTTP bridge
2. Modbus TCP (port 502)
3. Ethernet/IP (OMRON)

This adapter targets the FOCAS HTTP bridge for compatibility.
FANUC machines are among the most mature industrial platforms;
expect robust status reporting and parameter access.
Endpoints are rooted at /focas/api/* on the bridge.
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus


class FANUCAdapter(CNCAdapter):
    """FANUC industrial CNC machine adapter."""

    def __init__(self, config: PrinterConfig):
        """Initialize FANUC client.

        Args:
            config: PrinterConfig with base_url pointing at the FOCAS HTTP bridge
                (e.g., "http://192.168.1.50:80")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to FANUC FOCAS API."""
        try:
            res = await self._client.get(f"{self.base_url}/focas/api/version")
            if res.status_code == 200:
                data = res.json()
                return {
                    "ok": True,
                    "message": f"Connected to FANUC {data.get('model', '?')}",
                    "state": "ready",
                }
            else:
                return {
                    "ok": False,
                    "message": f"FOCAS API returned {res.status_code}",
                    "state": "error",
                }
        except Exception as e:
            return {"ok": False, "message": str(e), "state": "offline"}

    async def disconnect(self) -> dict:
        """Close FANUC connection."""
        try:
            await self._client.aclose()
        except Exception:
            pass
        return {"ok": True, "message": "Disconnected"}

    async def get_status(self) -> dict:
        """Poll FANUC machine status (position, spindle, state)."""
        try:
            res = await self._client.get(f"{self.base_url}/focas/api/status")
            if res.status_code != 200:
                return {"online": False, "state": "error"}

            data = res.json()
            # FANUC status codes: 0=idle, 1=running, 2=paused, 3=alarm, 4=edit
            state_map = {0: "ready", 1: "running", 2: "paused", 3: "error", 4: "edit"}
            state = state_map.get(data.get("run_status", 0), "unknown")

            return {
                "online": True,
                "state": state,
                "position_xyz": {
                    "x": float(data.get("current_position", {}).get("x", 0)),
                    "y": float(data.get("current_position", {}).get("y", 0)),
                    "z": float(data.get("current_position", {}).get("z", 0)),
                },
                "spindle_rpm_current": int(data.get("spindle_speed", 0)),
                "feed_rate_mm_min": float(data.get("feed_rate", 0)),
            }
        except Exception:
            return {"online": False, "state": "error"}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Detailed FANUC machine state."""
        status = await self.get_status()
        tool_id = None
        coolant_active = False

        try:
            # FANUC tool offset / tool change data
            tool_res = await self._client.get(f"{self.base_url}/focas/api/tool")
            if tool_res.status_code == 200:
                tool_data = tool_res.json()
                tool_id = str(tool_data.get("current_tool", ""))

            # Coolant status (via GPIO or M-code state)
            coolant_res = await self._client.get(f"{self.base_url}/focas/api/coolant")
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
        """Send G-code to FANUC (via MDI — Manual Data Input)."""
        if not gcode or not gcode.strip():
            return {"ok": False, "message": "Not connected or empty G-code"}

        try:
            res = await self._client.post(
                f"{self.base_url}/focas/api/mdi",
                json={"gcode": gcode},
            )
            if res.status_code in (200, 201):
                return {
                    "ok": True,
                    "message": "G-code sent to FANUC",
                    "result": res.json(),
                }
            else:
                return {"ok": False, "message": f"FANUC returned {res.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home machine reference point (machine zero) for specified axes.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "message": str, "homing": str}
        """
        try:
            res = await self._client.post(
                f"{self.base_url}/focas/api/home",
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
        whether real FOCAS-gateway deployments take an absolute mm/min
        setpoint (matching this method's parameter name and cnc_adapter.py's
        contract) or a percentage override. Currently treated as an
        already-computed percentage (0-200%), NOT divided by 100 — do not
        wire this to a live route without validating the real bridge's unit
        semantics first.
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
            res = await self._client.post(f"{self.base_url}/focas/api/stop")
            return {
                "ok": res.status_code in (200, 201),
                "message": "Emergency stop activated",
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def list_files(self, path: str = "/") -> list:
        """List G-code/part programs on FANUC machine (if available).

        Args:
            path: Directory path to list

        Returns:
            list of {"name": str, "path": str}
        """
        try:
            res = await self._client.get(
                f"{self.base_url}/focas/api/files",
                params={"path": path},
            )
            if res.status_code == 200:
                files = res.json()
                return files if isinstance(files, list) else []
            return []
        except Exception:
            return []
