"""FastAPI routes for motion estimation and calibration."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .deps import get_db, require_role
from .motion_estimator import (
    MotionSimulator,
    PrinterConfig,
    GCodeParser,
    estimate_print_time,
)
from .models_db import Base

logger = logging.getLogger(__name__)

# Dependency gate — require_role takes *roles as varargs
# Used as: require_role("admin", "operator")


router = APIRouter(prefix="/api/motion", tags=["Motion Estimation"])


@router.post(
    "/estimate",
    dependencies=[Depends(require_role("admin", "operator"))],
    summary="Estimate print time from G-code",
)
async def estimate_from_gcode(
    file: UploadFile = File(...),
    max_velocity: float = 120.0,
    max_accel: float = 500.0,
    nozzle_diameter_mm: float = 0.4,
) -> dict[str, Any]:
    """POST G-code file to get physics-based time estimate.

    Uses Klipper trapezoidal motion model (Cartesian kinematics).

    Query params:
      - max_velocity: printer max speed (mm/s), default 120
      - max_accel: printer max accel (mm/s²), default 500
      - nozzle_diameter_mm: nozzle size, default 0.4

    Returns:
      {
        "estimated_time_s": 1234.5,
        "estimated_time_min": 20.6,
        "total_distance_mm": 5000.0,
        "total_segments": 450,
        "avg_speed_mm_s": 6.7,
        "avg_accel_phase_pct": 15.2,
        "config": {printer config used}
      }
    """
    try:
        content = await file.read()
        gcode_text = content.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read G-code file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read G-code file",
        ) from e

    config = PrinterConfig(
        max_velocity=max_velocity,
        max_accel=max_accel,
        nozzle_diameter_mm=nozzle_diameter_mm,
    )

    try:
        total_time_s, summary = estimate_print_time(gcode_text, config)
    except Exception as e:
        logger.error(f"Motion estimation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Motion estimation failed",
        ) from e

    return {
        "estimated_time_s": total_time_s,
        "estimated_time_min": total_time_s / 60.0,
        **summary,
        "config": config.to_dict(),
    }


@router.post(
    "/calibrate",
    dependencies=[Depends(require_role("admin", "operator"))],
    summary="Calibrate motion model from job history",
)
async def calibrate_model(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calibrate motion estimator from job_log.

    Compares predicted (from motion model) vs actual times.
    Returns calibration statistics.

    NOTE: job_log table must be populated from printer webhooks.
    """
    # TODO: Implement full calibration loop
    # 1. Query job_log for completed jobs with gcode_path
    # 2. For each job: re-estimate with motion model
    # 3. Compute error (predicted vs actual)
    # 4. Fit systematic offset / scale factor
    # 5. Return coefficients

    return {
        "status": "not_implemented",
        "message": "Calibration requires job_log population and gcode archival",
        "next_step": "Populate job_log via print_monitor webhook handler",
    }


@router.get(
    "/health",
    dependencies=[Depends(require_role("admin", "operator", "viewer"))],
    summary="Motion estimation service status",
)
async def health() -> dict[str, Any]:
    """Health check for motion estimation."""
    return {
        "status": "ok",
        "service": "motion_estimator",
        "version": "0.1.0",
    }
