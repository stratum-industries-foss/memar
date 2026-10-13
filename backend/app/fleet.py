from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import HTTPException

from .config import update_farm_fields, update_printer_fields
from .macro_params import macro_metadata
from .models import (
    ALPHA_PROTOCOLS,
    Anomaly,
    BatchActionRequest,
    BatchActionResponse,
    BatchActionResult,
    CommandResult,
    CurrentFileResponse,
    DispatchUploadItem,
    DispatchUploadResponse,
    DispatchDryRunRequest,
    DispatchDryRunResponse,
    DispatchDryRunResult,
    DryRunRequest,
    DryRunResponse,
    DryRunResult,
    FileBrowserResponse,
    FileDetailResponse,
    FleetSettingsResponse,
    FleetSettingsUpdateRequest,
    FileEntry,
    FleetMetricCard,
    FleetMetricsResponse,
    FleetMetricsSummary,
    FleetPrinterStatus,
    HeaterStatus,
    HistoryJob,
    HistoryResponse,
    HistoryTotals,
    JobStatus,
    KlipperConfig,
    MacroEntry,
    MacroParam,
    NormalizedFileMetadata,
    NozzleUpdateResponse,
    MotionCheckRequest,
    MotionCheckResponse,
    JogRequest,
    PrinterSettingsSaveResponse,
    PrinterSettingsUpdateRequest,
    PrinterCapability,
    PrinterConfig,
    PrinterDiagnostics,
    TemperatureSetRequest,
    TimelapseEntry,
    TimelapseListResponse,
    UiTarget,
    UploadResponse,
    WebcamEntry,
    WebcamListResponse,
)
from .moonraker import MoonrakerClient
from .models import Protocol

_client_cache: dict[str, Any] = {}
# Per-printer-id locks so evicting/creating one device's adapter (which may do
# real network I/O, e.g. OPC UA disconnect()) never stalls another device's
# concurrent fetch in fetch_fleet's asyncio.gather. _client_locks_meta_lock
# only guards inserting a new Lock into the dict (no I/O) so it never blocks.
_client_locks: dict[str, asyncio.Lock] = {}
_client_locks_meta_lock = asyncio.Lock()


async def _get_client_lock(printer_id: str) -> asyncio.Lock:
    async with _client_locks_meta_lock:
        lock = _client_locks.get(printer_id)
        if lock is None:
            lock = asyncio.Lock()
            _client_locks[printer_id] = lock
        return lock


# Strong references to in-flight adapter-close tasks scheduled by
# _clear_client_cache. Without this, loop.create_task's return can be GC'd
# mid-flight and the close silently never runs — the very leak we're fixing.
_pending_close_tasks: set[asyncio.Task] = set()


async def _aclose_adapter(client: Any) -> None:
    """Close one adapter's HTTP pool and cancel its background task (best-effort).

    Mirrors the eviction path in _get_client: httpx pool via aclose(), and any
    MQTT/OPC-UA bridge's background task via disconnect() (bounded by a timeout,
    since some adapters' disconnect() does network I/O)."""
    http = getattr(client, "_client", None)
    if http is not None:
        try:
            await http.aclose()
        except Exception:
            pass
    disconnect = getattr(client, "disconnect", None)
    if callable(disconnect):
        try:
            await asyncio.wait_for(disconnect(), timeout=2.0)
        except Exception:
            pass


def _clear_client_cache() -> "asyncio.Task | None":
    """Invalidate all cached adapter instances (call on config reload).

    Adapters hold an httpx.AsyncClient pool and, for MQTT/OPC-UA bridges, a
    background task. The old bare .clear() leaked both on every reload. We can't
    await here (both callers — _watch_config, admin_reload_config — invoke this
    synchronously), so snapshot the adapters, clear immediately (no new request can
    reach them), and schedule the async close on the running loop, keeping a strong
    task ref so it can't be GC'd before running. Returns the task (callers ignore
    it; tests await it). No running loop → nothing safe to await, refs dropped."""
    clients = list(_client_cache.values())
    _client_cache.clear()
    if not clients:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _close_all() -> None:
        for client in clients:
            await _aclose_adapter(client)

    task = loop.create_task(_close_all())
    _pending_close_tasks.add(task)
    task.add_done_callback(_pending_close_tasks.discard)
    return task


def _build_client(printer: "PrinterConfig") -> Any:
    """Protocol factory — instantiates the correct machine adapter."""
    protocol = getattr(printer, "protocol", Protocol.MOONRAKER)
    if protocol == Protocol.OCTOPRINT:
        from .octoprint import OctoPrintClient
        return OctoPrintClient(printer)
    if protocol == Protocol.DUET:
        from .duet import DuetClient
        return DuetClient(printer)
    if protocol == Protocol.FLUIDNC:
        from .fluidnc import FluidNCClient
        return FluidNCClient(printer)
    if protocol == Protocol.PRUSA_CONNECT:
        from .prusa_connect import PrusaConnectClient
        return PrusaConnectClient(printer)
    if protocol == Protocol.OPENPCB:
        from .openpcb import OpenPnPClient
        return OpenPnPClient(printer)
    if protocol == Protocol.MARLIN:
        from .marlin import MarlinClient
        return MarlinClient(printer)
    if protocol == Protocol.GRBL:
        from .grbl import GRBLClient
        return GRBLClient(printer)
    if protocol == Protocol.LINUXCNC:
        from .linuxcnc import LinuxCNCClient
        return LinuxCNCClient(printer)
    if protocol == Protocol.MACH3:
        from .mach3 import MACH3Client
        return MACH3Client(printer)
    if protocol == Protocol.OPCUA:
        from .opcua import OPCUAClient
        return OPCUAClient(printer)
    if protocol == Protocol.SINUMERIK:
        from .sinumerik import SinumerikClient
        return SinumerikClient(printer)
    if protocol == Protocol.HAAS:
        from .haas import HaasAdapter
        return HaasAdapter(printer)
    if protocol == Protocol.FANUC:
        from .fanuc import FANUCAdapter
        return FANUCAdapter(printer)
    if protocol == Protocol.FADAL:
        from .fadal import FadalAdapter
        return FadalAdapter(printer)
    if protocol == Protocol.MACH4:
        from .mach4 import MACH4Adapter
        return MACH4Adapter(printer)
    if protocol == Protocol.BAMBU_MQTT:
        from .mqtt_client import BambuPollingAdapter
        return BambuPollingAdapter(printer)
    if protocol == Protocol.MQTT:
        from .mqtt_client import MQTTPollingAdapter
        return MQTTPollingAdapter(printer)
    if protocol == Protocol.MODBUS:
        # No Modbus adapter yet — return a stub that shows "offline" with a clear
        # message instead of crashing the fleet fetch.
        class _UnsupportedProtocol:
            _protocol = protocol.value
            async def get_status(self):
                return {
                    "online": False,
                    "state": "offline",
                    "state_message": f"Protocol '{self._protocol}' is configured but not yet supported.",
                }
        return _UnsupportedProtocol()
    return MoonrakerClient(printer)


