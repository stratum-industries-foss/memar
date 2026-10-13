"""Tests for GRBL HTTP/TCP adapter."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from app.grbl import GRBLClient
from app.models import PrinterConfig, MachineType, Protocol


@pytest.fixture
def http_printer_config():
    """Create a printer config for HTTP GRBL."""
    return PrinterConfig(
        id="grbl-http-test",
        name="GRBL HTTP Test",
        base_url="http://localhost:8080",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.GRBL,
    )


@pytest.fixture
def tcp_printer_config():
    """Create a printer config for TCP GRBL."""
    return PrinterConfig(
        id="grbl-tcp-test",
        name="GRBL TCP Test",
        base_url="tcp://192.168.1.100:23",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.GRBL,
    )


@pytest.fixture
def serial_printer_config():
    """Create a printer config for serial GRBL (unsupported)."""
    return PrinterConfig(
        id="grbl-serial-test",
        name="GRBL Serial Test",
        base_url="serial:///dev/ttyUSB0:115200",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.GRBL,
    )


class TestGRBLHTTPClient:
    """Test GRBL HTTP adapter."""

    def test_http_client_init(self, http_printer_config):
        """Test HTTP client initialization."""
        client = GRBLClient(http_printer_config)
        assert client._mode == "http"
        assert client._base_url_http == "http://localhost:8080"
        assert client._http_client is not None

    def test_tcp_client_init(self, tcp_printer_config):
        """Test TCP client initialization."""
        client = GRBLClient(tcp_printer_config)
        assert client._mode == "tcp"
        assert client.host == "192.168.1.100"
        assert client.port == 23

    def test_serial_client_init(self, serial_printer_config):
        """Test serial client initialization (should mark as unsupported)."""
        client = GRBLClient(serial_printer_config)
        assert client._mode == "serial"
        assert client._connection_error is not None
        assert "serial://" in client._connection_error

    @pytest.mark.asyncio
    async def test_http_connect_success(self, http_printer_config):
        """Test successful HTTP connection."""
        client = GRBLClient(http_printer_config)

        # Mock the HTTP response
        mock_response = "<Idle|MPos:0.000,0.000,0.000|FS:0,0|Pn:>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            result = await client.connect()
            assert result["online"] is True
            assert "Connected" in result["message"]

    @pytest.mark.asyncio
    async def test_http_connect_failure(self, http_printer_config):
        """Test failed HTTP connection."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await client.connect()
            assert result["online"] is False
            assert result["state"] == "offline"

    @pytest.mark.asyncio
    async def test_http_get_status(self, http_printer_config):
        """Test parsing GRBL status response."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Idle|MPos:10.500,20.300,5.100|FS:100,1500|Pn:XYZ>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()

            assert status["online"] is True
            assert status["state"] == "ready"  # Idle → ready
            assert status["grbl_state_raw"] == "Idle"
            assert status["position_xyz"]["x"] == 10.5
            assert status["position_xyz"]["y"] == 20.3
            assert status["position_xyz"]["z"] == 5.1
            assert status["feed_rate_mm_min"] == 100.0
            assert status["spindle_rpm_current"] == 1500

    @pytest.mark.asyncio
    async def test_http_get_status_running(self, http_printer_config):
        """Test status when machine is running."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Run|MPos:15.000,25.000,10.000|FS:200,2000>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()
            assert status["state"] == "printing"  # Run → printing

    @pytest.mark.asyncio
    async def test_http_get_status_paused(self, http_printer_config):
        """Test status when machine is paused."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Hold:0|MPos:15.000,25.000,10.000|FS:200,2000>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()
            assert status["state"] == "paused"  # Hold:0 → paused

    @pytest.mark.asyncio
    async def test_http_get_status_error(self, http_printer_config):
        """Test status when machine is in alarm/error state."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Alarm|MPos:0.000,0.000,0.000|FS:0,0>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()
            assert status["state"] == "error"  # Alarm → error

    @pytest.mark.asyncio
    async def test_send_gcode_command_ok(self, http_printer_config):
        """Test sending a valid G-code command."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text="ok",
            ),
        ):
            result = await client.send_gcode_command("G0 X10 Y20 Z5")

            assert result["ok"] is True
            assert result["response"] == "ok"
            assert result["command"] == "G0 X10 Y20 Z5"
            assert result["error"] is None

    @pytest.mark.asyncio
    async def test_send_gcode_command_error(self, http_printer_config):
        """Test sending an invalid G-code command."""
        client = GRBLClient(http_printer_config)

        error_msg = "error: Invalid gcode ID:13"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=error_msg,
            ),
        ):
            result = await client.send_gcode_command("G99 INVALID")

            assert result["ok"] is False
            assert error_msg in result["response"]
            assert result["error"] == error_msg

    @pytest.mark.asyncio
    async def test_send_gcode_linear_move(self, http_printer_config):
        """Test sending a linear move command."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=200, text="ok"),
        ):
            result = await client.send_gcode_command("G0 X50.5 Y100.0 Z10.0 F1000")
            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_send_gcode_spindle_control(self, http_printer_config):
        """Test sending spindle control commands."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=200, text="ok"),
        ):
            # Spindle on
            result = await client.send_gcode_command("M3 S1000")
            assert result["ok"] is True

            # Spindle off
            result = await client.send_gcode_command("M5")
            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_send_gcode_arc_command(self, http_printer_config):
        """Test sending arc (circular interpolation) commands."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=200, text="ok"),
        ):
            result = await client.send_gcode_command("G2 X30 Y30 I15 J15 F1000")
            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_get_machine_state(self, http_printer_config):
        """Test getting detailed machine state."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Run|MPos:10.500,20.300,5.100|FS:100,1500|Pn:XYZ>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            state = await client.get_machine_state()

            # get_machine_state now returns the canonical CNCAdapterStatus object
            # (was a bespoke dict with different keys, which broke the CNC routes).
            assert state.online is True
            assert state.state == "printing"
            assert state.position_xyz["x"] == 10.5
            assert state.feed_rate_mm_min == 100.0
            assert state.spindle_rpm_current == 1500

    @pytest.mark.asyncio
    async def test_home_axes_success(self, http_printer_config):
        """Test homing axes."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text="ok",
            ),
        ):
            result = await client.home_axes("XYZ")

            assert result["ok"] is True
            assert result["homing"] == "XYZ"

    @pytest.mark.asyncio
    async def test_disconnect(self, http_printer_config):
        """Test closing the connection."""
        client = GRBLClient(http_printer_config)

        result = await client.disconnect()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_http_timeout_handling(self, http_printer_config):
        """Test timeout handling."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Timeout"),
        ):
            result = await client.send_gcode_command("G0 X10")

            assert result["ok"] is False
            assert "timeout" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_http_fallback_get_param(self, http_printer_config):
        """Test fallback to GET with query param when POST /api/command fails."""
        client = GRBLClient(http_printer_config)

        # POST returns 404, GET returns success
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=404, text="Not found"),
        ):
            with patch.object(
                client._http_client,
                "get",
                new_callable=AsyncMock,
                return_value=MagicMock(status_code=200, text="ok"),
            ):
                result = await client.send_gcode_command("G0 X10")
                assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_serial_client_connect_fails(self, serial_printer_config):
        """Test that serial client connection fails gracefully."""
        client = GRBLClient(serial_printer_config)

        result = await client.connect()
        assert result["online"] is False
        assert "serial://" in result["message"]

    @pytest.mark.asyncio
    async def test_serial_client_send_command_fails(self, serial_printer_config):
        """Test that serial client send command fails gracefully."""
        client = GRBLClient(serial_printer_config)

        result = await client.send_gcode_command("G0 X10")
        assert result["ok"] is False
        assert "serial://" in result["error"]

    @pytest.mark.asyncio
    async def test_list_files_returns_empty(self, http_printer_config):
        """Test that list_files returns empty (GRBL has no filesystem)."""
        client = GRBLClient(http_printer_config)

        files = await client.list_files()
        assert files == []

    @pytest.mark.asyncio
    async def test_legacy_run_gcode_compatibility(self, http_printer_config):
        """Test legacy run_gcode method for backwards compatibility."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=200, text="ok"),
        ):
            result = await client.run_gcode("G0 X10 Y20")

            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_parse_status_missing_feeds(self, http_printer_config):
        """Test parsing status when feed/spindle fields are missing."""
        client = GRBLClient(http_printer_config)

        # Status without FS field
        mock_response = "<Idle|MPos:0.000,0.000,0.000>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()

            assert status["online"] is True
            assert status["position_xyz"]["x"] == 0.0
            # Feed rate defaults to 0
            assert status["feed_rate_mm_min"] == 0.0

    @pytest.mark.asyncio
    async def test_parse_status_invalid_format(self, http_printer_config):
        """Test parsing invalid status response."""
        client = GRBLClient(http_printer_config)

        mock_response = "INVALID RESPONSE"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()

            assert status["online"] is False

    @pytest.mark.asyncio
    async def test_http_url_with_trailing_slash(self):
        """Test HTTP URL normalization with trailing slash."""
        config = PrinterConfig(
            id="test",
            name="Test",
            base_url="http://localhost:8080/",  # with trailing slash
            machine_type=MachineType.CNC_MILL,
            protocol=Protocol.GRBL,
        )
        client = GRBLClient(config)
        assert client._base_url_http == "http://localhost:8080"

    @pytest.mark.asyncio
    async def test_default_http_scheme(self):
        """Test that non-prefixed URL defaults to HTTP."""
        config = PrinterConfig(
            id="test",
            name="Test",
            base_url="localhost:8080",
            machine_type=MachineType.CNC_MILL,
            protocol=Protocol.GRBL,
        )
        client = GRBLClient(config)
        assert client._mode == "http"
        assert client._base_url_http == "http://localhost:8080"

    @pytest.mark.asyncio
    async def test_tcp_default_port(self):
        """Test TCP default port (23)."""
        config = PrinterConfig(
            id="test",
            name="Test",
            base_url="tcp://192.168.1.100",  # no port
            machine_type=MachineType.CNC_MILL,
            protocol=Protocol.GRBL,
        )
        client = GRBLClient(config)
        assert client.port == 23

    @pytest.mark.asyncio
    async def test_http_post_error_response(self, http_printer_config):
        """Test handling of HTTP POST error."""
        client = GRBLClient(http_printer_config)

        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=500,
                text="Internal server error",
            ),
        ):
            with patch.object(
                client._http_client,
                "get",
                new_callable=AsyncMock,
                side_effect=Exception("Fallback failed"),
            ):
                result = await client.send_gcode_command("G0 X10")
                assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_status_with_door_state(self, http_printer_config):
        """Test status parsing with door open state."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Door:0|MPos:5.000,5.000,5.000|FS:0,0>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()
            assert status["state"] == "paused"  # Door:0 → paused

    @pytest.mark.asyncio
    async def test_status_with_check_state(self, http_printer_config):
        """Test status parsing with check state."""
        client = GRBLClient(http_printer_config)

        mock_response = "<Check|MPos:0.000,0.000,0.000|FS:0,0>"
        with patch.object(
            client._http_client,
            "post",
            new_callable=AsyncMock,
            return_value=MagicMock(
                status_code=200,
                text=mock_response,
            ),
        ):
            status = await client.get_status()
            assert status["state"] == "ready"  # Check → ready
