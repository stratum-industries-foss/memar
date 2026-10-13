"""Prusa Connect cloud REST adapter — Prusa MK4, XL, Mini+ fleet management."""
from __future__ import annotations

import httpx

from .models import PrinterConfig

PRUSA_CONNECT_BASE = "https://connect.prusa3d.com/api/v2"


class PrusaConnectClient:
    """Polls Prusa Connect cloud API for printer fleet status.
    Requires a Prusa Connect API token (api_key field in PrinterConfig).
    The printer_id is passed as base_url (UUID from Prusa Connect).
    """

    def __init__(self, config: PrinterConfig):
        self.printer_uuid = config.base_url.strip("/").split("/")[-1]
        self.token = config.api_key or ""
        self._headers = {"Authorization": f"Bearer {self.token}"}
        self._client = httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_status(self) -> dict:
        r = await self._client.get(
            f"{PRUSA_CONNECT_BASE}/printer/{self.printer_uuid}",
            headers=self._headers,
        )
        if r.status_code != 200:
            return {"online": False, "state": "offline"}
        data = r.json()
        telemetry = data.get("telemetry", {})
        job = data.get("job", {}) or {}
        conn = data.get("connect", {})
        return {
            "online": conn.get("online", False),
            "state": _map_state(data.get("printer_state", "IDLE")),
            "nozzle_temperature": telemetry.get("temp_nozzle"),
            "nozzle_target": telemetry.get("target_nozzle"),
            "bed_temperature": telemetry.get("temp_bed"),
            "bed_target": telemetry.get("target_bed"),
            "progress": job.get("progress"),
            "filename": job.get("file", {}).get("name") if job.get("file") else None,
            "eta_seconds": job.get("time_remaining"),
            "spool_remaining_g": telemetry.get("filament_remaining"),
        }

    async def list_printers(self) -> list[dict]:
        """Fetch all printers for this account — useful for initial setup."""
        r = await self._client.get(
            f"{PRUSA_CONNECT_BASE}/printers",
            headers=self._headers,
        )
        if r.status_code != 200:
            return []
        return [
            {"id": p["uuid"], "name": p.get("name", p["uuid"]), "state": p.get("printer_state")}
            for p in r.json().get("printers", [])
        ]


def _map_state(s: str) -> str:
    return {"PRINTING": "printing", "PAUSED": "paused", "IDLE": "ready",
            "FINISHED": "ready", "STOPPED": "paused", "ERROR": "error",
            "ATTENTION": "error", "BUSY": "printing", "OFFLINE": "offline"}.get(s, "idle")
