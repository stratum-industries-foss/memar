"""
MACH4 CNC Controller HTTP adapter.

MACH4 runs on Windows and exposes a REST API (http://localhost:4444 by default).
Supports spindle control, coolant, tool changes, and position monitoring.
Endpoints are rooted at /api/* on the controller's REST bridge.
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus


class MACH4Adapter(CNCAdapter):
    """MACH4 CNC controller adapter (Windows-based industrial CNC)."""

    def __init__(self, config: PrinterConfig):
        """Initialize MACH4 client.

        Args:
            config: PrinterConfig with base_url (e.g., "http://localhost:4444")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to MACH4 REST API."""
        try:
            res = await self._client.get(f"{self.base_url}/api/version")
            if res.status_code == 200:
                data = res.json()
                return {
                    "ok": True,
                    "message": f"Connected to MACH4 v{data.get('version', '?')}",
                    "state": "ready",
                }
            else:
                return {
                    "ok": False,
                    "message": f"MACH4 REST API returned {res.status_code}",
                    "state": "error",
                }
        except Exception as e:
            return {"ok": False, "message": str(e), "state": "offline"}

    async def disconnect(self) -> dict:
        """Close MACH4 connection."""
        try:
            await self._client.aclose()
        except Exception:
            pass
        return {"ok": True, "message": "Disconnected"}

    async def get_status(self) -> dict:
        """Poll MACH4 DRO (Digital Readout) and spindle status."""
        try:
            res = await self._client.get(f"{self.base_url}/api/position")
            if res.status_code != 200:
                return {"online": False, "state": "error"}

            pos = res.json()
            spindle_res = await self._client.get(f"{self.base_url}/api/spindle")
            spindle = spindle_res.json() if spindle_res.status_code == 200 else {}
            return {
                "online": True,
                "state": pos.get("state", "idle"),
                "position_xyz": {
                    "x": float(pos.get("x", 0)),
                    "y": float(pos.get("y", 0)),
                    "z": float(pos.get("z", 0)),
                },
                "spindle_rpm_current": int(spindle.get("rpm", 0)),
                "feed_rate_mm_min": float(spindle.get("feedrate", 0)),
            }
        except Exception:
            return {"online": False, "state": "error"}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Detailed MACH4 machine state (position, spindle, coolant, tool)."""
        status = await self.get_status()
        tool_id = None
        coolant_active = False

        try:
            tool_res = await self._client.get(f"{self.base_url}/api/tool")
            if tool_res.status_code == 200:
                tool_data = tool_res.json()
                raw_tool_id = tool_data.get("id")
                tool_id = str(raw_tool_id) if raw_tool_id is not None else None

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
        """Send G-code to MACH4 (MDI — Manual Data Input)."""
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
                    "message": "G-code queued",
                    "result": res.json(),
                }
            else:
                return {"ok": False, "message": f"MACH4 returned {res.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home specified axes (X, Y, Z, A, B, C, or any combination).

        MACH4 homes each axis individually.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "message": str, "homing": str}
        """
        try:
            all_ok = True
            for axis in axes.upper():
                res = await self._client.post(
                    f"{self.base_url}/api/home",
                    json={"axis": axis},
                )
                if res.status_code not in (200, 201):
                    all_ok = False
            return {
                "ok": all_ok,
                "message": f"Homed {axes}" if all_ok else f"Failed to home one or more axes ({axes})",
                "homing": axes,
            }
        except Exception as e:
            return {"ok": False, "message": str(e), "homing": axes}

    async def set_feed_rate(self, feed_mm_min: float) -> dict:
        """Override feed rate (override %, 0-200).

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
        """List G-code files on MACH4 (if available).

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
