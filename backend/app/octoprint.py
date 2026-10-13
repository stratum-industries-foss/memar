"""OctoPrint REST API adapter — covers ~30-40% of hobbyist 3D printers."""
from __future__ import annotations

import httpx

from .models import PrinterConfig
from .device_url import assert_safe_device_url


class OctoPrintClient:
    def __init__(self, config: PrinterConfig):
        assert_safe_device_url(config.base_url)  # LAN device: block metadata/link-local, allow RFC1918
        self.base_url = config.base_url.rstrip("/")
        self.api_key = config.api_key or ""
        self._headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_status(self) -> dict:
        printer_r, job_r = await _gather(
                self._client.get(f"{self.base_url}/api/printer", headers=self._headers),
                self._client.get(f"{self.base_url}/api/job", headers=self._headers),
            )
        printer = printer_r.json() if not isinstance(printer_r, Exception) and printer_r.status_code == 200 else {}
        job = job_r.json() if not isinstance(job_r, Exception) and job_r.status_code == 200 else {}
        temps = printer.get("temperature", {})
        tool0 = temps.get("tool0", {})
        bed = temps.get("bed", {})
        progress = job.get("progress", {})
        state = job.get("state", "Offline")
        job_file = job.get("job", {}).get("file", {}).get("name")
        return {
            "online": not _is_offline_state(state),
            "state": _map_state(state),
            "nozzle_temperature": tool0.get("actual"),
            "nozzle_target": tool0.get("target"),
            "bed_temperature": bed.get("actual"),
            "bed_target": bed.get("target"),
            "progress": progress.get("completion"),
            "filename": job_file,
            "eta_seconds": progress.get("printTimeLeft"),
        }

    async def send_command(self, command: str) -> dict:
        r = await self._client.post(
            f"{self.base_url}/api/job",
            headers=self._headers,
            json={"command": command},
        )
        return {"ok": r.status_code in (200, 204)}

    async def list_files(self) -> list[dict]:
        r = await self._client.get(f"{self.base_url}/api/files/local", headers=self._headers)
        if r.status_code != 200:
            return []
        return [
            {"name": f["name"], "path": f["path"], "size": f.get("size", 0)}
            for f in r.json().get("files", [])
            if f.get("type") == "machinecode"
        ]


def _is_offline_state(octo_state: str) -> bool:
    """OctoPrint reports connection loss / errors as COMPOUND strings, e.g.
    "Offline (Error: SerialException)" or "Offline after error". Exact-string
    equality misses those and reports a dead printer as online — match on the
    leading keyword instead.
    """
    low = (octo_state or "").strip().lower()
    return (
        low.startswith("offline")
        or low.startswith("error")
        or low.startswith("closed")
        or "error" in low
    )


def _map_state(octo_state: str) -> str:
    mapping = {
        "Printing": "printing", "Pausing": "printing", "Paused": "paused",
        "Cancelling": "paused", "Operational": "ready", "Finishing": "printing",
        "Error": "error", "Offline": "offline", "Connecting": "offline",
        "Closed": "offline",
    }
    if octo_state in mapping:
        return mapping[octo_state]
    # Compound strings ("Offline (Error: ...)", "Offline after error") never
    # match the exact keys above; classify by leading keyword so a dead printer
    # is not silently defaulted to "idle".
    low = (octo_state or "").strip().lower()
    if low.startswith("offline") or low.startswith("closed"):
        return "offline"
    if low.startswith("error") or "error" in low:
        return "error"
    if low.startswith("printing") or low.startswith("finishing") or low.startswith("pausing"):
        return "printing"
    if low.startswith("paused") or low.startswith("cancelling"):
        return "paused"
    if low.startswith("operational"):
        return "ready"
    return "idle"


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros, return_exceptions=True)
