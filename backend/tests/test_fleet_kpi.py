"""Fleet KPI: per-job OEE population (trend NULL-bug fix), fleet aggregate,
throughput. Guards the regression where job_log.oee was always NULL."""

from datetime import datetime, timedelta

import pytest
import yaml
from sqlalchemy import select


@pytest.fixture
def kpi_config(tmp_path, monkeypatch):
    import app.config as cfgmod
    cfg = {"printers": [
        {"id": "p1", "name": "P1", "base_url": "http://10.0.0.1", "enabled": True},
        {"id": "p2", "name": "P2", "base_url": "http://10.0.0.2", "enabled": True},
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


@pytest.mark.asyncio
async def test_failed_job_stores_zero_oee(client):
    """Failed jobs must persist oee=0.0 (not NULL) so the trend reflects lost yield."""
    from app.telemetry import record_job_completion
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog

    await record_job_completion("p1", "fail.gcode", "failed", failure_reason="thermal")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(JobLog).where(JobLog.job_name == "fail.gcode"))).scalars().first()
    assert row is not None and row.oee == 0.0


@pytest.mark.asyncio
async def test_completed_job_populates_oee_from_calc(client, kpi_config, monkeypatch):
    """Completed jobs derive oee from the canonical _calc_oee (was always NULL)."""
    import app.oee as oeemod
    from app.telemetry import record_job_completion
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog

    async def fake_calc(printer):
        return {"device_id": printer.id, "oee": 0.8, "availability": 0.9,
                "performance": 0.95, "quality": 0.93, "sample_jobs": 5}
    monkeypatch.setattr(oeemod, "_calc_oee", fake_calc)

    await record_job_completion("p1", "ok.gcode", "completed")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(JobLog).where(JobLog.job_name == "ok.gcode"))).scalars().first()
    assert row is not None and row.oee == 0.8


@pytest.mark.asyncio
async def test_oee_trend_nonzero(client):
    """Regression for the NULL-OEE bug: a populated oee column yields a real trend."""
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog
    from app.analytics import FleetKPICalculator

    async with AsyncSessionLocal() as db:
        db.add(JobLog(device_id="p1", job_name="a", status="completed", oee=0.8,
                      created_at=datetime.utcnow() - timedelta(hours=6)))
        db.add(JobLog(device_id="p1", job_name="b", status="completed", oee=0.6,
                      created_at=datetime.utcnow() - timedelta(hours=8)))
        await db.commit()
        trend = await FleetKPICalculator(db).calculate_oee_trend(days=7)
    assert any(d["oee"] > 0 for d in trend)


@pytest.mark.asyncio
async def test_throughput(client):
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog
    from app.analytics import FleetKPICalculator

    async with AsyncSessionLocal() as db:
        for i in range(3):
            db.add(JobLog(device_id="p1", job_name=f"j{i}", status="completed",
                          created_at=datetime.utcnow() - timedelta(hours=1)))
        await db.commit()
        thru = await FleetKPICalculator(db).calculate_throughput(hours=24)
    assert thru["jobs"] >= 3 and thru["jobs_per_day"] >= 3


@pytest.mark.asyncio
async def test_fleet_oee_weighted_none_safe(kpi_config, monkeypatch):
    """Fleet OEE: weighted by sample_jobs, None never coerced to 0, perf-less
    machines surfaced via devices_without_perf."""
    import app.oee as oeemod

    async def fake_calc(printer):
        if printer.id == "p1":
            return {"device_id": "p1", "oee": 0.9, "availability": 0.9,
                    "performance": 0.9, "quality": 1.0, "sample_jobs": 80}
        return {"device_id": "p2", "oee": None, "availability": 0.5,
                "performance": None, "quality": 0.5, "sample_jobs": 1}
    monkeypatch.setattr(oeemod, "_calc_oee", fake_calc)

    agg = await oeemod._aggregate_fleet_oee()
    assert agg["fleet_oee"] == 0.9          # only p1 measurable; None excluded, not zeroed
    assert agg["devices_with_data"] == 1
    assert agg["devices_without_perf"] == 1
    assert agg["device_count"] == 2


