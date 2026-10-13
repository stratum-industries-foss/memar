"""Unit tests for CNC metrics aggregation."""

import pytest
from datetime import datetime
from app.cnc_metrics import CNCMetricsAggregator
from app.models import PrinterConfig, MachineType, Protocol


@pytest.fixture
def cnc_config():
    """CNC printer config."""
    return PrinterConfig(
        id="cnc-mill-1",
        name="Test Mill",
        base_url="http://localhost:8080",
        machine_type=MachineType.CNC_MILL,
        protocol=Protocol.LINUXCNC,
    )


@pytest.fixture
def sample_history():
    """Sample machine state history (60 samples = 5 min at 5s interval)."""
    samples = []
    # First 30 samples: ready/idle
    for i in range(30):
        samples.append({
            "state": "ready",
            "spindle_rpm_current": 0,
            "feed_rate_mm_min": 0,
            "tool_id": "T01",
            "coolant_active": False,
        })
    # Next 20 samples: printing/cutting with spindle on
    for i in range(20):
        samples.append({
            "state": "printing",
            "spindle_rpm_current": 5000,
            "feed_rate_mm_min": 150.0,
            "tool_id": "T01",
            "coolant_active": True,
        })
    # Last 10 samples: tool change and ready
    for i in range(10):
        samples.append({
            "state": "ready",
            "spindle_rpm_current": 0,
            "feed_rate_mm_min": 0,
            "tool_id": "T02",
            "coolant_active": False,
        })
    return samples


def test_cnc_metrics_aggregation(sample_history):
    """Test aggregating CNC metrics from state history."""
    aggregator = CNCMetricsAggregator()
    aggregator.samples = sample_history
    metrics = aggregator._compute_aggregates(len(sample_history), 5)

    # Verify aggregates
    assert metrics["sample_count"] == 60
    assert metrics["sample_period_minutes"] == 5
    assert metrics["spindle_utilization_pct"] > 0  # 20 out of 60 samples had spindle active
    assert metrics["production_time_hours"] > 0  # 20 samples at 5s = 100s ≈ 0.03 hours
    assert metrics["tool_changes_count"] >= 1  # At least one tool change detected


def test_frontend_contract_keys(sample_history):
    """Lock the aggregated-metrics contract against the frontend CNCMetricsPanel.

    Every field the panel dereferences (often via .toFixed(), which throws on
    undefined) MUST be present and numeric in the aggregator output. device_name
    + timestamp are added by the route, not the aggregator, so they're excluded
    here and covered by the live endpoint check.
    """
    aggregator = CNCMetricsAggregator()
    aggregator.samples = sample_history
    metrics = aggregator._compute_aggregates(len(sample_history), 60)

    required_numeric = [
        "spindle_utilization_pct",
        "production_time_hours",
        "idle_time_hours",
        "downtime_hours",
        "tool_changes",            # frontend reads m.tool_changes
        "coolant_flow_hours",
        "avg_feed_rate_mm_min",
        "max_feed_rate_mm_min",    # frontend m.max_feed_rate_mm_min.toFixed(1)
        "max_spindle_rpm",
        "window_minutes",          # frontend gauge max / alert threshold
    ]
    for key in required_numeric:
        assert key in metrics, f"frontend contract: missing key {key!r}"
        assert isinstance(metrics[key], (int, float)), f"{key} must be numeric"

    # Empty history must also satisfy the contract (zeros, not missing keys).
    empty = CNCMetricsAggregator()._compute_aggregates(0, 60)
    for key in required_numeric:
        assert key in empty, f"empty-path contract: missing key {key!r}"
        assert isinstance(empty[key], (int, float))


def test_spindle_utilization():
    """Test spindle utilization calculation."""
    samples = []
    # Half the time: spindle active (>1000 RPM)
    for i in range(30):
        samples.append({
            "state": "printing",
            "spindle_rpm_current": 5000,
            "feed_rate_mm_min": 100.0,
            "coolant_active": True,
        })
    # Half the time: spindle off
    for i in range(30):
        samples.append({
            "state": "ready",
            "spindle_rpm_current": 0,
            "feed_rate_mm_min": 0,
            "coolant_active": False,
        })

    aggregator = CNCMetricsAggregator()
    aggregator.samples = samples
    metrics = aggregator._compute_aggregates(60, 60)

    # Should be approximately 50%
    assert 40 < metrics["spindle_utilization_pct"] < 60


def test_feed_rate_averaging():
    """Test average feed rate calculation."""
    samples = []
    feed_rates = [100.0, 150.0, 200.0, 250.0, 300.0]

    for rate in feed_rates * 12:  # 60 samples
        samples.append({
            "state": "printing",
            "spindle_rpm_current": 5000,
            "feed_rate_mm_min": rate,
            "coolant_active": True,
        })

    aggregator = CNCMetricsAggregator()
    aggregator.samples = samples
    metrics = aggregator._compute_aggregates(60, 60)

    # Average of [100, 150, 200, 250, 300] = 200
    assert 195 < metrics["avg_feed_rate_mm_min"] < 205


def test_max_spindle_rpm():
    """Test maximum spindle RPM tracking."""
    samples = []
    rpms = [2000, 4000, 6000, 8000, 10000]

    for rpm in rpms * 12:  # 60 samples
        samples.append({
            "state": "printing",
            "spindle_rpm_current": rpm,
            "feed_rate_mm_min": 100.0,
            "coolant_active": True,
        })

    aggregator = CNCMetricsAggregator()
    aggregator.samples = samples
    metrics = aggregator._compute_aggregates(60, 60)

    assert metrics["max_spindle_rpm"] == 10000


def test_empty_history():
    """Test with empty state history."""
    aggregator = CNCMetricsAggregator()
    metrics = aggregator._compute_aggregates(0, 60)

    assert metrics["sample_count"] == 0
    assert metrics["spindle_utilization_pct"] == 0.0
    assert metrics["production_time_hours"] == 0.0
