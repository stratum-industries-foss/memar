"""
CNC Fleet Metrics Aggregation.

Computes time-window metrics over CNC machine state history:
- Spindle utilization (% time spindle active)
- Production time (total hours in "cutting" state)
- Idle time, downtime
- Tool changes, coolant flow duration
- Average feed rate, max spindle RPM

Pattern: Similar to OEE but for subtractive/additive machining.
"""
from __future__ import annotations

from collections import defaultdict

from .models import MachineType

# CNC adapters (haas/fanuc/fadal) emit raw vendor states ("running"/"alarm"/
# "idle"/"stopped"/"edit"/"unknown") that this aggregator's buckets don't
# recognize, so those samples fell through and were silently dropped from
# production/idle/downtime. Map them onto the canonical status vocabulary
# (printing/ready/error/offline/paused) before bucketing. Canonical values
# pass through unchanged via .get(state, state).
_CNC_STATE_NORMALIZE = {
    "running": "printing",
    "cutting": "printing",
    "active": "printing",
    "alarm": "error",
    "idle": "ready",
    "stopped": "ready",
    "edit": "ready",
    "unknown": "offline",
}


class CNCMetricsAggregator:
    """Aggregate CNC machine metrics over time windows."""

    def __init__(self, sample_interval_seconds: int = 5):
        """Initialize aggregator.

        Args:
            sample_interval_seconds: How often to sample machine state (default 5s)
        """
        self.sample_interval = sample_interval_seconds
        self.samples: list[dict] = []
        self.prev_tool_id: str | None = None
        self.prev_state: str | None = None

    async def aggregate_static(
        self,
        states_history: list[dict],
        duration_minutes: int = 60,
    ) -> dict:
        """Aggregate metrics from a pre-collected state history (e.g., from database).

        Args:
            states_history: List of {"timestamp": datetime, "state": str, "spindle_rpm_current": int, ...}
            duration_minutes: Duration window

        Returns:
            dict with aggregated metrics
        """
        self.samples = states_history
        return self._compute_aggregates(len(states_history), duration_minutes)

    def _compute_aggregates(self, sample_count: int, duration_minutes: int) -> dict:
        """Compute all metrics from collected samples."""
        if not self.samples or sample_count == 0:
            return {
                "spindle_utilization_pct": 0.0,
                "production_time_hours": 0.0,
                "idle_time_hours": 0.0,
                "downtime_hours": 0.0,
                "tool_changes_count": 0,
                "tool_changes": 0,
                "coolant_flow_hours": 0.0,
                "avg_feed_rate_mm_min": 0.0,
                "max_feed_rate_mm_min": 0.0,
                "max_spindle_rpm": 0,
                "sample_count": 0,
                "sample_period_minutes": duration_minutes,
                "window_minutes": duration_minutes,
            }

        # Count state transitions
        cutting_samples = 0
        idle_samples = 0
        downtime_samples = 0
        spindle_active_samples = 0
        tool_change_count = 0
        coolant_active_samples = 0
        feed_rates = []
        spindle_rpms = []

        self.prev_tool_id = None
        self.prev_state = None

        for sample in self.samples:
            state = sample.get("state", "offline")
            state = _CNC_STATE_NORMALIZE.get(state, state)
            spindle_rpm = sample.get("spindle_rpm_current", 0) or 0
            feed_rate = sample.get("feed_rate_mm_min", 0) or 0
            coolant = sample.get("coolant_active", False)
            tool_id = sample.get("tool_id")

            # Count state buckets
            if state == "printing":
                cutting_samples += 1
            elif state == "ready":
                idle_samples += 1
            elif state in ("error", "offline", "paused"):
                downtime_samples += 1

            # Count spindle active (RPM > 1000)
            if spindle_rpm > 1000:
                spindle_active_samples += 1

            # Count coolant active
            if coolant:
                coolant_active_samples += 1

            # Track tool changes
            if tool_id and self.prev_tool_id and tool_id != self.prev_tool_id:
                tool_change_count += 1
            self.prev_tool_id = tool_id

            # Collect feed rates and spindle RPMs for stats
            if feed_rate > 0:
                feed_rates.append(feed_rate)
            if spindle_rpm > 0:
                spindle_rpms.append(spindle_rpm)

        # Convert sample counts to hours. Scale by ACTUAL covered time (each
        # sample represents self.sample_interval seconds) rather than the full
        # requested window: sampling 10min of a 60min window must not report 6x
        # the real cutting time. covered_minutes = samples * interval.
        total_samples = len(self.samples)
        covered_minutes = (total_samples * self.sample_interval) / 60 if total_samples > 0 else 0

        production_time_hours = (cutting_samples / total_samples * covered_minutes / 60) if total_samples > 0 else 0
        idle_time_hours = (idle_samples / total_samples * covered_minutes / 60) if total_samples > 0 else 0
        downtime_hours = (downtime_samples / total_samples * covered_minutes / 60) if total_samples > 0 else 0
        coolant_flow_hours = (coolant_active_samples / total_samples * covered_minutes / 60) if total_samples > 0 else 0

        # Spindle utilization: % of time spindle was active (>1000 RPM)
        spindle_utilization_pct = (spindle_active_samples / total_samples * 100) if total_samples > 0 else 0.0

        # Average + peak feed rate during cutting
        avg_feed_rate = sum(feed_rates) / len(feed_rates) if feed_rates else 0.0
        max_feed_rate = max(feed_rates) if feed_rates else 0.0

        # Max spindle RPM
        max_spindle_rpm = max(spindle_rpms) if spindle_rpms else 0

        return {
            "spindle_utilization_pct": round(spindle_utilization_pct, 1),
            "production_time_hours": round(production_time_hours, 2),
            "idle_time_hours": round(idle_time_hours, 2),
            "downtime_hours": round(downtime_hours, 2),
            # tool_changes_count is the canonical key; tool_changes mirrors it for
            # the frontend CNCMetricsPanel contract (both kept to avoid churn).
            "tool_changes_count": tool_change_count,
            "tool_changes": tool_change_count,
            "coolant_flow_hours": round(coolant_flow_hours, 2),
            "avg_feed_rate_mm_min": round(avg_feed_rate, 1),
            "max_feed_rate_mm_min": round(max_feed_rate, 1),
            "max_spindle_rpm": max_spindle_rpm,
            "sample_count": total_samples,
            # sample_period_minutes is canonical; window_minutes mirrors it for the
            # frontend contract (panel reads window_minutes for gauge maxes/alerts).
            "sample_period_minutes": duration_minutes,
            "window_minutes": duration_minutes,
        }
