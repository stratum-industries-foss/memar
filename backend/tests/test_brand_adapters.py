"""Unit tests for the 4 industrial CNC brand adapters: Haas, FANUC, Fadal, MACH4.

These adapters wrap their respective HTTP REST bridges via httpx.AsyncClient.
Each is patched at its own module path (e.g. `app.haas.httpx.AsyncClient.get`),
mirroring the structure of test_mach3_adapter.py.

Return-shape note (differs from MACH3/GRBL):
  - send_gcode    -> {"ok", "message", "result"}   (no "response"/"error" keys)
  - emergency_stop-> {"ok", "message"}             (no "state" key)
"""

import pytest
from unittest.mock import MagicMock, patch

from app.haas import HaasAdapter
from app.fanuc import FANUCAdapter
from app.fadal import FadalAdapter
from app.mach4 import MACH4Adapter
from app.models import PrinterConfig, MachineType, Protocol


def _config(protocol: Protocol, base_url: str) -> PrinterConfig:
    return PrinterConfig(
        id=f"cnc-{protocol.value}-1",
        name=f"{protocol.value} machine",
        base_url=base_url,
        machine_type=MachineType.CNC_MILL,
        protocol=protocol,
        spindle_rpm_max=10000,
        feed_rate_mm_min=500.0,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def haas_client():
    return HaasAdapter(_config(Protocol.HAAS, "http://192.168.1.100:80"))


@pytest.fixture
def fanuc_client():
    return FANUCAdapter(_config(Protocol.FANUC, "http://192.168.1.50:80"))


@pytest.fixture
def fadal_client():
    return FadalAdapter(_config(Protocol.FADAL, "http://192.168.1.200:4001"))


@pytest.fixture
def mach4_client():
    return MACH4Adapter(_config(Protocol.MACH4, "http://localhost:4444"))


def _ok_get(json_payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_payload
    return resp


def _ok_post(json_payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_payload or {"result": "ok"}
    return resp


# --------------------------------------------------------------------------- #
# Instantiation — every adapter must construct from a PrinterConfig and be a
# concrete CNCAdapter (all 9 abstract methods implemented), so this would raise
# TypeError if any abstract method were missing.
# --------------------------------------------------------------------------- #
def test_instantiation_no_raise(haas_client, fanuc_client, fadal_client, mach4_client):
    for client in (haas_client, fanuc_client, fadal_client, mach4_client):
        assert client.base_url
        # _client must be named exactly `_client` so fleet.py eviction closes the pool
        assert client._client is not None


# --------------------------------------------------------------------------- #
# Haas
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_haas_get_status(haas_client):
    with patch("app.haas.httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _ok_get({
            "state": "running",
            "position": {"x": 10.5, "y": 20.3, "z": 1.0},
            "spindle_speed": 5000,
            "feed_rate": 100.0,
        })
        status = await haas_client.get_status()
        assert status["online"] is True
        assert status["state"] == "running"
        assert status["position_xyz"]["x"] == 10.5
        assert status["spindle_rpm_current"] == 5000


@pytest.mark.asyncio
async def test_haas_send_gcode(haas_client):
    with patch("app.haas.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post({"accepted": True})
        result = await haas_client.send_gcode("G0 X10 Y20 Z5")
        assert result["ok"] is True
        assert "result" in result


@pytest.mark.asyncio
async def test_haas_send_gcode_empty(haas_client):
    result = await haas_client.send_gcode("")
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_haas_emergency_stop(haas_client):
    with patch("app.haas.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await haas_client.emergency_stop()
        assert result["ok"] is True
        assert "Emergency stop" in result["message"]


@pytest.mark.asyncio
async def test_haas_machine_state(haas_client):
    with patch("app.haas.httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _ok_get({
            "state": "running",
            "position": {"x": 1.0, "y": 2.0, "z": 3.0},
            "spindle_speed": 6000,
            "feed_rate": 150.0,
            "id": "T01",
            "active": True,
        })
        state = await haas_client.get_machine_state()
        assert state.online is True
        assert state.state == "running"
        assert state.tool_id == "T01"
        assert state.coolant_active is True


# --------------------------------------------------------------------------- #
# FANUC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_fanuc_get_status(fanuc_client):
    with patch("app.fanuc.httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _ok_get({
            "run_status": 1,  # running
            "current_position": {"x": 5.0, "y": 6.0, "z": 7.0},
            "spindle_speed": 8000,
            "feed_rate": 200.0,
        })
        status = await fanuc_client.get_status()
        assert status["online"] is True
        assert status["state"] == "running"
        assert status["position_xyz"]["z"] == 7.0
        assert status["spindle_rpm_current"] == 8000


@pytest.mark.asyncio
async def test_fanuc_send_gcode(fanuc_client):
    with patch("app.fanuc.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post({"queued": True})
        result = await fanuc_client.send_gcode("M3 S1000")
        assert result["ok"] is True
        assert result["message"] == "G-code sent to FANUC"


@pytest.mark.asyncio
async def test_fanuc_home_axes(fanuc_client):
    with patch("app.fanuc.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await fanuc_client.home_axes("XYZ")
        assert result["ok"] is True
        assert result["homing"] == "XYZ"


@pytest.mark.asyncio
async def test_fanuc_emergency_stop(fanuc_client):
    with patch("app.fanuc.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await fanuc_client.emergency_stop()
        assert result["ok"] is True


# --------------------------------------------------------------------------- #
# Fadal
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_fadal_get_status(fadal_client):
    with patch("app.fadal.httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _ok_get({
            "state": "running",
            "x_position": 12.0,
            "y_position": 13.0,
            "z_position": 14.0,
            "spindle_rpm": 3000,
            "feed_rate_in_min": 50.0,
        })
        status = await fadal_client.get_status()
        assert status["online"] is True
        assert status["state"] == "running"
        assert status["position_xyz"]["x"] == 12.0
        assert status["spindle_rpm_current"] == 3000


@pytest.mark.asyncio
async def test_fadal_send_gcode(fadal_client):
    with patch("app.fadal.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post({"queued": True})
        result = await fadal_client.send_gcode("G1 X5 F100")
        assert result["ok"] is True
        assert result["message"] == "G-code queued on Fadal"


@pytest.mark.asyncio
async def test_fadal_send_gcode_empty(fadal_client):
    result = await fadal_client.send_gcode("   ")
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_fadal_emergency_stop(fadal_client):
    with patch("app.fadal.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await fadal_client.emergency_stop()
        assert result["ok"] is True


# --------------------------------------------------------------------------- #
# MACH4
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mach4_get_status(mach4_client):
    with patch("app.mach4.httpx.AsyncClient.get") as mock_get:
        # Both /api/position and /api/spindle resolve to this same mock response.
        mock_get.return_value = _ok_get({
            "x": 1.5, "y": 2.5, "z": 3.5,       # position keys
            "rpm": 12000, "feedrate": 300.0,    # spindle keys
        })
        status = await mach4_client.get_status()
        assert status["online"] is True
        assert status["state"] == "idle"
        assert status["position_xyz"]["y"] == 2.5
        assert status["spindle_rpm_current"] == 12000


@pytest.mark.asyncio
async def test_mach4_send_gcode(mach4_client):
    with patch("app.mach4.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post({"queued": True})
        result = await mach4_client.send_gcode("G0 X0 Y0")
        assert result["ok"] is True
        assert result["message"] == "G-code queued"


@pytest.mark.asyncio
async def test_mach4_home_axes_per_axis(mach4_client):
    with patch("app.mach4.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await mach4_client.home_axes("XYZ")
        assert result["ok"] is True
        # MACH4 homes each axis individually -> one POST per character
        assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_mach4_emergency_stop(mach4_client):
    with patch("app.mach4.httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok_post()
        result = await mach4_client.emergency_stop()
        assert result["ok"] is True
        assert "Emergency stop" in result["message"]


# --------------------------------------------------------------------------- #
# OPC UA
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_opcua_get_status_lazy_connects():
    """HIGH-OPCUA-CONNECT-01 regression: fleet.py builds a fresh OPCUAClient per
    request and calls get_status() WITHOUT calling connect() first. Pre-fix,
    get_status() short-circuited to offline because _connected was False, so
    every OPC-UA device showed permanently offline. get_status() must lazy-connect
    on first use (mirroring get_machine_state)."""
    from app.opcua import OPCUAClient

    cfg = PrinterConfig(
        id="opcua-1", name="OPC UA Mill",
        base_url="opc.tcp://cnc-gateway.local:4840",
        machine_type=MachineType.CNC_MILL, protocol=Protocol.OPCUA, enabled=True,
    )
    client = OPCUAClient(cfg)

    connect_calls = {"n": 0}

    async def _fake_connect():
        connect_calls["n"] += 1
        client._connected = True
        client._client = object()  # truthy sentinel; reads are stubbed below
        return {"ok": True, "message": "connected", "state": "ready"}

    async def _fake_read_node(nodeid):
        # Return a mappable state token for the state node; harmless zeros elsewhere.
        if nodeid == client._nodes["state"]:
            return "Running"
        return 0

    client.connect = _fake_connect
    client._read_node = _fake_read_node

    status = await client.get_status()

    assert connect_calls["n"] == 1, "get_status did not lazy-connect"
    assert status["online"] is True
    assert status["state"] == "printing"  # "Running" -> "printing" via _STATE_MAP


@pytest.mark.asyncio
async def test_mach4_get_status_reflects_reported_state(mach4_client):
    """HIGH-MACH4-STATUS-01 regression: get_status() must surface the machine's
    actual reported state, not a hardcoded 'ready'. An alarmed machine must read
    as alarmed, never idle/safe."""
    with patch("app.mach4.httpx.AsyncClient.get") as mock_get:
        # Both /api/position and /api/spindle resolve to this one mock payload;
        # it now includes a machine-state field.
        mock_get.return_value = _ok_get({
            "state": "alarm",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "rpm": 0, "feedrate": 0.0,
        })
        status = await mach4_client.get_status()
        assert status["online"] is True
        assert status["state"] == "alarm"


# --------------------------------------------------------------------------- #
# HIGH-CNC-FEEDRATE-01 (gated fix): the alpha bridges take a
# 0-200% override, not the mm/min the control route sends. Each adapter must
# refuse rather than silently clamp+POST an inverted command to real hardware.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_haas_set_feed_rate_refuses_ambiguous_unit(haas_client):
    with patch("app.haas.httpx.AsyncClient.post") as mock_post:
        result = await haas_client.set_feed_rate(500.0)
        assert result["ok"] is False
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_fanuc_set_feed_rate_refuses_ambiguous_unit(fanuc_client):
    with patch("app.fanuc.httpx.AsyncClient.post") as mock_post:
        result = await fanuc_client.set_feed_rate(500.0)
        assert result["ok"] is False
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_fadal_set_feed_rate_refuses_ambiguous_unit(fadal_client):
    with patch("app.fadal.httpx.AsyncClient.post") as mock_post:
        result = await fadal_client.set_feed_rate(500.0)
        assert result["ok"] is False
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_mach4_set_feed_rate_refuses_ambiguous_unit(mach4_client):
    with patch("app.mach4.httpx.AsyncClient.post") as mock_post:
        result = await mach4_client.set_feed_rate(500.0)
        assert result["ok"] is False
        mock_post.assert_not_called()
