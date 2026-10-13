"""Anomaly-acknowledge feature tests.

Covers the durable ack table, the POST ack endpoint (and its writer gating), and
the suppression + auto-clear lifecycle in fleet._apply_anomaly_acks. The
suppression logic is unit-tested directly against hand-built FleetPrinterStatus
objects so no live adapter (Moonraker/etc.) is needed.
"""

import pytest
import yaml
from sqlalchemy import select

from app.models import Anomaly, FleetPrinterStatus


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Point the config at a devices.yaml with d1 so the ack endpoint's
    _get_printer_or_404 resolves (mirrors tests/test_telemetry.py)."""
    import app.config as cfgmod
    cfg = {"printers": [
        {"id": "d1", "name": "D1", "base_url": "http://10.9.9.9", "enabled": True},
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


def _status(device_id: str, codes: list[str]) -> FleetPrinterStatus:
    """Minimal FleetPrinterStatus carrying the given anomaly codes."""
    return FleetPrinterStatus(
        id=device_id,
        name=device_id.upper(),
        base_url="http://10.0.0.1",
        enabled=True,
        online=True,
        state="idle",
        anomalies=[
            Anomaly(code=c, severity="warning", message=f"{c} fired") for c in codes
        ],
    )


@pytest.mark.asyncio
async def test_ack_endpoint_inserts_row(admin_client, temp_config):
    """The endpoint upserts exactly one AnomalyAck row for (device, code)."""
    from app.models_db import AnomalyAck
    from app.db import AsyncSessionLocal

    resp = await admin_client.post(
        "/api/printers/d1/anomalies/ack", json={"code": "spool_low"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == "d1")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].code == "spool_low"

    # Idempotent upsert — acking the same (device, code) again does not duplicate.
    resp2 = await admin_client.post(
        "/api/printers/d1/anomalies/ack", json={"code": "spool_low"}
    )
    assert resp2.status_code == 200, resp2.text
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == "d1")
        )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ack_endpoint_rejects_empty_code(admin_client, temp_config):
    """Empty / non-string code => 422."""
    r1 = await admin_client.post("/api/printers/d1/anomalies/ack", json={"code": ""})
    assert r1.status_code == 422
    r2 = await admin_client.post("/api/printers/d1/anomalies/ack", json={"code": "   "})
    assert r2.status_code == 422
    r3 = await admin_client.post("/api/printers/d1/anomalies/ack", json={})
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_ack_endpoint_requires_writer(client, temp_config):
    """Unauthenticated callers cannot ack (route is gated by _WRITER)."""
    resp = await client.post("/api/printers/d1/anomalies/ack", json={"code": "spool_low"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_apply_acks_marks_matching_anomaly(client):
    """An existing AnomalyAck row marks the matching anomaly acked=True."""
    from app.fleet import _apply_anomaly_acks
    from app.models_db import AnomalyAck
    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(AnomalyAck(device_id="d1", code="spool_low"))
        await db.commit()

    statuses = [_status("d1", ["spool_low", "idle_bed_warm"])]
    await _apply_anomaly_acks(statuses)

    by_code = {a.code: a for a in statuses[0].anomalies}
    assert by_code["spool_low"].acked is True
    assert by_code["idle_bed_warm"].acked is False


@pytest.mark.asyncio
async def test_apply_acks_lifecycle_prune_and_recurrence(client):
    """When the condition clears, the ack row is pruned, so a later recurrence
    of the same code alerts again (acked=False)."""
    from app.fleet import _apply_anomaly_acks
    from app.models_db import AnomalyAck
    from app.db import AsyncSessionLocal

    # 1. Ack spool_low while it is active -> marked acked.
    async with AsyncSessionLocal() as db:
        db.add(AnomalyAck(device_id="d1", code="spool_low"))
        await db.commit()
    s1 = [_status("d1", ["spool_low"])]
    await _apply_anomaly_acks(s1)
    assert s1[0].anomalies[0].acked is True

    # 2. Condition clears (code no longer present) -> ack row pruned.
    s2 = [_status("d1", [])]
    await _apply_anomaly_acks(s2)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == "d1")
        )).scalars().all()
    assert rows == []

    # 3. Recurrence -> alerts again, not acked.
    s3 = [_status("d1", ["spool_low"])]
    await _apply_anomaly_acks(s3)
    assert s3[0].anomalies[0].acked is False


@pytest.mark.asyncio
async def test_apply_acks_prune_is_scoped_to_fetched_devices(client):
    """A fetch that does NOT include a device must not prune that device's acks.

    fetch_fleet is also called with a single-printer list (get_printer); a global
    prune would wipe every other device's acks. Guard: ack two devices, run the
    helper with only ONE in the fetch, assert the other's ack survives.
    """
    from app.fleet import _apply_anomaly_acks
    from app.models_db import AnomalyAck
    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(AnomalyAck(device_id="d1", code="spool_low"))
        db.add(AnomalyAck(device_id="d2", code="spool_low"))
        await db.commit()

    # Single-device fetch of d1 with the code now cleared -> only d1 is pruned.
    await _apply_anomaly_acks([_status("d1", [])])

    async with AsyncSessionLocal() as db:
        d1 = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == "d1")
        )).scalars().all()
        d2 = (await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == "d2")
        )).scalars().all()
    assert d1 == []          # d1's cleared ack pruned
    assert len(d2) == 1      # d2 untouched — it was not in the fetch
