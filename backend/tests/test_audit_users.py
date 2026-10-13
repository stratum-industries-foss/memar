"""Proves the Farm 'Audit log' and Maker 'Multi-user' tier claims are REAL.

Covers: audit read endpoint tier-gating, login auditing, user create/delete with
audit trail, the multi_user gate on creation, and the safety guards
(no self-delete, no last-admin delete, audit survives user deletion).
"""
import pytest

import app.license as licmod
from app.license import LicenseState, _tier_to_features


def _set_tier(tier: str) -> None:
    licmod._state = LicenseState(
        tier=tier, device_limit=150, expires_at="2099-01-01",
        features=_tier_to_features(tier), customer_id="cus_test", active=True,
    )


def _free() -> None:
    licmod._state = LicenseState(
        tier="free", device_limit=3, expires_at=None,
        features=_tier_to_features("free"), customer_id=None, active=True,
    )


@pytest.mark.asyncio
async def test_audit_endpoint_gated_by_active_license(admin_client):
    """Audit log is on every tier now — the gate is an ACTIVE license: inactive 402, any active tier 200."""
    try:
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        assert (await admin_client.get("/api/admin/audit")).status_code == 402
        _set_tier("maker")  # any active tier now unlocks audit_logs
        assert (await admin_client.get("/api/admin/audit")).status_code == 200
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_login_is_audited(admin_client):
    """The admin_client fixture logged in — that must have written an audit row."""
    try:
        _set_tier("farm")
        r = await admin_client.get("/api/admin/audit", params={"action": "login"})
        assert r.status_code == 200
        assert any(e["action"] == "login" and e["username"] == "admin" for e in r.json())
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_create_user_requires_active_license(admin_client):
    try:
        # multi_user is on every tier now — an INACTIVE license must still 402.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        r = await admin_client.post("/api/admin/users",
                                    json={"username": "bob", "password": "secret12", "role": "operator"})
        assert r.status_code == 402
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_create_and_delete_user_with_audit(admin_client):
    try:
        _set_tier("farm")
        r = await admin_client.post("/api/admin/users",
                                    json={"username": "bob", "password": "secret12", "role": "operator"})
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        assert r.json()["username"] == "bob" and r.json()["role"] == "operator"

        # duplicate username -> 409
        dup = await admin_client.post("/api/admin/users",
                                      json={"username": "bob", "password": "secret12"})
        assert dup.status_code == 409

        # the create was audited
        a = await admin_client.get("/api/admin/audit", params={"action": "user_create"})
        assert any(e["resource"] == f"user:{uid}" for e in a.json())

        # delete + audited
        d = await admin_client.delete(f"/api/admin/users/{uid}")
        assert d.status_code == 200 and d.json()["deleted"] == uid
        a = await admin_client.get("/api/admin/audit", params={"action": "user_delete"})
        assert any(e["resource"] == f"user:{uid}" for e in a.json())
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_cannot_delete_self(admin_client):
    try:
        _set_tier("farm")
        me = (await admin_client.get("/api/auth/me")).json()
        r = await admin_client.delete(f"/api/admin/users/{me['id']}")
        assert r.status_code == 400  # self-delete blocked (also the last admin)
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_audit_events_persist_after_user_deletion(admin_client):
    """Deleting a user must not erase the audit trail of actions on them."""
    try:
        _set_tier("farm")
        uid = (await admin_client.post("/api/admin/users",
               json={"username": "carol", "password": "secret12", "role": "viewer"})).json()["id"]
        await admin_client.delete(f"/api/admin/users/{uid}")
        events = (await admin_client.get("/api/admin/audit")).json()
        assert any(e["action"] == "user_create" and e["resource"] == f"user:{uid}" for e in events)
        assert any(e["action"] == "user_delete" and e["resource"] == f"user:{uid}" for e in events)
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_cannot_demote_last_active_admin_when_other_admin_suspended(admin_client):
    """BUG-HIGH-ADMIN-01: with a 2nd admin that is SUSPENDED, the sole active
    admin (self) must not be demotable — a suspended admin is not a fallback."""
    try:
        _set_tier("farm")  # multi_user feature needed to create the 2nd admin
        # Create a 2nd admin, then suspend it.
        r = await admin_client.post("/api/admin/users",
                                    json={"username": "admin2", "password": "secret123", "role": "admin"})
        assert r.status_code == 201, r.text
        uid2 = r.json()["id"]
        s = await admin_client.post(f"/api/admin/users/{uid2}/suspend")
        assert s.status_code == 200, s.text  # allowed: 2 active admins at suspend time
        # Only ONE active admin now (self). Demoting self to viewer must be blocked.
        me = (await admin_client.get("/api/auth/me")).json()
        d = await admin_client.post(f"/api/admin/users/{me['id']}/role", json={"role": "viewer"})
        assert d.status_code == 400, f"demoting the last ACTIVE admin must 400, got {d.status_code}"
    finally:
        licmod._state = None
