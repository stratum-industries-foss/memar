"""Integration tests for LinuxCNC REST adapter.

Mock LinuxCNC REST server and test:
- Machine state polling (position, spindle, coolant, tool, filename)
- G-code submission and execution
- Feed rate adjustments
- Emergency stop
- Connection loss + reconnection
- Error handling (invalid G-code, timeouts, malformed responses)
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import httpx

from app.linuxcnc import (
    LinuxCNCClient,
    MachineStatus,
    Position,
    GCodeResponse,
    FeedRateResponse,
    EmergencyStopResponse,
)
from app.models import PrinterConfig, MachineType, Protocol


def create_mock_response(status_code, json_data=None, text=""):
    """Helper to create mock httpx.Response with proper json() method."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or {}
    mock_response.text = text or str(json_data)
    return mock_response


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_config():
    """Sample PrinterConfig for LinuxCNC."""
    return PrinterConfig(
        id="test-cnc-1",
        name="Test LinuxCNC Router",
        base_url="http://localhost:5000",
        machine_type=MachineType.CNC_ROUTER,
        protocol=Protocol.LINUXCNC,
        auth_mode="trusted_local",
    )


@pytest.fixture
def cnc_client(sample_config):
    """Create a LinuxCNCClient with mock HTTP."""
    return LinuxCNCClient(sample_config)


@pytest.fixture
def mock_status_response():
    """Mock healthy status response from LinuxCNC."""
    return {
        "task": {
            "task_state": "auto",
            "file": "demo_part.nc",
            "progress": 45.5,
        },
        "motion": {
            "position": {"x": 10.5, "y": 20.3, "z": 5.2},
            "current_vel": 50,  # mm/min
            "spindle_speed": 2500,
        },
        "io": {
            "coolant": {"mist": False, "flood": True},
            "tool_in_spindle": 3,
        },
    }


@pytest.fixture
def mock_error_status():
    """Mock error status response (ESTOP engaged)."""
    return {
        "task": {
            "task_state": "estop",
            "file": None,
            "progress": None,
        },
        "motion": {
            "position": {"x": 0, "y": 0, "z": 0},
            "current_vel": 0,
            "spindle_speed": 0,
        },
        "io": {
            "coolant": {"mist": False, "flood": False},
            "tool_in_spindle": 0,
        },
    }


# ── Connection Tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_success(cnc_client, mock_status_response):
    """Successful connection to LinuxCNC REST bridge."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, mock_status_response)
        mock_get.return_value = mock_response

        result = await cnc_client.connect()

        assert result["ok"] is True
        assert "Connected" in result["message"]


@pytest.mark.asyncio
async def test_connect_http_error(cnc_client):
    """Connection failure (HTTP error)."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(500)
        mock_get.return_value = mock_response

        result = await cnc_client.connect()

        assert result["ok"] is False
        assert "500" in result["message"]


@pytest.mark.asyncio
async def test_connect_network_error(cnc_client):
    """Connection failure (network timeout)."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = await cnc_client.connect()

        assert result["ok"] is False
        assert "Connection failed" in result["message"]


@pytest.mark.asyncio
async def test_disconnect_success(cnc_client):
    """Successful disconnection."""
    with patch.object(cnc_client._client, "aclose", new_callable=AsyncMock) as mock_close:
        result = await cnc_client.disconnect()

        assert result["ok"] is True
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_error(cnc_client):
    """Disconnection error (graceful)."""
    with patch.object(cnc_client._client, "aclose", new_callable=AsyncMock) as mock_close:
        mock_close.side_effect = RuntimeError("Already closed")

        result = await cnc_client.disconnect()

        assert result["ok"] is False
        assert "error" in result["message"].lower()


# ── Machine State Polling Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_machine_state_printing(cnc_client, mock_status_response):
    """Get machine state while printing (auto mode)."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, mock_status_response)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert isinstance(status, MachineStatus)
        assert status.online is True
        assert status.state == "printing"
        assert status.position_xyz.x == 10.5
        assert status.position_xyz.y == 20.3
        assert status.position_xyz.z == 5.2
        assert status.feed_rate_mm_min == 50
        assert status.spindle_rpm_current == 2500
        assert status.coolant_active is True
        assert status.tool_id == "3"
        assert status.filename == "demo_part.nc"
        assert status.progress == 45.5