async def _get_client(printer: "PrinterConfig") -> Any:
    """Return a cached adapter instance, creating it on first access.

    Cache key includes api_key + serial so credential or device-identity changes
    bust the cache (serial is the MQTT topic/identity for Bambu). Stale clients for
    the same printer are evicted, their HTTP pools closed, and any background task
    (MQTT bridges) disconnected.
    """
    key = f"{printer.id}:{printer.protocol.value}:{printer.base_url}:{printer.api_key or ''}:{getattr(printer, 'serial', None) or ''}"
    lock = await _get_client_lock(printer.id)
    async with lock:
        if key not in _client_cache:
            stale_keys = [k for k in _client_cache if k.startswith(f"{printer.id}:")]
            for k in stale_keys:
                stale = _client_cache.pop(k)
                http = getattr(stale, "_client", None)
                if http is not None:
                    try:
                        await http.aclose()
                    except Exception:
                        pass
                # Adapters with a background task (e.g. MQTT push→poll bridges)
                # expose disconnect() to cancel it; without this the evicted loop
                # would leak on every config/credential change. Bounded by a
                # timeout: some adapters' disconnect() does network I/O (e.g. OPC
                # UA), and this runs under this printer's per-id lock — bounded so
                # an unresponsive device can't stall its own poll indefinitely
                # (other printers use their own lock and are never blocked by it).
                disconnect = getattr(stale, "disconnect", None)
                if callable(disconnect):
                    try:
                        await asyncio.wait_for(disconnect(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning("disconnect() timed out evicting client for %s", printer.id)
                    except Exception:
                        pass
            _client_cache[key] = _build_client(printer)
        return _client_cache[key]


def _offline_status(printer: PrinterConfig, exc: Exception) -> FleetPrinterStatus:
    """Build an offline FleetPrinterStatus for a device whose adapter failed."""
    return FleetPrinterStatus(
        id=printer.id, name=printer.name, base_url=printer.base_url,
        enabled=printer.enabled, online=False, state="offline",
        state_message=str(exc), warnings=[str(exc)], tags=printer.tags,
        ui_targets=_ui_targets_for_printer(printer),
        nozzle_diameter_mm=printer.nozzle_diameter_mm,
        available_actions=[], attention_needed=True,
        anomalies=[Anomaly(code="offline", severity="critical", message=str(exc))],
        capability=printer.capability(), raw={},
        protocol=printer.protocol, is_alpha_protocol=printer.protocol in ALPHA_PROTOCOLS,
    )


async def _safe_fetch_printer_status(printer: PrinterConfig) -> FleetPrinterStatus:
    """
    fetch_printer_status that can NEVER raise. The client factory (_get_client)
    runs before fetch_printer_status's own try blocks, so an adapter whose
    constructor raises (e.g. opcua when asyncua isn't installed) would otherwise
    propagate out of asyncio.gather and blank the ENTIRE fleet dashboard. One
    misconfigured device must only take itself offline, never the whole fleet.
    """
    try:
        return await fetch_printer_status(printer)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_printer_status failed for %s: %s", printer.id, exc)
        return _offline_status(printer, exc)


async def _generic_status_to_fleet(printer: PrinterConfig, client) -> FleetPrinterStatus:
    """Map non-Moonraker adapter get_status() dict to FleetPrinterStatus."""
    try:
        status = await client.get_status()
    except Exception as exc:
        return FleetPrinterStatus(
            id=printer.id, name=printer.name, base_url=printer.base_url,
            enabled=printer.enabled, online=False, state="offline",
            state_message=str(exc), warnings=[str(exc)], tags=printer.tags,
            ui_targets=_ui_targets_for_printer(printer),
            nozzle_diameter_mm=printer.nozzle_diameter_mm,
            available_actions=[], attention_needed=True,
            anomalies=[Anomaly(code="offline", severity="critical", message=str(exc))],
            capability=printer.capability(), raw={},
            protocol=printer.protocol, is_alpha_protocol=printer.protocol in ALPHA_PROTOCOLS,
        )
    cap = printer.capability()
    # Merge machine-specific fields from status into capability
    for field in ['spindle_rpm_current', 'feed_rate_mm_min', 'laser_power_pct',
                  'torch_voltage', 'arc_ok', 'thc_active', 'position_xyz', 'coolant_active', 'tool_id']:
        if field in status and status[field] is not None:
            setattr(cap, field, status[field])
    state = status.get('state', 'idle')
    anomalies = [] if status.get('online', True) else [
        Anomaly(code="offline", severity="critical", message=status.get('state_message', 'Offline'))
    ]
    return FleetPrinterStatus(
        id=printer.id, name=printer.name, base_url=printer.base_url,
        enabled=printer.enabled,
        online=status.get('online', True),
        state=state,
        state_message=status.get('state_message'),
        nozzle=HeaterStatus(temperature=status.get('nozzle_temperature'), target=status.get('nozzle_target')),
        bed=HeaterStatus(temperature=status.get('bed_temperature'), target=status.get('bed_target')),
        nozzle_diameter_mm=printer.nozzle_diameter_mm,
        job=JobStatus(
            filename=status.get('filename'),
            state=state,
            progress=status.get('progress'),
            eta_seconds=status.get('eta_seconds'),
            current_layer=status.get('layer_num'),
            total_layer=status.get('total_layers'),
        ),
        warnings=[],
        tags=printer.tags,
        ui_targets=_ui_targets_for_printer(printer),
        available_actions=_available_actions(state=state, online=status.get('online', True), job_state=state, machine_type=printer.machine_type.value),
        attention_needed=len(anomalies) > 0,
        anomalies=anomalies,
        macros_count=0,
        webcams_count=0,
        capability=cap,
        raw={},
        protocol=printer.protocol, is_alpha_protocol=printer.protocol in ALPHA_PROTOCOLS,
    )


OBJECTS_TO_QUERY: dict[str, list[str] | None] = {
    "webhooks": ["state", "state_message"],
    "print_stats": ["filename", "state", "print_duration", "total_duration", "message", "filament_used", "info"],
    "virtual_sdcard": ["progress"],
    "extruder": ["temperature", "target"],
    "heater_bed": ["temperature", "target"],
    "toolhead": None,
    "idle_timeout": ["state", "printing_time"],
    "gcode_move": ["speed_factor", "extrude_factor"],
    "temperature_sensor mcu_temp": ["temperature"],
}


# Live spool weights pulled from Spoolman (device_id -> grams), populated by the
# telemetry sampler (_sync_spoolman). Authoritative when present; lets us reflect a
# scale-backed weight without rewriting devices.yaml every poll. Empty unless a
# Spoolman server is configured.
_SPOOLMAN_G: dict[str, float] = {}


async def fetch_printer_status(printer: PrinterConfig) -> FleetPrinterStatus:
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return await _generic_status_to_fleet(printer, client)
    warnings: list[str] = []
    capability = printer.capability()
    # Re-detect filament_sensor from live Klipper objects — more accurate than YAML
    _filament_sensor_detected: bool | None = None
    try:
        from .ws_client import ws_manager
        cached = ws_manager.get_cached_state(printer.id)
        if cached:
            objects = cached
            # Still need info/server_info/loaded_objects/webcams from HTTP
            info_task = client.printer_info()
            server_task = client.server_info()
            loaded_objects_task = _safe_call(client.list_objects(), [])
            webcams_task = _safe_call(client.list_webcams(), [])
            info, server_info, loaded_objects, webcams = await asyncio.gather(
                info_task, server_task, loaded_objects_task, webcams_task
            )
        else:
            # Fallback to full HTTP polling
            info_task = client.printer_info()
            server_task = client.server_info()
            objects_task = client.query_objects(OBJECTS_TO_QUERY)
            loaded_objects_task = _safe_call(client.list_objects(), [])
            webcams_task = _safe_call(client.list_webcams(), [])
            info, server_info, objects, loaded_objects, webcams = await asyncio.gather(
                info_task, server_task, objects_task, loaded_objects_task, webcams_task
            )

        webhooks = objects.get("webhooks", {})
        print_stats = objects.get("print_stats", {})
        virtual_sdcard = objects.get("virtual_sdcard", {})
        extruder = objects.get("extruder", {})
        heater_bed = objects.get("heater_bed", {})
        idle_timeout = objects.get("idle_timeout", {})
        gcode_move = objects.get("gcode_move", {})
        mcu_raw = objects.get("temperature_sensor mcu_temp", {})

        state = str(webhooks.get("state") or info.get("state") or "unknown")
        state_message = webhooks.get("state_message") or info.get("state_message")
        warnings.extend(str(item) for item in (server_info.get("warnings") or []))
        if printer.maintenance_lockout:
            warnings.append("Printer is in maintenance lockout")
        if state in {"error", "shutdown"}:
            warnings.append(state_message or f"Printer reported state={state}")

        nozzle = HeaterStatus(temperature=_safe_float(extruder.get("temperature")), target=_safe_float(extruder.get("target")))
        bed = HeaterStatus(temperature=_safe_float(heater_bed.get("temperature")), target=_safe_float(heater_bed.get("target")))
        _job_progress = _progress_to_percent(virtual_sdcard.get("progress"))
        _job_print_duration = _safe_float(print_stats.get("print_duration"))
        _estimated_total = _estimate_total_duration(_job_print_duration, _job_progress)
        _remaining_duration = _estimate_remaining_duration(_job_print_duration, _job_progress)
        job = JobStatus(
            filename=print_stats.get("filename"),
            state=print_stats.get("state"),
            progress=_job_progress,
            print_duration=_job_print_duration,
            total_duration=_safe_float(print_stats.get("total_duration")),
            estimated_total_duration=_estimated_total,
            remaining_duration=_remaining_duration,
            message=print_stats.get("message"),
            eta_seconds=_remaining_duration,
            filament_used_mm=_safe_float(print_stats.get("filament_used")),
            current_layer=(print_stats.get("info") or {}).get("current_layer"),
            total_layer=(print_stats.get("info") or {}).get("total_layer"),
        )

        # Effective spool: Spoolman scale (authoritative) > live in-print subtraction
        # of the current job's filament > configured value. Computed before the
        # anomaly pass so the low-spool warning and the displayed value never disagree.
        eff_spool = capability.spool_remaining_g
        _sm = _SPOOLMAN_G.get(printer.id)
        if _sm is not None:
            eff_spool = round(_sm, 1)
        elif (eff_spool is not None and job.filament_used_mm
                and (job.state or state) in ("printing", "paused")):
            try:
                from .spool_deduction import compute_consumption
                used_g, _m = compute_consumption(
                    str(getattr(printer.machine_type, "value", printer.machine_type) or "fdm"),
                    filament_used_mm=job.filament_used_mm,
                    filament_diameter_mm=printer.filament_diameter_mm or 1.75,
                    material=capability.current_material,
                )
                if used_g:
                    eff_spool = max(0.0, round(eff_spool - used_g, 1))
            except Exception:  # noqa: BLE001 — display nicety, never break status
                pass
        capability.spool_remaining_g = eff_spool

        anomalies = _collect_anomalies(
            printer=printer,
            online=True,
            state=state,
            state_message=state_message,
            nozzle=nozzle,
            bed=bed,
            job=job,
            warnings=warnings,
            server_info=server_info,
            effective_spool_g=eff_spool,
        )

        # Override filament_sensor from live loaded Klipper objects (beats YAML static value)
        _live_filament_sensor = any(
            str(obj).startswith(("filament_switch_sensor ", "filament_motion_sensor "))
            for obj in loaded_objects
        )
        capability.filament_sensor = _live_filament_sensor

        raw = {"printer_info": info, "server_info": server_info, "objects": objects}
        ui_targets = _ui_targets_for_printer(printer)
        capability.ui_targets = ui_targets
        return FleetPrinterStatus(
            id=printer.id,
            name=printer.name,
            base_url=printer.base_url,
            enabled=printer.enabled,
            online=True,
            state=state,
            state_message=state_message,
            nozzle=nozzle,
            bed=bed,
            nozzle_diameter_mm=printer.nozzle_diameter_mm,
            job=job,
            warnings=warnings,
            tags=printer.tags,
            ui_targets=ui_targets,
            available_actions=_available_actions(state=state, online=True, job_state=job.state, machine_type=printer.machine_type.value),
            attention_needed=any(item.severity in {"warning", "critical"} for item in anomalies),
            anomalies=anomalies,
            macros_count=len([item for item in loaded_objects if str(item).startswith("gcode_macro ")]),
            webcams_count=len([item for item in webcams if item.get("enabled", True)]),
            capability=capability,
            idle_state=idle_timeout.get("state"),
            idle_since_s=_safe_float(idle_timeout.get("printing_time")),
            speed_factor=_safe_float(gcode_move.get("speed_factor")),
            flow_factor=_safe_float(gcode_move.get("extrude_factor")),
            mcu_temp=_safe_float(mcu_raw.get("temperature")),
            protocol=printer.protocol,
            raw=raw,
        )
    except Exception as exc:
        message = str(exc)
        anomalies = [Anomaly(code="offline", severity="critical", message=message)]
        return FleetPrinterStatus(
            id=printer.id,
            name=printer.name,
            base_url=printer.base_url,
            enabled=printer.enabled,
            online=False,
            state="offline",
            state_message=message,
            warnings=[message],
            tags=printer.tags,
            ui_targets=_ui_targets_for_printer(printer),
            nozzle_diameter_mm=printer.nozzle_diameter_mm,
            available_actions=[],
            attention_needed=True,
            anomalies=anomalies,
            capability=capability,
            raw={},
            protocol=printer.protocol,
        )


def _allowed_klipper_file(path_value: Any) -> Path | None:
    """Return a safe, resolved Path for a printer-reported klipper file, or None.

    config_file / log_file come from the REMOTE printer's Moonraker response — a
    compromised device can set them to any local path (memar's own .env,
    /etc/passwd, ...), and diagnostics would read it back. Only paths that resolve
    within an operator-configured allowlist of roots (MEMAR_KLIPPER_FILE_ROOTS,
    os.pathsep-separated) are permitted. Default is EMPTY = deny-all: in a normal
    networked-fleet deployment these paths live on the printer's host, not the
    server, so reading them off local disk already returns nothing except in a
    co-located install, where the operator can opt in by naming the safe root(s).
    Never default this to a home/app dir — memar's secrets live there.
    """
    if not path_value:
        return None
    roots_env = os.getenv("MEMAR_KLIPPER_FILE_ROOTS", "")
    roots = [Path(r).resolve() for r in roots_env.split(os.pathsep) if r.strip()]
    if not roots:
        return None
    try:
        resolved = Path(str(path_value)).resolve()
    except Exception:
        return None
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    return None


async def fetch_printer_diagnostics(printer: PrinterConfig) -> PrinterDiagnostics:
    status = await fetch_printer_status(printer)
    raw = status.raw or {}
    printer_info = raw.get("printer_info", {})
    server_info = raw.get("server_info", {})
    toolhead = (raw.get("objects") or {}).get("toolhead", {}) if raw else {}
    position = _extract_position(toolhead)
    homed_axes = str(toolhead.get("homed_axes") or "")
    # Parse klipper config from the config_file path reported by klippy
    klipper_config: KlipperConfig | None = None
    cfg_file = printer_info.get("config_file")
    _safe_cfg = _allowed_klipper_file(cfg_file)
    if _safe_cfg is not None:
        from .config_discovery import parse_printer_cfg as _parse_cfg
        try:
            klipper_config = KlipperConfig(**_parse_cfg(_safe_cfg))
        except Exception as _e:
            klipper_config = KlipperConfig(parse_notes=[f"Parse failed: {_e}"])
    return PrinterDiagnostics(
        printer_id=status.id,
        name=status.name,
        online=status.online,
        state=status.state,
        state_message=status.state_message,
        base_url=status.base_url,
        tags=status.tags,
        ui_targets=status.ui_targets,
        nozzle_diameter_mm=status.nozzle_diameter_mm,
        available_actions=status.available_actions,
        attention_needed=status.attention_needed,
        anomalies=status.anomalies,
        warnings=status.warnings,
        config_file=printer_info.get("config_file"),
        log_file=printer_info.get("log_file"),
        process_id=printer_info.get("process_id"),
        moonraker_version=server_info.get("moonraker_version"),
        api_version_string=server_info.get("api_version_string"),
        klippy_connected=server_info.get("klippy_connected"),
        components=[str(item) for item in server_info.get("components", [])],
        failed_components=[str(item) for item in server_info.get("failed_components", [])],
        suggested_checks=_suggested_checks(status),
        recent_log_lines=_tail_file(_allowed_klipper_file(printer_info.get("log_file")), limit=30),
        capability=printer.capability(),
        homed_axes=homed_axes,
        toolhead_position=position,
        klipper_config=klipper_config,
        raw=raw,
    )


async def fetch_history(printer: PrinterConfig, db: 'AsyncSession | None' = None, limit: int = 15) -> HistoryResponse:
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        # Fallback: use JobLog for non-Moonraker machines (CNC, etc.)
        if db:
            from .models_db import JobLog
            from sqlalchemy import select, desc
            try:
                jobs_query = await db.execute(
                    select(JobLog).where(JobLog.device_id == printer.id).order_by(desc(JobLog.ended_at)).limit(limit)
                )
                jobs_db = jobs_query.scalars().all()
                history_jobs = [
                    HistoryJob(
                        job_id=str(j.id),
                        filename=j.job_name or 'Unknown file',
                        status=j.status,
                        exists=True,
                        filament_used=None,
                        print_duration=j.duration_s if j.status == 'completed' else 0,
                        total_duration=j.duration_s or 0,
                        start_time=j.created_at.isoformat() if j.created_at else None,
                        end_time=j.ended_at.isoformat() if j.ended_at else None,
                        metadata=None,
                    )
                    for j in jobs_db
                ]
                total_jobs = len(history_jobs)
                completed = sum(1 for j in history_jobs if j.status == 'completed')
                total_duration = sum(j.total_duration or 0 for j in history_jobs)
                return HistoryResponse(
                    printer_id=printer.id,
                    jobs=history_jobs,
                    totals=HistoryTotals(
                        total_jobs=total_jobs,
                        total_print_time=sum(j.print_duration or 0 for j in history_jobs),
                        total_time=total_duration,
                        total_filament_used=None,
                        longest_print=max((j.print_duration for j in history_jobs if j.print_duration), default=0),
                        longest_job=max((j.total_duration for j in history_jobs if j.total_duration), default=0),
                    ),
                )
            except Exception:
                pass
        return HistoryResponse(printer_id=printer.id)
    try:
        history_raw, totals_raw = await asyncio.gather(client.history_list(limit=limit), client.history_totals())
    except Exception:
        return HistoryResponse(printer_id=printer.id, jobs=[], totals=HistoryTotals())

    jobs = [
        HistoryJob(
            job_id=item.get("job_id") or item.get("id"),
            filename=item.get("filename"),
            status=item.get("status") or item.get("state"),
            exists=item.get("exists"),
            filament_used=_safe_float(item.get("filament_used")),
            print_duration=_safe_float(item.get("print_duration")),
            total_duration=_safe_float(item.get("total_duration")),
            start_time=_safe_float(item.get("start_time")),
            end_time=_safe_float(item.get("end_time")),
            metadata=item.get("metadata") or {},
        )
        for item in history_raw.get("jobs", [])
    ]
    totals = totals_raw.get("job_totals") or {}
    return HistoryResponse(
        printer_id=printer.id,
        jobs=jobs,
        totals=HistoryTotals(
            total_jobs=int(totals.get("total_jobs") or 0),
            total_time=_safe_float(totals.get("total_time")) or 0.0,
            total_print_time=_safe_float(totals.get("total_print_time")) or 0.0,
            total_filament_used=_safe_float(totals.get("total_filament_used")) or 0.0,
            longest_job=_safe_float(totals.get("longest_job")) or 0.0,
            longest_print=_safe_float(totals.get("longest_print")) or 0.0,
        ),
    )


def _validate_file_path(path: str) -> str:
    """Validate file browser path is within gcodes directory."""
    if not path:
        return ""  # Root is ok
    # Normalize and check
    normalized = Path(path).as_posix()
    if ".." in normalized or normalized.startswith("/"):
        raise HTTPException(400, "Invalid path")
    # Only allow gcodes subdirectory
    parts = normalized.split("/")
    if parts[0] not in ("", "gcodes"):
        raise HTTPException(400, "Path must be within gcodes/")
    return normalized


_PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_profile_name(name: str) -> str:
    """Validate bed mesh profile name format before use in Moonraker commands."""
    if not _PROFILE_NAME.match(name):
        raise HTTPException(400, "Invalid profile name")
    return name


async def fetch_file_browser(printer: PrinterConfig, path: str = "gcodes") -> FileBrowserResponse:
    path = _validate_file_path(path)
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return FileBrowserResponse(printer_id=printer.id, path=path, root="gcodes")
    client = await _get_client(printer)
    try:
        listing = await client.list_directory(path=path, extended=True)
    except Exception:
        return FileBrowserResponse(printer_id=printer.id, path=path, root="gcodes", dirs=[], files=[], disk_usage={}, root_info={})

    dirs = [
        FileEntry(
            name=str(item.get("dirname") or ""),
            path=_join_path(path, str(item.get("dirname") or "")),
            kind="dir",
            size=_safe_int(item.get("size")),
            modified=_safe_float(item.get("modified")),
            permissions=item.get("permissions"),
        )
        for item in listing.get("dirs", [])
    ]
    files = []
    for item in listing.get("files", []):
        filename = str(item.get("filename") or "")
        metadata = dict(item)
        for key in ["filename", "size", "modified", "permissions"]:
            metadata.pop(key, None)
        # Build absolute thumbnail URL if thumbnail path exists
        if "thumbnail" in metadata and metadata["thumbnail"]:
            thumb_rel = str(metadata["thumbnail"])
            # Handle relative thumbnail path formats from Moonraker
            if not thumb_rel.startswith("/"):
                thumb_rel = f"server/files/gcodes/{thumb_rel}"
            try:
                metadata["thumbnail_url"] = client.absolute_url(thumb_rel)
            except Exception:
                pass
        files.append(
            FileEntry(
                name=filename,
                path=_join_path(path, filename),
                kind="file",
                size=_safe_int(item.get("size")),
                modified=_safe_float(item.get("modified")),
                permissions=item.get("permissions"),
                metadata=metadata,
            )
        )
    return FileBrowserResponse(
        printer_id=printer.id,
        path=path,
        root=str((listing.get("root_info") or {}).get("name") or "gcodes"),
        dirs=dirs,
        files=files,
        disk_usage=listing.get("disk_usage") or {},
        root_info=listing.get("root_info") or {},
    )


async def _fetch_macro_settings(client: MoonrakerClient) -> dict[str, dict]:
    """Return ``configfile.settings`` sections for gcode macros, keyed lower-case.

    Klipper lower-cases section names in ``configfile.settings`` while
    ``objects/list`` reports them in their original config casing — so
    ``gcode_macro PRINT_START`` from the object list only joins to
    ``gcode_macro print_start`` here after normalising. Getting this wrong is
    silent: every macro simply comes back with no params.

    Best-effort by design. A printer that is mid-restart, running a Klipper too
    old to report the object, or behind a Moonraker that errors, must still get
    its macro list — just without type information.
    """
    try:
        result = await client.query_objects({"configfile": None})
    except Exception as exc:  # noqa: BLE001 - metadata is optional, never fatal
        logger.debug("configfile query failed; macros will be untyped: %s", exc)
        return {}
    settings = ((result or {}).get("configfile") or {}).get("settings") or {}
    if not isinstance(settings, dict):
        return {}
    return {
        str(key).lower(): value
        for key, value in settings.items()
        if str(key).lower().startswith("gcode_macro ") and isinstance(value, dict)
    }


async def fetch_macros(printer: PrinterConfig) -> list[MacroEntry]:
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return []
    objects = await client.list_objects()
    # One configfile query for the whole fleet of macros, not one per macro —
    # the response is the printer's entire parsed config.
    settings = await _fetch_macro_settings(client)
    entries: list[MacroEntry] = []
    for item in objects:
        text = str(item)
        if not text.startswith("gcode_macro "):
            continue
        name = text.split("gcode_macro ", 1)[1]
        params, category, color = macro_metadata(settings.get(text.lower()))
        entries.append(
            MacroEntry(
                name=name,
                full_object=text,
                params={key: MacroParam(**spec) for key, spec in params.items()},
                category=category,
                color=color,
            )
        )
    return sorted(entries, key=lambda item: item.name.lower())


async def fetch_webcams(printer: PrinterConfig) -> WebcamListResponse:
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        # Fallback: use camera_url from capability for non-Moonraker machines
        if printer.capability().camera_url:
            entries = [
                WebcamEntry(
                    uid="default",
                    name="Camera",
                    enabled=True,
                    stream_url=printer.capability().camera_url,
                    snapshot_url=None,
                    location=None,
                    service=None,
                    aspect_ratio=None,
                    raw={},
                )
            ]
            return WebcamListResponse(printer_id=printer.id, webcams=entries)
        return WebcamListResponse(printer_id=printer.id)
    webcams = await client.list_webcams()
    entries: list[WebcamEntry] = []
    for item in webcams:
        uid = str(item.get("uid") or item.get("name") or "")
        entries.append(
            WebcamEntry(
                uid=uid,
                name=str(item.get("name") or uid),
                enabled=bool(item.get("enabled", True)),
                stream_url=client.absolute_url(item.get("stream_url")),
                snapshot_url=client.absolute_url(item.get("snapshot_url")),
                location=item.get("location"),
                service=item.get("service"),
                aspect_ratio=item.get("aspect_ratio"),
                raw=item,
            )
        )
    return WebcamListResponse(printer_id=printer.id, webcams=entries)


async def fetch_webcam_snapshot(printer: PrinterConfig, uid: str | None) -> tuple[bytes, str]:
    client = await _get_client(printer)
    selected_uid = uid
    if not selected_uid:
        webcams = await fetch_webcams(printer)
        enabled = [item for item in webcams.webcams if item.enabled]
        if not enabled:
            raise RuntimeError("No webcam is configured")
        selected_uid = enabled[0].uid
    tested = await client.webcam_test(selected_uid)
    snapshot_url = tested.get("snapshot_url") or tested.get("stream_url")
    if not snapshot_url:
        webcam = await client.webcam_item(selected_uid)
        snapshot_url = client.absolute_url(webcam.get("snapshot_url") or webcam.get("stream_url"))
    if not snapshot_url:
        raise RuntimeError("No snapshot URL available")
    response = await client.fetch_binary(snapshot_url)
    content_type = response.headers.get("content-type", "image/jpeg")
    return response.content, content_type


async def fetch_timelapses(printer: PrinterConfig, limit: int = 20) -> TimelapseListResponse:
    directory = printer.timelapse_dir
    if not directory:
        return TimelapseListResponse(printer_id=printer.id, source_dir=None, configured=False, entries=[])
    path = Path(directory).expanduser()
    if not path.exists() or not path.is_dir():
        return TimelapseListResponse(printer_id=printer.id, source_dir=str(path), configured=True, entries=[])
    entries: list[TimelapseEntry] = []
    for child in sorted(path.iterdir(), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix not in {".mp4", ".webm", ".gif", ".jpg", ".jpeg", ".png"}:
            continue
        kind = "video" if suffix in {".mp4", ".webm", ".gif"} else "image"
        entries.append(
            TimelapseEntry(
                id=hashlib.sha1(str(child).encode("utf-8")).hexdigest()[:12],
                name=child.name,
                path=str(child),
                size=child.stat().st_size,
                modified=child.stat().st_mtime,
                kind=kind,
            )
        )
        if len(entries) >= limit:
            break
    return TimelapseListResponse(printer_id=printer.id, source_dir=str(path), configured=True, entries=entries)


async def upload_gcode(printer: PrinterConfig, *, filename: str, content: bytes, relative_path: str | None, auto_print: bool) -> UploadResponse:
    filename = _sanitize_upload_filename(filename)
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return UploadResponse(printer_id=printer.id, filename=filename, warnings=["File upload not supported for this protocol"])
    client = await _get_client(printer)
    checksum = hashlib.sha256(content).hexdigest()
    clean_relative_path = _clean_relative_upload_path(relative_path)
    result = await client.upload_file(filename=filename, content=content, path=clean_relative_path, auto_print=auto_print)
    merged = dict(result)
    merged["client_sha256"] = checksum
    stored_item = merged.get("item") if isinstance(merged.get("item"), dict) else {}
    path_value = stored_item.get("path") or _join_path("gcodes", _join_path(clean_relative_path or "", filename).strip("/"))
    size_value = _safe_int(stored_item.get("size"))
    return UploadResponse(
        printer_id=printer.id,
        filename=filename,
        path=path_value,
        size=size_value if size_value is not None else len(content),
        started_print=auto_print,
        warnings=[],
        result=merged,
    )


async def run_batch_action(printers: list[PrinterConfig], request: BatchActionRequest, action: str) -> BatchActionResponse:
    selected = {p.id: p for p in printers if p.id in request.printer_ids and p.enabled}
    ordered: list[tuple[str, PrinterConfig | None]] = [(printer_id, selected.get(printer_id)) for printer_id in request.printer_ids]
    statuses = await asyncio.gather(*(_safe_fetch_printer_status(printer) for _, printer in ordered if printer is not None))
    status_map = {status.id: status for status in statuses}

    results_by_id: dict[str, BatchActionResult] = {}
    executable: list[PrinterConfig] = []
    for printer_id, printer in ordered:
        if printer is None:
            results_by_id[printer_id] = BatchActionResult(printer_id=printer_id, name=printer_id, allowed=False, status="blocked", message="Unknown or disabled printer")
            continue
        status = status_map.get(printer.id)
        if status is None:
            results_by_id[printer.id] = BatchActionResult(printer_id=printer.id, name=printer.name, allowed=False, status="error", message="Could not fetch printer status")
            continue
        plan = _evaluate_action_plan(printer, status, action)
        if not plan.eligible:
            results_by_id[printer.id] = BatchActionResult(printer_id=printer.id, name=printer.name, allowed=False, status="blocked", message="; ".join(plan.blocking_reasons) or f"Action {action} is not available")
            continue
        executable.append(printer)

    async def _run(printer: PrinterConfig) -> BatchActionResult:
        try:
            _batch_client = await _get_client(printer)
            if not isinstance(_batch_client, MoonrakerClient):
                return BatchActionResult(printer_id=printer.id, name=printer.name, allowed=False, status="blocked", message="Batch actions not supported for this protocol")
            await _execute_action(_batch_client, action)
            suffix = " (dispatched concurrently)" if len(executable) > 1 else ""
            return BatchActionResult(printer_id=printer.id, name=printer.name, allowed=True, status="ok", message=f"ok{suffix}")
        except Exception as exc:
            return BatchActionResult(printer_id=printer.id, name=printer.name, allowed=True, status="error", message=str(exc))

    executed = await asyncio.gather(*(_run(printer) for printer in executable)) if executable else []
    for item in executed:
        results_by_id[item.printer_id] = item

    results = [results_by_id[printer_id] for printer_id, _ in ordered if printer_id in results_by_id]
    return BatchActionResponse(action=action, results=results)


async def dry_run_batch_action(printers: list[PrinterConfig], request: DryRunRequest, action: str) -> DryRunResponse:
    selected = {p.id: p for p in printers if p.id in request.printer_ids and p.enabled}
    # PERF-FLEET-SEQFETCH-01: fetch every valid printer's status concurrently
    # instead of one at a time — a sequential loop here scaled dry-run latency
    # linearly with fleet size, unlike the sibling batch-action path (which
    # already gathers).
    valid_ids = [pid for pid in request.printer_ids if pid in selected]
    statuses = await asyncio.gather(*(fetch_printer_status(selected[pid]) for pid in valid_ids))
    status_by_id = dict(zip(valid_ids, statuses))
    results: list[DryRunResult] = []
    for printer_id in request.printer_ids:
        printer = selected.get(printer_id)
        if printer is None:
            results.append(DryRunResult(printer_id=printer_id, name=printer_id, eligible=False, would_execute=False, blocking_reasons=["Unknown or disabled printer"]))
            continue
        status = status_by_id[printer_id]
        results.append(_evaluate_action_plan(printer, status, action, macro_name=request.macro_name, nozzle_target=request.nozzle_target, bed_target=request.bed_target))
    return DryRunResponse(action=action, results=results)


async def motion_check(printer: PrinterConfig, request: MotionCheckRequest) -> MotionCheckResponse:
    status = await fetch_printer_status(printer)
    raw = status.raw or {}
    toolhead = (raw.get("objects") or {}).get("toolhead", {})
    homed_axes = str(toolhead.get("homed_axes") or "")
    checks = [
        f"online={status.online}",
        f"state={status.state}",
        f"job_state={status.job.state or 'unknown'}",
        f"homed_axes={homed_axes or 'none'}",
    ]
    warnings: list[str] = []
    blocking: list[str] = []
    if not status.online:
        blocking.append("Printer is offline")
    if status.state not in {"ready", "idle"}:
        warnings.append(f"Printer state is {status.state}")
    if printer.maintenance_lockout:
        blocking.append("Printer is in maintenance lockout")
    if request.intent == "jog" and not printer.jog_enabled:
        blocking.append("Jogging is disabled for this printer profile")
    if request.intent in {"jog", "park", "mesh", "macro"} and printer.motion_check_required and not homed_axes:
        blocking.append("Motion intent requires homed axes, but homed_axes is empty")
    if request.intent in {"jog", "park", "mesh", "macro"} and status.job.state == "printing":
        blocking.append("Motion intent blocked while a print is active")
    if request.intent == "home" and status.job.state == "printing":
        blocking.append("Homing blocked while a print is active")
    if (status.nozzle.temperature or 0) > 180 and request.intent in {"mesh", "macro", "jog", "park"}:
        warnings.append(f"Nozzle is hot at {status.nozzle.temperature:.1f} C")
    if (status.bed.temperature or 0) > 80 and request.intent in {"mesh", "park"}:
        warnings.append(f"Bed is hot at {status.bed.temperature:.1f} C")
    if request.intent == "macro" and not request.macro_name:
        warnings.append("No macro name provided; macro-specific validation was limited")
    return MotionCheckResponse(
        printer_id=printer.id,
        name=printer.name,
        ok=not blocking,
        homed_axes=homed_axes,
        current_state=status.state,
        checks=checks,
        warnings=warnings,
        blocking_reasons=blocking,
    )


async def _evaluate_dispatch_candidate(
    printer: PrinterConfig, request: DispatchDryRunRequest
) -> tuple[DispatchDryRunResult, tuple[str, float] | None]:
    status = await fetch_printer_status(printer)
    blocking: list[str] = []
    warnings: list[str] = []
    score = 0.0
    if not status.online:
        blocking.append("Printer is offline")
    if status.state not in {"ready", "idle"}:
        blocking.append(f"Printer state is {status.state}")
    if status.job.state == "printing" and not request.allow_busy_queue:
        blocking.append("Printer is actively printing")
    if printer.maintenance_lockout:
        blocking.append("Printer is in maintenance lockout")
    if request.material:
        supported = [m.lower() for m in printer.supported_materials]
        if supported and request.material.lower() not in supported:
            blocking.append(f"Material {request.material} is not in supported_materials")
        elif not supported:
            warnings.append("Printer has no supported_materials profile configured")
    if request.nozzle_diameter_mm is not None and printer.nozzle_diameter_mm is not None:
        if abs(float(printer.nozzle_diameter_mm) - float(request.nozzle_diameter_mm)) > 0.051:
            blocking.append(f"Requested nozzle {request.nozzle_diameter_mm} mm does not match printer nozzle {printer.nozzle_diameter_mm} mm")
    try:
        _dispatch_client = await _get_client(printer)
        if isinstance(_dispatch_client, MoonrakerClient):
            normalized = request.filename if request.filename.startswith("gcodes/") else f"gcodes/{request.filename.lstrip('/')}"
            await _dispatch_client.file_metadata(normalized)
    except Exception:
        blocking.append(f"File {request.filename} is not visible in Moonraker")
    if status.attention_needed:
        warnings.append("Printer currently has attention items")
    recommendation_entry = None
    if not blocking:
        score += 50.0
        if not status.attention_needed:
            score += 20.0
        if status.job.state in {None, '', 'standby'}:
            score += 10.0
        if request.material and printer.supported_materials and request.material.lower() in [m.lower() for m in printer.supported_materials]:
            score += 10.0
        if request.nozzle_diameter_mm is not None and printer.nozzle_diameter_mm is not None and abs(float(printer.nozzle_diameter_mm) - float(request.nozzle_diameter_mm)) <= 0.051:
            score += 10.0
        recommendation_entry = (printer.id, score)
    result = DispatchDryRunResult(
        printer_id=printer.id,
        name=printer.name,
        eligible=not blocking,
        would_queue=not blocking,
        score=round(score, 1),
        blocking_reasons=blocking,
        warnings=warnings,
        recommendation="recommended" if not blocking and score >= 70 else None,
    )
    return result, recommendation_entry


async def dispatch_dry_run(printers: list[PrinterConfig], request: DispatchDryRunRequest) -> DispatchDryRunResponse:
    target_printers = [p for p in printers if p.enabled and (not request.printer_ids or p.id in request.printer_ids)]
    # PERF-FLEET-SEQFETCH-03: evaluate every candidate printer concurrently —
    # each printer's evaluation is independent (see PERF-FLEET-SEQFETCH-01),
    # the final sort/ranking below is unaffected by evaluation order.
    evaluated = await asyncio.gather(*(_evaluate_dispatch_candidate(p, request) for p in target_printers))
    results = [item[0] for item in evaluated]
    recommended = [item[1] for item in evaluated if item[1] is not None]
    recommended_ids = [item[0] for item in sorted(recommended, key=lambda x: x[1], reverse=True)]
    results.sort(key=lambda item: (-item.score, item.name.lower()))
    return DispatchDryRunResponse(
        filename=request.filename,
        requested_material=request.material,
        requested_nozzle_diameter_mm=request.nozzle_diameter_mm,
        results=results,
        recommended_printer_ids=recommended_ids,
    )


async def run_single_command(printer: PrinterConfig, command: str) -> CommandResult:
    client = await _get_client(printer)
    if isinstance(client, MoonrakerClient):
        return CommandResult(result=await client.run_gcode(command))
    cmd_fn = getattr(client, 'run_gcode', None) or getattr(client, 'send_command', None)
    if cmd_fn:
        result = await cmd_fn(command)
        return CommandResult(result=str(result.get('response', result) if isinstance(result, dict) else result))
    raise HTTPException(501, f"run_single_command not implemented for {printer.protocol.value}")


async def set_temperatures(printer: PrinterConfig, request: TemperatureSetRequest) -> CommandResult:
    lines: list[str] = []
    # Enforce the per-printer configured safe maxima on the REAL heating command.
    # These are otherwise only checked in the unreachable dry-run path
    # (_evaluate_action_plan, action="temperature"). Strict > so a request exactly
    # at the cap is allowed. safe_*_max_c defaults to the global cap (300/120), so
    # this is a no-op EXCEPT for printers configured with a lower limit (e.g. a PTFE
    # hotend rated to 240C). t1_nozzle (IDEX second hotend) is bounded by the same
    # nozzle max — same physical hazard on the same command.
    if request.nozzle_target is not None and printer.safe_nozzle_max_c is not None and request.nozzle_target > printer.safe_nozzle_max_c:
        raise ValueError(f"Requested nozzle temperature {request.nozzle_target} exceeds configured safe_nozzle_max_c {printer.safe_nozzle_max_c}")
    if request.t1_nozzle is not None and printer.safe_nozzle_max_c is not None and request.t1_nozzle > printer.safe_nozzle_max_c:
        raise ValueError(f"Requested T1 nozzle temperature {request.t1_nozzle} exceeds configured safe_nozzle_max_c {printer.safe_nozzle_max_c}")
    if request.bed_target is not None and printer.safe_bed_max_c is not None and request.bed_target > printer.safe_bed_max_c:
        raise ValueError(f"Requested bed temperature {request.bed_target} exceeds configured safe_bed_max_c {printer.safe_bed_max_c}")
    if request.nozzle_target is not None:
        lines.append(f"M104 S{request.nozzle_target}")
    if request.t1_nozzle is not None:
        lines.append(f"M104 T1 S{request.t1_nozzle}")
    if request.bed_target is not None:
        lines.append(f"M140 S{request.bed_target}")
    if not lines:
        raise ValueError("At least one target temperature is required")
    return await run_single_command(printer, "\n".join(lines))


async def jog(printer: PrinterConfig, request: JogRequest) -> CommandResult:
    """Jog one axis. Sends G91/G90 + G1 + G90 as three sequenced commands, aborting on failure."""
    axis = request.axis.upper()
    if axis not in ('X', 'Y', 'Z', 'E'):
        raise HTTPException(400, 'invalid axis')
    distance = float(request.distance)
    if abs(distance) > 500:
        raise HTTPException(400, 'distance out of range')
    if axis == "E":
        feed = request.feedrate or 180.0
    elif axis == "Z":
        feed = request.feedrate or 600.0
    else:
        feed = request.feedrate or 3000.0

    # Step 1: Switch to relative/absolute mode
    mode_cmd = "G91" if request.relative else "G90"
    result = await run_single_command(printer, mode_cmd)
    if not result.result or "error" in (result.result or "").lower():
        return CommandResult(result=f"Failed to set positioning mode: {result.result}")

    # Step 2: Execute the jog move
    move_cmd = f"G1 {axis}{request.distance} F{feed}"
    result = await run_single_command(printer, move_cmd)
    if not result.result or "error" in (result.result or "").lower():
        # Try to restore absolute mode before returning error
        await run_single_command(printer, "G90")
        return CommandResult(result=f"Jog move failed: {result.result}")

    # Step 3: Restore absolute mode (only needed if we switched to relative)
    if request.relative:
        result = await run_single_command(printer, "G90")
        if not result.result or "error" in (result.result or "").lower():
            return CommandResult(result=f"Warning: failed to restore absolute mode: {result.result}")

    return CommandResult(result="ok")


# A macro call is assembled into ONE line of g-code, so any character that can
# terminate a command or begin another one is an injection vector: newline/CR
# starts a second command, ';' comments out the remainder, and whitespace
# fabricates an extra KEY=VALUE token. These are allowlists rather than
# denylists — a denylist of "shell metacharacters" is the wrong shape here,
# because the sink is Klipper's g-code parser, not a shell. Quoted/spaced values
# are deliberately unsupported; no real Klipper param needs them.
_MACRO_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
_MACRO_PARAM_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_MACRO_PARAM_VALUE_RE = re.compile(r'^[A-Za-z0-9_.:,+/-]+$')
_MACRO_PARAM_MAX_COUNT = 32
_MACRO_PARAM_KEY_MAX_LEN = 64
_MACRO_PARAM_VALUE_MAX_LEN = 128


def build_macro_command(macro_name: str, params: dict[str, str] | None = None) -> str:
    """Assemble a validated ``MACRO KEY=VALUE ...`` g-code line.

    Raises HTTPException(400) on anything that fails validation. Split out from
    `run_macro` so the validation is testable without a printer, and so every
    caller that builds a macro invocation goes through the same gate.
    """
    if not _MACRO_NAME_RE.match(macro_name or ""):
        raise HTTPException(400, 'invalid macro name')
    if not params:
        return macro_name
    if len(params) > _MACRO_PARAM_MAX_COUNT:
        raise HTTPException(400, 'too many macro parameters')
    parts: list[str] = []
    for key, value in params.items():
        key_str = str(key)
        if len(key_str) > _MACRO_PARAM_KEY_MAX_LEN or not _MACRO_PARAM_KEY_RE.match(key_str):
            raise HTTPException(400, 'invalid macro parameter name')
        # Casing is passed through untouched: Klipper's params dict is
        # case-sensitive, so normalising here would silently break macros.
        value_str = str(value)
        if len(value_str) > _MACRO_PARAM_VALUE_MAX_LEN or not _MACRO_PARAM_VALUE_RE.match(value_str):
            raise HTTPException(400, 'invalid macro parameter value')
        parts.append(f"{key_str}={value_str}")
    return " ".join([macro_name, *parts])


async def run_macro(
    printer: PrinterConfig,
    macro_name: str,
    params: dict[str, str] | None = None,
) -> CommandResult:
    return await run_single_command(printer, build_macro_command(macro_name, params))


async def start_print(printer: PrinterConfig, filename: str) -> CommandResult:
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        start_fn = getattr(client, 'start_print', None)
        if start_fn:
            result = await start_fn(filename)
            return CommandResult(result=str(result.get('response', result) if isinstance(result, dict) else result))
        raise HTTPException(501, f"start_print not implemented for {printer.protocol.value}")
    return CommandResult(result=await client.start_print(_relative_gcode_filename(filename)))


async def _apply_anomaly_acks(statuses: list[FleetPrinterStatus]) -> None:
    """Mark acked anomalies and auto-clear stale acks for the fetched devices.

    Fetches every AnomalyAck for the devices in THIS fetch in a single query
    (device_id -> set(codes)), then in one pass per status: marks each anomaly
    whose code is acked, and DELETEs any ack rows whose code is no longer present
    in that device's current anomaly set (the condition cleared) so a later
    recurrence re-alerts. Scoped strictly to `statuses` — `fetch_fleet` is also
    called with a single-printer list (get_printer), so a global prune would wipe
    other devices' acks. Devices not in this fetch are never touched.
    """
    from sqlalchemy import select, delete
    from .db import AsyncSessionLocal
    from .models_db import AnomalyAck

    device_ids = [s.id for s in statuses]
    if not device_ids:
        return

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id.in_(device_ids))
        )).scalars().all()
        acked: dict[str, set[str]] = {}
        for row in rows:
            acked.setdefault(row.device_id, set()).add(row.code)

        pruned = False
        for status in statuses:
            device_acked = acked.get(status.id)
            if not device_acked:
                continue
            current = {item.code for item in status.anomalies}
            for item in status.anomalies:
                if item.code in device_acked:
                    item.acked = True
            stale = device_acked - current
            if stale:
                await db.execute(
                    delete(AnomalyAck).where(
                        AnomalyAck.device_id == status.id,
                        AnomalyAck.code.in_(stale),
                    )
                )
                pruned = True
        if pruned:
            await db.commit()


