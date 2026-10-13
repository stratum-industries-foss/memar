"""FluidNC REST adapter — modern GRBL successor (ESP32), covers CNC routers and lasers."""
from __future__ import annotations

import httpx

from .cnc_adapter import CNCAdapter, CNCAdapterStatus
from .models import PrinterConfig


class FluidNCClient(CNCAdapter):
    """FluidNC HTTP API at /api/* — much cleaner than serial GRBL.

    FluidNC speaks the same G-code/realtime-byte language as GRBL, just over
    an HTTP POST to /api/command instead of a raw serial/TCP stream — same
    reliability class as GRBLClient's http:// mode, which this mirrors.
    """

    def __init__(self, config: PrinterConfig):
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def connect(self) -> dict:
        status = await self.get_status()
        return {
            "ok": status.get("online", False),
            "message": "Connected to FluidNC" if status.get("online") else "Failed to connect",
            "state": status.get("state", "offline"),
        }

    async def disconnect(self) -> dict:
        try:
            await self._client.aclose()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_status(self) -> dict:
        r = await self._client.get(f"{self.base_url}/api/status")
        if r.status_code != 200:
            return {"online": False, "state": "offline"}
        data = r.json()
        state = data.get("state", "Idle")
        pos = data.get("wpos", {}) or {}
        speed = data.get("feed", 0)
        spindle = data.get("spindle", 0)
        return {
            "online": True,
            "state": _map_state(state),
            "spindle_rpm_current": _to_int(spindle),
            "feed_rate_mm_min": _to_float(speed),
            "position_xyz": {
                "x": _to_float(pos.get("x", 0)),
                "y": _to_float(pos.get("y", 0)),
                "z": _to_float(pos.get("z", 0)),
            },
            "filename": data.get("file"),
            "progress": data.get("progress"),
        }

    async def run_gcode(self, gcode: str) -> dict:
        r = await self._client.post(
                f"{self.base_url}/api/command",
                json={"gcode": gcode},
            )
        return {"ok": r.status_code == 200, "response": r.text}

    async def list_files(self, path: str = "/") -> list[dict]:
        r = await self._client.get(f"{self.base_url}/api/files")
        if r.status_code != 200:
            return []
        return [
            {"name": f["name"], "path": f.get("path", f["name"]), "size": f.get("size", 0)}
            for f in r.json().get("files", [])
        ]

    async def home(self) -> dict:
        return await self.run_gcode("$H")

    async def spindle_on(self, rpm: int = 12000) -> dict:
        return await self.run_gcode(f"M3 S{rpm}")

    async def spindle_off(self) -> dict:
        return await self.run_gcode("M5")

    # ── CNCAdapter contract (cnc_routes.py dispatches through these) ────────

    async def get_machine_state(self) -> CNCAdapterStatus:
        """Conforms to the CNCAdapter contract — see GRBLClient's identical wrapper."""
        status = await self.get_status()
        if not status.get("online"):
            return CNCAdapterStatus(online=False, state="offline")
        return CNCAdapterStatus(
            online=True,
            state=status.get("state") or "offline",
            position_xyz=status.get("position_xyz") or {"x": 0.0, "y": 0.0, "z": 0.0},
            feed_rate_mm_min=status.get("feed_rate_mm_min"),
            spindle_rpm_current=status.get("spindle_rpm_current"),
        )

    async def send_gcode(self, gcode: str) -> dict:
        return await self.run_gcode(gcode)

    async def home_axes(self, axes: str = "XYZ") -> dict:
        result = await self.home()
        return {"ok": result.get("ok", False), "response": result.get("response", "")}

    async def set_feed_rate(self, rate_mm_min: float) -> dict:
        result = await self.run_gcode(f"F{rate_mm_min}")
        return {"ok": result.get("ok", False), "new_rate_mm_min": rate_mm_min if result.get("ok") else None}

    async def emergency_stop(self) -> dict:
        """Realtime soft-reset (Ctrl-X / 0x18) — identical command GRBLClient
        sends for the same purpose, just relayed through FluidNC's HTTP
        /api/command endpoint instead of a raw serial/TCP stream."""
        try:
            result = await self.run_gcode("\x18")  # Ctrl-X
            ok = result.get("ok", False)
            return {"ok": ok, "state": "error" if ok else "unknown"}
        except Exception as e:
            return {"ok": False, "error": str(e), "state": "unknown"}


def _to_float(v, default: float = 0.0) -> float:
    """Coerce to float, tolerating None (device sends null feed/spindle at idle)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v, default: int = 0) -> int:
    """Coerce to int, tolerating None / float strings without crashing."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _map_state(s: str) -> str:
    return {"Idle": "ready", "Run": "printing", "Hold:0": "paused", "Hold:1": "paused",
            "Jog": "printing", "Alarm": "error", "Door:0": "paused", "Check": "ready",
            "Home": "printing", "Sleep": "offline"}.get(s, "idle")
