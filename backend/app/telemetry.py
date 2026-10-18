"""Telemetry sampler — persists fleet time-series that analytics reads.

Device identity lives in config; this loop periodically snapshots live status and
writes it to the telemetry tables (FleetStatusLog + CNCMetricsLog). Job history
(JobLog) is written on job-completion transitions from the webhook event detector
(see webhooks.detect_state_changes -> record_job_completion). Without this loop,
the analytics tables stay empty and every KPI reads zero — so analytics being
"functional" depends on this running.

coolant_psi is intentionally left NULL: no shipped adapter reports a pressure
reading (only coolant_active on/off). The column is reserved for a future
pressure-sensor source; coolant-PSI analytics correctly report no_data until then.
"""

from .timeutil import utcnow as _utcnow
import asyncio
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from .db import AsyncSessionLocal
from .models_db import FleetStatusLog, CNCMetricsLog, JobLog, SamplerLock

logger = logging.getLogger(__name__)

# How often to snapshot fleet status (seconds). Kept modest to bound DB growth;
# analytics windows (24h / 7d) are insensitive to the exact rate.
SAMPLE_INTERVAL_S = 60

# This process's unique sampler-lease holder id, and how long a lease stays valid
# without renewal before another worker may take it over.
_HOLDER = f"{os.getpid()}-{secrets.token_hex(4)}"
_LEASE_TTL_S = SAMPLE_INTERVAL_S * 3

# Serializes backfill so a startup run + a manual /api/admin/backfill-jobs can't
# both read the same max(ended_at) and double-insert.
_backfill_lock = asyncio.Lock()

# Retention for the time-series tables (sampler writes ~1 row/device/minute).
RETENTION_DAYS = 30


async def _acquire_sampler_lease(holder: str | None = None) -> bool:
    """Return True iff `holder` (default this process) holds — or just acquired/
    renewed — the sampler lease. Guarantees a single active sampler across
    multiple uvicorn workers. `holder` is injectable for testing."""
    holder = holder or _HOLDER
    now = _utcnow()  # naive UTC — consistent with the stored value
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(SamplerLock).where(SamplerLock.id == 1)
            )).scalar_one_or_none()
            if row is None:
                db.add(SamplerLock(id=1, holder=holder, heartbeat_at=now))
                await db.commit()
                return True
            stale = (now - row.heartbeat_at).total_seconds() > _LEASE_TTL_S
            if row.holder == holder or stale:
                row.holder = holder
                row.heartbeat_at = now
                await db.commit()
                return True
            return False
    except Exception as e:  # noqa: BLE001 — a race on insert just means we lost; skip this tick
        logger.debug("sampler lease contention: %s", e)
        return False

_CNC_MACHINE_TYPES = {
    "cnc_mill", "cnc_lathe", "cnc_router", "wire_edm", "plasma", "waterjet", "laser",
}


async def _sample_once() -> int:
    """Take one fleet snapshot and persist FleetStatusLog (+ CNCMetricsLog) rows."""
    from .config import get_config
    from .fleet import fetch_fleet

    cfg = get_config()
    printers = [p for p in cfg.printers if p.enabled]
    if not printers:
        return 0

    statuses = await fetch_fleet(printers)
    # Record job-completion transitions even when no dashboard WebSocket is open.
    # The 2s WS loop also calls this; _prev_states is shared + lock-guarded, so a
    # given transition is logged exactly once. This is what keeps JobLog (and thus
    # throughput / error-rate / OEE-trend analytics) populated on a headless server.
    try:
        from .webhooks import detect_state_changes
        await detect_state_changes(statuses)
    except Exception as e:  # noqa: BLE001
        logger.debug("sampler state-change detection failed: %s", e)
    # Pull live spool weights from Spoolman if configured (no-op otherwise).
    try:
        await _sync_spoolman()
    except Exception as e:  # noqa: BLE001
        logger.debug("spoolman sync failed: %s", e)
    # Map config machine_type by id for the CNC check.
    mtype = {
        p.id: str(getattr(p.machine_type, "value", p.machine_type)) for p in printers
    }

    written = 0
    async with AsyncSessionLocal() as db:
        for st in statuses:
            db.add(FleetStatusLog(
                device_id=st.id,
                state=st.state or "offline",
                online=bool(st.online),
            ))
            written += 1
            if mtype.get(st.id) in _CNC_MACHINE_TYPES:
                cap = st.capability
                coolant_active = getattr(cap, "coolant_active", None) if cap else None
                # coolant_psi flows through only if an adapter actually reports it
                # (PrinterCapability.coolant_psi); external sensors use the
                # /api/devices/{id}/coolant-psi ingestion endpoint instead. NULL
                # otherwise — coolant-PSI analytics then correctly read no_data.
                coolant_psi = getattr(cap, "coolant_psi", None) if cap else None
                db.add(CNCMetricsLog(
                    device_id=st.id,
                    coolant_psi=coolant_psi,
                    coolant_active=coolant_active,
                    # spindle/feed live on the capability object, not the status
                    # row — reading them off `st` always yielded NULL.
                    spindle_rpm=getattr(cap, "spindle_rpm_current", None) if cap else None,
                    feed_rate_mm_min=getattr(cap, "feed_rate_mm_min", None) if cap else None,
                    machine_state=st.state,
                    tool_id=getattr(cap, "tool_id", None) if cap else None,
                ))
        await db.commit()
    return written


