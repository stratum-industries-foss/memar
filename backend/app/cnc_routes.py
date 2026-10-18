"""CNC machine metrics endpoints (GRBL, LinuxCNC, MACH3, OPC-UA, Sinumerik)."""

from .timeutil import utcnow as _utcnow
import asyncio
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_config
from .deps import get_current_user, require_alpha_ack, require_role
from .db import get_db
from .models_db import AlphaControlAck, CNCMetricsLog
from .models import CNCMetrics, CNCPosition
from .grbl import GRBLClient
from .linuxcnc import LinuxCNCClient
from .mach3 import MACH3Client
from .opcua import OPCUAClient
from .sinumerik import SinumerikClient
from .haas import HaasAdapter
from .fanuc import FANUCAdapter
from .fadal import FadalAdapter
from .mach4 import MACH4Adapter
from .fluidnc import FluidNCClient
from .models import ALPHA_PROTOCOLS, PrinterConfig, Protocol
from .cnc_metrics import CNCMetricsAggregator
from .telemetry import SAMPLE_INTERVAL_S
from .cnc_webhooks import detect_cnc_anomalies
from .webhooks import publish_event
from .audit import record_audit

router = APIRouter(tags=["cnc"])

# Simple in-memory cache for metrics (TTL: 2 seconds)
_metrics_cache: dict[str, tuple[CNCMetrics, datetime]] = {}
_CACHE_TTL_SECONDS = 2


def _get_cached_metrics(device_id: str) -> CNCMetrics | None:
    """Retrieve metrics from cache if still valid."""
    if device_id in _metrics_cache:
        metrics, timestamp = _metrics_cache[device_id]
        if (datetime.now() - timestamp).total_seconds() < _CACHE_TTL_SECONDS:
            return metrics
        else:
            del _metrics_cache[device_id]
    return None


def _cache_metrics(device_id: str, metrics: CNCMetrics) -> None:
    """Store metrics in cache with timestamp."""
    _metrics_cache[device_id] = (metrics, datetime.now())


def _get_cnc_client(printer: PrinterConfig):
    """Factory: return the correct CNC adapter for the printer's protocol."""
    if printer.protocol == Protocol.GRBL:
        return GRBLClient(printer)
    elif printer.protocol == Protocol.LINUXCNC:
        return LinuxCNCClient(printer)
    elif printer.protocol == Protocol.MACH3:
        return MACH3Client(printer)
    elif printer.protocol == Protocol.OPCUA:
        return OPCUAClient(printer)
    elif printer.protocol == Protocol.SINUMERIK:
        return SinumerikClient(printer)
    elif printer.protocol == Protocol.HAAS:
        return HaasAdapter(printer)
    elif printer.protocol == Protocol.FANUC:
        return FANUCAdapter(printer)
    elif printer.protocol == Protocol.FADAL:
        return FadalAdapter(printer)
    elif printer.protocol == Protocol.MACH4:
        return MACH4Adapter(printer)
    elif printer.protocol == Protocol.FLUIDNC:
        return FluidNCClient(printer)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Device {printer.id} does not support CNC metrics (protocol: {printer.protocol})"
        )


async def _safe_disconnect(client) -> None:
    """Best-effort close of a per-request adapter.

    Adapters open sockets / httpx clients in __init__ (e.g. GRBL, FluidNC) or
    lazily (OPC-UA). They are built fresh per request in _get_cnc_client and
    never reused, so failing to close them churns/leaks fds until exhaustion.
    Never raises — cleanup must not turn a good response into a 502.
    """
    disc = getattr(client, "disconnect", None)
    if disc is None:
        return
    try:
        await disc()
    except Exception:
        pass


def _normalize_adapter_result(result: dict) -> dict:
    """Normalize adapter response to consistent {ok, response, error} format."""
    if not result:
        return {"ok": False, "error": "No response from adapter"}
    
    # Normalize error field
    error = result.get("error") or result.get("message") or result.get("error_msg")
    if error and "error" not in result:
        result["error"] = error
    
    return result


