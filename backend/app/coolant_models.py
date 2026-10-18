"""Coolant PSI depletion tracking and failure prediction.

Async rewrite: device identity/names come from config (devices.yaml); PSI history
comes from CNCMetricsLog. NOTE: no shipped adapter currently reports coolant_psi
(adapters expose coolant_active on/off), so analyze_device returns status
"no_data" until a real pressure-sensor source is wired. The math below is ready
for that source.
"""

from .timeutil import utcnow as _utcnow
import logging
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CNC_MACHINE_TYPES = {"cnc_mill", "cnc_lathe", "cnc_router", "wire_edm", "plasma", "waterjet", "laser"}


class CoolantDepletionAnalysis(BaseModel):
    """Coolant depletion status for a single device."""
    device_id: str
    device_name: Optional[str] = None
    current_psi: float
    psi_24h_ago: Optional[float] = None
    depletion_rate_psi_per_hour: Optional[float] = None
    hours_to_depletion: Optional[float] = None
    days_to_depletion: Optional[float] = None
    alert_triggered: bool = False
    status: str  # "healthy", "declining", "critical", "no_data", "error"


def _config_devices() -> dict[str, str]:
    """Map device_id -> name from config (single source of identity)."""
    from .config import get_config
    return {p.id: p.name for p in get_config().printers if p.enabled}


def _config_cnc_device_ids() -> list[str]:
    """Enabled CNC-class device ids from config."""
    from .config import get_config
    return [
        p.id for p in get_config().printers
        if p.enabled and str(getattr(p.machine_type, "value", p.machine_type)) in _CNC_MACHINE_TYPES
    ]


class CoolantDepletionPredictor:
    """Predict when coolant will be depleted."""

    LOW_PSI_THRESHOLD = 20  # PSI below which coolant change is mandatory
    WARNING_THRESHOLD = 7   # Days to depletion before alert

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_device(self, device_id: str, device_name: Optional[str] = None) -> CoolantDepletionAnalysis:
        """Analyze coolant depletion for one CNC device."""
        from .models_db import CNCMetricsLog

        if device_name is None:
            device_name = _config_devices().get(device_id, device_id)

        try:
            current = (await self.db.execute(
                select(CNCMetricsLog)
                .where(
                    CNCMetricsLog.device_id == device_id,
                    CNCMetricsLog.coolant_psi.isnot(None),
                )
                .order_by(CNCMetricsLog.timestamp.desc())
                .limit(1)
            )).scalar_one_or_none()

            if not current or current.coolant_psi is None:
                return CoolantDepletionAnalysis(
                    device_id=device_id, device_name=device_name,
                    current_psi=0, status="no_data",
                )

            cutoff = _utcnow() - timedelta(hours=24)
            past = (await self.db.execute(
                select(CNCMetricsLog)
                .where(
                    CNCMetricsLog.device_id == device_id,
                    CNCMetricsLog.coolant_psi.isnot(None),
                    CNCMetricsLog.timestamp <= cutoff,
                )
                .order_by(CNCMetricsLog.timestamp.desc())
                .limit(1)
            )).scalar_one_or_none()

            depletion_rate = None
            hours_to_depletion = None
            if past and past.coolant_psi is not None:
                depletion_rate = (past.coolant_psi - current.coolant_psi) / 24
                if depletion_rate > 0:
                    psi_until_critical = current.coolant_psi - self.LOW_PSI_THRESHOLD
                    if psi_until_critical > 0:
                        hours_to_depletion = psi_until_critical / depletion_rate

            if current.coolant_psi < self.LOW_PSI_THRESHOLD:
                status, alert = "critical", True
            elif depletion_rate and depletion_rate > 2.0:
                status = "declining"
                alert = (hours_to_depletion is None or hours_to_depletion < 168)
            else:
                status, alert = "healthy", False

            days_to_depletion = (hours_to_depletion / 24) if hours_to_depletion else None

            return CoolantDepletionAnalysis(
                device_id=device_id,
                device_name=device_name,
                current_psi=round(current.coolant_psi, 1),
                psi_24h_ago=round(past.coolant_psi, 1) if past else None,
                depletion_rate_psi_per_hour=round(depletion_rate, 2) if depletion_rate else None,
                hours_to_depletion=round(hours_to_depletion, 1) if hours_to_depletion else None,
                days_to_depletion=round(days_to_depletion, 1) if days_to_depletion else None,
                alert_triggered=alert,
                status=status,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error analyzing device {device_id}: {e}")
            return CoolantDepletionAnalysis(device_id=device_id, device_name=device_name, current_psi=0, status="error")

    async def analyze_fleet(self) -> list[CoolantDepletionAnalysis]:
        """Analyze all CNC devices in the fleet (identity from config)."""
        try:
            names = _config_devices()
            return [await self.analyze_device(did, names.get(did)) for did in _config_cnc_device_ids()]
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error analyzing fleet: {e}")
            return []