@pytest.mark.asyncio
async def test_reliability_excludes_always_offline_device(kpi_config):
    """BUG-HIGH-ANALYTICS-01: a single always-offline configured device must not
    inflate fleet MTTR — its downtime is excluded (never-up = decommissioned, not a
    repair). MTTR must reflect only devices that were up at some point."""
    from app.db import AsyncSessionLocal
    from app.models_db import FleetStatusLog
    from app.analytics import FleetKPICalculator

    base = datetime.utcnow() - timedelta(hours=2)
    async with AsyncSessionLocal() as db:
        # p1: up,up,up,down,up  → exactly 1 up->down failure and 1 down sample.
        for i, (st, on) in enumerate(
            [("idle", True), ("idle", True), ("printing", True), ("offline", False), ("idle", True)]
        ):
            db.add(FleetStatusLog(device_id="p1", state=st, online=on,
                                  timestamp=base + timedelta(minutes=i)))
        # p2: ALWAYS offline — 100 down samples, 0 failures, never up.
        for i in range(100):
            db.add(FleetStatusLog(device_id="p2", state="offline", online=False,
                                  timestamp=base + timedelta(minutes=i)))
        await db.commit()
        rel = await FleetKPICalculator(db).calculate_reliability(days=7)

    assert rel["failures"] == 1
    # SAMPLE_S=60 → 1 down sample == 1.0 minute of downtime; p2's 100 must NOT count.
    assert rel["mttr_minutes"] == 1.0, f"always-offline p2 must not inflate MTTR; got {rel['mttr_minutes']}"


# ── Per-file print counts (Files tab "Times printed") ────────────────────────


async def _seed_jobs(rows: list[tuple[str, str | None]]) -> None:
    """Seed JobLog with (device_id, job_name) pairs, all terminal 'completed'."""
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog

    async with AsyncSessionLocal() as db:
        for device_id, job_name in rows:
            db.add(JobLog(device_id=device_id, job_name=job_name, status="completed",
                          created_at=datetime.utcnow() - timedelta(hours=1)))
        await db.commit()


@pytest.mark.asyncio
async def test_print_counts_groups_by_job_name(admin_client, kpi_config):
    """3 runs of thing.gcode on p1 → exactly one bucket with count 3."""
    await _seed_jobs([("p1", "thing.gcode")] * 3)

    r = await admin_client.get("/api/printers/p1/files/print-counts")
    assert r.status_code == 200, r.text
    assert r.json() == [{"job_name": "thing.gcode", "count": 3}]


@pytest.mark.asyncio
async def test_print_counts_scoped_to_device(admin_client, kpi_config):
    """Counts are per-device: p2's runs of the same file must not leak into p1."""
    await _seed_jobs([("p1", "shared.gcode"), ("p2", "shared.gcode"), ("p2", "shared.gcode")])

    p1 = (await admin_client.get("/api/printers/p1/files/print-counts")).json()
    p2 = (await admin_client.get("/api/printers/p2/files/print-counts")).json()
    assert p1 == [{"job_name": "shared.gcode", "count": 1}]
    assert p2 == [{"job_name": "shared.gcode", "count": 2}]


@pytest.mark.asyncio
async def test_print_counts_normalizes_gcodes_prefix(admin_client, kpi_config):
    """Moonraker-style prefixed paths and bare relative paths are the SAME file —
    they must merge into one bucket, not emit a duplicate key. Subdirectory paths
    keep their directory (the browser keys on the gcodes-relative path, not the
    basename), so calib/x.gcode stays distinct from x.gcode."""
    await _seed_jobs([
        ("p1", "gcodes/thing.gcode"),
        ("p1", "thing.gcode"),
        ("p1", "/gcodes/thing.gcode"),
        ("p1", "calib/x.gcode"),
    ])

    body = (await admin_client.get("/api/printers/p1/files/print-counts")).json()
    assert body == [
        {"job_name": "calib/x.gcode", "count": 1},
        {"job_name": "thing.gcode", "count": 3},
    ]


@pytest.mark.asyncio
async def test_print_counts_null_job_name_is_unknown_file(admin_client, kpi_config):
    """CNC machines can report no program name (NULL job_name). Those rows surface
    as 'Unknown file' — the same label fetch_history uses — and never collide with
    a real browsed file (which then reads '—' in the UI)."""
    await _seed_jobs([("p1", None), ("p1", ""), ("p1", "real.gcode")])

    body = (await admin_client.get("/api/printers/p1/files/print-counts")).json()
    assert {row["job_name"]: row["count"] for row in body} == {"Unknown file": 2, "real.gcode": 1}


@pytest.mark.asyncio
async def test_print_counts_empty_and_unknown_printer(admin_client, kpi_config):
    """No history → empty list (frontend renders '—'). Unknown printer → 404."""
    assert (await admin_client.get("/api/printers/p1/files/print-counts")).json() == []
    assert (await admin_client.get("/api/printers/nope/files/print-counts")).status_code == 404


@pytest.mark.asyncio
async def test_print_counts_requires_auth(client, kpi_config):
    """Read endpoint is behind the normal auth gate."""
    assert (await client.get("/api/printers/p1/files/print-counts")).status_code in (401, 403)
