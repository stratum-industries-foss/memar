"""Telemetry write-path + schema-migration tests.

These cover code the rest of the suite structurally cannot: the ASGI test
transport never fires lifespan, so the sampler / dispatcher never run in other
tests. Here we invoke the sampler directly and assert it actually persists rows,
and we verify the additive column migration that create_all cannot perform.
"""

import asyncio

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    import app.config as cfgmod
    cfg = {"printers": [
        {"id": "d1", "name": "D1", "base_url": "http://10.9.9.9", "enabled": True},
        {"id": "cnc1", "name": "Mill", "base_url": "http://10.9.9.8",
         "enabled": True, "machine_type": "cnc_mill"},
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


@pytest.mark.asyncio
async def test_sampler_writes_and_analytics_reads(client, temp_config):
    """_sample_once persists FleetStatusLog rows, and the analytics calculator
    reads them back — proving the write+read path the dashboards depend on."""
    from app.telemetry import _sample_once
    from app.models_db import FleetStatusLog, CNCMetricsLog
    from app.analytics import FleetKPICalculator
    from app.db import AsyncSessionLocal

    n = await _sample_once()
    assert n >= 2  # both configured devices snapshotted

    async with AsyncSessionLocal() as db:
        fleet_rows = (await db.execute(select(FleetStatusLog))).scalars().all()
        cnc_rows = (await db.execute(select(CNCMetricsLog))).scalars().all()
        assert len(fleet_rows) >= 2
        # The CNC-class device also gets a CNCMetricsLog row.
        assert any(r.device_id == "cnc1" for r in cnc_rows)

        calc = FleetKPICalculator(db)
        util = await calc.calculate_utilization(hours=24)
        assert util["device_count"] == 2
        assert util["sample_count"] >= 2


@pytest.mark.asyncio
async def test_record_job_completion_writes_joblog(client):
    from app.telemetry import record_job_completion
    from app.models_db import JobLog
    from app.db import AsyncSessionLocal

    await record_job_completion("d1", "part.gcode", "completed")
    await record_job_completion("d1", "bad.gcode", "failed", failure_reason="thermal")

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(JobLog).where(JobLog.device_id == "d1"))).scalars().all()
    statuses = {r.status for r in rows}
    assert "completed" in statuses and "failed" in statuses
    assert any(r.failure_reason == "thermal" for r in rows)


@pytest.mark.asyncio
async def test_migration_adds_webhook_secret_to_legacy_db(tmp_path):
    """An existing DB whose webhooks table predates the `secret` column must get
    the column added by init_db's additive migration (create_all won't do it)."""
    from app.db import _ensure_added_columns

    db_file = tmp_path / "legacy.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        async with eng.begin() as conn:
            # Legacy schema: webhooks WITHOUT the secret column.
            await conn.exec_driver_sql(
                "CREATE TABLE webhooks (id INTEGER PRIMARY KEY, url TEXT, events TEXT, "
                "active BOOLEAN, created_by INTEGER, created_at TIMESTAMP)"
            )
        async with eng.begin() as conn:
            cols_before = {r[1] for r in (await conn.exec_driver_sql('PRAGMA table_info("webhooks")')).fetchall()}
            assert "secret" not in cols_before
            await _ensure_added_columns(conn)
        async with eng.begin() as conn:
            cols_after = {r[1] for r in (await conn.exec_driver_sql('PRAGMA table_info("webhooks")')).fetchall()}
        assert "secret" in cols_after
        # Idempotent: running again must not raise.
        async with eng.begin() as conn:
            await _ensure_added_columns(conn)
    finally:
        await eng.dispose()