async def fetch_fleet(printers: list[PrinterConfig]) -> list[FleetPrinterStatus]:
    statuses = await asyncio.gather(*(_safe_fetch_printer_status(p) for p in printers if p.enabled))
    await _apply_anomaly_acks(statuses)
    return sorted(statuses, key=lambda item: item.name.lower())


async def fetch_printer_settings(printer: PrinterConfig) -> PrinterConfig:
    return printer


async def save_printer_settings(printer: PrinterConfig, request: PrinterSettingsUpdateRequest) -> PrinterSettingsSaveResponse:
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        _, config_path, backup_path = await update_printer_fields(printer.id, {})
        return PrinterSettingsSaveResponse(printer_id=printer.id, config_path=str(config_path), backup_path=str(backup_path), printer=printer)

    normalized = _normalize_printer_settings_updates(updates)
    if 'nozzle_diameter_mm' in normalized:
        nozzle = normalized['nozzle_diameter_mm']
        if nozzle is not None and (nozzle < 0.1 or nozzle > 2.0):
            raise ValueError('Nozzle diameter must be between 0.10 mm and 2.00 mm')

    # H4 BUG FIX: Enforce the seat-limit check on the disabled->enabled transition before
    # calling the writer. update_printer_fields (app.config) does not accept a device_limit
    # kwarg, so the check must happen here rather than being passed through to the writer.
    if normalized.get('enabled') is True and not printer.enabled:
        from .config import get_config
        from .license import get_license
        device_limit = get_license().device_limit
        enabled_count = sum(1 for p in get_config().printers if p.enabled)
        if enabled_count >= device_limit:
            raise ValueError(f"Device limit reached ({enabled_count}/{device_limit})")

    updated, config_path, backup_path = await update_printer_fields(printer.id, normalized)
    return PrinterSettingsSaveResponse(
        printer_id=printer.id,
        config_path=str(config_path),
        backup_path=str(backup_path),
        printer=PrinterConfig.model_validate(updated),
    )