async def _record_alpha_dispatch_if_applicable(
    db: AsyncSession, printer: PrinterConfig, user: dict, request: Request,
) -> None:
    """Log a distinct, independently-queryable audit row for any control
    dispatch to an ALPHA_PROTOCOLS device — alongside, not instead of, the
    route's own action-specific audit entry. Called from every gated route's
    finally block plus e-stop (which is never gated, but is still the
    highest-risk action in the system and deserves the same trail)."""
    if printer.protocol not in ALPHA_PROTOCOLS:
        return
    await record_audit(
        db,
        action="alpha_control_dispatch",
        user=user,
        resource=f"device:{printer.id}",
        detail={"alpha": True, "protocol": printer.protocol.value},
        request=request,
    )


async def _get_cnc_metrics(printer: PrinterConfig) -> CNCMetrics:
    """Fetch current metrics from a CNC machine."""
    client = _get_cnc_client(printer)
    try:
        state = await client.get_machine_state()
    finally:
        await _safe_disconnect(client)

    # Convert adapter status to CNCMetrics
    return CNCMetrics(
        spindle_rpm=state.spindle_rpm_current,
        feed_rate_mm_min=state.feed_rate_mm_min,
        position_xyz=CNCPosition(
            x=state.position_xyz.get("x", 0.0) if isinstance(state.position_xyz, dict) else getattr(state.position_xyz, "x", 0.0),
            y=state.position_xyz.get("y", 0.0) if isinstance(state.position_xyz, dict) else getattr(state.position_xyz, "y", 0.0),
            z=state.position_xyz.get("z", 0.0) if isinstance(state.position_xyz, dict) else getattr(state.position_xyz, "z", 0.0),
        ),
        machine_state=state.state,
        tool_id=state.tool_id,
        coolant_active=state.coolant_active,
    )


