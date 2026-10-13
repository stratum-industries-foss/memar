"""LinuxCNC REST adapter for MEMAR.

LinuxCNC is an open-source CNC control system. This adapter assumes
a REST bridge providing JSON endpoints (e.g., linuxcnc-rest or custom wrapper).

Assume REST API on localhost:5000 or configured base_url:
- GET /status → machine state, position, feed rate, spindle speed, tool, coolant
- POST /command/mdi → MDI (Manual Data Input) G-code execution
- POST /command/home → axis homing
- GET /files → file listing
- POST /command/estop → emergency stop
- PUT /motion/feedrate → feed rate adjustment

State mapping:
  "on" → "ready"
  "off" → "offline"
  "estop" → "error"
  "auto" → "printing" (running a file)
  "mdi" → "printing" (MDI mode)
  "manual" → "ready"
  "jog" → "printing"
  other → "idle"
"""
from __future__ import annotations

import asyncio
import httpx
from pydantic import BaseModel, Field
from .models import PrinterConfig
from .cnc_adapter import CNCAdapter, CNCAdapterStatus


# ── Pydantic Response Models ──────────────────────────────────────────────────

class Position(BaseModel):
    """3D position (XYZ coordinates)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class MachineStatus(BaseModel):
    """Complete machine status response."""
    online: bool = True
    state: str = "idle"  # "idle", "ready", "printing", "paused", "error", "offline"
    position_xyz: Position = Field(default_factory=Position)
    feed_rate_mm_min: float | None = None
    spindle_rpm_current: int | None = None
    coolant_active: bool = False
    tool_id: str | None = None
    filename: str | None = None
    progress: float | None = None


class GCodeResponse(BaseModel):
    """Response from G-code execution."""
    ok: bool = True
    response: str = ""
    error_msg: str | None = None


class FeedRateResponse(BaseModel):
    """Response from feed rate adjustment."""
    ok: bool = True
    new_rate_mm_min: float | None = None


class EmergencyStopResponse(BaseModel):
    """Response from emergency stop."""
    ok: bool = True
    state: str = "estop"  # Machine should be in estop state


_STATE_MAP = {
    "on": "ready",
    "off": "offline",
    "estop": "error",
    "estop_reset": "ready",
    "auto": "printing",
    "mdi": "printing",
    "manual": "ready",
    "jog": "printing",
}


class LinuxCNCClient(CNCAdapter):
    """HTTP/JSON client for LinuxCNC REST adapter."""

    def __init__(self, config: PrinterConfig):
        """Initialize with PrinterConfig pointing to LinuxCNC REST API."""
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
        self._connection_failed = False

    async def connect(self) -> dict:
        """Verify connection to LinuxCNC REST bridge."""
        try:
            r = await self._client.get(f"{self.base_url}/status", timeout=3)
            if r.status_code == 200:
                self._connection_failed = False
                return {"ok": True, "message": "Connected to LinuxCNC"}
            else:
                self._connection_failed = True
                return {"ok": False, "message": f"HTTP {r.status_code} from {self.base_url}"}
        except Exception as e:
            self._connection_failed = True
            return {"ok": False, "message": f"Connection failed: {e}"}

    async def disconnect(self) -> dict:
        """Close connection and cleanup."""
        try:
            await self._client.aclose()
            return {"ok": True, "message": "Disconnected from LinuxCNC"}
        except Exception as e:
            return {"ok": False, "message": f"Disconnect error: {e}"}

    async def get_status(self) -> dict:
        """CNCAdapter protocol: minimal status (state, position, spindle)."""
        status = await self.get_machine_state()
        return {
            "online": status.online,
            "state": status.state,
            "position_xyz": {
                "x": status.position_xyz.x,
                "y": status.position_xyz.y,
                "z": status.position_xyz.z,
            },
            "feed_rate_mm_min": status.feed_rate_mm_min,
            "spindle_rpm_current": status.spindle_rpm_current,
        }

    async def get_machine_state(self) -> MachineStatus:
        """Poll current machine state (position, spindle, coolant, tool, filename)."""
        try:
            r = await self._client.get(f"{self.base_url}/status", timeout=3)
            if r.status_code != 200:
                return MachineStatus(online=False, state="offline")

            data = r.json()
            task = data.get("task", {})
            motion = data.get("motion", {})
            io = data.get("io", {})

            task_state = task.get("task_state", "")
            state = _STATE_MAP.get(task_state, "idle")

            pos = motion.get("position", {})
            position_xyz = Position(
                x=float(pos.get("x", 0)),
                y=float(pos.get("y", 0)),
                z=float(pos.get("z", 0)),
            )

            # Feed rate: assume mm/min (standard G-code unit)
            # Some systems report in mm/s; conversion is optional and not recommended
            # without explicit configuration. Assume the REST API returns mm/min.
            feed_rate = motion.get("current_vel", 0)
            if isinstance(feed_rate, (int, float)):
                feed_rate = float(feed_rate)
            else:
                feed_rate = 0.0

            spindle_rpm = int(motion.get("spindle_speed", 0))

            coolant_active = False
            coolant = io.get("coolant", {})
            if isinstance(coolant, dict):
                coolant_active = coolant.get("mist", False) or coolant.get("flood", False)
            elif isinstance(coolant, bool):
                coolant_active = coolant

            return MachineStatus(
                online=True,
                state=state,
                position_xyz=position_xyz,
                feed_rate_mm_min=feed_rate,
                spindle_rpm_current=spindle_rpm,
                coolant_active=coolant_active,
                tool_id=str(io.get("tool_in_spindle", "")),
                filename=task.get("file"),
                progress=task.get("progress"),
            )
        except Exception as e:
            return MachineStatus(
                online=False,
                state="error",
                filename=f"Error: {e}",
            )

    async def get_position(self) -> Position:
        """Get current XYZ position only (shorthand for get_machine_state)."""
        status = await self.get_machine_state()
        return status.position_xyz

    async def send_gcode(self, gcode: str) -> GCodeResponse:
        """Send G-code command via MDI (Manual Data Input)."""
        if not gcode or not gcode.strip():
            return GCodeResponse(ok=False, error_msg="Empty G-code command")

        # Sanitize: reject commands starting with '-' to prevent flag injection
        if gcode.strip().startswith("-"):
            return GCodeResponse(ok=False, error_msg="G-code cannot start with '-'")

        try:
            r = await self._client.post(
                f"{self.base_url}/command/mdi",
                json={"command": gcode.strip()},
                timeout=5,
            )

            if r.status_code == 200:
                return GCodeResponse(
                    ok=True,
                    response=r.json().get("result", ""),
                )
            else:
                return GCodeResponse(
                    ok=False,
                    error_msg=f"HTTP {r.status_code}: {r.text[:200]}",
                )
        except asyncio.TimeoutError:
            return GCodeResponse(ok=False, error_msg="G-code execution timeout (>5s)")
        except Exception as e:
            return GCodeResponse(ok=False, error_msg=f"Request error: {e}")

    async def set_feed_rate(self, rate_mm_min: float) -> FeedRateResponse:
        """Set feed rate override (feed rate as mm/min)."""
        if rate_mm_min < 0:
            return FeedRateResponse(ok=False)

        try:
            r = await self._client.put(
                f"{self.base_url}/motion/feedrate",
                json={"feedrate_mm_min": rate_mm_min},
                timeout=3,
            )

            if r.status_code == 200:
                return FeedRateResponse(
                    ok=True,
                    new_rate_mm_min=rate_mm_min,
                )
            else:
                return FeedRateResponse(ok=False)
        except Exception:
            return FeedRateResponse(ok=False)

    async def emergency_stop(self) -> EmergencyStopResponse:
        """Trigger emergency stop (ESTOP)."""
        try:
            r = await self._client.post(
                f"{self.base_url}/command/estop",
                json={},
                timeout=2,
            )

            if r.status_code == 200:
                return EmergencyStopResponse(ok=True, state="estop")
            else:
                return EmergencyStopResponse(ok=False)
        except Exception:
            return EmergencyStopResponse(ok=False)

    _VALID_AXES = set("XYZABCUV")

    async def home_axes(self, axes: str = "XYZ") -> GCodeResponse:
        """Home one or more axes.

        Tries the dedicated /command/home REST endpoint first; on failure
        (non-200 response or network/exception error) falls back to sending
        a G28 G-code command via send_gcode().
        """
        axes_upper = (axes or "XYZ").strip().upper()
        if not axes_upper or any(ch not in self._VALID_AXES for ch in axes_upper):
            return GCodeResponse(ok=False, error_msg=f"Invalid axis: {axes}")

        try:
            r = await self._client.post(
                f"{self.base_url}/command/home",
                json={"axes": axes_upper},
                timeout=10,
            )

            if r.status_code == 200:
                return GCodeResponse(
                    ok=True,
                    response=r.json().get("result", f"Homing {axes_upper}"),
                )
            return await self.send_gcode(f"G28 {' '.join(axes_upper)}")
        except Exception:
            return await self.send_gcode(f"G28 {' '.join(axes_upper)}")

    async def home_axis(self, axis: str = "XYZ") -> GCodeResponse:
        """Home one or more axes. Deprecated: use home_axes()."""
        return await self.home_axes(axes=axis or "XYZ")

    async def list_files(self, path: str = "/") -> list:
        """List G-code files in the specified directory."""
        try:
            r = await self._client.get(
                f"{self.base_url}/files",
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
