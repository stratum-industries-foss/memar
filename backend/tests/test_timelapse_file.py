"""HTTP-level tests for GET /api/printers/{id}/timelapse/{name}.

FOUND BY REVIEW: this route didn't exist at all — the timelapse list route
(GET /api/printers/{id}/timelapse) worked, but every <video src> and
download link built from its entries hit the SPA catch-all 404. Covers the
new route: happy path, missing-directory config, and path traversal.
"""
import tempfile
from pathlib import Path

import pytest

import app.license as licmod
import app.main as main_module
from app.license import LicenseState, _tier_to_features
from app.models import FarmConfig, MachineType, PrinterConfig, Protocol

PRINTER_ID = "timelapse-test-1"


@pytest.fixture(autouse=True)
def _active_license():
    """viewer_client (conftest.py) needs the multi_user feature, which
    requires an active license — mirrors test_cnc_control.py's pattern."""
    licmod._state = LicenseState(
        tier="farm",
        device_limit=150,
        expires_at="2099-01-01",
        features=_tier_to_features("farm"),
        customer_id="cus_test",
        active=True,
    )
    yield
    licmod._state = None


@pytest.fixture
def timelapse_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "print_001.mp4"
        video.write_bytes(b"fake mp4 bytes")

        def _config() -> FarmConfig:
            return FarmConfig(
                printers=[
                    PrinterConfig(
                        id=PRINTER_ID,
                        name="Test Printer",
                        base_url="http://localhost:7125",
                        machine_type=MachineType.FDM,
                        protocol=Protocol.MOONRAKER,
                        enabled=True,
                        timelapse_dir=tmp,
                    )
                ]
            )
        monkeypatch.setattr(main_module, "get_config", _config)
        yield tmp


@pytest.fixture
def no_timelapse_dir_config(monkeypatch):
    def _config() -> FarmConfig:
        return FarmConfig(
            printers=[
                PrinterConfig(
                    id=PRINTER_ID,
                    name="Test Printer",
                    base_url="http://localhost:7125",
                    machine_type=MachineType.FDM,
                    protocol=Protocol.MOONRAKER,
                    enabled=True,
                )
            ]
        )
    monkeypatch.setattr(main_module, "get_config", _config)


@pytest.mark.asyncio
async def test_fetches_existing_timelapse_file(admin_client, timelapse_dir):
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/timelapse/print_001.mp4")
    assert r.status_code == 200, r.text
    assert r.content == b"fake mp4 bytes"


@pytest.mark.asyncio
async def test_unknown_filename_returns_404(admin_client, timelapse_dir):
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/timelapse/does-not-exist.mp4")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_no_timelapse_dir_configured_returns_404(admin_client, no_timelapse_dir_config):
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/timelapse/anything.mp4")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_path_traversal_is_blocked(admin_client, timelapse_dir):
    """../../../etc/passwd-style names must never escape timelapse_dir."""
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/timelapse/..%2F..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (404, 400), r.text


@pytest.mark.asyncio
async def test_viewer_can_fetch_timelapse(viewer_client, timelapse_dir):
    """Timelapse playback is a read, same RBAC as the list route (any
    authenticated user, not gated to admin/operator)."""
    r = await viewer_client.get(f"/api/printers/{PRINTER_ID}/timelapse/print_001.mp4")
    assert r.status_code == 200, r.text
