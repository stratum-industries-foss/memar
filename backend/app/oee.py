"""OEE (Overall Equipment Effectiveness) calculation endpoint."""
import asyncio
from fastapi import APIRouter, Depends
from .config import get_config
from .deps import get_current_user, require_feature
from .fleet import fetch_history

router = APIRouter(tags=["oee"])

@router.get("/api/oee")
async def get_oee(
    _: dict = Depends(get_current_user),
    __: None = Depends(require_feature("oee")),
) -> dict:
    cfg = get_config()
    results = await asyncio.gather(*[_calc_oee(p) for p in cfg.printers if p.enabled], return_exceptions=True)
    return {"devices": results}

async def _calc_oee(printer) -> dict:
    """Three genuinely-distinct OEE factors:

      • availability — fraction of job time actually printing (vs paused/idle)
      • performance  — actual print speed vs the slicer's estimate (ideal/actual)
      • quality      — yield (completed vs attempted)

    Performance uses Moonraker slicer metadata (`estimated_time`); when no jobs
    carry an estimate (e.g. CNC, or un-sliced gcode) it is reported as None rather
    than fabricated, and the composite OEE is left None since it can't be measured.
    """
    resp = await fetch_history(printer, limit=100)
    jobs = [j for j in resp.jobs if j.status is not None]
    completed = [j for j in jobs if j.status == "completed"]
    # Terminal failure statuses mirror telemetry._map_history_status's failure set
    # (raw Moonraker statuses) — "error" alone undercounted klippy_shutdown/
    # klippy_disconnect/failed as non-failures, inflating the quality yield.
    failed = [j for j in jobs if j.status in ("error", "klippy_shutdown", "klippy_disconnect", "failed")]
    non_cancelled = completed + failed

    avail = perf = qual = oee = None

    # Availability: productive (printing) time / total job time.
    total_dur = sum(j.total_duration or 0 for j in non_cancelled)
    if total_dur > 0:
        avail = sum(j.print_duration or 0 for j in non_cancelled) / total_dur

    # Performance: estimated/actual print time per completed job, capped at 1.0.
    perf_samples = []
    for j in completed:
        raw = j.metadata.get("estimated_time")
        try:
            est = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            est = None
        actual = j.print_duration or 0
        if est and est > 0 and actual > 0:
            perf_samples.append(min(1.0, est / actual))
    if perf_samples:
        perf = sum(perf_samples) / len(perf_samples)

    # Quality: yield.
    if completed or failed:
        qual = len(completed) / (len(completed) + len(failed))

    # Composite OEE only when all three factors are actually measurable.
    # Returned as a FRACTION (0-1), same scale as availability/performance/quality
    # so the frontend's single fmtPct() (×100) renders it correctly (was ×100 here
    # AND ×100 in fmtPct -> showed e.g. 8790% instead of 87.9%).
    if avail is not None and perf is not None and qual is not None:
        oee = round(avail * perf * qual, 4)

    return {
        "device_id": printer.id,
        "oee": oee, "availability": avail, "performance": perf, "quality": qual,
        "sample_jobs": len(jobs),
    }


async def _aggregate_fleet_oee() -> dict:
    """Fleet-level OEE: sample_jobs-weighted, None-safe mean of per-printer factors.

    Each factor (oee/availability/performance/quality) is averaged independently,
    including ONLY printers where that factor is measurable — never coercing
    None->0 (that would be the same bug class as the historical NULL-OEE trend) —
    and weighted by each printer's sample_jobs so a 1-job printer doesn't swing the
    fleet like an 80-job one. CNC / un-sliced machines (performance None) are
    surfaced via devices_without_perf rather than silently dragging the average.
    """
    cfg = get_config()
    enabled = [p for p in cfg.printers if p.enabled]
    results = await asyncio.gather(*[_calc_oee(p) for p in enabled], return_exceptions=True) if enabled else []

    def wmean(key: str):
        num = den = 0.0
        for r in results:
            v, w = r.get(key), (r.get("sample_jobs") or 0)
            if v is not None and w > 0:
                num += v * w
                den += w
        return round(num / den, 4) if den > 0 else None

    return {
        "fleet_oee": wmean("oee"),
        "availability": wmean("availability"),
        "performance": wmean("performance"),
        "quality": wmean("quality"),
        "sample_jobs": sum(r.get("sample_jobs") or 0 for r in results),
        "devices_with_data": sum(1 for r in results if r.get("oee") is not None),
        "devices_without_perf": sum(1 for r in results if r.get("performance") is None),
        "device_count": len(enabled),
    }
