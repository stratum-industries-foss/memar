"""OpenPnP REST adapter — pick-and-place SMD assembly machines."""
from __future__ import annotations

import httpx

from .models import PrinterConfig


class OpenPnPClient:
    """OpenPnP exposes a REST API on port 8080 (configurable).
    Machine state, job progress, head/nozzle positions all available.
    """

    def __init__(self, config: PrinterConfig):
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_status(self) -> dict:
        machine_r, job_r = await _gather(
            self._client.get(f"{self.base_url}/api/machine"),
            self._client.get(f"{self.base_url}/api/job"),
        )
        machine = machine_r.json() if not isinstance(machine_r, Exception) and machine_r.status_code == 200 else {}
        job = job_r.json() if not isinstance(job_r, Exception) and job_r.status_code == 200 else {}

        state = machine.get("state", "Disconnected")
        head = machine.get("heads", [{}])[0] if machine.get("heads") else {}
        pos = head.get("position", {})

        return {
            "online": state not in ("Disconnected", "Error"),
            "state": _map_state(state),
            "position_xyz": {
                "x": float(pos.get("x", 0)),
                "y": float(pos.get("y", 0)),
                "z": float(pos.get("z", 0)),
            },
            "progress": job.get("completionRatio") and round(job["completionRatio"] * 100, 1),
            "filename": job.get("boardName"),
            "feeder_count": len(machine.get("feeders", [])),
            "vision_errors": job.get("visionErrors", 0),
        }

    async def home(self) -> dict:
        r = await self._client.put(f"{self.base_url}/api/machine/home", timeout=15.0)
        return {"ok": r.status_code == 200}

    async def start_job(self) -> dict:
        r = await self._client.post(f"{self.base_url}/api/job/start")
        return {"ok": r.status_code == 200}

    async def pause_job(self) -> dict:
        r = await self._client.post(f"{self.base_url}/api/job/pause")
        return {"ok": r.status_code == 200}


def _map_state(s: str) -> str:
    return {"Homing": "printing", "Running": "printing", "Paused": "paused",
            "Stopped": "ready", "Homed": "ready", "Disconnected": "offline",
            "Error": "error"}.get(s, "idle")


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros, return_exceptions=True)
