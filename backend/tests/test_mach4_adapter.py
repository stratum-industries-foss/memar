"""MACH4-TOOLID-NONE-01 / MACH4-HOMING-PARTIAL-01: tool_id must not render the
literal string "None" when the controller omits an id, and a partial homing
failure must say so in the message instead of claiming success."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mach4 import MACH4Adapter
from app.models import MachineType, PrinterConfig, Protocol


def make_adapter():
    config = PrinterConfig(
        id="mach4-1",
        name="Test Mill",
        base_url="http://localhost:4444",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.MACH4,
    )
    adapter = MACH4Adapter(config)
    adapter._client = AsyncMock()
    return adapter


def _resp(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


@pytest.mark.asyncio
async def test_tool_id_is_none_not_the_string_none_when_controller_omits_id():
    adapter = make_adapter()
    adapter._client.get.side_effect = [
        _resp(200, {"state": "idle", "x": 0, "y": 0, "z": 0}),  # /api/position
        _resp(200, {"rpm": 0, "feedrate": 0}),                  # /api/spindle
        _resp(200, {}),                                          # /api/tool — no "id"
        _resp(200, {"active": False}),                           # /api/coolant
    ]
    status = await adapter.get_machine_state()
    assert status.tool_id is None


@pytest.mark.asyncio
async def test_tool_id_still_populated_when_controller_provides_id():
    adapter = make_adapter()
    adapter._client.get.side_effect = [
        _resp(200, {"state": "idle", "x": 0, "y": 0, "z": 0}),
        _resp(200, {"rpm": 0, "feedrate": 0}),
        _resp(200, {"id": 3}),
        _resp(200, {"active": False}),
    ]
    status = await adapter.get_machine_state()
    assert status.tool_id == "3"


@pytest.mark.asyncio
async def test_partial_homing_failure_reports_failure_not_success_text():
    adapter = make_adapter()
    adapter._client.post.side_effect = [_resp(200), _resp(200), _resp(500)]
    result = await adapter.home_axes("XYZ")
    assert result["ok"] is False
    assert "fail" in result["message"].lower()
    assert result["message"] != "Homed XYZ"


@pytest.mark.asyncio
async def test_full_homing_success_still_reports_success_text():
    adapter = make_adapter()
    adapter._client.post.side_effect = [_resp(200), _resp(200), _resp(200)]
    result = await adapter.home_axes("XYZ")
    assert result["ok"] is True
    assert result["message"] == "Homed XYZ"
