"""Tests for the alpha-adapter liability acknowledgment gate.

Covers deps.require_alpha_ack + the routes it protects
(feed-rate/gcode/home/jog) plus the two it deliberately does NOT protect
(e-stop, which always dispatches and instead carries a warning in its
response — see cnc_routes.cnc_emergency_stop's own docstring for why).

Uses the same fake-adapter-via-monkeypatch isolation as test_cnc_control.py.
No real hardware/network touched. See ALPHA_PROTOCOLS in app/models.py for
the single source of truth on which protocols this gate applies to.
"""
from unittest.mock import AsyncMock

import pytest

import app.cnc_routes as cnc_routes
import app.deps as deps
import app.license as licmod
from app.license import LicenseState, _tier_to_features
from app.models import ALPHA_PROTOCOLS, FarmConfig, MachineType, PrinterConfig, Protocol

ALPHA_DEVICE_ID = "haas-mill-1"
VERIFIED_DEVICE_ID = "linuxcnc-mill-1"

# One representative alpha protocol per test unless the test explicitly
# parametrizes over all four — ALPHA_PROTOCOLS itself is asserted against
# directly in test_alpha_protocols_are_exactly_the_unverified_four below, so
# the rest of this file doesn't need to re-enumerate all four everywhere.
_ALPHA_PROTOCOL = Protocol.HAAS


def _alpha_config() -> FarmConfig:
    return FarmConfig(printers=[
        PrinterConfig(
            id=ALPHA_DEVICE_ID, name="Test Haas", base_url="http://localhost:8080",
            machine_type=MachineType.CNC_MILL, protocol=_ALPHA_PROTOCOL, enabled=True,
        ),
        PrinterConfig(
            id=VERIFIED_DEVICE_ID, name="Test LinuxCNC", base_url="http://localhost:8081",
            machine_type=MachineType.CNC_MILL, protocol=Protocol.LINUXCNC, enabled=True,
        ),
    ])


@pytest.fixture(autouse=True)
def _active_license():
    """operator_client (used for the per-user test) needs multi_user, which
    needs an active license — same pattern as test_cnc_control.py."""
    licmod._state = LicenseState(
        tier="farm", device_limit=150, expires_at="2099-01-01",
        features=_tier_to_features("farm"), customer_id="cus_test", active=True,
    )
    yield
    licmod._state = None


@pytest.fixture
def alpha_fleet(monkeypatch):
    """Patch BOTH cnc_routes.get_config and deps.get_config to the same fake
    fleet — each module holds its own `from .config import get_config`
    binding, so patching only one leaves require_alpha_ack looking at the
    real (unrelated) config and silently no-op'ing the gate. Returns a fake
    adapter mock so individual tests can set return values."""
    monkeypatch.setattr(cnc_routes, "get_config", _alpha_config)
    monkeypatch.setattr(deps, "get_config", _alpha_config)
    mock = AsyncMock()
    mock.send_gcode.return_value = {"ok": True, "response": "ok"}
    mock.home_axes.return_value = {"ok": True, "response": "homed"}
    mock.set_feed_rate.return_value = {"ok": True}
    mock.emergency_stop.return_value = {"ok": True, "state": "estopped"}
    monkeypatch.setattr(cnc_routes, "_get_cnc_client", lambda printer: mock)
    return mock


def test_alpha_protocols_are_exactly_the_unverified_four():
    assert ALPHA_PROTOCOLS == frozenset({Protocol.HAAS, Protocol.FANUC, Protocol.FADAL, Protocol.MACH4, Protocol.MACH3, Protocol.SINUMERIK})


# ── Ack required before dispatch (feed-rate / gcode / home / jog) ──────────