@pytest.mark.asyncio
async def test_get_machine_state_idle(cnc_client):
    """Get machine state while idle (ready)."""
    response = {
        "task": {
            "task_state": "manual",
            "file": None,
            "progress": None,
        },
        "motion": {
            "position": {"x": 0, "y": 0, "z": 0},
            "current_vel": 0,
            "spindle_speed": 0,
        },
        "io": {
            "coolant": {"mist": False, "flood": False},
            "tool_in_spindle": 0,
        },
    }

    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, response)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert status.online is True
        assert status.state == "ready"
        assert status.position_xyz.x == 0
        assert status.coolant_active is False
        assert status.filename is None


@pytest.mark.asyncio
async def test_get_machine_state_estop(cnc_client, mock_error_status):
    """Get machine state in ESTOP (error condition)."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, mock_error_status)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert status.state == "error"
        assert status.spindle_rpm_current == 0


@pytest.mark.asyncio
async def test_get_machine_state_offline(cnc_client):
    """Machine state when REST API is unreachable."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(502)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert status.online is False
        assert status.state == "offline"


@pytest.mark.asyncio
async def test_get_machine_state_exception(cnc_client):
    """Machine state when request raises exception."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.RequestError("Network unreachable")

        status = await cnc_client.get_machine_state()

        assert status.online is False
        assert status.state == "error"


@pytest.mark.asyncio
async def test_get_position(cnc_client, mock_status_response):
    """Get position shorthand (without full status)."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, mock_status_response)
        mock_get.return_value = mock_response

        pos = await cnc_client.get_position()

        assert isinstance(pos, Position)
        assert pos.x == 10.5
        assert pos.y == 20.3
        assert pos.z == 5.2


# ── G-code Execution Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_gcode_success(cnc_client):
    """Send valid G-code and receive OK."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(200, {"result": "G01 executed"})
        mock_post.return_value = mock_response

        result = await cnc_client.send_gcode("G01 X10 Y20 F100")

        assert isinstance(result, GCodeResponse)
        assert result.ok is True
        assert "G01 executed" in result.response
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/command/mdi" in call_args[0][0]
        assert call_args[1]["json"]["command"] == "G01 X10 Y20 F100"


@pytest.mark.asyncio
async def test_send_gcode_invalid_empty(cnc_client):
    """Reject empty G-code command."""
    result = await cnc_client.send_gcode("")

    assert result.ok is False
    assert "Empty" in result.error_msg


@pytest.mark.asyncio
async def test_send_gcode_invalid_dash(cnc_client):
    """Reject G-code starting with '-' (flag injection prevention)."""
    result = await cnc_client.send_gcode("-c rm -rf /")

    assert result.ok is False
    assert "cannot start with '-'" in result.error_msg


@pytest.mark.asyncio
async def test_send_gcode_http_error(cnc_client):
    """G-code execution with HTTP error."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(400, text="G-code syntax error: unknown command")
        mock_post.return_value = mock_response

        result = await cnc_client.send_gcode("INVALID_GCODE")

        assert result.ok is False
        assert "400" in result.error_msg
        assert "syntax error" in result.error_msg


@pytest.mark.asyncio
async def test_send_gcode_timeout(cnc_client):
    """G-code execution timeout (>5s)."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = asyncio.TimeoutError()

        result = await cnc_client.send_gcode("G04 P99999")  # Dwell for 99999 seconds

        assert result.ok is False
        assert "timeout" in result.error_msg.lower()


@pytest.mark.asyncio
async def test_send_gcode_network_error(cnc_client):
    """G-code execution with network error."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.RequestError("Connection reset")

        result = await cnc_client.send_gcode("G01 X5")

        assert result.ok is False
        assert "Request error" in result.error_msg