@router.get("/api/devices/{device_id}/metrics/cnc")
async def get_cnc_metrics(
    device_id: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Get real-time CNC metrics (spindle RPM, feed rate, position, state).

    Response:
        {
            "spindle_rpm": int,
            "feed_rate_mm_min": float,
            "position_xyz": {"x": float, "y": float, "z": float},
            "machine_state": str,
            "tool_id": str | null,
            "coolant_active": bool,
            "cached": bool,
            "timestamp": str (ISO 8601)
        }
    """
    cfg = get_config()
    printer = next((p for p in cfg.printers if p.id == device_id and p.enabled), None)
    if not printer:
        raise HTTPException(status_code=404, detail="Device not found")

    # Try cache first
    cached = _get_cached_metrics(device_id)
    if cached:
        return {
            **cached.model_dump(),
            "cached": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Fetch from device
    try:
        metrics = await _get_cnc_metrics(printer)
        _cache_metrics(device_id, metrics)

        # Detect anomalies and publish events (fire-and-forget)
        state_dict = {
            "state": metrics.machine_state,
            "spindle_rpm_current": metrics.spindle_rpm,
            "feed_rate_mm_min": metrics.feed_rate_mm_min,
            "tool_id": metrics.tool_id,
            "coolant_active": metrics.coolant_active,
        }
        asyncio.create_task(detect_cnc_anomalies(printer, state_dict, publish_event))

        return {
            **metrics.model_dump(),
            "cached": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        # Preserve client-side statuses (e.g. 400 "device does not support CNC
        # metrics" for Moonraker/FDM printers) — don't mask them as 502.
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch metrics: {str(e)}")


@router.put("/api/devices/{device_id}/feed-rate/{rate}")
async def set_feed_rate(
    device_id: str,
    rate: float,
    _: dict = Depends(require_role("admin", "operator")),
    __: dict = Depends(require_alpha_ack),
) -> dict:
    """Set feed rate on a CNC machine.

    For ALPHA_PROTOCOLS adapters (Haas/Fanuc/Fadal/Mach4), require_alpha_ack
    already 403'd here unless the user acknowledged the liability warning —
    their set_feed_rate() treats the value as an already-computed 0-200%
    override, not the mm/min this route validates and advertises. The
    acknowledgment copy names this ambiguity explicitly rather than guessing
    a conversion (see each adapter's own "do not wire this to a live route"
    docstring in fanuc.py/fadal.py/haas.py/mach4.py for the underlying caveat).
    """
    cfg = get_config()
    printer = next((p for p in cfg.printers if p.id == device_id and p.enabled), None)
    if not printer:
        raise HTTPException(status_code=404, detail="Device not found")

    if not (0.0 < rate <= 500.0):
        raise HTTPException(status_code=400, detail="Feed rate must be 0-500 mm/min")

    client = None
    try:
        client = _get_cnc_client(printer)

        # Most adapters support set_feed_rate, but not all
        # Check if the method exists and is callable
        if not hasattr(client, 'set_feed_rate') or not callable(getattr(client, 'set_feed_rate')):
            raise HTTPException(
                status_code=400,
                detail=f"Feed rate adjustment not supported for {printer.protocol}"
            )

        result = await client.set_feed_rate(rate)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
        if result.get("ok"):
            return {"ok": True, "new_feed_rate": rate}
        else:
            raise HTTPException(
                status_code=502,
                detail="Failed to set feed rate on device"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to set feed rate: {str(e)}")
    finally:
        if client is not None:
            await _safe_disconnect(client)


@router.get("/api/devices/{device_id}/metrics/cnc/aggregated")
async def get_cnc_metrics_aggregated(
    device_id: str,
    minutes: int = 60,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get aggregated CNC metrics over a time window.

    Reads from the persisted ``cnc_metrics_log`` history (written by the
    telemetry sampler every monitor interval) and aggregates it in-memory.
    This returns immediately — it does NOT poll the live machine for the
    duration of the window (the old behaviour blocked the request for the
    full ``minutes``, timing out every HTTP client).

    Query Parameters:
        minutes: Lookback window (default 60 min), 1-120 min

    Response keys consumed by the frontend CNCMetricsPanel:
        device_id, device_name, spindle_utilization_pct, production_time_hours,
        idle_time_hours, downtime_hours, tool_changes, coolant_flow_hours,
        avg_feed_rate_mm_min, max_feed_rate_mm_min, max_spindle_rpm,
        window_minutes, timestamp
    """
    cfg = get_config()
    printer = next((p for p in cfg.printers if p.id == device_id and p.enabled), None)
    if not printer:
        raise HTTPException(status_code=404, detail="Device not found")

    if minutes < 1 or minutes > 120:
        raise HTTPException(
            status_code=400,
            detail="Time window must be 1-120 minutes"
        )

    try:
        # cnc_metrics_log timestamps are written via SQL server_default now()
        # (UTC on SQLite) — filter against utcnow() to match.
        cutoff = _utcnow() - timedelta(minutes=minutes)
        rows = (await db.execute(
            select(CNCMetricsLog)
            .where(
                CNCMetricsLog.device_id == device_id,
                CNCMetricsLog.timestamp >= cutoff,
            )
            .order_by(CNCMetricsLog.timestamp.asc())
        )).scalars().all()

        history = [
            {
                "timestamp": r.timestamp,
                "state": r.machine_state or "offline",
                "spindle_rpm_current": r.spindle_rpm or 0,
                "feed_rate_mm_min": r.feed_rate_mm_min or 0.0,
                "coolant_active": bool(r.coolant_active),
                "tool_id": r.tool_id,
            }
            for r in rows
        ]

        # Must match the telemetry sampler's real cadence (SAMPLE_INTERVAL_S=60):
        # the aggregator scales covered time by this interval, so a wrong value
        # mis-scales production/idle/downtime hours (5 vs 60 → 12x under-report).
        aggregator = CNCMetricsAggregator(sample_interval_seconds=SAMPLE_INTERVAL_S)
        metrics = await aggregator.aggregate_static(history, duration_minutes=minutes)
        return {
            **metrics,
            "device_id": device_id,
            "device_name": printer.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to aggregate metrics: {str(e)}"
        )


# ── Motion control routes (admin-only: gcode, home, e-stop) ─────────────────
#
# These call through to the adapters' send_gcode/home_axes/emergency_stop,
# which move real hardware. Gated stricter than the read/rate routes above
# (require_role("admin") instead of any-authenticated-user) and every call is
# audit-logged. emergency_stop intentionally carries NO rate-limit decorator
# — see _limiter.py: rate limiting here is opt-in per-route, so simply never
# opting E-stop in is sufficient to guarantee it's never throttled.


class GCodeRequest(BaseModel):
    code: str = Field(max_length=240)

    @field_validator('code')
    @classmethod
    def no_multiline(cls, v: str) -> str:
        if '\n' in v or '\r' in v:
            raise ValueError('Multiline G-code not allowed')
        return v.strip()


class HomeAxesRequest(BaseModel):
    axes: list[str] | None = None  # None = home all axes (adapter default "XYZ")


class CNCJogRequest(BaseModel):
    axis: Literal["X", "Y", "Z", "A", "B", "C"]
    distance: float = Field(..., gt=-500, lt=500)
    feedrate: float | None = Field(default=None, gt=0, le=6000)
    relative: bool = True


def _get_enabled_printer_or_404(device_id: str) -> PrinterConfig:
    cfg = get_config()
    printer = next((p for p in cfg.printers if p.id == device_id and p.enabled), None)
    if not printer:
        raise HTTPException(status_code=404, detail="Device not found")
    return printer


@router.post("/api/devices/{device_id}/cnc/alpha-ack")
async def ack_alpha_control(
    device_id: str,
    current_user: dict = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge the alpha-adapter liability warning for one device.

    Upserts one AlphaControlAck(user_id, device_id) row — same
    check-then-insert-if-missing idempotency pattern as ack_anomaly in
    main.py. Never auto-expires; unlike an anomaly ack, the underlying risk
    (unverified hardware bridge) doesn't clear on its own. Role-matched to
    the routes it unlocks (feed-rate/gcode/home/jog all require admin or
    operator), not admin-only, so an operator can self-serve past the gate.
    """
    _get_enabled_printer_or_404(device_id)  # 404 if the device isn't in the fleet config
    existing = (await db.execute(
        select(AlphaControlAck).where(
            AlphaControlAck.user_id == current_user["id"],
            AlphaControlAck.device_id == device_id,
        )
    )).scalar_one_or_none()
    if existing is None:
        new_ack = AlphaControlAck(user_id=current_user["id"], device_id=device_id)
        db.add(new_ack)
        await db.commit()
        await db.refresh(new_ack)
        acked_at = new_ack.acked_at
    else:
        acked_at = existing.acked_at
    return {"ok": True, "acked_at": acked_at.isoformat() if acked_at else None}


@router.post("/api/devices/{device_id}/cnc/gcode")
async def send_cnc_gcode(
    device_id: str,
    body: GCodeRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    _: dict = Depends(require_alpha_ack),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send an MDI G-code line to a CNC machine (admin only — physical motion)."""
    printer = _get_enabled_printer_or_404(device_id)

    code = body.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="G-code command cannot be empty")

    client = None
    try:
        client = _get_cnc_client(printer)
        result = await client.send_gcode(code)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to send G-code: {str(e)}")
    finally:
        await record_audit(
            db,
            action="cnc_send_gcode",
            user=current_user,
            resource=f"device:{device_id}",
            detail={"code": code},
            request=request,
        )
        await _record_alpha_dispatch_if_applicable(db, printer, current_user, request)
        if client is not None:
            await _safe_disconnect(client)

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error") or "Device rejected the G-code command",
        )
    return {"ok": True, "response": result.get("response")}