async def fetch_fleet_settings(printers: list[PrinterConfig]) -> FleetSettingsResponse:
    from .config import get_config
    cfg = get_config()
    return FleetSettingsResponse(dashboard_settings=cfg.dashboard_settings, material_presets=cfg.material_presets)


async def save_fleet_settings(request: FleetSettingsUpdateRequest) -> FleetSettingsResponse:
    updates = request.model_dump(exclude_unset=True)
    normalized: dict[str, Any] = {}
    if 'dashboard_settings' in updates and updates['dashboard_settings'] is not None:
        normalized['dashboard_settings'] = updates['dashboard_settings']
    if 'material_presets' in updates and updates['material_presets'] is not None:
        presets = []
        for item in updates['material_presets']:
            if not item.get('label'):
                continue
            presets.append({
                'label': str(item['label']).strip(),
                'nozzle': round(float(item.get('nozzle', 0) or 0), 3),
                'bed': round(float(item.get('bed', 0) or 0), 3),
                'builtin': bool(item.get('builtin', False)),
            })
        normalized['material_presets'] = presets
    updated, config_path, backup_path = await update_farm_fields(normalized)
    from .models import FarmConfig
    cfg = FarmConfig.model_validate(updated)
    return FleetSettingsResponse(
        dashboard_settings=cfg.dashboard_settings,
        material_presets=cfg.material_presets,
        config_path=str(config_path),
        backup_path=str(backup_path),
    )


