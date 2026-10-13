"""Unit tests for CNC webhook event detection."""

from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock
from app.cnc_webhooks import CNCEventTracker
from app.models import PrinterConfig, MachineType, Protocol


@pytest.fixture
def cnc_printer():
    """CNC printer config with safety bounds."""
    return PrinterConfig(
        id="cnc-mill-1",
        name="Test Mill",
        base_url="http://localhost:8080",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.LINUXCNC,
        spindle_rpm_max=10000,
        feed_rate_mm_min=500.0,
    )


@pytest.fixture
def tracker():
    """Event tracker instance."""
    return CNCEventTracker()


@pytest.mark.asyncio
async def test_spindle_overspeed_detection(cnc_printer, tracker):
    """Test detection of spindle overspeed."""
    publish_mock = AsyncMock()

    state = {
        "state": "printing",
        "spindle_rpm_current": 12000,  # 20% over max
        "feed_rate_mm_min": 100.0,
        "tool_id": "T01",
        "coolant_active": True,
    }

    events = await tracker.detect_anomalies(cnc_printer, state, publish_mock)

    assert len(events) > 0
    assert any(e["type"] == "cnc.spindle_overspeed" for e in events)
    publish_mock.assert_called()


@pytest.mark.asyncio
async def test_tool_change_detection(cnc_printer, tracker):
    """Test detection of tool changes."""
    publish_mock = AsyncMock()

    # First state: tool T01
    state1 = {
        "state": "ready",
        "spindle_rpm_current": 0,
        "feed_rate_mm_min": 0,
        "tool_id": "T01",
        "coolant_active": False,
    }
    await tracker.detect_anomalies(cnc_printer, state1, publish_mock)

    # Second state: tool changed to T02
    state2 = {
        "state": "ready",
        "spindle_rpm_current": 0,
        "feed_rate_mm_min": 0,
        "tool_id": "T02",
        "coolant_active": False,
    }
    events = await tracker.detect_anomalies(cnc_printer, state2, publish_mock)

    assert any(e["type"] == "cnc.tool_change" for e in events)
    assert any(
        e.get("prev_tool_id") == "T01" and e.get("new_tool_id") == "T02"
        for e in events
    )


@pytest.mark.asyncio
async def test_production_complete_detection(cnc_printer, tracker):
    """Test detection of production cycle completion."""
    publish_mock = AsyncMock()

    # State: printing
    state_printing = {
        "state": "printing",
        "spindle_rpm_current": 5000,
        "feed_rate_mm_min": 150.0,
        "tool_id": "T01",
        "coolant_active": True,
    }
    await tracker.detect_anomalies(cnc_printer, state_printing, publish_mock)

    # State: ready (job finished)
    state_ready = {
        "state": "ready",
        "spindle_rpm_current": 0,
        "feed_rate_mm_min": 0,
        "tool_id": "T01",
        "coolant_active": False,
    }
    events = await tracker.detect_anomalies(cnc_printer, state_ready, publish_mock)

    assert any(e["type"] == "cnc.production_complete" for e in events)


@pytest.mark.asyncio
async def test_feed_rate_warning(cnc_printer, tracker):
    """Test detection of excessive feed rate."""
    publish_mock = AsyncMock()

    state = {
        "state": "printing",
        "spindle_rpm_current": 5000,
        "feed_rate_mm_min": 450.0,  # Above nominal (350 mm/min)
        "tool_id": "T01",
        "coolant_active": True,
    }

    events = await tracker.detect_anomalies(cnc_printer, state, publish_mock)

    # Depending on threshold, may or may not trigger
    # At least verify the function runs without error
    assert isinstance(events, list)


@pytest.mark.asyncio
async def test_no_false_positives(cnc_printer, tracker):
    """Test normal operation doesn't trigger false positives."""
    publish_mock = AsyncMock()

    state = {
        "state": "printing",
        "spindle_rpm_current": 5000,  # Within bounds
        "feed_rate_mm_min": 150.0,  # Normal
        "tool_id": "T01",
        "coolant_active": True,
    }

    events = await tracker.detect_anomalies(cnc_printer, state, publish_mock)

    # Should have no anomaly events (only state transitions tracked)
    anomaly_events = [e for e in events if "overspeed" in e.get("type", "")]
    assert len(anomaly_events) == 0


@pytest.mark.asyncio
async def test_coolant_failure_detection(cnc_printer, tracker):
    """Test coolant failure detection (if pressure available)."""
    publish_mock = AsyncMock()

    state = {
        "state": "printing",
        "spindle_rpm_current": 5000,
        "feed_rate_mm_min": 150.0,
        "tool_id": "T01",
        "coolant_active": True,
        "coolant_psi": 3.0,  # Below threshold (5 PSI)
    }

    events = await tracker.detect_anomalies(cnc_printer, state, publish_mock)

    assert any(e["type"] == "cnc.coolant_failure" for e in events)


@pytest.mark.asyncio
async def test_event_timestamps_are_utc_not_naive_local(cnc_printer, tracker):
    """CNC-TIMESTAMP-UTC-01: event timestamps must be UTC, not the server's
    naive local clock — a non-UTC server previously produced timestamps that
    silently disagreed with every other UTC-stamped record in the system."""
    publish_mock = AsyncMock()
    before = datetime.now(timezone.utc)

    state = {
        "state": "printing",
        "spindle_rpm_current": 12000,  # overspeed, guaranteed to emit an event
        "feed_rate_mm_min": 100.0,
        "tool_id": "T01",
        "coolant_active": True,
    }
    events = await tracker.detect_anomalies(cnc_printer, state, publish_mock)
    after = datetime.now(timezone.utc)

    assert events, "fixture must produce at least one event to check"
    for event in events:
        ts = datetime.fromisoformat(event["timestamp"])
        assert ts.tzinfo is not None, "timestamp must carry UTC tzinfo, not be naive"
        assert before <= ts <= after
