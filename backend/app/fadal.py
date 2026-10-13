"""
Fadal CNC Machine adapter.

Fadal industrial VMCs (Vertical Machining Centers) expose status via:
1. Serial port RS-232 (classic protocol)
2. Ethernet gateway (if retrofitted)
3. DNC network protocol

This adapter targets the Ethernet gateway / DNC bridge (HTTP), with
endpoints rooted at the base URL (e.g., http://192.168.1.200:4001/status).
Fadal machines are older, so this adapter includes fallback error handling.
"""
from __future__ import annotations

import httpx
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus


class FadalAdapter(CNCAdapter):
    """Fadal industrial CNC machine adapter."""

    def __init__(self, config: PrinterConfig):
        """Initialize Fadal client.

        Args:
            config: PrinterConfig with base_url pointing at the DNC/Ethernet
                gateway (e.g., "http://192.168.1.200:4001")
        """
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        """Test connection to Fadal DNC gateway."""
        try:
            res = await self._client.get(f"{self.base_url}/status")
            if res.status_code == 200:
                data = res.json()
                return {
                    "ok": True,
                    "message": f"Connected to Fadal {data.get('model', 'VMC')}",
                    "state": "ready",
                }
            else:
                return {
                    "ok": False,
                    "message": f"Fadal DNC returned {res.status_code}",
                    "state": "error",
                }
        except Exception as e:
            return {"ok": False, "message": str(e), "state": "offline"}

    async def disconnect(self) -> dict:
        """Close Fadal connection."""
        try:
            await self._client.aclose()
        except Exception:
            pass
        return {"ok": True, "message": "Disconnected"}

    async def get_status(self) -> dict:
        """Poll Fadal machine status."""
        try:
            res = await self._client.get(f"{self.base_url}/status")
            if res.status_code != 200:
                return {"online": False, "state": "error"}

            data = res.json()
            # Fadal status: idle, running, paused, alarm, offline
            state = data.get("state", "idle")

            return {
                "online": True,
                "state": state,
                "position_xyz": {
                    "x": float(data.get("x_position", 0)),
                    "y": float(data.get("y_position", 0)),
                    "z": float(data.get("z_position", 0)),
                },
                "spindle_rpm_current": int(data.get("spindle_rpm", 0)),
                # Fadal DNC reports feed in inches/min; convert to mm/min (the
                # canonical unit for this field, consumed by CNCMetricsLog +
                # cnc_metrics avg/max_feed_rate_mm_min). 1 in = 25.4 mm.
                "feed_rate_mm_min": float(data.get("feed_rate_in_min", 0)) * 25.4,
            }
        except Exception:
            return {"online": False, "state": "error"}

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Detailed Fadal machine state."""
        status = await self.get_status()
        tool_id = None
        coolant_active = False

        try:
            # Fadal tool changer status
            tool_res = await self._client.get(f"{self.base_url}/tool")
            if tool_res.status_code == 200:
                tool_data = tool_res.json()
                tool_id = str(tool_data.get("current_tool", ""))

            # Coolant status (M7/M8/M9 commands)
            coolant_res = await self._client.get(f"{self.base_url}/coolant")
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
        """Send G-code to Fadal (via DNC command queue)."""
        if not gcode or not gcode.strip():
            return {"ok": False, "message": "Not connected or empty G-code"}

        try:
            res = await self._client.post(
                f"{self.base_url}/mdi",
                json={"gcode": gcode},
            )
            if res.status_code in (200, 201):
                return {
                    "ok": True,
                    "message": "G-code queued on Fadal",
                    "result": res.json(),
                }
            else:
                return {"ok": False, "message": f"Fadal returned {res.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def home_axes(self, axes: str = "XYZ") -> dict:
        """Home machine zero for specified axes.

        Args:
            axes: Axes to home (e.g., "X", "XY", "XYZ")

        Returns:
            {"ok": bool, "message": str, "homing": str}
        """
        try:
            res = await self._client.post(
                f"{self.base_url}/home",
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
            res = await self._client.post(f"{self.base_url}/stop")
            return {
                "ok": res.status_code in (200, 201),
                "message": "Emergency stop activated",
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    async def list_files(self, path: str = "/") -> list:
        """List G-code/DNC files on Fadal machine (if available).

        Args:
            path: Directory path to list

        Returns:
            list of {"name": str, "path": str}
        """
        try:
            res = await self._client.get(
                f"{self.base_url}/files",
                params={"path": path},
            )
            if res.status_code == 200:
                files = res.json()
                return files if isinstance(files, list) else []
            return []
        except Exception:
            return []
