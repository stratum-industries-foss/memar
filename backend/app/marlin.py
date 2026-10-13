"""Marlin firmware adapter.

Marlin itself has no network API — this adapter targets the two most
common WiFi bridges used with Marlin printers:

1. ESP3D (ESP8266/ESP32 module) — simple HTTP API, very widespread
   Used by: Creality boards with WiFi, custom ESP3D setups
   URL: http://printer_ip/command?commandText=M105

2. Repetier Server — REST API, wraps Marlin serial connection
   URL: http://host:3344/printer/api/{slug}

Set config.api_key = "esp3d" | "repetier" to select mode.
Repetier also requires api_key = "repetier:{api_token}".
"""
from __future__ import annotations

import httpx

from .models import PrinterConfig


class MarlinClient:
    def __init__(self, config: PrinterConfig):
        self.base_url = config.base_url.rstrip("/")
        raw_key = config.api_key or "esp3d"
        if raw_key.startswith("repetier:"):
            self._mode = "repetier"
            self._api_key = raw_key.split(":", 1)[1]
        else:
            self._mode = "esp3d"
            self._api_key = ""
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_status(self) -> dict:
        if self._mode == "repetier":
            return await self._repetier_status()
        return await self._esp3d_status()

    # ── ESP3D ────────────────────────────────────────────────────────────────

    async def _esp3d_status(self) -> dict:
        """Query temperatures and print status via ESP3D HTTP API."""
        temp_r = await self._client.get(
                f"{self.base_url}/command",
                params={"commandText": "M105"},
            )
        job_r = await self._client.get(
                f"{self.base_url}/command",
                params={"commandText": "M27"},  # SD print status
            )
        temps = _parse_m105(temp_r.text if temp_r.status_code == 200 else "")
        job = _parse_m27(job_r.text if job_r.status_code == 200 else "")
        return {
            "online": temp_r.status_code == 200,
            "state": "printing" if job.get("printing") else "ready",
            "nozzle_temperature": temps.get("T0_current"),
            "nozzle_target": temps.get("T0_target"),
            "bed_temperature": temps.get("B_current"),
            "bed_target": temps.get("B_target"),
            "progress": job.get("progress"),
        }

    # ── Repetier Server ──────────────────────────────────────────────────────

    async def _repetier_status(self) -> dict:
        """Repetier Server REST API — wraps one or more Marlin printers.

        Two calls against the server root:
          * a=listPrinter → array of printer objects: online / job (filename) / slug.
          * a=stateList   → dict keyed by slug → temperatures (extruder[], heatedBed).
        `base_url` is the Repetier Server ROOT (e.g. http://host:3344). The printer
        slug is the last path segment of base_url, or "default".
        """
        from urllib.parse import urlsplit, urlunsplit

        headers = {"X-Api-Key": self._api_key}
        parts = urlsplit(self.base_url)
        segments = [s for s in parts.path.split("/") if s]
        slug = segments[-1] if segments else "default"
        server_root = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        api_url = f"{server_root}/printer/api/{slug}"

        lp = await self._client.get(api_url, headers=headers, params={"a": "listPrinter"})
        sl = await self._client.get(api_url, headers=headers, params={"a": "stateList"})
        if lp.status_code != 200 and sl.status_code != 200:
            return {"online": False, "state": "offline"}

        printers = lp.json() if lp.status_code == 200 else []
        if not isinstance(printers, list):
            printers = []
        info = next(
            (p for p in printers if isinstance(p, dict) and p.get("slug") == slug),
            printers[0] if printers else {},
        )
        if not isinstance(info, dict):
            info = {}

        states = sl.json() if sl.status_code == 200 else {}
        state: dict = {}
        if isinstance(states, dict):
            picked = states.get(slug)
            if picked is None:
                picked = next(iter(states.values()), {})
            if isinstance(picked, dict):
                state = picked

        extruders = state.get("extruder") or [{}]
        nozzle = extruders[0] if isinstance(extruders, list) and extruders else {}
        bed = state.get("heatedBed")
        if isinstance(bed, list):
            bed = bed[0] if bed else {}
        if not isinstance(bed, dict):
            # Some Repetier versions expose beds as a `heatedBeds` array instead.
            beds = state.get("heatedBeds") or [{}]
            bed = beds[0] if isinstance(beds, list) and beds else {}

        job_name = info.get("job")
        printing = bool(job_name) and job_name != "none"
        done = info.get("done")  # progress %, best-effort (present on active jobs)
        print_time = info.get("printTime")
        eta = None
        if printing and print_time and done is not None:
            eta = max(0.0, print_time * (1 - (done / 100.0)))

        return {
            "online": bool(info.get("online")),
            "state": "printing" if printing else "ready",
            "nozzle_temperature": nozzle.get("tempRead"),
            "nozzle_target": nozzle.get("tempSet"),
            "bed_temperature": bed.get("tempRead"),
            "bed_target": bed.get("tempSet"),
            "progress": done,
            "filename": job_name if printing else None,
            "eta_seconds": eta,
        }


# ── G-code response parsers ──────────────────────────────────────────────────

def _parse_m105(response: str) -> dict:
    """Parse Marlin M105 temperature response.
    Example: ok T:210.3 /215.0 B:60.1 /60.0 @:64 B@:7
    """
    import re
    result: dict = {}
    for match in re.finditer(r"T(\d*):([0-9.]+)\s*/([0-9.]+)", response):
        idx = match.group(1) or "0"
        result[f"T{idx}_current"] = float(match.group(2))
        result[f"T{idx}_target"] = float(match.group(3))
    for match in re.finditer(r"B:([0-9.]+)\s*/([0-9.]+)", response):
        result["B_current"] = float(match.group(1))
        result["B_target"] = float(match.group(2))
    return result


def _parse_m27(response: str) -> dict:
    """Parse Marlin M27 SD print status.
    Examples:
      SD printing byte 12345/98765   → progress = 12.5
      Not SD printing
    """
    import re
    if "Not SD printing" in response or "No SD card" in response:
        return {"printing": False}
    match = re.search(r"byte (\d+)/(\d+)", response)
    if match:
        pos, total = int(match.group(1)), int(match.group(2))
        progress = round(pos / total * 100, 1) if total > 0 else 0
        return {"printing": True, "progress": progress}
    return {"printing": False}