async def record_job_completion(device_id: str, job_name: str | None, status: str,
                                failure_reason: str | None = None, oee: float | None = None,
                                duration_s: int | None = None) -> None:
    """Persist a JobLog row on a job-completion transition (called from the
    webhook state-change detector). Best-effort; never raises into the caller."""
    try:
        # Populate per-job OEE so the trend is real (job_log.oee was historically
        # always NULL -> calculate_oee_trend / Analytics "Avg OEE" read 0). Failed
        # jobs store 0.0 (kept in the average as lost yield, not filter-excluded);
        # completed jobs derive the canonical composite from _calc_oee (a rolling
        # snapshot at completion time — acceptable at fleet scale, far simpler than
        # a per-job recompute the webhook can't feed). Stays None if unmeasurable.
        if oee is None:
            if status == "failed":
                oee = 0.0
            else:
                try:
                    from .config import get_config
                    from .oee import _calc_oee
                    printer = next((p for p in get_config().printers if p.id == device_id), None)
                    if printer is not None:
                        oee = (await _calc_oee(printer)).get("oee")
                except Exception:  # noqa: BLE001
                    oee = None
        async with AsyncSessionLocal() as db:
            db.add(JobLog(
                device_id=device_id,
                job_name=job_name,
                status=status,
                failure_reason=failure_reason,
                oee=oee,
                ended_at=_utcnow(),  # naive UTC — matches backfill + analytics + the column
                duration_s=duration_s,
            ))
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("record_job_completion failed for %s: %s", device_id, e)


def _map_history_status(s: str | None) -> str | None:
    """Map a Moonraker history status to a JobLog terminal status, or None to skip
    (non-terminal / unknown). JobLog stores completed / failed / cancelled."""
    if not s:
        return None
    s = s.lower()
    if s in ("completed", "complete", "finished", "done"):
        return "completed"
    if s in ("cancelled", "canceled", "interrupted", "server_exit"):
        return "cancelled"
    if s in ("error", "klippy_shutdown", "klippy_disconnect", "failed"):
        return "failed"
    return None  # in_progress / standby / printing / unknown — not a finished job


async def backfill_job_history(printers=None, limit: int = 100, lookback_days: int = 30) -> int:
    """Idempotent import of Moonraker job history into JobLog, serialized so a
    startup run and a manual /api/admin/backfill-jobs can't double-insert."""
    async with _backfill_lock:
        return await _backfill_job_history_impl(printers, limit, lookback_days)


async def _backfill_job_history_impl(printers=None, limit: int = 100, lookback_days: int = 30) -> int:
    """Import Moonraker job *history* into JobLog so the DB-backed analytics
    (throughput / error-rate / OEE trend) reflect real past jobs instead of
    reading 0 on a fresh deployment. Rows use the job's real end_time as
    created_at/ended_at (so calculate_oee_trend buckets by the correct day —
    record_job_completion hard-codes now(), which is wrong for a backfill).

    Idempotent + incremental: per device, only imports jobs newer than the latest
    JobLog.ended_at already stored. Best-effort; never raises into the caller.
    """
    from .config import get_config
    from .fleet import fetch_history

    if printers is None:
        printers = [p for p in get_config().printers if p.enabled]
    cutoff = _utcnow() - timedelta(days=lookback_days)
    inserted = 0
    for printer in printers:
        try:
            async with AsyncSessionLocal() as db:
                # Existing (ended_at, job_name) pairs for this device — one query.
                # Used for a precise duplicate check so a genuinely-new job whose
                # end_time collides to the second with a prior import is NOT skipped
                # (the old `ended <= last` cutoff dropped it permanently).
                existing = {
                    (r[0], r[1]) for r in (await db.execute(
                        select(JobLog.ended_at, JobLog.job_name)
                        .where(JobLog.device_id == printer.id)
                    )).all()
                }
            hist = await fetch_history(printer, limit=limit)
            if not hist.jobs:
                continue
            rows = []
            for j in hist.jobs:
                if j.end_time is None:
                    continue
                ended = datetime.utcfromtimestamp(j.end_time)  # naive UTC (matches analytics)
                if ended < cutoff:
                    continue
                if (ended, j.filename) in existing:
                    continue  # already imported on a prior run (exact ended_at + name)
                status = _map_history_status(j.status)
                if status is None:
                    continue
                rows.append(JobLog(
                    device_id=printer.id,
                    job_name=j.filename,
                    status=status,
                    failure_reason=None,
                    oee=0.0 if status == "failed" else None,  # no historical per-job OEE — keep the trend honest
                    created_at=ended,
                    ended_at=ended,
                    duration_s=int(j.print_duration) if j.print_duration else None,
                ))
            if rows:
                async with AsyncSessionLocal() as db:
                    db.add_all(rows)
                    await db.commit()
                inserted += len(rows)
        except Exception as e:  # noqa: BLE001
            logger.warning("backfill_job_history failed for %s: %s", printer.id, e)
    if inserted:
        logger.info("backfill_job_history: imported %d job row(s) from Moonraker history", inserted)
    return inserted


