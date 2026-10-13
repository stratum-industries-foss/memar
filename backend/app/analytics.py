"""Fleet-level KPI calculations and aggregation.

All device IDENTITY comes from config (devices.yaml); all history comes from the
telemetry tables (FleetStatusLog / JobLog / CNCMetricsLog) written by the
telemetry sampler. This module is fully ASYNC — it is constructed with the
app's AsyncSession and every calculation awaits select() queries. (It was
previously written against the sync ORM API and would have failed at runtime.)
"""

import logging
import statistics
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# States that count as "the machine was usefully up" for availability.
_UP_STATES = {"idle", "printing", "running", "heating", "ready", "busy"}


def _config_device_ids() -> list[str]:
    """Enabled device ids from config (the single source of device identity)."""
    from .config import get_config
    return [p.id for p in get_config().printers if p.enabled]


class FleetKPICalculator:
    """Calculate real-time fleet metrics from persisted telemetry."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_utilization(self, hours: int = 24) -> dict:
        """Availability %: fraction of samples in which devices were up."""
        from .models_db import FleetStatusLog

        device_ids = _config_device_ids()
        empty = {
            "utilization_pct": 0.0, "uptime_seconds": 0,
            "total_seconds": hours * 3600, "period_hours": hours,
            "device_count": len(device_ids),
        }
        if not device_ids:
            return empty
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            rows = (await self.db.execute(
                select(FleetStatusLog.state, FleetStatusLog.online)
                .where(
                    FleetStatusLog.device_id.in_(device_ids),
                    FleetStatusLog.timestamp >= cutoff,
                )
            )).all()
            total = len(rows)
            if total == 0:
                return empty
            up = sum(1 for state, online in rows if online and state in _UP_STATES)
            pct = up / total * 100
            return {
                "utilization_pct": round(pct, 1),
                "uptime_seconds": int(up / total * hours * 3600),
                "total_seconds": hours * 3600,
                "period_hours": hours,
                "device_count": len(device_ids),
                "sample_count": total,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating utilization: {e}")
            return empty

    async def calculate_oee_trend(self, days: int = 7, device_id: str | None = None) -> list[dict]:
        """Per-day average OEE over the last `days` days (from JobLog). Filter by device_id if provided."""
        from .models_db import JobLog

        try:
            daily = []
            for day_offset in range(days):
                day_start = datetime.utcnow() - timedelta(days=day_offset + 1)
                day_end = day_start + timedelta(days=1)
                where_clause = [
                    JobLog.created_at >= day_start,
                    JobLog.created_at < day_end,
                    JobLog.oee.isnot(None),
                ]
                if device_id:
                    where_clause.append(JobLog.device_id == device_id)
                oees = (await self.db.execute(
                    select(JobLog.oee).where(*where_clause)
                )).scalars().all()

                count_where = [
                    JobLog.created_at >= day_start,
                    JobLog.created_at < day_end,
                ]
                if device_id:
                    count_where.append(JobLog.device_id == device_id)
                count = (await self.db.execute(
                    select(func.count(JobLog.id)).where(*count_where)
                )).scalar() or 0
                avg_oee = statistics.mean(oees) if oees else 0
                daily.append({
                    "date": day_start.strftime("%Y-%m-%d"),
                    "oee": round(avg_oee, 2),
                    "job_count": int(count),
                })
            return sorted(daily, key=lambda x: x["date"])
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating OEE trend: {e}")
            return []

    async def calculate_error_rate(self, hours: int = 24) -> dict:
        """Error rate %: failed jobs / total jobs over the window."""
        from .models_db import JobLog

        empty = {"error_rate_pct": 0.0, "failed_jobs": 0, "total_jobs": 0, "period_hours": hours}
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            total = (await self.db.execute(
                select(func.count(JobLog.id)).where(JobLog.created_at >= cutoff)
            )).scalar() or 0
            failed = (await self.db.execute(
                select(func.count(JobLog.id)).where(
                    JobLog.created_at >= cutoff, JobLog.status == "failed"
                )
            )).scalar() or 0
            rate = (failed / total * 100) if total > 0 else 0
            return {
                "error_rate_pct": round(rate, 1),
                "failed_jobs": int(failed),
                "total_jobs": int(total),
                "period_hours": hours,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating error rate: {e}")
            return empty

    async def get_coolant_stats(self) -> dict:
        """Current coolant PSI across CNC devices.

        Returns {"status": "no_data"} when no pressure samples exist — which is
        the normal case today, because no shipped adapter reports coolant_psi
        (they report coolant_active). This is honest, not a failure.
        """
        from .models_db import CNCMetricsLog

        try:
            psi_values = (await self.db.execute(
                select(CNCMetricsLog.coolant_psi)
                .where(CNCMetricsLog.coolant_psi.isnot(None))
                .order_by(CNCMetricsLog.timestamp.desc())
                .limit(100)
            )).scalars().all()
            psi_values = [p for p in psi_values if p is not None]
            if not psi_values:
                return {"status": "no_data"}
            return {
                "current_psi": round(psi_values[0], 1),
                "avg_psi": round(statistics.mean(psi_values), 1),
                "min_psi": round(min(psi_values), 1),
                "max_psi": round(max(psi_values), 1),
                "sample_count": len(psi_values),
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error getting coolant stats: {e}")
            return {"status": "no_data"}

    async def get_top_error_modes(self, limit: int = 5) -> list[dict]:
        """Most common failure reasons across failed jobs."""
        from .models_db import JobLog

        try:
            rows = (await self.db.execute(
                select(
                    func.lower(JobLog.failure_reason),
                    func.count(JobLog.id).label("count"),
                )
                .where(JobLog.status == "failed", JobLog.failure_reason.isnot(None))
                .group_by(func.lower(JobLog.failure_reason))
                .order_by(func.count(JobLog.id).desc())
                .limit(limit)
            )).all()
            return [{"mode": r[0] or "unknown", "count": int(r[1])} for r in rows]
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error getting top error modes: {e}")
            return []

    async def calculate_throughput(self, hours: int = 24) -> dict:
        """Job throughput over the window (count and jobs/day)."""
        from .models_db import JobLog

        empty = {"jobs": 0, "jobs_per_day": 0.0, "period_hours": hours}
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            jobs = (await self.db.execute(
                select(func.count(JobLog.id)).where(JobLog.created_at >= cutoff)
            )).scalar() or 0
            return {
                "jobs": int(jobs),
                "jobs_per_day": round(jobs / hours * 24, 1) if hours else 0.0,
                "period_hours": hours,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating throughput: {e}")
            return empty

    async def calculate_reliability(self, days: int = 7) -> dict:
        """Fleet MTBF / MTTR from the FleetStatusLog state-sample stream.

        Samples are ~60s apart; a 'failure' is an up->down transition per device,
        downtime is time spent down, uptime is time spent up. MTBF = uptime /
        failures; MTTR = downtime / failures. Sample-grained (approximate) but
        cheap — reads the existing indexed table, no new schema.
        """
        from .models_db import FleetStatusLog

        SAMPLE_S = 60
        empty = {"mtbf_hours": None, "mttr_minutes": None, "failures": 0, "period_days": days}
        device_ids = _config_device_ids()
        if not device_ids:
            return empty
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            rows = (await self.db.execute(
                select(FleetStatusLog.device_id, FleetStatusLog.state, FleetStatusLog.online)
                .where(FleetStatusLog.device_id.in_(device_ids),
                       FleetStatusLog.timestamp >= cutoff)
                .order_by(FleetStatusLog.device_id, FleetStatusLog.timestamp)
            )).all()
            if not rows:
                return empty
            from collections import defaultdict
            per_dev = defaultdict(lambda: {"up": 0, "down": 0, "fail": 0, "ever_up": False})
            last_dev = None
            prev_up = None
            for device_id, state, online in rows:
                is_up = bool(online) and state in _UP_STATES
                d = per_dev[device_id]
                if device_id != last_dev:
                    last_dev, prev_up = device_id, is_up
                else:
                    if prev_up and not is_up:
                        d["fail"] += 1
                    prev_up = is_up
                if is_up:
                    d["up"] += 1
                    d["ever_up"] = True
                else:
                    d["down"] += 1
            # A device that was NEVER up in the window is decommissioned / never-
            # provisioned, not a repair scenario — excluding its downtime keeps a
            # single always-offline device from inflating fleet MTTR ~1000x. It has
            # zero failures anyway, so MTBF is unaffected.
            up_samples = sum(d["up"] for d in per_dev.values() if d["ever_up"])
            down_samples = sum(d["down"] for d in per_dev.values() if d["ever_up"])
            failures = sum(d["fail"] for d in per_dev.values())
            uptime_h = up_samples * SAMPLE_S / 3600
            downtime_min = down_samples * SAMPLE_S / 60
            return {
                "mtbf_hours": round(uptime_h / failures, 1) if failures else None,
                "mttr_minutes": round(downtime_min / failures, 1) if failures else None,
                "failures": failures,
                "uptime_hours": round(uptime_h, 1),
                "downtime_minutes": round(downtime_min, 1),
                "period_days": days,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating reliability: {e}")
            return empty

    async def calculate_cost(self, hours: int = 24, price_per_kg: float = 25.0) -> dict:
        """Filament cost over the window from SpoolLog consumption.

        Filament-only (no labor/energy). price_per_kg is configurable via
        MEMAR_FILAMENT_COST_PER_KG (default $25/kg).
        """
        from .models_db import SpoolLog, JobLog

        empty = {"cost_total": 0.0, "cost_per_day": 0.0, "cost_per_part": None,
                 "filament_g": 0, "price_per_kg": price_per_kg, "period_hours": hours}
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            grams = (await self.db.execute(
                select(func.coalesce(func.sum(SpoolLog.filament_used_g), 0))
                .where(SpoolLog.created_at >= cutoff)
            )).scalar() or 0
            jobs = (await self.db.execute(
                select(func.count(JobLog.id)).where(JobLog.created_at >= cutoff)
            )).scalar() or 0
            cost_total = grams / 1000.0 * price_per_kg
            return {
                "cost_total": round(cost_total, 2),
                "cost_per_day": round(cost_total / hours * 24, 2) if hours else 0.0,
                "cost_per_part": round(cost_total / jobs, 2) if jobs else None,
                "filament_g": int(grams),
                "price_per_kg": price_per_kg,
                "period_hours": hours,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error calculating cost: {e}")
            return empty
