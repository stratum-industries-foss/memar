"""Multi-worker safety (sampler single-election) + coolant-PSI ingestion path.

These cover the Phase-2 hardening: a real coolant-pressure data source (external
sensors POST readings) and the DB lease that keeps exactly one sampler active
across multiple uvicorn workers.
"""

from app.timeutil import utcnow as _utcnow
import asyncio

import pytest
import yaml
from sqlalchemy import select


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    import app.config as cfgmod
    cfg = {"printers": [
        {"id": "mill1", "name": "Mill 1", "base_url": "http://10.0.0.1",
         "enabled": True, "machine_type": "cnc_mill"},
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


# --- Coolant-PSI ingestion -------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_coolant_psi_persists_and_feeds_analytics(auth_client, temp_config):
    """An external sensor POSTs a PSI reading; it lands in CNCMetricsLog and the
    coolant analytics/depletion then return real data instead of no_data."""
    from app.models_db import CNCMetricsLog
    from app.db import AsyncSessionLocal
    from app.analytics import FleetKPICalculator

    r = await auth_client.post("/api/devices/mill1/coolant-psi", json={"psi": 85.5, "coolant_active": True})
    assert r.status_code == 200
    assert r.json()["psi"] == 85.5

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CNCMetricsLog).where(CNCMetricsLog.device_id == "mill1"))).scalars().all()
        assert len(rows) == 1 and rows[0].coolant_psi == 85.5

        stats = await FleetKPICalculator(db).get_coolant_stats()
        assert stats.get("current_psi") == 85.5  # no longer no_data


@pytest.mark.asyncio
async def test_ingest_coolant_psi_unknown_device_404(auth_client, temp_config):
    r = await auth_client.post("/api/devices/ghost/coolant-psi", json={"psi": 10})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ingest_coolant_psi_negative_rejected(auth_client, temp_config):
    r = await auth_client.post("/api/devices/mill1/coolant-psi", json={"psi": -5})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_ingest_coolant_psi_requires_auth(client, temp_config):
    r = await client.post("/api/devices/mill1/coolant-psi", json={"psi": 50})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_coolant_depletion_reads_ingested_psi(auth_client, temp_config):
    """End-to-end: ingest -> coolant-depletion analysis sees the device."""
    await auth_client.post("/api/devices/mill1/coolant-psi", json={"psi": 12.0})  # below critical
    resp = await auth_client.get("/api/analytics/coolant-depletion")
    assert resp.status_code == 200
    body = resp.json()
    devs = {d["device_id"]: d for d in body["devices"]}
    assert "mill1" in devs
    assert devs["mill1"]["status"] == "critical"  # 12 PSI < 20 threshold


# --- Sampler single-election (multi-worker) -------------------------------------

async def _clear_lock():
    """Reset the shared in-memory lock row (the client fixture doesn't wipe rows)."""
    from app.models_db import SamplerLock
    from app.db import AsyncSessionLocal
    from sqlalchemy import delete
    async with AsyncSessionLocal() as db:
        await db.execute(delete(SamplerLock))
        await db.commit()


@pytest.mark.asyncio
async def test_only_one_holder_acquires_lease(client):
    """Two distinct workers contend for the lease; only the holder keeps it."""
    import app.telemetry as tel
    await _clear_lock()
    assert await tel._acquire_sampler_lease("workerA") is True   # A takes it
    assert await tel._acquire_sampler_lease("workerB") is False  # B blocked (A fresh)
    assert await tel._acquire_sampler_lease("workerA") is True   # A renews


@pytest.mark.asyncio
async def test_stale_lease_can_be_taken_over(client):
    """If the holder goes silent past the TTL, another worker takes the lease."""
    import app.telemetry as tel
    from app.models_db import SamplerLock
    from app.db import AsyncSessionLocal
    from datetime import datetime, timedelta

    await _clear_lock()
    assert await tel._acquire_sampler_lease("deadWorker") is True
    # Age the heartbeat well past the TTL.
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(SamplerLock).where(SamplerLock.id == 1))).scalar_one()
        row.heartbeat_at = _utcnow() - timedelta(seconds=tel._LEASE_TTL_S + 60)
        await db.commit()
    assert await tel._acquire_sampler_lease("freshWorker") is True  # takes over stale lease
    # And the previous holder is now locked out.
    assert await tel._acquire_sampler_lease("deadWorker") is False


@pytest.mark.asyncio
async def test_lease_is_single_holder_and_single_row(client):
    """The lease invariant: once a holder owns a fresh lease, every other worker
    is locked out and the lock table holds exactly one row (id=1 PK guarantees
    no duplicate sampler ownership across workers). True wall-clock concurrency
    safety is provided by the PK + transaction isolation at the DB layer; here we
    assert the ownership logic deterministically."""
    import app.telemetry as tel
    from app.models_db import SamplerLock
    from app.db import AsyncSessionLocal

    await _clear_lock()
    assert await tel._acquire_sampler_lease("w0") is True
    # Every other distinct worker is refused while w0's lease is fresh.
    for i in range(1, 8):
        assert await tel._acquire_sampler_lease(f"w{i}") is False
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SamplerLock))).scalars().all()
    assert len(rows) == 1
    assert rows[0].holder == "w0"
