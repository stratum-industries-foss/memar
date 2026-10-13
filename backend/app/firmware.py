"""Firmware management and versioning."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class FirmwareManager:
    """Read firmware state from Moonraker and Klipper."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=5)

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> "FirmwareManager":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def get_firmware_state(self) -> dict:
        """Fetch current firmware versions from Moonraker."""
        try:
            response = await self._client.get(
                f"{self.base_url}/machine/update/status"
            )
            if response.status_code == 200:
                data = response.json()
                return self._parse_update_status(data.get("result", {}))
        except Exception as e:
            logger.error(f"Failed to fetch firmware state: {e}")

        return {
            "components": [],
            "mcu_board": None,
            "mcu_firmware": None,
            "update_available": False,
        }

    def _parse_update_status(self, result: dict) -> dict:
        """Parse Moonraker's update/status response into firmware state."""
        components = []
        update_available = False

        # Parse version_info correctly - commits_behind is a list of commit SHAs
        version_info = result.get("version_info", {})

        # Parse klipper
        klipper = version_info.get("klipper", {})
        if klipper:
            commits_behind_list = klipper.get("commits_behind", [])
            commits_behind = len(commits_behind_list) if isinstance(commits_behind_list, list) else 0
            components.append({
                "name": "klipper",
                "version": klipper.get("version", "unknown"),
                "branch": klipper.get("branch"),
                "commits_behind": commits_behind,
                "is_dirty": klipper.get("is_dirty", False),
                "git_hash": klipper.get("git_hash", "unknown"),
            })
            if commits_behind > 0:
                update_available = True

        # Parse moonraker
        moonraker = version_info.get("moonraker", {})
        if moonraker:
            commits_behind_list = moonraker.get("commits_behind", [])
            commits_behind = len(commits_behind_list) if isinstance(commits_behind_list, list) else 0
            components.append({
                "name": "moonraker",
                "version": moonraker.get("version", "unknown"),
                "branch": moonraker.get("branch"),
                "commits_behind": commits_behind,
                "is_dirty": moonraker.get("is_dirty", False),
                "git_hash": moonraker.get("git_hash", "unknown"),
            })
            if commits_behind > 0:
                update_available = True

        return {
            "components": components,
            "mcu_board": result.get("mcu", None),
            "mcu_firmware": result.get("system", {}).get("package_version", None),
            "update_available": update_available,
        }

    async def get_firmware_history(self, printer_id: str) -> dict:
        """Fetch firmware change history from Moonraker DB."""
        try:
            response = await self._client.get(
                f"{self.base_url}/server/database/item",
                params={'namespace': 'moonraker', 'key': f'firmware_history.{printer_id}'},
            )
            if response.status_code == 200:
                data = response.json()
                history = data.get("result", {}).get("value", {})
                return {
                    "printer_id": printer_id,
                    "entries": history.get("entries", []),
                    "total_count": len(history.get("entries", [])),
                }
        except Exception as e:
            logger.warning(f"Could not fetch firmware history for {printer_id}: {e}")

        return {"printer_id": printer_id, "entries": [], "total_count": 0}
