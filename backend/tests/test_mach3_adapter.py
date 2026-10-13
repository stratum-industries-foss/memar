"""Unit tests for MACH3 CNC adapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.mach3 import MACH3Client
from app.models import PrinterConfig, MachineType, Protocol


@pytest.fixture
def mach3_config():
    """MACH3 printer config."""
    return PrinterConfig(
        id="cnc-mach3-1",
        name="MACH3 Mill",
        base_url="http://192.168.1.100:5000",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.MACH3,
        spindle_rpm_max=10000,
        feed_rate_mm_min=500.0,
    )


@pytest.fixture
def mach3_client(mach3_config):
    """MACH3 client instance."""
    return MACH3Client(mach3_config)


@pytest.mark.asyncio
async def test_mach3_connect_success(mach3_client):
    """Test successful connection to MACH3."""
    with patch('app.mach3.httpx.AsyncClient.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"state": "Idle"}
        mock_get.return_value = mock_response

        result = await mach3_client.connect()
        assert result["ok"] is True
        assert result["state"] == "ready"


@pytest.mark.asyncio
async def test_mach3_connect_failure(mach3_client):
    """Test failed connection to MACH3."""
    with patch('app.mach3.httpx.AsyncClient.get') as mock_get:
        mock_get.side_effect = Exception("Connection refused")

        result = await mach3_client.connect()
        assert result["ok"] is False
        assert result["state"] == "offline"


@pytest.mark.asyncio
async def test_mach3_get_status(mach3_client):
    """Test polling MACH3 status."""
    with patch('app.mach3.httpx.AsyncClient.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "state": "Running",
            "position_x": 10.5,
            "position_y": 20.3,
            "position_z": 0.0,
            "feed_rate": 100.0,
            "spindle_rpm": 5000,
        }
        mock_get.return_value = mock_response

        status = await mach3_client.get_status()
        assert status["online"] is True
        assert status["state"] == "printing"
        assert status["position_xyz"]["x"] == 10.5
        assert status["spindle_rpm_current"] == 5000


@pytest.mark.asyncio
async def test_mach3_get_machine_state(mach3_client):
    """Test getting detailed MACH3 machine state."""
    with patch('app.mach3.httpx.AsyncClient.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "state": "Running",
            "position_x": 15.0,
            "position_y": 25.0,
            "position_z": 5.0,
            "feed_rate": 150.0,
            "spindle_rpm": 6000,
            "tool_id": "T01",
            "coolant_active": True,
        }
        mock_get.return_value = mock_response

        state = await mach3_client.get_machine_state()
        assert state.online is True
        assert state.state == "printing"
        assert state.tool_id == "T01"
        assert state.coolant_active is True


@pytest.mark.asyncio
async def test_mach3_send_gcode_success(mach3_client):
    """Test sending G-code to MACH3."""
    with patch('app.mach3.httpx.AsyncClient.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "Command accepted"}
        mock_post.return_value = mock_response

        result = await mach3_client.send_gcode("G0 X10 Y20 Z5")
        assert result["ok"] is True
        assert result["error"] is None


@pytest.mark.asyncio
async def test_mach3_send_gcode_empty(mach3_client):
    """Test sending empty G-code."""
    result = await mach3_client.send_gcode("")
    assert result["ok"] is False
    assert "Empty" in result["error"]


@pytest.mark.asyncio
async def test_mach3_home_axes(mach3_client):
    """Test homing axes."""
    with patch('app.mach3.httpx.AsyncClient.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = await mach3_client.home_axes("XYZ")
        assert result["ok"] is True


@pytest.mark.asyncio
async def test_mach3_emergency_stop(mach3_client):
    """Test emergency stop."""
    with patch('app.mach3.httpx.AsyncClient.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = await mach3_client.emergency_stop()
        assert result["ok"] is True
        assert result["state"] == "error"


@pytest.mark.asyncio
async def test_mach3_set_feed_rate(mach3_client):
    """Test setting feed rate."""
    with patch('app.mach3.httpx.AsyncClient.put') as mock_put:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response

        result = await mach3_client.set_feed_rate(250.0)
        assert result["ok"] is True
        assert result["new_rate_mm_min"] == 250.0


@pytest.mark.asyncio
async def test_mach3_list_files(mach3_client):
    """Test listing G-code files."""
    with patch('app.mach3.httpx.AsyncClient.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [
                {"name": "part1.nc", "path": "/part1.nc"},
                {"name": "part2.nc", "path": "/part2.nc"},
            ]
        }
        mock_get.return_value = mock_response

        files = await mach3_client.list_files()
        assert len(files) == 2
        assert files[0]["name"] == "part1.nc"
