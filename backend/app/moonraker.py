from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .models import PrinterConfig
from .device_url import assert_safe_device_url


class MoonrakerError(RuntimeError):
    pass


class MoonrakerClient:
    def __init__(self, printer: PrinterConfig, timeout: float = 8.0):
        assert_safe_device_url(printer.base_url)  # LAN device: block metadata/link-local, allow RFC1918
        self.printer = printer
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.printer.api_key:
            headers["X-Api-Key"] = self.printer.api_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
        raw_response: bool = False,
    ) -> Any:
        url = self.printer.base_url.rstrip("/") + path
        merged_headers = {**self._headers(), **(headers or {})}
        try:
            response = await self._client.request(
                method, url, json=json, params=params, data=data, files=files,
                headers=merged_headers,
            )
        except httpx.RequestError as e:
            raise MoonrakerError(str(e)) from e
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MoonrakerError(str(e)) from e
        if raw_response:
            return response
        if not response.content:
            return None
        payload = response.json()
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    async def printer_info(self) -> dict[str, Any]:
        return await self._request("GET", "/printer/info")

    async def server_info(self) -> dict[str, Any]:
        return await self._request("GET", "/server/info")

    async def list_objects(self) -> list[str]:
        result = await self._request("GET", "/printer/objects/list")
        return result.get("objects", [])

    async def query_objects(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        # Moonraker expects ?objectname=field1,field2 (not ?objects=objectname)
        params: list[tuple[str, str]] = [
            (name, ",".join(fields) if fields else "")
            for name, fields in objects.items()
        ]
        result = await self._request("GET", "/printer/objects/query", params=params)
        return result.get("status", {})

    async def query_single_object(self, object_name: str) -> dict[str, Any]:
        result = await self.query_objects({object_name: None})
        return result.get(object_name, {}) if isinstance(result, dict) else {}

    async def run_gcode(self, script: str) -> str:
        result = await self._request("POST", "/printer/gcode/script", json={"script": script})
        return str(result)

    async def emergency_stop(self) -> str:
        result = await self._request("POST", "/printer/emergency_stop")
        return str(result)

    async def pause(self) -> str:
        result = await self._request("POST", "/printer/print/pause")
        return str(result)

    async def resume(self) -> str:
        result = await self._request("POST", "/printer/print/resume")
        return str(result)

    async def cancel(self) -> str:
        result = await self._request("POST", "/printer/print/cancel")
        return str(result)

    async def firmware_restart(self) -> str:
        result = await self._request("POST", "/printer/firmware_restart")
        return str(result)

    async def start_print(self, filename: str) -> str:
        result = await self._request("POST", "/printer/print/start", params={"filename": filename})
        return str(result)

    async def list_directory(self, path: str = "gcodes", extended: bool = True) -> dict[str, Any]:
        return await self._request("GET", "/server/files/directory", params={"path": path, "extended": str(extended).lower()})

    async def file_metadata(self, filename: str) -> dict[str, Any]:
        return await self._request("GET", "/server/files/metadata", params={"filename": filename})

    async def upload_file(
        self,
        *,
        filename: str,
        content: bytes,
        root: str = "gcodes",
        path: str | None = None,
        auto_print: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"root": root, "print": "true" if auto_print else "false"}
        if path:
            data["path"] = path
        files = {"file": (filename, content, "application/octet-stream")}
        result = await self._request("POST", "/server/files/upload", data=data, files=files)
        return result if isinstance(result, dict) else {"result": result}

    async def history_list(self, limit: int = 20) -> dict[str, Any]:
        return await self._request("GET", "/server/history/list", params={"limit": limit})

    async def history_totals(self) -> dict[str, Any]:
        return await self._request("GET", "/server/history/totals")

    async def list_webcams(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/server/webcams/list")
        return result.get("webcams", []) if isinstance(result, dict) else []

    async def webcam_item(self, uid: str) -> dict[str, Any]:
        result = await self._request("GET", "/server/webcams/item", params={"uid": uid})
        return result.get("webcam", {}) if isinstance(result, dict) else {}

    async def webcam_test(self, uid: str) -> dict[str, Any]:
        result = await self._request("POST", "/server/webcams/test", params={"uid": uid})
        return result if isinstance(result, dict) else {}

    async def fetch_binary(self, absolute_url: str) -> httpx.Response:
        printer_host = urlparse(self.printer.base_url).netloc
        url_host = urlparse(absolute_url).netloc
        if url_host and url_host != printer_host:
            raise ValueError('URL host mismatch')
        response = await self._client.get(absolute_url, headers=self._headers())
        response.raise_for_status()
        return response

    def absolute_url(self, maybe_relative_url: str | None) -> str | None:
        if not maybe_relative_url:
            return None
        return urljoin(self.printer.base_url.rstrip("/") + "/", maybe_relative_url)

    async def aclose(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def gcode_store(self, count: int = 100) -> list[dict[str, Any]]:
        """Fetch G-code command history from Moonraker store."""
        result = await self._request("GET", "/server/gcode_store", params={"count": count})
        return result.get("gcode_store", []) if isinstance(result, dict) else []

    async def get_bed_mesh(self) -> dict[str, Any]:
        """Fetch bed mesh data (probed_matrix) from Moonraker."""
        result = await self.query_objects({"bed_mesh": None})
        return result.get("bed_mesh", {}) if isinstance(result, dict) else {}

    async def get_exclude_objects(self) -> dict[str, Any]:
        """Fetch exclude_object state from Moonraker."""
        result = await self.query_objects({"exclude_object": None})
        return result.get("exclude_object", {}) if isinstance(result, dict) else {}

    async def run_exclude_object(self, name: str) -> str:
        """Exclude a named object from the current print."""
        if not re.match(r'^[A-Za-z0-9_\-\.]+$', name):
            raise ValueError(f'invalid exclude object name: {name}')
        return await self.run_gcode(f"EXCLUDE_OBJECT NAME={name}")