@router.post("/api/devices/{device_id}/cnc/home")
async def home_cnc_axes(
    device_id: str,
    body: HomeAxesRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    _: dict = Depends(require_alpha_ack),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Home CNC axes (admin only — physical motion). Body {"axes": null} homes all axes."""
    printer = _get_enabled_printer_or_404(device_id)

    axes_str = "".join(a.strip().upper() for a in body.axes) if body.axes else "XYZ"
    if not axes_str or any(c not in "XYZABC" for c in axes_str):
        raise HTTPException(status_code=400, detail="axes must contain only X, Y, Z, A, B, C")

    client = None
    try:
        client = _get_cnc_client(printer)
        result = await client.home_axes(axes_str)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to home axes: {str(e)}")
    finally:
        await record_audit(
            db,
            action="cnc_home_axes",
            user=current_user,
            resource=f"device:{device_id}",
            detail={"axes": axes_str},
            request=request,
        )
        await _record_alpha_dispatch_if_applicable(db, printer, current_user, request)
        if client is not None:
            await _safe_disconnect(client)

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("response") or "Device rejected the home command",
        )
    return {"ok": True, "response": result.get("response")}


@router.post("/api/devices/{device_id}/cnc/jog")
async def jog_cnc_axis(
    device_id: str,
    body: CNCJogRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    _: dict = Depends(require_alpha_ack),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Jog one CNC axis (admin only — physical motion).

    Dedicated route rather than reusing the generic /api/printers/{id}/jog:
    that route dispatches through run_gcode()/send_command(), neither of
    which any CNC adapter implements — only send_gcode(). Before this route
    existed, jogging a CNC device silently returned {"ok": true} without the
    command ever reaching the machine (fleet.run_single_command's own
    fallback when no matching method exists). This constructs the G-code
    directly and sends it via send_gcode(), which every CNC adapter has.
    """
    printer = _get_enabled_printer_or_404(device_id)

    feed = body.feedrate or 600.0
    mode_cmd = "G91" if body.relative else "G90"
    move_cmd = f"G1 {body.axis}{body.distance} F{feed}"

    client = None
    try:
        client = _get_cnc_client(printer)
        if not hasattr(client, "send_gcode"):
            raise HTTPException(status_code=400, detail=f"Jog not supported for {printer.protocol}")

        # Step 1: Switch to relative/absolute mode
        result = await client.send_gcode(mode_cmd)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=f"Failed to set positioning mode: {result.get('error', 'unknown')}")

        # Step 2: Execute the jog move
        result = await client.send_gcode(move_cmd)
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
        if not result.get("ok"):
            # Try to restore absolute mode before returning error
            await client.send_gcode("G90")
            raise HTTPException(status_code=502, detail=f"Jog move failed: {result.get('error', 'unknown')}")

        # Step 3: Restore absolute mode (only needed if we switched to relative)
        if body.relative:
            result = await client.send_gcode("G90")
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            result = _normalize_adapter_result(result)
            if not result.get("ok"):
                raise HTTPException(status_code=502, detail=f"Warning: failed to restore absolute mode: {result.get('error', 'unknown')}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to jog axis: {str(e)}")
    finally:
        await record_audit(
            db,
            action="cnc_jog",
            user=current_user,
            resource=f"device:{device_id}",
            detail={"axis": body.axis, "distance": body.distance, "relative": body.relative},
            request=request,
        )
        await _record_alpha_dispatch_if_applicable(db, printer, current_user, request)
        if client is not None:
            await _safe_disconnect(client)

    if not result.get("ok"):
        # This should not be reached since we check after each step, but keep as safety net
        raise HTTPException(
            status_code=502,
            detail=result.get("error") or "Device rejected the jog command",
        )
    return {"ok": True, "response": result.get("response")}