async def _execute_action(client: MoonrakerClient, action: str) -> None:
    if action == "home":
        await client.run_gcode("G28")
        return
    if action == "motors_off":
        await client.run_gcode("M84")
        return
    if action == "cooldown":
        await client.run_gcode("M104 S0\nM140 S0")
        return
    if action == "emergency_stop":
        await client.emergency_stop()
        return
    if action == "pause":
        await client.pause()
        return
    if action == "resume":
        await client.resume()
        return
    if action == "cancel":
        await client.cancel()
        return
    if action == "firmware_restart":
        await client.firmware_restart()
        return
    raise ValueError(f"Unsupported action: {action}")


def _evaluate_action_plan(printer: PrinterConfig, status: FleetPrinterStatus, action: str, macro_name: str | None = None, nozzle_target: float | None = None, bed_target: float | None = None) -> DryRunResult:
    blocking: list[str] = []
    warnings: list[str] = []
    required_state = _required_state_for_action(action)
    if not status.online and action != "emergency_stop":
        blocking.append("Printer is offline")
    if printer.maintenance_lockout and action not in {"cooldown", "motors_off", "emergency_stop"}:
        blocking.append("Printer is in maintenance lockout")
    if action != "emergency_stop" and action not in status.available_actions and action not in {"macro", "temperature"}:
        blocking.append(f"Action {action} is not currently available")
    if action == "pause" and status.job.state != "printing":
        blocking.append("Pause only makes sense while printing")
    if action == "resume" and status.job.state != "paused":
        blocking.append("Resume only makes sense while paused")
    if action == "cancel" and status.job.state not in {"printing", "paused"}:
        blocking.append("Cancel only makes sense while a print is active or paused")
    if action == "firmware_restart" and status.job.state == "printing":
        warnings.append("Firmware restart would interrupt an active print")
    if action == "home":
        motion_note = _motion_summary(status)
        if status.job.state == "printing":
            blocking.append("Home is blocked while a print is active")
        if status.capability.motion_check_required and not _homed_axes(status):
            warnings.append("Motion check: axes are not currently marked homed")
        if (status.nozzle.temperature or 0) > 180:
            warnings.append(f"Nozzle is hot at {status.nozzle.temperature:.1f} C")
        return DryRunResult(
            printer_id=printer.id,
            name=printer.name,
            eligible=not blocking,
            would_execute=not blocking,
            current_state=status.job.state or status.state,
            required_state=required_state,
            blocking_reasons=blocking,
            warnings=warnings,
            motion_summary=motion_note,
        )
    if action == "macro":
        if not macro_name:
            blocking.append("Macro name is required")
        if status.job.state == "printing":
            warnings.append("Macro execution during an active print should be treated as unsafe unless explicitly intended")
        if status.capability.motion_check_required and not _homed_axes(status):
            warnings.append("Macro motion check: axes are not currently marked homed")
    if action == "temperature":
        if nozzle_target is None and bed_target is None:
            blocking.append("At least one target temperature is required")
        if nozzle_target is not None and printer.safe_nozzle_max_c is not None and nozzle_target > printer.safe_nozzle_max_c:
            blocking.append(f"Requested nozzle temperature {nozzle_target} exceeds configured safe_nozzle_max_c {printer.safe_nozzle_max_c}")
        if bed_target is not None and printer.safe_bed_max_c is not None and bed_target > printer.safe_bed_max_c:
            blocking.append(f"Requested bed temperature {bed_target} exceeds configured safe_bed_max_c {printer.safe_bed_max_c}")
        if nozzle_target is not None and nozzle_target > 260:
            warnings.append("Requested nozzle target is unusually high")
        if bed_target is not None and bed_target > 100:
            warnings.append("Requested bed target is unusually high")
    return DryRunResult(
        printer_id=printer.id,
        name=printer.name,
        eligible=not blocking,
        would_execute=not blocking,
        current_state=status.job.state or status.state,
        required_state=required_state,
        blocking_reasons=blocking,
        warnings=warnings,
        motion_summary=_motion_summary(status) if action in {"home", "macro"} else None,
    )


def _required_state_for_action(action: str) -> str | None:
    mapping = {
        "pause": "printing",
        "resume": "paused",
        "cancel": "printing_or_paused",
        "home": "ready_or_idle",
        "motors_off": "ready_or_idle",
        "cooldown": "any_online_state",
        "firmware_restart": "safe_idle_state",
        "macro": "safe_motion_state",
        "temperature": "any_online_state",
    }
    return mapping.get(action)


def _ui_targets_for_printer(printer: PrinterConfig) -> list[UiTarget]:
    targets: list[UiTarget] = []
    seen: set[tuple[str, str]] = set()
    for item in printer.ui_targets:
        key = (item.provider, item.url)
        if key in seen:
            continue
        seen.add(key)
        targets.append(item)

    if printer.fluidd_url:
        key = ("fluidd", printer.fluidd_url)
        if key not in seen:
            targets.append(UiTarget(provider="fluidd", label="Fluidd", url=printer.fluidd_url, mode="direct", primary=not targets))

    return targets


# CNC-class machine types whose job/motion concepts don't map onto the
# generic FDM action set below (home/motors_off/cooldown/firmware_restart are
# Klipper concepts; pause/resume/cancel/start_print would need dedicated
# routes this app doesn't have yet — see cnc_routes.py's estop/home/gcode for
# the ones that DO exist). Mirrors the same 7-type set already duplicated in
# coolant_alerts_integration.py, coolant_models.py, and telemetry.py.
_CNC_MACHINE_TYPES = {"cnc_mill", "cnc_lathe", "cnc_router", "wire_edm", "plasma", "waterjet", "laser"}