@pytest.mark.asyncio
async def test_feed_rate_requires_ack_on_alpha_device(admin_client, alpha_fleet):
    r = await admin_client.put(f"/api/devices/{ALPHA_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"
    alpha_fleet.set_feed_rate.assert_not_awaited()


@pytest.mark.asyncio
async def test_gcode_requires_ack_on_alpha_device(admin_client, alpha_fleet):
    r = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"
    alpha_fleet.send_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_home_requires_ack_on_alpha_device(admin_client, alpha_fleet):
    r = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/home", json={"axes": None})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"
    alpha_fleet.home_axes.assert_not_awaited()


@pytest.mark.asyncio
async def test_jog_requires_ack_on_alpha_device(admin_client, alpha_fleet):
    r = await admin_client.post(
        f"/api/devices/{ALPHA_DEVICE_ID}/cnc/jog",
        json={"axis": "X", "distance": 10, "relative": True},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"
    alpha_fleet.send_gcode.assert_not_awaited()


# ── Verified protocols never require the gate ───────────────────────────────


@pytest.mark.asyncio
async def test_feed_rate_on_verified_protocol_never_requires_ack(admin_client, alpha_fleet):
    r = await admin_client.put(f"/api/devices/{VERIFIED_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 200, r.text
    alpha_fleet.set_feed_rate.assert_awaited_once_with(100.0)


@pytest.mark.asyncio
async def test_jog_on_verified_protocol_never_requires_ack(admin_client, alpha_fleet):
    r = await admin_client.post(
        f"/api/devices/{VERIFIED_DEVICE_ID}/cnc/jog",
        json={"axis": "X", "distance": 10, "relative": True},
    )
    assert r.status_code == 200, r.text
    # Relative jog sends 3 sequenced G-code commands: G91 (switch to relative),
    # G1 (the move), G90 (restore absolute) — see T46.
    assert alpha_fleet.send_gcode.await_count == 3


# ── Ack persists across routes, once granted ────────────────────────────────


@pytest.mark.asyncio
async def test_ack_unlocks_all_gated_routes_for_that_device(admin_client, alpha_fleet):
    ack = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert ack.status_code == 200, ack.text
    assert ack.json()["ok"] is True
    assert ack.json()["acked_at"] is not None

    r1 = await admin_client.put(f"/api/devices/{ALPHA_DEVICE_ID}/feed-rate/100")
    assert r1.status_code == 200, r1.text
    r2 = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    assert r2.status_code == 200, r2.text
    r3 = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/home", json={"axes": None})
    assert r3.status_code == 200, r3.text
    r4 = await admin_client.post(
        f"/api/devices/{ALPHA_DEVICE_ID}/cnc/jog",
        json={"axis": "X", "distance": 10, "relative": True},
    )
    assert r4.status_code == 200, r4.text


@pytest.mark.asyncio
async def test_ack_does_not_unlock_a_different_alpha_device(admin_client, alpha_fleet, monkeypatch):
    """Acking haas-mill-1 must not unlock a second, distinct alpha device —
    the gate is per (user, device), not per protocol or blanket-per-user."""
    other_id = "haas-mill-2"

    def _two_haas_config():
        cfg = _alpha_config()
        cfg.printers.append(PrinterConfig(
            id=other_id, name="Second Haas", base_url="http://localhost:8082",
            machine_type=MachineType.CNC_MILL, protocol=_ALPHA_PROTOCOL, enabled=True,
        ))
        return cfg

    monkeypatch.setattr(cnc_routes, "get_config", _two_haas_config)
    monkeypatch.setattr(deps, "get_config", _two_haas_config)

    ack = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert ack.status_code == 200, ack.text

    r = await admin_client.put(f"/api/devices/{other_id}/feed-rate/100")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"


# ── Ack is per-user ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_is_per_user_not_global(admin_client, operator_client, alpha_fleet):
    ack = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert ack.status_code == 200, ack.text

    # admin is acked, but operator (a different user) on the SAME device is not.
    r = await operator_client.put(f"/api/devices/{ALPHA_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"

    # operator acks for themself, then proceeds.
    op_ack = await operator_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert op_ack.status_code == 200, op_ack.text
    r2 = await operator_client.put(f"/api/devices/{ALPHA_DEVICE_ID}/feed-rate/100")
    assert r2.status_code == 200, r2.text


# ── Ack endpoint idempotency ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alpha_ack_endpoint_is_idempotent(admin_client, alpha_fleet):
    first = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert first.status_code == 200, first.text
    second = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    assert second.status_code == 200, second.text
    # Same acked_at both times — the second call must not create a new row
    # (which would violate the UniqueConstraint on (user_id, device_id) and
    # 500, not silently duplicate).
    assert first.json()["acked_at"] == second.json()["acked_at"]


# ── E-stop: always dispatches, never gated, warns instead ───────────────────


@pytest.mark.asyncio
async def test_estop_dispatches_without_ack_on_alpha_device(admin_client, alpha_fleet):
    """The one deliberate exception: e-stop never requires require_alpha_ack —
    gating a device's first-ever E-stop behind a confirmation modal would be
    the "throttled or delayed E-stop" the route's own docstring calls a
    safety bug. It fires immediately and carries the same risk information
    as a warning in the response instead."""
    r = await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    alpha_fleet.emergency_stop.assert_awaited_once()
    assert r.json()["alpha_warning"] == "unverified adapter — stop not guaranteed"


@pytest.mark.asyncio
async def test_estop_on_verified_device_has_no_alpha_warning(admin_client, alpha_fleet):
    r = await admin_client.post(f"/api/devices/{VERIFIED_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    assert "alpha_warning" not in r.json()


@pytest.mark.asyncio
async def test_estop_on_alpha_device_is_audit_logged_as_alpha_dispatch(admin_client, alpha_fleet):
    await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/estop")
    events = (await admin_client.get("/api/admin/audit")).json()
    actions = {e["action"] for e in events}
    assert "cnc_emergency_stop" in actions
    assert "alpha_control_dispatch" in actions
    alpha_rows = [e for e in events if e["action"] == "alpha_control_dispatch"]
    assert any(e["resource"] == f"device:{ALPHA_DEVICE_ID}" for e in alpha_rows)


@pytest.mark.asyncio
async def test_gated_route_dispatch_is_also_audit_logged_as_alpha(admin_client, alpha_fleet):
    await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/alpha-ack")
    await admin_client.post(f"/api/devices/{ALPHA_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    events = (await admin_client.get("/api/admin/audit")).json()
    actions = {e["action"] for e in events}
    assert "cnc_send_gcode" in actions
    assert "alpha_control_dispatch" in actions


@pytest.mark.asyncio
async def test_verified_device_dispatch_is_not_tagged_alpha(admin_client, alpha_fleet):
    await admin_client.post(f"/api/devices/{VERIFIED_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    events = (await admin_client.get("/api/admin/audit")).json()
    actions = [e["action"] for e in events]
    assert "cnc_send_gcode" in actions
    assert "alpha_control_dispatch" not in actions


# ── Regression guard: 3D-printer routes are completely untouched ───────────
# require_alpha_ack is only wired as a Depends() on the four CNC control
# routes in cnc_routes.py — by construction no /api/printers/... FDM route
# can reach it. What's worth testing directly is the is_alpha_protocol field
# this work added to FleetPrinterStatus: it must default False/absent for
# every 3D-printer protocol, since the frontend's ALPHA badge (App.tsx) is
# driven entirely off this one flag.


def test_is_alpha_protocol_false_for_fdm_offline_status():
    from app.fleet import _offline_status

    fdm_printer = PrinterConfig(
        id="fdm-1", name="Test FDM", base_url="http://localhost:9999",
        machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER, enabled=True,
    )
    status = _offline_status(fdm_printer, RuntimeError("connection refused"))
    assert status.is_alpha_protocol is False


def test_is_alpha_protocol_true_for_alpha_cnc_offline_status():
    from app.fleet import _offline_status

    haas_printer = PrinterConfig(
        id=ALPHA_DEVICE_ID, name="Test Haas", base_url="http://localhost:8080",
        machine_type=MachineType.CNC_MILL, protocol=_ALPHA_PROTOCOL, enabled=True,
    )
    status = _offline_status(haas_printer, RuntimeError("connection refused"))
    assert status.is_alpha_protocol is True


def test_is_alpha_protocol_false_for_verified_cnc_offline_status():
    from app.fleet import _offline_status

    linuxcnc_printer = PrinterConfig(
        id=VERIFIED_DEVICE_ID, name="Test LinuxCNC", base_url="http://localhost:8081",
        machine_type=MachineType.CNC_MILL, protocol=Protocol.LINUXCNC, enabled=True,
    )
    status = _offline_status(linuxcnc_printer, RuntimeError("connection refused"))
    assert status.is_alpha_protocol is False
