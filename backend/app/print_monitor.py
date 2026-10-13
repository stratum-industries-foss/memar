"""Print CV monitoring — background loop that checks webcam frames for anomalies."""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Binary path — override with MEMAR_PRINT_CV_BIN env var
_CV_BIN_DEFAULT = str(
    Path(__file__).parent.parent.parent / "tools" / "print-cv" / "target" / "release" / "print-cv"
)

# In-memory state
_prev_frames: dict[str, bytes] = {}          # printer_id -> last JPEG bytes
_monitor_anomalies: dict[str, list] = {}     # printer_id -> recent anomaly dicts (last 10)
_anomaly_callbacks: list = []                # coroutine callbacks for anomaly events

# SSE broadcast queue — frontend polls /api/monitor/events
_sse_queue: asyncio.Queue | None = None


def register_anomaly_callback(cb) -> None:
    """Register an async callback called on each anomaly: cb(printer_id, result)"""
    _anomaly_callbacks.append(cb)


def get_monitor_state() -> dict:
    """Return current anomaly state for all printers."""
    return {
        pid: list(anoms)
        for pid, anoms in _monitor_anomalies.items()
    }


def get_printer_monitor_anomalies(printer_id: str) -> list:
    """Return recent anomalies for a specific printer."""
    return list(_monitor_anomalies.get(printer_id, []))


async def _run_cv(current_bytes: bytes, prev_bytes: bytes | None) -> dict:
    """Run print-cv binary on current frame, optionally with prev frame."""
    cv_bin = os.environ.get("MEMAR_PRINT_CV_BIN", _CV_BIN_DEFAULT)
    if not (shutil.which(cv_bin) or os.path.isfile(cv_bin)):
        return {"anomaly": False, "type": "ok", "score": 0.0,
                "confidence": "low", "reasoning": "print-cv binary not found", "checks": {}}

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(current_bytes)
        cur_path = f.name

    prev_path = None
    if prev_bytes:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(prev_bytes)
            prev_path = f.name

    try:
        cmd = [cv_bin, cur_path]
        if prev_path:
            cmd += ["--prev", prev_path]

        loop = asyncio.get_running_loop()
        def _run():
            return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        proc = await loop.run_in_executor(None, _run)

        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip())
        else:
            logger.warning(f"print-cv failed: {proc.stderr[:200]}")
            return {"anomaly": False, "type": "ok", "score": 0.0,
                    "confidence": "low", "reasoning": f"cv error: {proc.stderr[:100]}", "checks": {}}
    except Exception as e:
        logger.warning(f"print-cv exception: {e}")
        return {"anomaly": False, "type": "ok", "score": 0.0,
                "confidence": "low", "reasoning": str(e), "checks": {}}
    finally:
        try:
            os.unlink(cur_path)
        except OSError:
            pass
        if prev_path:
            try:
                os.unlink(prev_path)
            except OSError:
                pass


async def _check_printer(printer_id: str, fetch_snapshot_fn) -> dict | None:
    """Fetch snapshot and run CV for one printer. Returns anomaly dict or None."""
    try:
        frame_bytes, _ = await fetch_snapshot_fn()
    except Exception as e:
        logger.debug(f"[monitor] snapshot failed for {printer_id}: {e}")
        return None

    prev = _prev_frames.get(printer_id)
    result = await _run_cv(frame_bytes, prev)
    _prev_frames[printer_id] = frame_bytes

    if result.get("anomaly"):
        entry = {
            "printer_id": printer_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            **result,
        }
        if printer_id not in _monitor_anomalies:
            _monitor_anomalies[printer_id] = []
        _monitor_anomalies[printer_id].append(entry)
        # Keep only last 10 anomalies per printer
        _monitor_anomalies[printer_id] = _monitor_anomalies[printer_id][-10:]

        # Push to SSE queue
        if _sse_queue is not None:
            try:
                _sse_queue.put_nowait({"type": "cv_anomaly", "printer_id": printer_id, "data": result})
            except asyncio.QueueFull:
                pass

        # Fire registered callbacks (webhook publish)
        for cb in _anomaly_callbacks:
            try:
                await cb(printer_id, result)
            except Exception as e:
                logger.warning(f"anomaly callback error: {e}")

        return entry
    return None


async def _monitor_loop(get_config_fn, fetch_snapshot_fn) -> None:
    """Background loop. get_config_fn() returns config with .printers list.
    fetch_snapshot_fn(printer) returns async callable -> (bytes, str)."""
    interval = int(os.environ.get("MEMAR_MONITOR_INTERVAL", "30"))
    logger.info(f"[monitor] print monitor started (interval={interval}s)")

    from .fleet import fetch_fleet, fetch_webcam_snapshot
    while True:
        try:
            cfg = get_config_fn()
            # Only monitor enabled printers — fetch_fleet state not available here,
            # so we check all enabled printers with webcams configured
            printers_cfg = [p for p in cfg.printers if p.enabled]
            if not printers_cfg:
                pass
            else:
                # Get current fleet state to filter only printing printers
                try:
                    fleet = await fetch_fleet(printers_cfg)
                except Exception as e:
                    logger.debug(f"[monitor] fleet fetch failed: {e}")
                    fleet = []

                printing = [p for p in fleet if p.job and p.job.state in ("printing", "busy")]
                if printing:
                    # Find config for each printing printer
                    cfg_map = {p.id: p for p in printers_cfg}

                    tasks = []
                    for fp in printing:
                        pcfg = cfg_map.get(fp.id)
                        if not pcfg:
                            continue
                        # Build a zero-arg async callable for fetch_snapshot_fn
                        async def _snap(p=pcfg):
                            return await fetch_webcam_snapshot(p, None)
                        tasks.append(_check_printer(fp.id, _snap))

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    anomalies = [r for r in results if r and not isinstance(r, Exception)]
                    if anomalies:
                        logger.info(f"[monitor] {len(anomalies)} anomaly(ies) detected")
        except Exception as e:
            logger.warning(f"[monitor] loop error: {e}")
        await asyncio.sleep(interval)


def start_monitor(get_config_fn, fetch_snapshot_fn=None) -> asyncio.Task:
    """Start the background monitor task and return it so the caller can
    track/cancel it (asyncio holds only a weak ref — an untracked task can be
    garbage-collected mid-run, silently killing CV monitoring)."""
    global _sse_queue
    _sse_queue = asyncio.Queue(maxsize=200)
    return asyncio.create_task(_monitor_loop(get_config_fn, fetch_snapshot_fn))
