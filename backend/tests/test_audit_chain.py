"""Audit hash chain: detects edits and deletions in the real database."""

import pytest
from sqlalchemy import delete, select, update

from app import audit_chain
from app.audit import record_audit
from app.db import AsyncSessionLocal
from app.models_db import AuditLog


async def _write(n: int, prefix: str = "evt"):
    async with AsyncSessionLocal() as db:
        for i in range(n):
            await record_audit(db, action=f"{prefix}.{i}", user={"id": None, "username": "owner"},
                               resource="test", detail={"i": i})


@pytest.fixture
async def clean_audit(client):
    # `client` builds the app database (init_db) before the table is touched.
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog))
        await db.commit()
    yield


async def test_fresh_chain_verifies(clean_audit):
    await _write(5)
    async with AsyncSessionLocal() as db:
        rep = await audit_chain.verify_chain(db)
    assert rep.intact and rep.chained == 5 and rep.unchained == 0
    assert rep.head and len(rep.head) == 64


async def test_edited_row_is_detected(clean_audit):
    await _write(4)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
        target = rows[1].id
        await db.execute(update(AuditLog).where(AuditLog.id == target).values(username="mallory"))
        await db.commit()
    async with AsyncSessionLocal() as db:
        rep = await audit_chain.verify_chain(db)
    assert not rep.intact
    assert rep.first_break_id == target


async def test_deleted_row_is_detected(clean_audit):
    await _write(4)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
        middle = rows[1].id
        await db.execute(delete(AuditLog).where(AuditLog.id == middle))
        await db.commit()
    async with AsyncSessionLocal() as db:
        rep = await audit_chain.verify_chain(db)
    assert not rep.intact
    assert rep.first_break_id == rows[2].id, "the row after the gap no longer chains"


async def test_rows_before_the_chain_are_unchained_not_tampered(clean_audit):
    async with AsyncSessionLocal() as db:
        db.add(AuditLog(action="legacy.event", username="old"))  # no hashes: pre-chain row
        await db.commit()
    await _write(2)
    async with AsyncSessionLocal() as db:
        rep = await audit_chain.verify_chain(db)
    assert rep.intact and rep.unchained == 1 and rep.chained == 2


async def test_concurrent_writes_stay_one_chain(clean_audit):
    import asyncio
    await asyncio.gather(*[_write(3, prefix=f"p{k}") for k in range(4)])
    async with AsyncSessionLocal() as db:
        rep = await audit_chain.verify_chain(db)
    assert rep.intact and rep.chained == 12


@pytest.fixture
def pro_licence():
    """Feature gates read the in-memory licence; give this test a Pro plan and
    restore whatever was there (the same approach test_audit_users.py uses)."""
    from app import license as licmod
    from app.license import LicenseState, _tier_to_features
    saved = licmod._state
    licmod._state = LicenseState(
        tier="pro", device_limit=40, expires_at="2099-01-01",
        features=_tier_to_features("pro"), customer_id="cus_test", active=True,
    )
    yield
    licmod._state = saved


async def test_verify_endpoint_reports_intact(admin_client, clean_audit, pro_licence):
    await _write(3)
    r = await admin_client.get("/api/admin/audit/verify")
    assert r.status_code == 200, r.text
    assert r.json()["intact"] is True and r.json()["chained_rows"] == 3


async def test_export_has_header_and_chain_fields(admin_client, clean_audit, pro_licence):
    import json
    await _write(2)
    r = await admin_client.get("/api/admin/audit/export?format=json")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["header"]["chain_intact"] is True
    assert body["header"]["chain_head"]
    assert len(body["records"]) == 2 and all(rec["row_hash"] for rec in body["records"])


async def test_export_csv_is_real_rows_only(admin_client, clean_audit, pro_licence):
    await _write(2)
    r = await admin_client.get("/api/admin/audit/export?format=csv")
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("# {")
    assert lines[1].startswith("id,created_at")
    assert len(lines) == 2 + 2  # comment, header, two data rows
    assert "2026-08-06" not in r.text, "must not contain the old fabricated sample rows"
