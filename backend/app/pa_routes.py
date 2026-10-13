"""Pressure Advance calibration routes.

Endpoints for initiating calibrations, retrieving results, storing metadata.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.deps import get_current_user, require_role
from app.pa_calibration import generate_pa_sweep_gcode
from app.pa_vision import analyze_calibration_image

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calibrate", tags=["calibration"])

# Validation for job_id format
_JOB_ID_PATTERN = re.compile(r"^pa-calibration-[0-9.]+$")
_PA_SWEEPS_DIR = Path("/tmp/pa-sweeps")


def _validate_job_id(job_id: str) -> str:
    """Validate job_id format and path safety."""
    if not _JOB_ID_PATTERN.match(job_id):
        raise HTTPException(400, "Invalid job_id format")
    # Ensure path stays within PA sweeps directory
    resolved = (_PA_SWEEPS_DIR / f"{job_id}.json").resolve()
    if not resolved.is_relative_to(_PA_SWEEPS_DIR.resolve()):
        raise HTTPException(400, "Invalid job_id path")
    return job_id


class PACalibrationRequest(BaseModel):
    """Request to start PA calibration on a printer."""
    printer_id: str
    pa_start: float = 0.0
    pa_end: float = 0.15
    pa_step: float = 0.01


class PACalibrationJobResponse(BaseModel):
    """Response after queueing a PA calibration job."""
    job_id: str
    printer_id: str
    status: str  # "queued"
    gcode_url: str
    metadata_url: str


@router.post("/pressure-advance", response_model=PACalibrationJobResponse)
async def start_pa_calibration(
    req: PACalibrationRequest,
    current_user: Annotated = Depends(require_role("admin")),
):
    """Generate and queue a PA calibration sweep.

    Steps:
    1. Generate G-code sweep
    2. Store G-code and metadata
    3. Queue as a normal print job
    4. Return job info
    """
    # Fail-closed: PA calibration queue not yet implemented
    raise HTTPException(501, "PA calibration queue not implemented")

    # TODO: fetch printer config from DB
    # For now, use defaults

    gcode, metadata = generate_pa_sweep_gcode(
        pa_start=req.pa_start,
        pa_end=req.pa_end,
        pa_step=req.pa_step,
    )

    # Store G-code and metadata
    job_id = f"pa-calibration-{datetime.now().timestamp()}"
    gcode_dir = Path("/tmp/pa-sweeps")  # TODO: use persistent storage
    gcode_dir.mkdir(exist_ok=True)

    gcode_file = gcode_dir / f"{job_id}.gcode"
    metadata_file = gcode_dir / f"{job_id}.json"

    gcode_file.write_text(gcode)
    metadata_file.write_text(json.dumps({
        "job_id": job_id,
        "printer_id": req.printer_id,
        "pa_start": metadata.pa_start,
        "pa_end": metadata.pa_end,
        "pa_step": metadata.pa_step,
        "layout": metadata.layout,
        "bands": [
            {
                "index": b.band_index,
                "pa": b.pa_value,
                "z": b.z_height_mm,
            }
            for b in metadata.bands
        ],
    }, indent=2))

    # TODO: integrate with Moonraker to queue the print
    logger.info(f"PA calibration queued: {job_id} on {req.printer_id}")

    return PACalibrationJobResponse(
        job_id=job_id,
        printer_id=req.printer_id,
        status="queued",
        gcode_url=f"/api/calibrate/gcode/{job_id}",
        metadata_url=f"/api/calibrate/metadata/{job_id}",
    )


@router.post("/pressure-advance/{job_id}/analyze")
async def analyze_pa_result(
    job_id: str,
    image: UploadFile = File(...),
    current_user: Annotated = Depends(require_role("admin")),
):
    """Upload and analyze a PA calibration print image.

    Steps:
    1. Save uploaded image
    2. Load metadata for this job
    3. Run vision analysis
    4. Store result in DB
    """
    # Validate job_id format first
    _validate_job_id(job_id)

    # Use safe filename to prevent path traversal
    safe_filename = Path(image.filename).name if image.filename else "image"

    # Save image
    image_dir = Path("/tmp/pa-results")  # TODO: persistent storage
    image_dir.mkdir(exist_ok=True)
    image_path = image_dir / f"{job_id}_{safe_filename}"

    # Verify path confinement
    if not image_path.resolve().is_relative_to(image_dir.resolve()):
        raise HTTPException(400, "Invalid filename - path traversal detected")

    contents = await image.read()
    image_path.write_bytes(contents)

    # Load metadata
    metadata_file = Path(f"/tmp/pa-sweeps/{job_id}.json")
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail=f"No metadata for {job_id}")

    metadata_dict = json.loads(metadata_file.read_text())

    # Run vision analysis
    try:
        result = analyze_calibration_image(
            image_path=str(image_path),
            band_metadata=metadata_dict,
        )
        result.job_id = job_id
    except ImportError as e:
        logger.warning(f"Vision module requires optional deps: {e}")
        raise HTTPException(
            status_code=501,
            detail="Vision analysis requires opencv-python, pillow, numpy. Install via: pip install -r requirements-optional.txt",
        )

    # TODO: store result in DB, return to user
    logger.info(f"PA analysis complete: {job_id}, recommended PA={result.recommended_pa}")

    return {
        "job_id": job_id,
        "recommended_pa": result.recommended_pa,
        "confidence": result.confidence,
        "analyses": [
            {
                "band_index": a.band_index,
                "pa": a.pa_value,
                "score": a.quality_score,
            }
            for a in result.band_analyses
        ],
    }


@router.get("/pressure-advance/{job_id}/metadata")
async def get_pa_metadata(
    job_id: str,
    current_user: Annotated = Depends(get_current_user),
):
    """Fetch stored metadata for a PA calibration job."""
    _validate_job_id(job_id)
    metadata_file = Path(f"/tmp/pa-sweeps/{job_id}.json")
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail=f"No metadata for {job_id}")
    return json.loads(metadata_file.read_text())


@router.get("/pressure-advance/{job_id}/gcode")
async def get_pa_gcode(
    job_id: str,
    current_user: Annotated = Depends(get_current_user),
):
    """Fetch the G-code for a PA calibration job."""
    _validate_job_id(job_id)
    gcode_file = Path(f"/tmp/pa-sweeps/{job_id}.gcode")
    if not gcode_file.exists():
        raise HTTPException(status_code=404, detail=f"No G-code for {job_id}")
    return {
        "job_id": job_id,
        "gcode": gcode_file.read_text(),
    }