def _available_actions(*, state: str, online: bool, job_state: str | None, machine_type: str | None = None) -> list[str]:
    if not online:
        return []
    if machine_type in _CNC_MACHINE_TYPES:
        # None of the generic actions below actually work for these — the
        # batch dispatcher only ever reaches MoonrakerClient (fleet.py's
        # run_batch_action), so offering them here renders buttons that
        # always silently no-op. Real CNC control is the dedicated
        # /cnc/estop, /cnc/home, /cnc/gcode routes instead.
        return []
    actions = ["home", "motors_off", "cooldown", "firmware_restart"]
    normalized_job = (job_state or "").lower()
    normalized_state = state.lower()
    if normalized_job == "printing":
        actions.extend(["pause", "cancel"])
    elif normalized_job == "paused":
        actions.extend(["resume", "cancel"])
    else:
        actions.append("start_print")
    if normalized_state in {"shutdown", "error"}:
        actions = ["firmware_restart"]
    return actions


def _collect_anomalies(*, printer: PrinterConfig, online: bool, state: str, state_message: str | None, nozzle: HeaterStatus, bed: HeaterStatus, job: JobStatus, warnings: list[str], server_info: dict[str, Any], effective_spool_g: float | None = None) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    if not online:
        return [Anomaly(code="offline", severity="critical", message="Printer is offline")]
    if printer.maintenance_lockout:
        anomalies.append(Anomaly(code="maintenance_lockout", severity="warning", message="Printer is in maintenance lockout"))
    # Maintenance-due: next_service_due date (if passed) overrides the YAML boolean.
    # Same helper feeds maintenance_due_count so attention and the count agree.
    if _printer_maintenance_due(printer):
        _due_msg = f"Maintenance due since {printer.next_service_due}" if printer.next_service_due else "Maintenance is due"
        anomalies.append(Anomaly(code="maintenance_due", severity="warning", message=_due_msg))
    if state in {"error", "shutdown"}:
        anomalies.append(Anomaly(code="state_error", severity="critical", message=state_message or f"State is {state}"))
    if job.state == "paused":
        anomalies.append(Anomaly(code="job_paused", severity="warning", message="Print is paused"))
    if (nozzle.temperature or 0) >= 35 and (nozzle.target or 0) <= 0.1 and job.state != "printing":
        anomalies.append(Anomaly(code="idle_nozzle_warm", severity="warning", message=f"Idle nozzle is warm at {nozzle.temperature:.1f} C"))
    if (bed.temperature or 0) >= 45 and (bed.target or 0) <= 0.1 and job.state != "printing":
        anomalies.append(Anomaly(code="idle_bed_warm", severity="warning", message=f"Idle bed is warm at {bed.temperature:.1f} C"))
    # webcam_expected is a static config hint; only fire if Moonraker actually
    # returned webcams (webcam_count from live API) but none are active.
    # Omit the check entirely to avoid false positives from auto-discovery defaults.
    if server_info.get("klippy_connected") is False:
        anomalies.append(Anomaly(code="klippy_disconnected", severity="critical", message="Moonraker is not connected to Klippy"))
    for item in warnings[:3]:
        anomalies.append(Anomaly(code="server_warning", severity="warning", message=item))
    # Spool low warning — fire at <100g (critical) or <200g (warning).
    # Use the effective (live/Spoolman-subtracted) value so the warning matches
    # what the dashboard displays, falling back to the configured value.
    spool_g = effective_spool_g if effective_spool_g is not None else printer.spool_remaining_g
    if spool_g is not None:
        if spool_g < 100:
            anomalies.append(Anomaly(code="spool_critical", severity="critical", message=f"Spool critically low: {spool_g:.0f}g remaining"))
        elif spool_g < 200:
            anomalies.append(Anomaly(code="spool_low", severity="warning", message=f"Spool low: {spool_g:.0f}g remaining"))
    return anomalies


def _suggested_checks(status: FleetPrinterStatus) -> list[str]:
    checks: list[str] = []
    if not status.online:
        checks.append("Verify Moonraker port responds on localhost and systemd units are active.")
        checks.append("Check the MCU by-id path and printer instance mapping.")
        return checks
    if status.capability.maintenance_lockout:
        checks.append("Printer is locked out for maintenance; clear the lockout before dispatching jobs.")
    if status.state in {"error", "shutdown"}:
        checks.append("Inspect the state message and recent log lines before restarting firmware.")
        checks.append("Confirm heaters and endstops are in a safe state.")
    if any(item.code == "idle_nozzle_warm" for item in status.anomalies):
        checks.append("Confirm the hotend target is zero and the printer is not warming for a queued job.")
    if status.job.state == "paused":
        checks.append("Decide whether to resume or cancel the paused job.")
    if not checks:
        checks.append("No immediate issues detected.")
    return checks


def _extract_position(toolhead: dict[str, Any]) -> dict[str, float]:
    position = toolhead.get("position")
    if isinstance(position, dict):
        return {str(k): float(v) for k, v in position.items() if _safe_float(v) is not None}
    if isinstance(position, (list, tuple)) and len(position) >= 3:
        keys = ["x", "y", "z", "e"]
        return {keys[i]: float(value) for i, value in enumerate(position[:4]) if _safe_float(value) is not None}
    return {}


def _homed_axes(status: FleetPrinterStatus) -> str:
    raw = status.raw or {}
    toolhead = (raw.get("objects") or {}).get("toolhead", {}) if raw else {}
    return str(toolhead.get("homed_axes") or "")


def _motion_summary(status: FleetPrinterStatus) -> str:
    homed = _homed_axes(status) or "none"
    state = status.job.state or status.state
    return f"state={state}; homed_axes={homed}; nozzle={status.nozzle.temperature or 0:.1f}C; bed={status.bed.temperature or 0:.1f}C"


def _tail_file(path_value: Any, limit: int = 30) -> list[str]:
    if not path_value:
        return []
    try:
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return []
        size = path.stat().st_size
        with open(path, 'rb') as f:
            f.seek(max(0, size - 65536))
            data = f.read().decode('utf-8', errors='replace')
        return data.splitlines()[-limit:]
    except Exception:
        return []



async def fetch_file_detail(printer: PrinterConfig, filename_or_path: str) -> FileDetailResponse:
    if not isinstance(await _get_client(printer), MoonrakerClient):
        raise HTTPException(status_code=404, detail="File detail not supported for this protocol")
    client = await _get_client(printer)
    relative_name = _relative_gcode_filename(filename_or_path)
    raw_metadata = await client.file_metadata(relative_name)
    normalized = _normalize_file_metadata(client, relative_name, raw_metadata)
    file_entry = FileEntry(
        name=Path(relative_name).name,
        path=_ensure_gcodes_path(relative_name),
        kind="file",
        size=normalized.size,
        modified=normalized.modified,
        permissions=None,
        metadata=normalized.raw,
    )
    return FileDetailResponse(
        printer_id=printer.id,
        file=file_entry,
        metadata=normalized,
        compatibility_hints=_build_compatibility_hints(printer, normalized),
    )


async def fetch_current_file(printer: PrinterConfig) -> CurrentFileResponse:
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return CurrentFileResponse(printer_id=printer.id)
    client = await _get_client(printer)
    objects = await client.query_objects({"print_stats": ["filename", "state"]})
    print_stats = objects.get("print_stats", {})
    filename = print_stats.get("filename")
    if not filename:
        return CurrentFileResponse(printer_id=printer.id, filename=None, detail=None)
    detail = await _safe_call(fetch_file_detail(printer, str(filename)), None)
    return CurrentFileResponse(printer_id=printer.id, filename=str(filename), detail=detail)


async def dispatch_upload(
    printers: list[PrinterConfig],
    *,
    printer_ids: list[str],
    filename: str,
    content: bytes,
    relative_path: str | None,
    auto_print: bool,
) -> DispatchUploadResponse:
    selected = {printer.id: printer for printer in printers if printer.enabled and printer.id in printer_ids}
    results: list[DispatchUploadItem] = []
    for printer_id in printer_ids:
        printer = selected.get(printer_id)
        if printer is None:
            results.append(DispatchUploadItem(printer_id=printer_id, filename=filename, errors=["Unknown or disabled printer"]))
            continue
        try:
            uploaded = await upload_gcode(
                printer,
                filename=filename,
                content=content,
                relative_path=relative_path,
                auto_print=auto_print,
            )
            results.append(
                DispatchUploadItem(
                    printer_id=printer_id,
                    filename=uploaded.filename,
                    path=uploaded.path,
                    size=uploaded.size,
                    started_print=uploaded.started_print,
                    warnings=uploaded.warnings,
                )
            )
        except Exception as exc:
            results.append(DispatchUploadItem(printer_id=printer_id, filename=filename, errors=[str(exc)]))
    return DispatchUploadResponse(filename=filename, size=len(content), results=results)


async def set_nozzle_diameter(printer: PrinterConfig, nozzle_diameter_mm: float) -> NozzleUpdateResponse:
    if nozzle_diameter_mm < 0.1 or nozzle_diameter_mm > 2.0:
        raise ValueError("Nozzle diameter must be between 0.10 mm and 2.00 mm")
    _, config_path, backup_path = await update_printer_fields(printer.id, {"nozzle_diameter_mm": round(float(nozzle_diameter_mm), 3)})
    return NozzleUpdateResponse(
        printer_id=printer.id,
        nozzle_diameter_mm=round(float(nozzle_diameter_mm), 3),
        config_path=str(config_path),
        backup_path=str(backup_path),
    )