async def _sync_spoolman() -> int:
    """If a Spoolman server is configured (dashboard_settings.spoolman_url), pull
    active spool weights into the in-memory cache fleet._SPOOLMAN_G (read by
    fetch_printer_status). Self-hosted, best-effort, no-op when unconfigured.
    Deliberately does NOT rewrite devices.yaml — that churned the config file and
    its rotating backups every poll. Returns the number of printers cached."""
    from .config import get_config
    from . import fleet as _fleet
    cfg = get_config()
    url = getattr(getattr(cfg, "dashboard_settings", None), "spoolman_url", None)
    # Scheme allowlist (defense-in-depth; the settings write is admin-gated).
    if not url or not str(url).lower().startswith(("http://", "https://")):
        return 0
    from .spoolman import SpoolmanClient
    spools = await SpoolmanClient(url).get_active_spools()
    by_pid = {s.get("printer_id"): s for s in spools if s.get("printer_id")}
    seen: set[str] = set()
    for printer in cfg.printers:
        s = by_pid.get(printer.id)
        if not s or s.get("remaining_weight") is None:
            continue
        try:
            _fleet._SPOOLMAN_G[printer.id] = round(float(s["remaining_weight"]), 1)
            seen.add(printer.id)
        except (TypeError, ValueError):
            pass
    # Forget devices Spoolman no longer reports (so stale weights don't linger).
    for pid in [p for p in _fleet._SPOOLMAN_G if p not in seen]:
        _fleet._SPOOLMAN_G.pop(pid, None)
    if seen:
        logger.debug("spoolman sync: cached weights for %d printer(s)", len(seen))
    return len(seen)


async def _prune_old_telemetry() -> int:
    """Delete telemetry rows older than RETENTION_DAYS so the time-series tables
    don't grow unbounded (sampler writes ~1 row/device/minute). Best-effort."""
    from sqlalchemy import delete
    cutoff = _utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = 0
    try:
        async with AsyncSessionLocal() as db:
            for model in (FleetStatusLog, CNCMetricsLog):
                r = await db.execute(delete(model).where(model.timestamp < cutoff))
                deleted += r.rowcount or 0
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("telemetry prune failed: %s", e)
    if deleted:
        logger.info("telemetry prune: removed %d rows older than %dd", deleted, RETENTION_DAYS)
    return deleted


async def telemetry_sampler_loop() -> None:
    """Background loop: snapshot fleet status every SAMPLE_INTERVAL_S seconds,
    but only while this process holds the sampler lease (single-sampler across
    multiple workers)."""
    logger.info("Telemetry sampler started (holder=%s, interval=%ds)", _HOLDER, SAMPLE_INTERVAL_S)
    _tick = 0
    while True:
        try:
            if await _acquire_sampler_lease():
                n = await _sample_once()
                logger.debug("Telemetry: wrote %d status rows", n)
                _tick += 1
                if _tick % 60 == 1:  # ~hourly, while holding the lease
                    await _prune_old_telemetry()
        except Exception as e:  # noqa: BLE001
            logger.warning("Telemetry sample failed: %s", e)
        await asyncio.sleep(SAMPLE_INTERVAL_S)


def start_telemetry_sampler() -> "asyncio.Task":
    """Start the background telemetry sampler task and return its handle (so the
    app lifespan can cancel it on shutdown)."""
    return asyncio.create_task(telemetry_sampler_loop())
