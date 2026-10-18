"""Tests for the Moonraker-history -> JobLog backfill (telemetry.backfill_job_history)
and its status mapper. The backfill makes DB-backed analytics (throughput /
error-rate / OEE trend) reflect real past jobs instead of reading 0."""

from app.timeutil import utcnow as _utcnow
import time
from datetime import datetime

import pytest
from sqlalchemy import select


def test_map_history_status():
    from app.telemetry import _map_history_status
    assert _map_history_status("completed") == "completed"
    assert _map_history_status("error") == "failed"
    assert _map_history_status("klippy_shutdown") == "failed"
    assert _map_history_status("cancelled") == "cancelled"
    assert _map_history_status("interrupted") == "cancelled"
    assert _map_history_status("in_progress") is None
    assert _map_history_status(None) is None
    assert _map_history_status("") is None


@pytest.mark.asyncio
async def test_backfill_imports_history_idempotently(client, monkeypatch):
    from app import telemetry
    from app.models import PrinterConfig, HistoryResponse, HistoryJob
    from app.models_db import JobLog
    from app.db import AsyncSessionLocal

    printer = PrinterConfig(id="bf1", name="BF1", base_url="http://x")
    now = time.time()
    jobs = [
        HistoryJob(job_id="1", filename="a.gcode", status="completed", end_time=now - 3600, print_duration=1200),
        HistoryJob(job_id="2", filename="b.gcode", status="error", end_time=now - 1800, print_duration=300),
        HistoryJob(job_id="3", filename="c.gcode", status="in_progress", end_time=None),  # skipped (not terminal)
    ]

    async def fake_history(p, limit=100):
        return HistoryResponse(printer_id=p.id, jobs=jobs)

    async def fake_oee(p):
        return {"oee": 0.9}

    monkeypatch.setattr("app.fleet.fetch_history", fake_history)
    monkeypatch.setattr("app.oee._calc_oee", fake_oee)

    n = await telemetry.backfill_job_history([printer], lookback_days=30)
    assert n == 2  # completed + error imported; in_progress skipped

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(JobLog).where(JobLog.device_id == "bf1"))).scalars().all()
    assert {r.status for r in rows} == {"completed", "failed"}
    completed = next(r for r in rows if r.status == "completed")
    failed = next(r for r in rows if r.status == "failed")
    assert completed.oee is None  # no historical per-job OEE — left null to keep the trend honest
    assert failed.oee == 0.0      # failures stored as 0.0 (kept in the average)
    # created_at is bucketed from the job's real end_time, not now().
    assert completed.created_at < _utcnow()
    assert completed.created_at < failed.created_at  # ordering preserved from end_time

    # Idempotent: a second run imports nothing new (incremental dedup on ended_at).
    n2 = await telemetry.backfill_job_history([printer], lookback_days=30)
    assert n2 == 0


@pytest.mark.asyncio
async def test_backfill_imports_new_job_at_same_second(client, monkeypatch):
    """A genuinely-new job whose end_time collides to the exact second with an
    already-imported job MUST still be imported (regression for the old
    `ended <= max(ended_at)` cutoff, which permanently skipped it). Re-running
    afterward is still a no-op."""
    from app import telemetry
    from app.models import PrinterConfig, HistoryResponse, HistoryJob
    from app.models_db import JobLog
    from app.db import AsyncSessionLocal

    printer = PrinterConfig(id="bf2", name="BF2", base_url="http://x")
    # Integer-second timestamp inside the lookback window — no microsecond ambiguity.
    same_second = float(int(time.time()) - 3600)
    jobs = [HistoryJob(job_id="1", filename="first.gcode", status="completed",
                       end_time=same_second, print_duration=1200)]

    async def fake_history(p, limit=100):
        return HistoryResponse(printer_id=p.id, jobs=list(jobs))

    async def fake_oee(p):
        return {"oee": 0.9}

    monkeypatch.setattr("app.fleet.fetch_history", fake_history)
    monkeypatch.setattr("app.oee._calc_oee", fake_oee)

    # First import: one job at `same_second`.
    n1 = await telemetry.backfill_job_history([printer], lookback_days=30)
    assert n1 == 1

    # A genuinely-new job at the SAME second, different filename — must import.
    jobs.append(HistoryJob(job_id="2", filename="second.gcode", status="completed",
                           end_time=same_second, print_duration=900))
    n2 = await telemetry.backfill_job_history([printer], lookback_days=30)
    assert n2 == 1  # not skipped by the exact-second collision

    async with AsyncSessionLocal() as db:
        names = {r.job_name for r in (await db.execute(
            select(JobLog).where(JobLog.device_id == "bf2"))).scalars().all()}
    assert names == {"first.gcode", "second.gcode"}

    # Re-running with the same history imports nothing new (still idempotent).
    n3 = await telemetry.backfill_job_history([printer], lookback_days=30)
    assert n3 == 0