def _normalize_printer_settings_updates(updates: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    string_keys = {
        'name', 'compatibility_profile', 'current_material', 'current_spool_name', 'camera_url', 'timelapse_dir',
        'maintenance_state', 'last_service_at', 'next_service_due', 'base_url', 'ws_url', 'auth_mode', 'api_key',
        'ui_label', 'fluidd_url', 'serial', 'mqtt_topic'
    }
    float_keys = {'nozzle_diameter_mm', 'filament_diameter_mm', 'wire_used_mm_per_job', 'spool_remaining_g', 'spool_capacity_g', 'maintenance_interval_hours', 'maintenance_interval_filament_g', 'safe_nozzle_max_c', 'safe_bed_max_c'}
    int_keys = {'maintenance_interval_jobs'}
    bool_keys = {'enabled', 'filament_sensor', 'probe', 'webcam_expected', 'maintenance_lockout', 'maintenance_due', 'jog_enabled', 'motion_check_required'}

    for key, value in updates.items():
        if key in string_keys:
            if value is None:
                normalized[key] = None
            else:
                stripped = str(value).strip()
                normalized[key] = stripped or None
        elif key in float_keys:
            normalized[key] = None if value in (None, '') else round(float(value), 3)
        elif key in int_keys:
            normalized[key] = None if value in (None, '') else int(value)
        elif key in bool_keys:
            normalized[key] = bool(value)
        elif key == 'mqtt_field_mapping':
            # {memar_status_key: payload_key} — keep only non-empty string→string pairs.
            mapping = {}
            for mk, pk in (value or {}).items():
                mk_s, pk_s = str(mk).strip(), str(pk).strip()
                if mk_s and pk_s:
                    mapping[mk_s] = pk_s
            normalized[key] = mapping or None
        elif key == 'tags':
            normalized[key] = [str(item).strip() for item in (value or []) if str(item).strip()]
        elif key in {'supported_materials', 'notes', 'maintenance_notes'}:
            normalized[key] = [str(item).strip() for item in (value or []) if str(item).strip()]
        elif key == 'build_volume':
            build = {}
            for axis, raw in (value or {}).items():
                if raw in (None, ''):
                    continue
                try:
                    build[str(axis).lower()] = round(float(raw), 3)
                except Exception:
                    continue
            normalized[key] = build
        elif key == 'ui_targets':
            targets = []
            for item in (value or []):
                url = str(item.get('url') or '').strip()
                label = str(item.get('label') or '').strip()
                if not url or not label:
                    continue
                targets.append({
                    'provider': str(item.get('provider') or 'other').strip() or 'other',
                    'label': label,
                    'url': url,
                    'mode': str(item.get('mode') or 'direct').strip() or 'direct',
                    'primary': bool(item.get('primary', False)),
                })
            if targets and not any(item.get('primary') for item in targets):
                targets[0]['primary'] = True
            normalized[key] = targets
        else:
            normalized[key] = value
    return normalized


def _normalize_file_metadata(client: MoonrakerClient, filename: str, raw_metadata: dict[str, Any]) -> NormalizedFileMetadata:
    thumbnails = raw_metadata.get("thumbnails") or []
    thumbnail_url = None
    for thumb in thumbnails:
        if not isinstance(thumb, dict):
            continue
        relative_path = thumb.get("relative_path") or thumb.get("path") or thumb.get("thumbnail_path")
        if relative_path:
            clean_rel = str(relative_path).lstrip("/")
            if clean_rel.startswith("server/files/"):
                thumbnail_url = client.absolute_url(clean_rel)
            else:
                thumbnail_url = client.absolute_url(f"server/files/gcodes/{clean_rel}")
            break
        if thumb.get("data"):
            thumbnail_url = None
            break
    return NormalizedFileMetadata(
        filename=Path(filename).name,
        path=_ensure_gcodes_path(filename),
        size=_safe_int(raw_metadata.get("size")),
        modified=_safe_float(raw_metadata.get("modified")),
        estimated_time_s=_safe_float(raw_metadata.get("estimated_time")),
        filament_mm=_safe_float(raw_metadata.get("filament_total")),
        filament_g=_safe_float(raw_metadata.get("filament_weight_total")),
        layer_height_mm=_safe_float(raw_metadata.get("layer_height")),
        object_height_mm=_safe_float(raw_metadata.get("object_height")),
        slicer=(raw_metadata.get("slicer") or raw_metadata.get("slicer_name") or raw_metadata.get("generated_by")),
        thumbnail_url=thumbnail_url,
        thumbnails=[thumb for thumb in thumbnails if isinstance(thumb, dict)],
        raw=raw_metadata,
    )


def _build_compatibility_hints(printer: PrinterConfig, metadata: NormalizedFileMetadata) -> list[str]:
    hints: list[str] = []
    nozzle = printer.nozzle_diameter_mm
    if nozzle is None:
        hints.append("No nozzle diameter stored for this printer yet.")
    else:
        hints.append(f"Printer nozzle: {nozzle:.2f} mm")
        if metadata.layer_height_mm is not None:
            if metadata.layer_height_mm > nozzle:
                hints.append("Layer height exceeds nozzle diameter; verify slicer output before printing.")
            elif metadata.layer_height_mm > nozzle * 0.8:
                hints.append("Layer height is aggressive for this nozzle; a preflight check is recommended.")
    if metadata.estimated_time_s is not None:
        hints.append("Estimated print time available from Moonraker metadata.")
    else:
        hints.append("Moonraker did not return an estimated print time for this file.")
    return hints


def _estimate_total_duration(print_duration: float | None, progress: float | None) -> float | None:
    if print_duration is None or progress is None or progress <= 0 or progress >= 100:
        return None
    return round(print_duration / (progress / 100.0), 2)


def _estimate_remaining_duration(print_duration: float | None, progress: float | None) -> float | None:
    estimated_total = _estimate_total_duration(print_duration, progress)
    if estimated_total is None or print_duration is None:
        return None
    remaining = estimated_total - print_duration
    if remaining < 0:
        return 0.0
    return round(remaining, 2)


def _strip_traversal_segments(value: str) -> str:
    """Resolve a relative path against an implicit root, refusing to let
    '..' escape above it (any excess '..' is simply dropped rather than
    climbing past the root).

    Defense-in-depth: even though these paths are only ever forwarded to a
    remote Moonraker API (never opened/written on the MEMAR server's own
    filesystem), we still refuse to pass '..' traversal sequences downstream.
    """
    clean = value.strip().lstrip("/")
    resolved: list[str] = []
    for part in clean.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
    return "/".join(resolved)


def _sanitize_upload_filename(filename: str) -> str:
    """Reduce an untrusted upload filename to a bare basename.

    Uploaded filenames must never carry directory components — this strips
    any path traversal (`../`, absolute paths, embedded separators) before
    the name is used to build a display path or forwarded to a downstream
    API. Raises 400 if nothing usable remains.
    """
    name = Path(filename.strip().replace("\\", "/")).name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def _ensure_gcodes_path(filename: str) -> str:
    clean = _strip_traversal_segments(filename)
    if clean.startswith("gcodes/"):
        return clean
    return f"gcodes/{clean}"


def _relative_gcode_filename(filename_or_path: str) -> str:
    clean = _strip_traversal_segments(filename_or_path)
    if clean.startswith("gcodes/"):
        return clean[len("gcodes/") :]
    return clean


def _clean_relative_upload_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    clean = relative_path.strip().strip("/")
    if not clean or clean == "gcodes":
        return None
    if clean.startswith("gcodes/"):
        clean = clean[len("gcodes/"):]
    if any(part == ".." for part in clean.replace("\\", "/").split("/")):
        raise HTTPException(status_code=400, detail="Invalid upload path")
    return clean

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _progress_to_percent(value: Any) -> float | None:
    progress = _safe_float(value)
    if progress is None:
        return None
    return round(progress * 100.0, 2)


def _join_path(root: str, name: str) -> str:
    base = root.rstrip("/")
    return f"{base}/{name}" if base else name


async def _safe_call(coro, default):
    try:
        return await coro
    except Exception:
        return default


def _printer_maintenance_due(printer: PrinterConfig) -> bool:
    """Maintenance-due state, mirroring the per-printer anomaly logic.

    Precedence:
    1. An explicit next_service_due date overrides everything (manual override).
    2. Otherwise, if last_service_at + maintenance_interval_hours are set, derive
       the due date from the last service plus the cadence — self-healing, so it
       never goes stale and reactivates after each service.
    3. Otherwise fall back to the YAML boolean."""
    if printer.next_service_due:
        try:
            return date.fromisoformat(printer.next_service_due) <= date.today()
        except ValueError:
            pass
    if printer.last_service_at and printer.maintenance_interval_hours and printer.maintenance_interval_hours > 0:
        try:
            last = date.fromisoformat(printer.last_service_at)
            due_on = last + timedelta(days=printer.maintenance_interval_hours / 24)
            return date.today() >= due_on
        except ValueError:
            pass
    return bool(printer.maintenance_due)


async def fetch_fleet_metrics(printers: list[PrinterConfig], history_limit: int = 50) -> FleetMetricsResponse:
    active_printers = [printer for printer in printers if printer.enabled]
    statuses = await fetch_fleet(active_printers)
    status_map = {item.id: item for item in statuses}
    # PERF-FLEET-SEQFETCH-02: fetch every printer's history concurrently
    # instead of one at a time (see PERF-FLEET-SEQFETCH-01).
    histories = await asyncio.gather(*(
        _safe_call(fetch_history(printer, limit=history_limit), HistoryResponse(printer_id=printer.id))
        for printer in active_printers
    ))
    metrics: list[FleetMetricCard] = []
    total_jobs_window = completed_jobs_window = failed_jobs_window = cancelled_jobs_window = 0
    total_print_time_window = total_filament_used_window = 0.0
    for printer, history in zip(active_printers, histories):
        card = _history_to_metric_card(printer, status_map.get(printer.id), history)
        metrics.append(card)
        total_jobs_window += card.completed_jobs + card.failed_jobs + card.cancelled_jobs
        completed_jobs_window += card.completed_jobs
        failed_jobs_window += card.failed_jobs
        cancelled_jobs_window += card.cancelled_jobs
        total_print_time_window += card.total_print_time
        total_filament_used_window += card.total_filament_used
    hottest = None
    for status in statuses:
        temp = max(status.nozzle.temperature or 0.0, status.bed.temperature or 0.0)
        if hottest is None or temp > hottest[1]:
            hottest = (status.name, temp)
    summary = FleetMetricsSummary(
        printer_count=len(statuses),
        online_count=len([item for item in statuses if item.online]),
        active_prints=len([item for item in statuses if item.job.state == "printing"]),
        paused_count=len([item for item in statuses if item.job.state == "paused"]),
        attention_count=len([item for item in statuses if item.attention_needed]),
        maintenance_due_count=len([printer for printer in active_printers if _printer_maintenance_due(printer)]),
        total_jobs_window=total_jobs_window,
        completed_jobs_window=completed_jobs_window,
        failed_jobs_window=failed_jobs_window,
        cancelled_jobs_window=cancelled_jobs_window,
        success_rate_window=_percentage(completed_jobs_window, total_jobs_window),
        total_print_time_window=round(total_print_time_window, 2),
        total_filament_used_window=round(total_filament_used_window, 2),
        total_spool_remaining_g=round(sum((printer.spool_remaining_g or 0.0) for printer in active_printers), 1),
        avg_print_time_window=round(total_print_time_window / completed_jobs_window, 2) if completed_jobs_window else 0.0,
        hottest_printer_name=hottest[0] if hottest else None,
        hottest_printer_temp=round(hottest[1], 2) if hottest else None,
    )
    return FleetMetricsResponse(generated_at=datetime.now(timezone.utc).isoformat(), window_limit=history_limit, summary=summary, printers=sorted(metrics, key=lambda i: i.name.lower()))


def _history_to_metric_card(printer: PrinterConfig, status: FleetPrinterStatus | None, history: HistoryResponse) -> FleetMetricCard:
    completed = failed = cancelled = 0
    last_job_end_time = None
    for job in history.jobs:
        normalized = (job.status or "").lower()
        if normalized in {"completed", "success"}:
            completed += 1
        elif normalized in {"error", "failed", "failure"}:
            failed += 1
        elif normalized in {"cancelled", "canceled"}:
            cancelled += 1
        timestamp = job.end_time or job.start_time
        if timestamp and (last_job_end_time is None or timestamp > last_job_end_time):
            last_job_end_time = timestamp
    total_jobs = completed + failed + cancelled
    return FleetMetricCard(
        printer_id=printer.id,
        name=printer.name,
        online=status.online if status else True,
        state=status.job.state if status and status.job.state else (status.state if status else None),
        success_rate=_percentage(completed, total_jobs),
        completed_jobs=completed,
        failed_jobs=failed,
        cancelled_jobs=cancelled,
        total_print_time=round(history.totals.total_print_time, 2),
        total_filament_used=round(history.totals.total_filament_used, 2),
        avg_print_time=round(history.totals.total_print_time / completed, 2) if completed else 0.0,
        spool_remaining_g=printer.spool_remaining_g,
        nozzle_diameter_mm=printer.nozzle_diameter_mm,
        current_material=printer.current_material,
        last_job_end_time=last_job_end_time,
    )


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 1)


async def fetch_temperature_history(printer: PrinterConfig) -> dict:
    """Fetch temperature history from Moonraker temperature store."""
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return {"extruder": [], "bed": [], "mcu": []}
    client = await _get_client(printer)
    try:
        result = await client._request("GET", "/server/temperature_store", params={"include_monitors": "false"})

        import time as _time

        def make_points(heater_data: dict | None) -> list[dict]:
            if not isinstance(heater_data, dict):
                return []
            temps = heater_data.get("temperatures") or []
            targets = heater_data.get("targets") or []
            n = len(temps)
            now = _time.time()
            return [
                {
                    "time": now - (n - 1 - i),
                    "temperature": temps[i],
                    "target": targets[i] if i < len(targets) else None,
                }
                for i in range(n)
            ]

        mcu_raw = result.get("temperature_sensor mcu_temp") or {}
        return {
            "extruder": make_points(result.get("extruder")),
            "bed": make_points(result.get("heater_bed")),
            "mcu": mcu_raw.get("temperatures", []) if isinstance(mcu_raw, dict) else [],
        }
    except Exception as e:
        logger.warning(f"Failed to fetch temperature history for {printer.id}: {e}")

    return {"extruder": [], "bed": [], "mcu": []}


