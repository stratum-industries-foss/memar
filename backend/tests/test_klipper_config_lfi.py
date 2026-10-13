"""BUG-HIGH-LFI-01: GET /api/printers/{id}/klipper-config must not read an arbitrary
local file at a path the REMOTE printer supplies via /printer/info. With no allowlist
configured (MEMAR_KLIPPER_FILE_ROOTS unset → deny-all), the secret path must never
reach the parser."""
import pytest
from unittest.mock import AsyncMock

import app.main as main_module
import app.fleet as fleet_module
import app.config_discovery as cd_module
from app.moonraker import MoonrakerClient
from app.models import PrinterConfig


@pytest.mark.asyncio
async def test_klipper_config_route_denies_remote_supplied_path(admin_client, monkeypatch, tmp_path):
    monkeypatch.delenv("MEMAR_KLIPPER_FILE_ROOTS", raising=False)  # deny-all default
    secret = tmp_path / "server_secret.env"
    secret.write_text("MEMAR_JWT_SECRET=supersecret\n")

    printer = PrinterConfig(id="evil", name="Evil", base_url="http://evil")
    monkeypatch.setattr(main_module, "_get_printer_or_404", lambda pid: printer)

    client = MoonrakerClient(printer)
    client.printer_info = AsyncMock(return_value={"config_file": str(secret)})

    async def _fake_get_client(pr):
        return client
    monkeypatch.setattr(fleet_module, "_get_client", _fake_get_client)

    # Spy on the parser: it must NEVER be invoked for the denied secret path.
    parsed_paths = []

    def _spy(path):
        parsed_paths.append(str(path))
        return {}
    monkeypatch.setattr(cd_module, "parse_printer_cfg", _spy)

    resp = await admin_client.get("/api/printers/evil/klipper-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("klipper_config") is None, "denied path must not yield a parsed config"
    assert str(secret) not in parsed_paths, "remote-supplied secret path must never reach the parser"