@router.post("/api/devices/{device_id}/cnc/estop")
async def cnc_emergency_stop(
    device_id: str,
    request: Request,
    current_user: dict = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger emergency stop on a CNC machine (admin or operator).

    Deliberately open to operator, not just admin: the person who needs the
    stop button in an emergency is whoever's on the floor, not necessarily
    whoever holds an admin login. Motion-*initiating* commands (gcode/home)
    stay admin-only; the stop itself is the one command where wider access
    is the safer default. Deliberately carries no rate-limit decorator, no
    require_alpha_ack, and no other gating beyond auth — a throttled or
    delayed E-stop is a safety bug, full stop, even on an unverified adapter.
    Audit-logged after the adapter call regardless of outcome (via `finally`)
    so a failed E-stop is never silently un-logged. On an ALPHA_PROTOCOLS
    device the response instead carries an honest warning that the stop
    isn't guaranteed to behave as expected — surfacing the same risk
    require_alpha_ack would have gated elsewhere, without blocking it here.
    """
    printer = _get_enabled_printer_or_404(device_id)

    client = None
    try:
        client = _get_cnc_client(printer)
        result = await client.emergency_stop()
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        result = _normalize_adapter_result(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to trigger emergency stop: {str(e)}")
    finally:
        await record_audit(
            db,
            action="cnc_emergency_stop",
            user=current_user,
            resource=f"device:{device_id}",
            request=request,
        )
        await _record_alpha_dispatch_if_applicable(db, printer, current_user, request)
        if client is not None:
            await _safe_disconnect(client)

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail="Device did not confirm emergency stop",
        )
    response = {"ok": True, "state": result.get("state")}
    if printer.protocol in ALPHA_PROTOCOLS:
        response["alpha_warning"] = "unverified adapter — stop not guaranteed"
    return response


@router.get("/api/devices/{device_id}/cnc/files")
async def list_cnc_files(
    device_id: str,
    path: str = "",
    current_user: dict = Depends(require_role("admin", "operator")),
) -> dict:
    """List G-code files on a CNC machine (admin/operator only)."""
    # Validate path to prevent directory traversal
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    printer = _get_enabled_printer_or_404(device_id)

    client = None
    try:
        client = _get_cnc_client(printer)
        files = await client.list_files(path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list files: {str(e)}")
    finally:
        if client is not None:
            await _safe_disconnect(client)

    return {"files": files}
