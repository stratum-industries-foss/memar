"""Tests for the Marlin adapter's Repetier Server mode."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.marlin import MarlinClient
from app.models import PrinterConfig


def _cfg(base_url):
    return PrinterConfig(id="rep-1", name="Rep", base_url=base_url, api_key="repetier:TOKEN")


@pytest.mark.asyncio
async def test_repetier_parses_listprinter_and_statelist():
    client = MarlinClient(_cfg("http://host:3344/delta"))
    assert client._mode == "repetier"
    lp = MagicMock(status_code=200)
    lp.json.return_value = [
        {"active": True, "job": "bracket.gcode", "name": "Delta",
         "online": 1, "slug": "delta", "done": 40.0, "printTime": 3600.0},
    ]
    sl = MagicMock(status_code=200)
    sl.json.return_value = {
        "delta": {"extruder": [{"tempRead": 210.4, "tempSet": 215.0}],
                  "heatedBed": {"tempRead": 60.1, "tempSet": 60.0}},
    }
    with patch.object(client._client, "get", new_callable=AsyncMock, side_effect=[lp, sl]):
        status = await client.get_status()
    assert status["online"] is True
    assert status["state"] == "printing"
    assert status["nozzle_temperature"] == 210.4
    assert status["nozzle_target"] == 215.0
    assert status["bed_temperature"] == 60.1
    assert status["bed_target"] == 60.0
    assert status["filename"] == "bracket.gcode"
    assert status["progress"] == 40.0


@pytest.mark.asyncio
async def test_repetier_idle_when_job_is_none():
    client = MarlinClient(_cfg("http://host:3344/delta"))
    lp = MagicMock(status_code=200)
    lp.json.return_value = [{"job": "none", "online": 1, "slug": "delta"}]
    sl = MagicMock(status_code=200)
    sl.json.return_value = {"delta": {"extruder": [{"tempRead": 25.0, "tempSet": 0.0}]}}
    with patch.object(client._client, "get", new_callable=AsyncMock, side_effect=[lp, sl]):
        status = await client.get_status()
    assert status["online"] is True
    assert status["state"] == "ready"
    assert status["filename"] is None


@pytest.mark.asyncio
async def test_repetier_url_does_not_collapse_to_printer_host():
    # Regression: base_url with NO path segment must produce host = the real
    # host, not the literal "printer" the old rsplit() produced.
    client = MarlinClient(_cfg("http://192.168.1.50:3344"))
    lp = MagicMock(status_code=200); lp.json.return_value = []
    sl = MagicMock(status_code=200); sl.json.return_value = {}
    mock_get = AsyncMock(side_effect=[lp, sl])
    with patch.object(client._client, "get", mock_get):
        await client.get_status()
    called_url = mock_get.call_args_list[0].args[0]
    assert called_url == "http://192.168.1.50:3344/printer/api/default"
    assert "//printer/" not in called_url
