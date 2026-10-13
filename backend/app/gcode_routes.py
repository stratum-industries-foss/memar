"""
NOT MOUNTED — stubs return fake success.

Gcode command routes: M220 (speed), M221 (flow), babystep (Z-offset).
Provides REST endpoints for real-time printer control during active prints.

POST /api/printers/{printerId}/gcode/speed
POST /api/printers/{printerId}/gcode/flow
POST /api/printers/{printerId}/gcode/babystep
GET /api/printers/{printerId}/metrics
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import logging
from datetime import datetime, timezone

from .db import get_db
from .auth import get_current_user
from .deps import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/printers", tags=["gcode"])


# ============================================================================
# Request/Response Models
# ============================================================================

class SpeedAdjustRequest(BaseModel):
    """M220 S{speed} command request."""
    speed: int = Field(ge=10, le=200, description="Speed percentage (10-200%)")


class SpeedAdjustResponse(BaseModel):
    """Response after applying M220 command."""
    success: bool
    appliedSpeed: int
    previousSpeed: Optional[int]
    command: str
    timestamp: str


class FlowAdjustRequest(BaseModel):
    """M221 S{flow} command request."""
    flow: int = Field(ge=10, le=200, description="Flow percentage (10-200%)")


class FlowAdjustResponse(BaseModel):
    """Response after applying M221 command."""
    success: bool
    appliedFlow: int
    previousFlow: Optional[int]
    command: str
    timestamp: str


class BabystepRequest(BaseModel):
    """G91 G0 Z{delta} babystep command request."""
    delta: float = Field(ge=-5.0, le=5.0, description="Z offset delta in mm")
    absolute: bool = Field(default=False, description="If true, treat delta as absolute offset")


class BabystepResponse(BaseModel):
    """Response after applying babystep command."""
    success: bool
    appliedDelta: float
    newOffset: float
    sessionOffset: float
    command: str
    timestamp: str


class TemperatureDataPoint(BaseModel):
    """Single temperature measurement."""
    timestamp: int  # Unix ms
    nozzle: float
    bed: float
    ambient: Optional[float] = None


class MetricsResponse(BaseModel):
    """Temperature metrics response."""
    printerId: str
    dataPoints: List[TemperatureDataPoint]
    count: int
    range: str
    resolution: str


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/{printerId}/gcode/speed", response_model=SpeedAdjustResponse)
async def set_speed(
    printerId: str,
    request: SpeedAdjustRequest,
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply M220 (speed) adjustment to printer.

    - **printerId**: Target printer UUID
    - **speed**: New speed percentage (10-200%)

    Returns applied speed, previous value, and gcode command sent.
    """
    # TODO: Implement:
    # 1. Verify printer ownership (user has access)
    # 2. Check printer is online/connected
    # 3. Get current speed from printer state (if available)
    # 4. Send M220 S{speed} to printer (via Moonraker or direct)
    # 5. Log to audit trail
    # 6. Return response

    return {
        "success": True,
        "appliedSpeed": request.speed,
        "previousSpeed": None,
        "command": f"M220 S{request.speed}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{printerId}/gcode/flow", response_model=FlowAdjustResponse)
async def set_flow(
    printerId: str,
    request: FlowAdjustRequest,
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply M221 (flow) adjustment to printer.

    - **printerId**: Target printer UUID
    - **flow**: New flow percentage (10-200%)

    Returns applied flow, previous value, and gcode command sent.
    """
    # TODO: Same as set_speed, but for M221

    return {
        "success": True,
        "appliedFlow": request.flow,
        "previousFlow": None,
        "command": f"M221 S{request.flow}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{printerId}/gcode/babystep", response_model=BabystepResponse)
async def babystep(
    printerId: str,
    request: BabystepRequest,
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply Z-offset micro-adjustment (babystep).

    - **printerId**: Target printer UUID
    - **delta**: Incremental Z offset in mm (±5.0 range)
    - **absolute**: If true, treat delta as absolute offset (default: false)

    For incremental (absolute=false):
        Sends: G91 G0 Z{delta} F300 G90

    For absolute (absolute=true):
        Sends: G90 G0 Z{value} F300

    Also persists new offset to printer config (Klipper/Moonraker).

    Returns applied delta, new total offset, and session offset.
    """
    # TODO: Implement:
    # 1. Verify printer is actively printing (babystep only during print)
    # 2. Get current session offset
    # 3. If incremental: newOffset = currentOffset + delta
    # 4. If absolute: newOffset = delta
    # 5. Validate newOffset is within bounds
    # 6. Send G91 G0 Z{delta} F300 G90 to printer
    # 7. Persist offset to printer config
    # 8. Track session offset separately
    # 9. Log to audit trail

    return {
        "success": True,
        "appliedDelta": request.delta,
        "newOffset": 0.0 + request.delta,
        "sessionOffset": request.delta,
        "command": f"G91\nG0 Z{request.delta} F300\nG90",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{printerId}/metrics", response_model=MetricsResponse)
async def get_metrics(
    printerId: str,
    range: int = Query(60, ge=15, le=120, description="Minutes of data to return"),
    startTime: Optional[int] = Query(None, description="Unix ms start time (overrides range)"),
    endTime: Optional[int] = Query(None, description="Unix ms end time (overrides range)"),
    fields: Optional[str] = Query(None, description="Comma-separated fields (temperature, humidity, etc)"),
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch temperature metrics for printer.

    - **range**: Minutes of historical data (15, 30, 60, 120)
    - **startTime**: Optional Unix ms start (overrides range)
    - **endTime**: Optional Unix ms end (overrides range)
    - **fields**: Optional CSV filter (e.g., "nozzle,bed")

    Returns time-sorted array of temperature data points.

    TODO: Implement:
    1. Query metrics database/cache (Redis, TimescaleDB, InfluxDB, etc)
    2. Apply time range filter
    3. Downsample if >1000 points (compute moving average)
    4. Filter by requested fields
    5. Return time-sorted array
    """

    return {
        "printerId": printerId,
        "dataPoints": [],
        "count": 0,
        "range": f"{range}m",
        "resolution": "1s",
    }


# ============================================================================
# Error Handlers
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    status: Optional[str] = None
    code: Optional[int] = None


# Usage:
# raise HTTPException(status_code=404, detail=ErrorResponse(error="Printer not found").dict())
# raise HTTPException(status_code=403, detail=ErrorResponse(error="Access denied").dict())
# raise HTTPException(status_code=400, detail=ErrorResponse(error="Invalid speed").dict())
# raise HTTPException(status_code=503, detail=ErrorResponse(error="Printer offline", status="disconnected").dict())
