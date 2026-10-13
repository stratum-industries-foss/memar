"""Analytics and reporting API endpoints."""

import os
import re
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

# Email validation regex and allowed recipients for report endpoints
_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _get_allowed_report_recipients() -> list[str]:
    """Get allowed recipient emails from MEMAR_ALERT_EMAILS env var."""
    raw = os.getenv("MEMAR_ALERT_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _validate_report_recipient(email: str, allowed: list[str]) -> str:
    """Validate a report recipient email against format and allowed list."""
    if not _EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if email.lower() not in allowed:
        raise HTTPException(status_code=403, detail="Recipient not in allowed list")
    return email

from .analytics import FleetKPICalculator
from .coolant_models import CoolantDepletionPredictor
from .email_reports import MonthlyReportGenerator
from .deps import get_current_user, require_feature, require_role
from .license import get_license
from .oee import _aggregate_fleet_oee

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Single-entry 2s TTL cache — shields the per-printer _calc_oee fan-out behind
# /fleet-kpi from dashboard poll storms (mirrors cnc_routes.py's cache pattern).
_fleet_kpi_cache: tuple[dict, float] | None = None
_FLEET_KPI_TTL_S = 2.0


@router.get("/fleet-kpi")
async def get_fleet_kpi_snapshot(db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user), __: None = Depends(require_feature("oee"))):
    """At-a-glance fleet KPI snapshot for the dashboard strip (2s cached).

    Always returns utilization / error-rate / throughput / reliability / cost /
    downtime-pareto. The OEE block is additionally license-gated (feature "oee"):
    null when the feature is off, so the dashboard strip fails soft.
    """
    global _fleet_kpi_cache
    now = time.monotonic()
    if _fleet_kpi_cache and (now - _fleet_kpi_cache[1]) < _FLEET_KPI_TTL_S:
        return {**_fleet_kpi_cache[0], "cached": True}

    calc = FleetKPICalculator(db)
    util = await calc.calculate_utilization(hours=24)
    errr = await calc.calculate_error_rate(hours=24)
    thru = await calc.calculate_throughput(hours=24)
    rel = await calc.calculate_reliability(days=7)
    try:
        price = float(os.getenv("MEMAR_FILAMENT_COST_PER_KG", "25"))
    except ValueError:
        price = 25.0
    cost = await calc.calculate_cost(hours=24, price_per_kg=price)
    pareto = await calc.get_top_error_modes(limit=5)
    trend = await calc.calculate_oee_trend(days=7)

    lic = get_license()
    oee_block = None
    if lic.active and "oee" in (lic.features or []):
        oee_block = await _aggregate_fleet_oee()
        if oee_block.get("fleet_oee") is not None:
            oee_block["teep"] = round(
                oee_block["fleet_oee"] * (util.get("utilization_pct", 0) / 100.0), 4
            )

    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "oee": oee_block,
        "utilization_pct": util.get("utilization_pct"),
        "error_rate_pct": errr.get("error_rate_pct"),
        "throughput": thru,
        "reliability": rel,
        "cost": cost,
        "downtime_pareto": pareto,
        "oee_trend": [{"date": d["date"], "oee": d["oee"], "job_count": d.get("job_count", 0)} for d in trend],
        "cached": False,
    }
    _fleet_kpi_cache = (payload, now)
    return payload


@router.get("/kpi")
async def get_fleet_kpi(db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user), __: None = Depends(require_feature("oee")), device_id: str | None = Query(None)):
    """Fleet-level or device-specific KPI snapshot. If device_id is provided, returns per-device OEE trend."""
    calc = FleetKPICalculator(db)
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "utilization": await calc.calculate_utilization(hours=24),
        "oee_trend": await calc.calculate_oee_trend(days=7, device_id=device_id),
        "error_rate": await calc.calculate_error_rate(hours=24),
        "coolant": await calc.get_coolant_stats(),
        "top_errors": await calc.get_top_error_modes(limit=5),
    }


@router.get("/coolant-depletion")
async def get_coolant_depletion(db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user), __: None = Depends(require_feature("oee"))):
    """Coolant depletion analysis for all CNC devices."""
    predictor = CoolantDepletionPredictor(db)
    fleet_analysis = await predictor.analyze_fleet()
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "devices": [a.model_dump() for a in fleet_analysis],
        "critical_count": sum(1 for a in fleet_analysis if a.status == "critical"),
        "declining_count": sum(1 for a in fleet_analysis if a.status == "declining"),
        "healthy_count": sum(1 for a in fleet_analysis if a.status == "healthy"),
    }


@router.get("/reports/monthly-pdf")
async def get_monthly_pdf(year: int, month: int, db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user), __: None = Depends(require_feature("oee"))):
    """Download monthly PDF report."""
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="Invalid month")
    if year < 2020 or year > 2100:
        raise HTTPException(status_code=400, detail="Invalid year")

    generator = MonthlyReportGenerator(db)
    html = await generator.generate_html_report(year, month)

    return {
        "success": True,
        "report_type": "monthly",
        "period": f"{year}-{month:02d}",
        "generated_at": datetime.utcnow().isoformat(),
        "html": html  # Frontend can render or convert to PDF
    }


@router.post("/reports/send-monthly")
async def send_monthly_report(
    recipient_email: str,
    year: int = None,
    month: int = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    _: None = Depends(require_feature("oee")),
    __: None = Depends(require_role("admin")),
):
    """Manually trigger monthly report email."""
    # Validate recipient against allowed list
    allowed = _get_allowed_report_recipients()
    _validate_report_recipient(recipient_email, allowed)

    # Default to current month if not specified
    now = datetime.utcnow()
    year = year or now.year
    month = month or now.month

    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="Invalid month")

    generator = MonthlyReportGenerator(db)
    success = await generator.send_email(recipient_email, year, month)

    return {
        "success": success,
        "recipient": recipient_email,
        "period": f"{year}-{month:02d}",
        "message": "Report sent successfully" if success else "Failed to send report"
    }


@router.post("/reports/send-bulk")
async def send_bulk_reports(
    recipient_list: list[str],
    year: int = None,
    month: int = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    _: None = Depends(require_feature("oee")),
    __: None = Depends(require_role("admin")),
):
    """Send monthly reports to multiple recipients."""
    # Validate all recipients against allowed list
    allowed = _get_allowed_report_recipients()
    for email in recipient_list:
        _validate_report_recipient(email, allowed)

    now = datetime.utcnow()
    year = year or now.year
    month = month or now.month

    generator = MonthlyReportGenerator(db)
    results = await generator.send_bulk_monthly_reports(year, month, recipient_list)

    return {
        "success": results["failed"] == 0,
        "summary": results,
        "period": f"{year}-{month:02d}"
    }
