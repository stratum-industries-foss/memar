"""Duet/RepRapFirmware REST adapter — Duet 2/3 boards, Prusa MK4/XL."""
from __future__ import annotations

import httpx

from .models import PrinterConfig
from .device_url import assert_safe_device_url


class DuetClient:
    """Supports both DSF (Duet Software Framework, /machine/status) and
    legacy RRF2 (/rr_status?type=3) endpoints."""

    def __init__(self, config: PrinterConfig):
        assert_safe_device_url(config.base_url)  # LAN device: block metadata/link-local, allow RFC1918
        self.base_url = config.base_url.rstrip("/")
        self.password = config.api_key or "reprap"
        self._dsf = None  # detected on first call
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_status(self) -> dict:
        # Try DSF first (Duet 3 / newer firmware)
        r = await self._client.get(f"{self.base_url}/machine/status", timeout=5)
        if r.status_code == 200:
            self._dsf = True
            return self._parse_dsf(r.json())
        # Fall back to RRF2 legacy
        r = await self._client.get(
            f"{self.base_url}/rr_status",
            params={"type": "3", "password": self.password},
            timeout=5,
        )
        if r.status_code == 200:
            self._dsf = False
            return self._parse_rrf2(r.json())
        return {"online": False, "state": "offline"}

    def _parse_dsf(self, data: dict) -> dict:
        heat = data.get("heat", {})
        heaters = heat.get("heaters", [])
        job = data.get("job", {})
        state = data.get("state", {}).get("status", "idle")
        nozzle = heaters[1] if len(heaters) > 1 else {}
        bed = heaters[0] if heaters else {}
        return {
            "online": state not in ("off", "disconnected"),
            "state": _map_dsf_state(state),
            "nozzle_temperature": nozzle.get("current"),
            "nozzle_target": nozzle.get("active"),
            "bed_temperature": bed.get("current"),
            "bed_target": bed.get("active"),
            "progress": job.get("filePosition") and job.get("file", {}).get("size") and
                        round(job["filePosition"] / job["file"]["size"] * 100, 1),
            "filename": job.get("file", {}).get("fileName"),
        }

    def _parse_rrf2(self, data: dict) -> dict:
        temps = data.get("temps", {})
        state = data.get("status", "I")
        return {
            "online": state not in ("H", "F", "O"),
            "state": _map_rrf2_state(state),
            "nozzle_temperature": temps.get("tools", [{}])[0].get("active", [None])[0]
                if temps.get("tools") else None,
            "nozzle_target": temps.get("tools", [{}])[0].get("standby", [None])[0]
                if temps.get("tools") else None,
            "bed_temperature": temps.get("bed", {}).get("current"),
            "bed_target": temps.get("bed", {}).get("active"),
            "progress": data.get("fractionPrinted"),
            "filename": data.get("name"),
        }

    async def send_gcode(self, gcode: str) -> dict:
        if self._dsf:
            r = await self._client.post(
                f"{self.base_url}/machine/code", content=gcode,
                headers={"Content-Type": "text/plain"},
            )
        else:
            r = await self._client.get(
                f"{self.base_url}/rr_gcode", params={"gcode": gcode}
            )
        return {"ok": r.status_code == 200}


def _map_dsf_state(s: str) -> str:
    return {"idle": "ready", "processing": "printing", "paused": "paused",
            "pausing": "paused", "resuming": "printing", "halted": "error",
            "cancelling": "paused"}.get(s, "idle")


def _map_rrf2_state(s: str) -> str:
    return {"I": "ready", "P": "printing", "S": "paused", "R": "printing",
            "A": "paused", "H": "error", "F": "error", "D": "paused",
            "T": "printing", "B": "printing"}.get(s, "idle")