# ── Feed Rate Tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_feed_rate_success(cnc_client):
    """Set feed rate override successfully."""
    with patch.object(cnc_client._client, "put", new_callable=AsyncMock) as mock_put:
        mock_response = create_mock_response(200, {"feedrate": 100.0})
        mock_put.return_value = mock_response

        result = await cnc_client.set_feed_rate(100.0)

        assert isinstance(result, FeedRateResponse)
        assert result.ok is True
        assert result.new_rate_mm_min == 100.0


@pytest.mark.asyncio
async def test_set_feed_rate_invalid_negative(cnc_client):
    """Reject negative feed rate."""
    result = await cnc_client.set_feed_rate(-50)

    assert result.ok is False


@pytest.mark.asyncio
async def test_set_feed_rate_http_error(cnc_client):
    """Feed rate adjustment with HTTP error."""
    with patch.object(cnc_client._client, "put", new_callable=AsyncMock) as mock_put:
        mock_response = create_mock_response(400)
        mock_put.return_value = mock_response

        result = await cnc_client.set_feed_rate(100.0)

        assert result.ok is False


@pytest.mark.asyncio
async def test_set_feed_rate_timeout(cnc_client):
    """Feed rate adjustment timeout."""
    with patch.object(cnc_client._client, "put", new_callable=AsyncMock) as mock_put:
        mock_put.side_effect = asyncio.TimeoutError()

        result = await cnc_client.set_feed_rate(100.0)

        assert result.ok is False


# ── Emergency Stop Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_stop_success(cnc_client):
    """Emergency stop executed successfully."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(200, {"state": "estop"})
        mock_post.return_value = mock_response

        result = await cnc_client.emergency_stop()

        assert isinstance(result, EmergencyStopResponse)
        assert result.ok is True
        assert result.state == "estop"
        call_args = mock_post.call_args
        assert "/command/estop" in call_args[0][0]


@pytest.mark.asyncio
async def test_emergency_stop_http_error(cnc_client):
    """Emergency stop with HTTP error."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(500)
        mock_post.return_value = mock_response

        result = await cnc_client.emergency_stop()

        assert result.ok is False


@pytest.mark.asyncio
async def test_emergency_stop_timeout(cnc_client):
    """Emergency stop timeout (should be fast)."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = asyncio.TimeoutError()

        result = await cnc_client.emergency_stop()

        assert result.ok is False


# ── Homing Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_home_axis_all(cnc_client):
    """Home all axes (XYZ)."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(200, {"result": "Homing complete"})
        mock_post.return_value = mock_response

        result = await cnc_client.home_axis("XYZ")

        assert isinstance(result, GCodeResponse)
        assert result.ok is True


@pytest.mark.asyncio
async def test_home_axis_single(cnc_client):
    """Home single axis (Z)."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_response = create_mock_response(200, {"result": "Z homing complete"})
        mock_post.return_value = mock_response

        result = await cnc_client.home_axis("Z")

        assert result.ok is True


@pytest.mark.asyncio
async def test_home_axis_invalid(cnc_client):
    """Reject invalid axis."""
    result = await cnc_client.home_axis("W")  # Invalid axis

    assert result.ok is False
    assert "Invalid axis" in result.error_msg


@pytest.mark.asyncio
async def test_home_axis_fallback_gcode(cnc_client):
    """Home fallback to G28 G-code if dedicated endpoint fails."""
    with patch.object(cnc_client._client, "post", new_callable=AsyncMock) as mock_post:
        # First call (dedicated /command/home) returns error
        mock_response_fail = create_mock_response(404)
        mock_post.return_value = mock_response_fail

        # We'll mock send_gcode fallback
        with patch.object(cnc_client, "send_gcode") as mock_send:
            mock_send.return_value = GCodeResponse(ok=True)

            result = await cnc_client.home_axis("X")

            # Should fall back to send_gcode
            assert mock_send.called


# ── File Listing Tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_files_success(cnc_client):
    """List G-code files successfully."""
    files_response = {
        "files": [
            {"name": "part1.nc", "path": "/gcode/part1.nc"},
            {"name": "part2.nc", "path": "/gcode/part2.nc"},
            {"name": "demo.gcode", "path": "/gcode/demo.gcode"},
        ]
    }

    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, files_response)
        mock_get.return_value = mock_response

        files = await cnc_client.list_files()

        assert isinstance(files, list)
        assert len(files) == 3
        assert files[0]["name"] == "part1.nc"
        assert files[1]["path"] == "/gcode/part2.nc"


@pytest.mark.asyncio
async def test_list_files_empty(cnc_client):
    """List files when directory is empty."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, {"files": []})
        mock_get.return_value = mock_response

        files = await cnc_client.list_files()

        assert files == []


