"""Tests for the OctoPrint adapter's compound-status handling."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.octoprint import OctoPrintClient, _map_state, _is_offline_state
from app.models import PrinterConfig


def _cfg():
    return PrinterConfig(id="octo-1", name="Octo", base_url="http://host:80", api_key="K")


async def _run(job_state):
    client = OctoPrintClient(_cfg())
    printer_resp = MagicMock(status_code=200); printer_resp.json.return_value = {"temperature": {}}
    job_resp = MagicMock(status_code=200)
    job_resp.json.return_value = {"state": job_state, "progress": {}, "job": {}}
    with patch.object(client._client, "get", new_callable=AsyncMock,
                      side_effect=[printer_resp, job_resp]):
        return await client.get_status()


@pytest.mark.asyncio
async def test_compound_offline_error_is_offline_not_online():
    status = await _run("Offline (Error: SerialException)")
    assert status["online"] is False           # regression: was True
    assert status["state"] == "offline"        # regression: was "idle"


@pytest.mark.asyncio
async def test_offline_after_error_is_offline():
    status = await _run("Offline after error")
    assert status["online"] is False
    assert status["state"] == "offline"


@pytest.mark.asyncio
async def test_operational_still_online():
    status = await _run("Operational")
    assert status["online"] is True
    assert status["state"] == "ready"


def test_helpers_direct():
    assert _is_offline_state("Offline (Error: x)") is True
    assert _is_offline_state("Operational") is False
    assert _map_state("Error: MCU shutdown") == "error"
    assert _map_state("Printing") == "printing"
