"""Safe write operations to Moonraker database and live printer control."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MoonrakerDBWriter:
    """Abstraction for safe writes to Moonraker database and live control."""

    def __init__(self, base_url: str, api_key: str | None = None):
        """Initialize with Moonraker base URL (e.g., http://127.0.0.1:7125)."""
        self.base_url = base_url
        self.api_key = api_key
        self._headers = {"X-Api-Key": api_key} if api_key else {}

    async def write_to_db(self, namespace: str, key: str, value: Any) -> bool:
        """Write a key-value pair to Moonraker database.

        Args:
            namespace: Database namespace (fluidd, moonraker, etc)
            key: Key name (can be dot-separated for nested, e.g., 'uiSettings.general.material')
            value: Value to store (any JSON-serializable type)

        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    f"{self.base_url}/server/database/item",
                    headers=self._headers,
                    json={
                        "namespace": namespace,
                        "key": key,
                        "value": value,
                    }
                )
                if response.status_code == 200:
                    logger.info(f"Wrote {namespace}[{key}] = {value}")
                    return True
                else:
                    logger.error(f"Failed to write {namespace}[{key}]: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"DB write error for {namespace}[{key}]: {e}")
            return False

    async def execute_gcode(self, gcode: str) -> bool:
        """Execute arbitrary GCode (for live control: M220, M221, etc).

        Args:
            gcode: GCode command (e.g., 'M220 S120' for speed 120%)

        Returns:
            True if queued successfully
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    f"{self.base_url}/printer/gcode/script",
                    headers=self._headers,
                    json={"script": gcode}
                )
                if response.status_code == 200:
                    logger.info(f"Executed GCode: {gcode}")
                    return True
                else:
                    logger.error(f"GCode execution failed: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"GCode execution error: {e}")
            return False

    async def set_active_spool(self, spool_id: str) -> bool:
        """Set active spool in Fluidd database."""
        return await self.write_to_db(
            namespace="fluidd",
            key="uiSettings.general.activeSpool",
            value=spool_id
        )

    async def set_material(self, material_name: str) -> bool:
        """Record current material in database."""
        return await self.write_to_db(
            namespace="fluidd",
            key="uiSettings.general.currentMaterial",
            value=material_name
        )

    async def set_speed_factor(self, factor: float) -> bool:
        """Set live speed factor (M220 command + persist).

        Args:
            factor: Speed factor (0.1-2.0, where 1.0 = 100%)
        """
        # Send live GCode
        await self.execute_gcode(f"M220 S{int(factor * 100)}")
        # Persist to DB
        return await self.write_to_db(
            namespace="moonraker",
            key="live_settings.speed_factor",
            value=factor
        )

    async def set_extrude_factor(self, factor: float) -> bool:
        """Set live extrude/flow factor (M221 command + persist).

        Args:
            factor: Extrude factor (0.5-1.5)
        """
        # Send live GCode
        await self.execute_gcode(f"M221 S{int(factor * 100)}")
        # Persist to DB
        return await self.write_to_db(
            namespace="moonraker",
            key="live_settings.extrude_factor",
            value=factor
        )