@pytest.mark.asyncio
async def test_list_files_http_error(cnc_client):
    """List files with HTTP error."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(500)
        mock_get.return_value = mock_response

        files = await cnc_client.list_files()

        assert files == []


@pytest.mark.asyncio
async def test_list_files_network_error(cnc_client):
    """List files with network error."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.RequestError("Connection refused")

        files = await cnc_client.list_files()

        assert files == []


# ── Reconnection Tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconnection_after_failure(cnc_client, mock_status_response):
    """Reconnect to LinuxCNC after transient failure."""
    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        # First call: failure
        mock_response_fail = create_mock_response(503)
        # Second call: success
        mock_response_ok = create_mock_response(200, mock_status_response)

        mock_get.side_effect = [mock_response_fail, mock_response_ok]

        # First status: offline
        status1 = await cnc_client.get_machine_state()
        assert status1.online is False

        # Second status: online (reconnected)
        status2 = await cnc_client.get_machine_state()
        assert status2.online is True
        assert status2.state == "printing"


@pytest.mark.asyncio
async def test_feed_rate_passthrough(cnc_client):
    """Feed rate is passed through as-is (expected in mm/min from REST API)."""
    response = {
        "task": {
            "task_state": "auto",
            "file": "test.nc",
            "progress": 0,
        },
        "motion": {
            "position": {"x": 0, "y": 0, "z": 0},
            "current_vel": 50,  # Expected to be mm/min
            "spindle_speed": 1000,
        },
        "io": {
            "coolant": {"mist": False, "flood": False},
            "tool_in_spindle": 0,
        },
    }

    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, response)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        # Should be 50 mm/min (passed through as-is)
        assert status.feed_rate_mm_min == 50.0


@pytest.mark.asyncio
async def test_coolant_bool_format(cnc_client):
    """Handle coolant as boolean (not dict with mist/flood)."""
    response = {
        "task": {"task_state": "auto", "file": None, "progress": None},
        "motion": {
            "position": {"x": 0, "y": 0, "z": 0},
            "current_vel": 0,
            "spindle_speed": 0,
        },
        "io": {
            "coolant": True,  # Boolean instead of dict
            "tool_in_spindle": 0,
        },
    }

    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, response)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert status.coolant_active is True


@pytest.mark.asyncio
async def test_unknown_task_state(cnc_client):
    """Handle unknown task state (gracefully map to idle)."""
    response = {
        "task": {"task_state": "unknown_future_state", "file": None, "progress": None},
        "motion": {
            "position": {"x": 0, "y": 0, "z": 0},
            "current_vel": 0,
            "spindle_speed": 0,
        },
        "io": {
            "coolant": False,
            "tool_in_spindle": 0,
        },
    }

    with patch.object(cnc_client._client, "get", new_callable=AsyncMock) as mock_get:
        mock_response = create_mock_response(200, response)
        mock_get.return_value = mock_response

        status = await cnc_client.get_machine_state()

        assert status.state == "idle"  # Unknown states map to idle