async def fetch_host_stats(printer: PrinterConfig) -> dict:
    """Fetch host system stats from Moonraker."""
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return {
            "cpu_temp": None,
            "cpu_usage": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
            "uptime_s": None,
            "network_rx_mb": None,
            "network_tx_mb": None,
            "websocket_count": 0,
        }
    client = await _get_client(printer)
    try:
        result = await client._request("GET", "/machine/proc_stats")

        # Moonraker sources system_memory from /proc/meminfo, so these are already
        # in kB — dividing twice yielded GB under an "_mb" name and the Health panel
        # rendered "3 / 15 MB" for a 15.7 GB host. One divide: kB -> MB.
        mem_total = result.get("system_memory", {}).get("total", 0) / 1024
        mem_avail = result.get("system_memory", {}).get("available", 0) / 1024
        mem_used = mem_total - mem_avail

        # Parse network RX/TX from wlan0 or primary interface
        network_rx_mb = 0
        network_tx_mb = 0
        network = result.get("network", {})
        for iface_name, iface_data in network.items():
            if "wlan" in iface_name or "eth" in iface_name:
                network_rx_mb += iface_data.get("rx_bytes", 0) / 1024 / 1024
                network_tx_mb += iface_data.get("tx_bytes", 0) / 1024 / 1024

        # Moonraker reports system_cpu_usage as a PER-CORE dict
        # ({"cpu": 9.8, "cpu0": 8.9, "cpu1": 5.0, ...}); the aggregate is "cpu".
        # models.HostStats declares cpu_usage as float|None and the Health panel
        # calls .toFixed() on it, so a raw dict here crashes the whole dashboard.
        # Other/older firmwares may return a bare number — handle both.
        _cpu_usage_raw = result.get("system_cpu_usage")
        if isinstance(_cpu_usage_raw, dict):
            _cpu_usage_raw = _cpu_usage_raw.get("cpu")

        return {
            "cpu_temp": _safe_float(result.get("cpu_temp")),
            "cpu_usage": _safe_float(_cpu_usage_raw),
            "memory_used_mb": round(mem_used, 2),
            "memory_total_mb": round(mem_total, 2),
            "uptime_s": result.get("system_uptime"),
            "network_rx_mb": round(network_rx_mb, 2),
            "network_tx_mb": round(network_tx_mb, 2),
            "websocket_count": result.get("websocket_connections", 0),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch host stats for {printer.id}: {e}")

    return {
        "cpu_temp": None,
        "cpu_usage": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "uptime_s": None,
        "network_rx_mb": None,
        "network_tx_mb": None,
        "websocket_count": 0,
    }


async def fetch_print_queue(printer: PrinterConfig) -> dict:
    """Fetch print queue status from Moonraker."""
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return {"state": "unknown", "jobs": []}
    client = await _get_client(printer)
    try:
        result = await client._request("GET", "/server/job_queue/status")

        return {
            "state": result.get("queue_state", "unknown"),
            "jobs": [
                {
                    "job_id": job.get("job_id", ""),
                    "filename": job.get("filename", ""),
                    "time_added": job.get("time_added", 0),
                }
                for job in result.get("queued_jobs", [])
            ]
        }
    except Exception as e:
        logger.warning(f"Failed to fetch print queue for {printer.id}: {e}")

    return {"state": "unknown", "jobs": []}


async def fetch_update_status(printer: PrinterConfig) -> dict:
    """Fetch update status for Klipper and Moonraker."""
    if not isinstance(await _get_client(printer), MoonrakerClient):
        return {"components": [], "system_packages_pending": 0}
    client = await _get_client(printer)
    try:
        result = await client._request("GET", "/machine/update/status")

        components = []
        version_info = result.get("version_info", {})
        for comp_name, comp_data in version_info.items():
            if isinstance(comp_data, dict) and "version" in comp_data:
                components.append({
                    "name": comp_name,
                    "version": comp_data.get("version", "unknown"),
                    "commits_behind": comp_data.get("commits_behind", 0),
                    "is_dirty": comp_data.get("is_dirty", False),
                })

        return {
            "components": components,
            "system_packages_pending": version_info.get("system", {}).get("package_count", 0),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch update status for {printer.id}: {e}")

    return {"components": [], "system_packages_pending": 0}


async def run_gcode_console(printer: PrinterConfig, script: str) -> dict:
    """Run a G-code command and return the response."""
    client = await _get_client(printer)
    try:
        if isinstance(client, MoonrakerClient):
            result = await client.run_gcode(script)
            return {"ok": True, "result": result or "ok"}
        if hasattr(client, "run_gcode"):
            result = await client.run_gcode(script)
            return {"ok": True, "result": str(result)}
        return {"ok": False, "error": f"G-code console not supported for {printer.protocol.value} protocol"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def fetch_gcode_history(printer: PrinterConfig) -> dict:
    """Fetch G-code command history from Moonraker store."""
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return {"supported": False, "commands": []}
    try:
        lines = await client.gcode_store(100)
        return {
            "supported": True,
            "commands": [
                {"time": item.get("time", 0), "message": item.get("message", ""), "type": item.get("type", "command")}
                for item in lines
            ],
        }
    except Exception as exc:
        logger.warning("Failed to fetch gcode history for %s: %s", printer.id, exc)
        return {"supported": False, "commands": []}


async def auto_load_bed_mesh(printer: PrinterConfig) -> None:
    """If Klippy just became ready and no mesh is active, load the best saved profile.

    Priority: profile named 'default' > alphabetically first profile.
    Skips silently if: not a Moonraker printer, no saved profiles, or a profile is
    already active.
    """
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return
    try:
        data = await client.get_bed_mesh()
    except Exception as exc:
        logger.debug("auto_load_bed_mesh: best-effort query of bed_mesh for %s unavailable (expected when Klippy not ready): %s", printer.id, exc)
        return

    active_profile = data.get("profile_name", "")
    saved_profiles: dict = data.get("profiles", {})

    if active_profile:
        logger.debug("auto_load_bed_mesh: %s already has profile %r active", printer.id, active_profile)
        return
    if not saved_profiles:
        logger.debug("auto_load_bed_mesh: %s has no saved profiles", printer.id)
        return

    # Pick profile to load
    target = "default" if "default" in saved_profiles else sorted(saved_profiles.keys())[0]
    try:
        _validate_profile_name(target)
    except HTTPException:
        logger.warning("auto_load_bed_mesh: %s — skipping profile %r with invalid name", printer.id, target)
        return
    logger.info("auto_load_bed_mesh: %s — loading profile %r", printer.id, target)
    try:
        await client.run_gcode(f"BED_MESH_PROFILE LOAD={target}")
    except Exception as exc:
        logger.debug("auto_load_bed_mesh: best-effort gcode for %s did not apply (expected when printer is in error/shutdown state): %s", printer.id, exc)


def _matrix_bounds(matrix: list[list[float]]) -> tuple[float, float]:
    """Extract min/max Z from a 2D matrix."""
    if not matrix or not all(row for row in matrix):
        return 0.0, 0.0
    flat = [z for row in matrix for z in row if isinstance(z, (int, float))]
    if not flat:
        return 0.0, 0.0
    return min(flat), max(flat)


def _xy_pair(val) -> tuple[float, float] | None:
    """Parse [x, y] pair from Klipper config."""
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return (float(val[0]), float(val[1]))
        except (ValueError, TypeError):
            return None
    return None


def _parse_bed_mesh_profiles(profiles_dict: dict) -> list[dict]:
    """Extract profile metadata from Klipper bed_mesh profiles."""
    if not profiles_dict:
        return []
    result = []
    for name, profile_data in profiles_dict.items():
        if isinstance(profile_data, dict) and "points" in profile_data:
            points = profile_data.get("points", [])
            params = profile_data.get("mesh_params", {})
            matrix = profile_data.get("mesh_matrix") or []
            min_z, max_z = _matrix_bounds(matrix)
            result.append({
                "name": str(name),
                "points": points,
                "mesh_params": params,
                "mesh_matrix": matrix,  # Include matrix for 3D/comparison visualization
                "probed_points": len(points) if points else 0,
                "min_z": round(min_z, 4) if matrix else None,
                "max_z": round(max_z, 4) if matrix else None,
            })
    return result


async def fetch_bed_mesh(printer: PrinterConfig) -> dict:
    """Fetch bed mesh data from Moonraker for visualization (including all saved profiles)."""
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return {"supported": False}
    try:
        data = await client.get_bed_mesh()
        matrix = data.get("probed_matrix") or data.get("mesh_matrix") or []

        # Extract all saved profiles
        profiles_dict = data.get("profiles", {})
        profiles = _parse_bed_mesh_profiles(profiles_dict)

        # Current/active profile state
        profile_name = data.get("profile_name", "")
        is_probed = bool(data.get("probed_matrix"))

        # Spatial extent of active mesh
        mesh_min = data.get("mesh_min")
        mesh_max = data.get("mesh_max")
        x_min, y_min = _xy_pair(mesh_min) if mesh_min else (None, None)
        x_max, y_max = _xy_pair(mesh_max) if mesh_max else (None, None)

        if not matrix:
            return {
                "supported": True,
                "active_profile": profile_name,
                "active_is_probed": is_probed,
                "profiles": profiles,
                "mesh_matrix": [],
                "x_count": 0,
                "y_count": 0,
                "global_min_z": None,
                "global_max_z": None,
            }

        if not all(row for row in matrix):
            return {
                "supported": True,
                "active_profile": profile_name,
                "active_is_probed": is_probed,
                "profiles": profiles,
                "mesh_matrix": [],
                "x_count": 0,
                "y_count": 0,
                "global_min_z": None,
                "global_max_z": None,
            }

        # Global min/max across all profiles for consistent color scale
        all_matrices = [matrix] + [p.get("mesh_matrix", []) for p in profiles if p.get("mesh_matrix")]
        min_z_global = None
        max_z_global = None
        for m in all_matrices:
            if m and all(row for row in m):
                min_z, max_z = _matrix_bounds(m)
                if min_z_global is None or min_z < min_z_global:
                    min_z_global = min_z
                if max_z_global is None or max_z > max_z_global:
                    max_z_global = max_z

        return {
            "supported": True,
            "active_profile": profile_name,
            "active_is_probed": is_probed,
            "profiles": profiles,
            "mesh_matrix": matrix,
            "x_count": len(matrix[0]) if matrix else 0,
            "y_count": len(matrix),
            "global_min_z": round(min_z_global, 4) if min_z_global is not None else None,
            "global_max_z": round(max_z_global, 4) if max_z_global is not None else None,
            "mesh_extent": {
                "x_min": x_min, "x_max": x_max,
                "y_min": y_min, "y_max": y_max,
            } if all(v is not None for v in [x_min, x_max, y_min, y_max]) else None,
        }
    except Exception as exc:
        logger.warning("Failed to fetch bed mesh for %s: %s", printer.id, exc)
        return {"supported": False}


async def fetch_exclude_objects(printer: PrinterConfig) -> dict:
    """Fetch exclude_object state from Moonraker."""
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return {"supported": False, "objects": [], "excluded": []}
    try:
        data = await client.get_exclude_objects()
        return {
            "supported": True,
            "objects": data.get("objects", []),
            "excluded": data.get("excluded_objects", []),
            "current_object": data.get("current_object"),
        }
    except Exception as exc:
        logger.warning("Failed to fetch exclude objects for %s: %s", printer.id, exc)
        return {"supported": False, "objects": [], "excluded": []}


async def exclude_object(printer: PrinterConfig, name: str) -> dict:
    """Exclude an object from the current print."""
    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        return {"ok": False, "error": "Not supported for this protocol"}
    try:
        await client.run_exclude_object(name)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def stream_webcam(printer: PrinterConfig, uid: str):
    """Proxy MJPEG stream from printer webcam to browser."""
    from fastapi import HTTPException as _HTTPException
    from fastapi.responses import StreamingResponse
    from urllib.parse import urlparse as _urlparse
    import httpx as _httpx

    client = await _get_client(printer)
    if not isinstance(client, MoonrakerClient):
        raise _HTTPException(status_code=404, detail="Webcam streaming not supported for this protocol")

    try:
        if uid and uid not in ("default", ""):
            webcam_data = await client.webcam_item(uid)
        else:
            cams = await client.list_webcams()
            webcam_data = cams[0] if cams else {}

        stream_url = webcam_data.get("stream_url") or webcam_data.get("snapshot_url")
        if not stream_url:
            raise _HTTPException(status_code=404, detail="No stream URL configured for this webcam")

        stream_url = client.absolute_url(stream_url) or stream_url

        # --- SSRF guard (mirrors MoonrakerClient.fetch_binary) ---
        # webcam_data is returned by the printer itself, so a malicious/compromised
        # device could set stream_url to an absolute URL pointing at cloud metadata
        # (169.254.169.254), loopback, or any other internal host. absolute_url()
        # leaves already-absolute URLs untouched, so it does NOT constrain the host.
        # The stream must live on the same host as the operator-configured base_url
        # (the trust anchor). We compare hostname only — legitimate webcams commonly
        # run on a different PORT of the same device (e.g. base :7125, webcam :8080)
        # — while still blocking any pivot to a different host. Private-LAN printer
        # IPs stay allowed by design (the printer itself is on the LAN).
        printer_host = (_urlparse(printer.base_url).hostname or "").lower()
        target_host = (_urlparse(stream_url).hostname or "").lower()
        if not target_host or target_host != printer_host:
            raise _HTTPException(
                status_code=502,
                detail="Webcam stream URL host does not match the configured printer host",
            )

        proxy_headers = client._headers()

        http = _httpx.AsyncClient(timeout=_httpx.Timeout(None, connect=8.0))
        req = http.build_request("GET", stream_url, headers=proxy_headers)
        resp = await http.send(req, stream=True)
        content_type = resp.headers.get("content-type", "multipart/x-mixed-replace; boundary=--BoundaryString")

        async def generate():
            try:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    yield chunk
            finally:
                await resp.aclose()
                await http.aclose()

        return StreamingResponse(generate(), media_type=content_type)
    except _HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to stream webcam %s for %s: %s", uid, printer.id, exc)
        raise _HTTPException(status_code=502, detail=f"Failed to connect to webcam stream: {exc}")
