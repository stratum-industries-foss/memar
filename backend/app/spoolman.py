"""Spoolman filament management integration — fleet-level spool tracking.

Spoolman is a sidecar service (not per-machine). When configured, MEMAR
fetches active spool data and merges it into printer capability fields.
See: https://github.com/Donkie/Spoolman
"""
from __future__ import annotations

import json

import httpx

from .device_url import assert_safe_device_url


class SpoolmanClient:
    def __init__(self, base_url: str):
        assert_safe_device_url(base_url)  # LAN sidecar: block metadata/link-local, allow RFC1918
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=8,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def get_active_spools(self) -> list[dict]:
        """Returns all active/non-archived spools with filament metadata."""
        r = await self._client.get(
            f"{self.base_url}/api/v1/spool",
            params={"allow_archived": False},
        )
        if r.status_code != 200:
            return []
        spools = r.json()
        result: list[dict] = []
        for s in spools:
            # Skip malformed entries individually — one spool missing "id"
            # must not abort the whole sync and leave every printer's spool
            # weight stale.
            if not isinstance(s, dict) or "id" not in s:
                continue
            filament = s.get("filament") or {}
            result.append({
                "id": s["id"],
                "name": filament.get("name"),
                "material": filament.get("material"),
                "color_hex": filament.get("color_hex"),
                "remaining_weight": s.get("remaining_weight"),
                "printer_name": _extra(s, "printer_name"),
                "printer_id": _extra(s, "printer_id"),
            })
        return result

    async def update_spool_remaining(self, spool_id: int, remaining: float) -> bool:
        """Update spool remaining weight on job complete.

        Args:
            spool_id: Spoolman spool ID
            remaining: Remaining weight in grams

        Returns:
            True if successful, False otherwise
        """
        try:
            r = await self._client.patch(
                f"{self.base_url}/api/v1/spool/{spool_id}",
                json={"remaining_weight": remaining},
            )
            return r.status_code == 200
        except Exception:
            return False

def _extra(spool: dict, key: str) -> str | None:
    """Read a value from Spoolman's `extra` fields.

    Spoolman stores `extra` as a dict {field_name: json_encoded_value}, where
    each value is a JSON string — a text field "voron-1" is stored as the
    literal '"voron-1"' (quotes included). So we must (a) index the dict by
    `key`, not iterate it as a list, and (b) json.loads() the value before
    comparing/returning it, or it never matches a plain printer id.
    """
    extra = spool.get("extra") or {}
    if not isinstance(extra, dict):
        return None
    raw = extra.get(key)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = raw  # tolerate a plain (non-JSON) string, just in case
    return str(value) if value is not None else None
