"""HTTP-level tests for CNC motion-control routes added to cnc_routes.py:

    POST /api/devices/{id}/cnc/gcode  (MDI G-code)
    POST /api/devices/{id}/cnc/home   (home axes)
    POST /api/devices/{id}/cnc/estop  (emergency stop)
    GET  /api/devices/{id}/cnc/files  (list files)

Covers: admin can drive all four, non-admin (operator/viewer) gets 403 on the
motion routes, files is admin/operator only (same RBAC as feed-rate), a
disconnected/erroring adapter returns a clean 502 (never a 500), and E-stop
goes through even with the shared slowapi limiter turned on (it carries no
rate-limit decorator).

Uses a fake adapter (AsyncMock) swapped in via monkeypatch on
cnc_routes._get_cnc_client — mirrors the isolation pattern used by
test_cnc_metrics.py / test_cnc_webhooks.py. No real hardware/network touched.
"""
from unittest.mock import AsyncMock

import httpx
import pytest

import app.cnc_routes as cnc_routes
import app.deps as deps
import app.license as licmod
from app.license import LicenseState, _tier_to_features
from app.main import app
from app.models import FarmConfig, MachineType, PrinterConfig, Protocol

CNC_DEVICE_ID = "cnc-mill-1"


def _cnc_config() -> FarmConfig:
    return FarmConfig(
        printers=[
            PrinterConfig(
                id=CNC_DEVICE_ID,
                name="Test Mill",
                base_url="http://localhost:8080",
                machine_type=MachineType.CNC_MILL,
                protocol=Protocol.LINUXCNC,
                enabled=True,
            )
        ]
    )


@pytest.fixture(autouse=True)
def _active_license():
    """user creation (operator/viewer fixtures below) needs the multi_user feature,
    which requires an active license — mirrors test_audit_users.py's _set_tier()."""
    licmod._state = LicenseState(
        tier="farm",
        device_limit=150,
        expires_at="2099-01-01",
        features=_tier_to_features("farm"),
        customer_id="cus_test",
        active=True,
    )
    yield
    licmod._state = None


@pytest.fixture
def fake_adapter(monkeypatch):
    """Swap in a mock CNC adapter and point cnc_routes.get_config at a fixed
    one-device fleet. Returned so individual tests can override return values
    or raise errors."""
    mock = AsyncMock()
    mock.send_gcode.return_value = {"ok": True, "response": "ok", "error": None}
    mock.home_axes.return_value = {"ok": True, "response": "homed"}
    mock.emergency_stop.return_value = {"ok": True, "state": "estopped"}
    mock.list_files.return_value = [{"name": "part.nc", "path": "/part.nc"}]

    monkeypatch.setattr(cnc_routes, "_get_cnc_client", lambda printer: mock)
    monkeypatch.setattr(cnc_routes, "get_config", _cnc_config)
    return mock


# operator_client / viewer_client are provided by conftest.py (shared across
# test modules — this file's former local copies were identical and have been
# deduplicated in favor of the conftest versions).


# ── Admin can drive all four routes ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_send_gcode(admin_client, fake_adapter):
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    fake_adapter.send_gcode.assert_awaited_once_with("G0 X10")


@pytest.mark.asyncio
async def test_admin_can_home_axes_default_all(admin_client, fake_adapter):
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={})
    assert r.status_code == 200, r.text
    fake_adapter.home_axes.assert_awaited_once_with("XYZ")


@pytest.mark.asyncio
async def test_admin_can_home_specific_axes(admin_client, fake_adapter):
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={"axes": ["x", "y"]})
    assert r.status_code == 200, r.text
    fake_adapter.home_axes.assert_awaited_once_with("XY")


@pytest.mark.asyncio
async def test_admin_can_estop(admin_client, fake_adapter):
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "state": "estopped"}
    fake_adapter.emergency_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_can_list_files(admin_client, fake_adapter):
    r = await admin_client.get(f"/api/devices/{CNC_DEVICE_ID}/cnc/files")
    assert r.status_code == 200, r.text
    assert r.json()["files"] == [{"name": "part.nc", "path": "/part.nc"}]


# ── Non-admin: 403 on motion-initiating routes, 200 on files ────────────────
# E-stop is the one motion route NOT admin-only — see cnc_routes.py's
# cnc_emergency_stop docstring: whoever's on the floor needs the stop button,
# not just whoever holds an admin login.


@pytest.mark.asyncio
async def test_operator_forbidden_on_motion_initiating_routes(operator_client, fake_adapter):
    gcode = await operator_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    home = await operator_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={})

    assert gcode.status_code == 403, gcode.text
    assert home.status_code == 403, home.text
    fake_adapter.send_gcode.assert_not_awaited()
    fake_adapter.home_axes.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_can_estop(operator_client, fake_adapter):
    fake_adapter.emergency_stop.return_value = {"ok": True, "state": "estopped"}
    estop = await operator_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")

    assert estop.status_code == 200, estop.text
    fake_adapter.emergency_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_viewer_forbidden_on_motion_routes(viewer_client, fake_adapter):
    gcode = await viewer_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    home = await viewer_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={})
    estop = await viewer_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")

    assert gcode.status_code == 403
    assert home.status_code == 403
    assert estop.status_code == 403


@pytest.mark.asyncio
async def test_operator_can_list_files_viewer_forbidden(operator_client, viewer_client, fake_adapter):
    """list_files matches set_feed_rate's RBAC: admin/operator only (T128)."""
    op = await operator_client.get(f"/api/devices/{CNC_DEVICE_ID}/cnc/files")
    view = await viewer_client.get(f"/api/devices/{CNC_DEVICE_ID}/cnc/files")
    assert op.status_code == 200, op.text
    assert view.status_code == 403, view.text
    fake_adapter.list_files.assert_awaited_once()  # the viewer never reached the adapter


# ── Defensive error handling: adapter failure -> clean 502, never 500 ───────


@pytest.mark.asyncio
async def test_adapter_exception_returns_502_not_500(admin_client, fake_adapter):
    fake_adapter.send_gcode.side_effect = ConnectionError("machine unreachable")
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    assert r.status_code == 502, r.text
    assert "machine unreachable" in r.json()["detail"]


@pytest.mark.asyncio
async def test_adapter_rejects_home_returns_502(admin_client, fake_adapter):
    fake_adapter.home_axes.return_value = {"ok": False, "response": "limit switch fault"}
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={})
    assert r.status_code == 502, r.text
    assert "limit switch fault" in r.json()["detail"]


@pytest.mark.asyncio
async def test_estop_adapter_exception_returns_502_not_500(admin_client, fake_adapter):
    fake_adapter.emergency_stop.side_effect = RuntimeError("serial port closed")
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 502, r.text
    assert "serial port closed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_device_returns_404(admin_client, fake_adapter):
    r = await admin_client.post("/api/devices/does-not-exist/cnc/estop")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_axes_returns_400(admin_client, fake_adapter):
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={"axes": ["Q"]})
    assert r.status_code == 400
    fake_adapter.home_axes.assert_not_awaited()


# ── E-stop bypasses rate limiting ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_estop_never_rate_limited(admin_client, fake_adapter):
    """E-stop carries no @rate_limit decorator. Prove it by turning the shared
    slowapi limiter BACK ON (conftest disables it globally for the whole
    suite) and firing more calls than any of this app's existing per-route
    limits (10/minute on login) would tolerate — none should come back 429."""
    if hasattr(app.state, "limiter") and app.state.limiter is not None:
        app.state.limiter.enabled = True
    try:
        statuses = []
        for _ in range(20):
            r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")
            statuses.append(r.status_code)
        assert all(s == 200 for s in statuses), statuses
        assert 429 not in statuses
        assert fake_adapter.emergency_stop.await_count == 20
    finally:
        if hasattr(app.state, "limiter") and app.state.limiter is not None:
            app.state.limiter.enabled = False


# ── Audit logging ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_motion_routes_are_audit_logged(admin_client, fake_adapter):
    await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode", json={"code": "G0 X10"})
    await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/home", json={})
    await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")

    events = (await admin_client.get("/api/admin/audit")).json()
    actions = {e["action"] for e in events}
    assert "cnc_send_gcode" in actions
    assert "cnc_home_axes" in actions
    assert "cnc_emergency_stop" in actions
    assert all(e.get("resource") != f"device:{CNC_DEVICE_ID}" or e["username"] == "admin"
               for e in events if e["action"].startswith("cnc_"))


@pytest.mark.asyncio
async def test_failed_estop_is_still_audit_logged(admin_client, fake_adapter):
    """Safety-critical: even a failed E-stop attempt must leave an audit trail."""
    fake_adapter.emergency_stop.side_effect = RuntimeError("serial port closed")
    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 502

    events = (await admin_client.get("/api/admin/audit", params={"action": "cnc_emergency_stop"})).json()
    assert any(e["resource"] == f"device:{CNC_DEVICE_ID}" for e in events)


# ── FluidNC: real dispatch (not fake_adapter), real HTTP mocked at httpx level ──
# FluidNC previously wasn't in _get_cnc_client's dispatch table at all — any
# device configured with protocol=fluidnc (a real, live protocol; fleet.py
# dispatches FluidNCClient for it elsewhere, and it's explicitly documented as
# covering "CNC routers and lasers") 400'd on every /cnc/* route including
# estop. These exercise the real FluidNCClient class end-to-end (mocking only
# the outbound httpx calls, not the whole adapter), to prove the fix isn't
# just "the enum case exists" but that the adapter genuinely implements the
# CNCAdapter contract cnc_routes.py calls into.

FLUIDNC_DEVICE_ID = "fluidnc-laser-1"


def _fluidnc_config() -> FarmConfig:
    return FarmConfig(
        printers=[
            PrinterConfig(
                id=FLUIDNC_DEVICE_ID,
                name="Test FluidNC Laser",
                base_url="http://localhost:8090",
                machine_type=MachineType.LASER,
                protocol=Protocol.FLUIDNC,
                enabled=True,
            )
        ]
    )


@pytest.fixture
def fluidnc_config(monkeypatch):
    monkeypatch.setattr(cnc_routes, "get_config", _fluidnc_config)


@pytest.mark.asyncio
async def test_fluidnc_estop_no_longer_400s(admin_client, fluidnc_config, monkeypatch):
    """The original bug: protocol=fluidnc had no case in _get_cnc_client, so
    every /cnc/* call — including estop — hit the `else: raise
    HTTPException(400, ...)` branch regardless of machine state."""
    orig_post = httpx.AsyncClient.post

    async def _ok_post(self, url, **kwargs):
        # admin_client is ALSO an httpx.AsyncClient (ASGITransport-backed) —
        # patching AsyncClient.post globally intercepts its own outer request
        # too. Only fake the FluidNC device's own outbound call; pass every
        # other call (including the test client's request into the app)
        # through to the real implementation.
        if "localhost:8090" not in str(url):
            return await orig_post(self, url, **kwargs)
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))
    monkeypatch.setattr("httpx.AsyncClient.post", _ok_post)

    r = await admin_client.post(f"/api/devices/{FLUIDNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "state": "error"}


@pytest.mark.asyncio
async def test_fluidnc_estop_sends_grbl_realtime_soft_reset(admin_client, fluidnc_config, monkeypatch):
    """FluidNC speaks the same G-code/realtime-byte language as GRBL over its
    HTTP /api/command endpoint — emergency_stop must send the identical
    soft-reset byte (0x18 / Ctrl-X) GRBLClient sends for the same purpose."""
    orig_post = httpx.AsyncClient.post
    sent = {}

    async def _capture_post(self, url, **kwargs):
        if "localhost:8090" not in str(url):
            return await orig_post(self, url, **kwargs)
        sent["url"] = str(url)
        sent["json"] = kwargs.get("json")
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))
    monkeypatch.setattr("httpx.AsyncClient.post", _capture_post)

    r = await admin_client.post(f"/api/devices/{FLUIDNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    assert sent["url"].endswith("/api/command")
    assert sent["json"] == {"gcode": "\x18"}


@pytest.mark.asyncio
async def test_fluidnc_estop_adapter_failure_returns_502(admin_client, fluidnc_config, monkeypatch):
    orig_post = httpx.AsyncClient.post

    async def _boom_post(self, url, **kwargs):
        if "localhost:8090" not in str(url):
            return await orig_post(self, url, **kwargs)
        raise ConnectionError("device unreachable")
    monkeypatch.setattr("httpx.AsyncClient.post", _boom_post)

    r = await admin_client.post(f"/api/devices/{FLUIDNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 502, r.text


# ── Feed-rate unverified-protocol liability gate ────────────────────────────
# FOUND BY REVIEW: the old hard-400 denylist (_FEED_RATE_UNVERIFIED_PROTOCOLS)
# had zero test coverage. It's since been replaced by require_alpha_ack (see
# test_cnc_alpha_ack.py for the full gate suite) — these two tests keep the
# feed-rate-specific regression: unacked alpha protocols 403, acked ones 200.

_UNVERIFIED_FEED_RATE_PROTOCOLS = [Protocol.FANUC, Protocol.FADAL, Protocol.HAAS, Protocol.MACH4]


def _feed_rate_config(protocol: Protocol) -> FarmConfig:
    return FarmConfig(
        printers=[
            PrinterConfig(
                id=CNC_DEVICE_ID,
                name="Test Mill",
                base_url="http://localhost:8080",
                machine_type=MachineType.CNC_MILL,
                protocol=protocol,
                enabled=True,
            )
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", _UNVERIFIED_FEED_RATE_PROTOCOLS)
async def test_feed_rate_rejected_for_unverified_protocols(admin_client, monkeypatch, protocol):
    """Without an alpha-ack, feed-rate 403s — replaces the old hard 400."""
    monkeypatch.setattr(cnc_routes, "get_config", lambda: _feed_rate_config(protocol))
    monkeypatch.setattr(deps, "get_config", lambda: _feed_rate_config(protocol))
    r = await admin_client.put(f"/api/devices/{CNC_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "alpha_ack_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", _UNVERIFIED_FEED_RATE_PROTOCOLS)
async def test_feed_rate_accepted_after_alpha_ack(admin_client, monkeypatch, protocol):
    """With the ack granted, feed-rate proceeds to the adapter as normal."""
    monkeypatch.setattr(cnc_routes, "get_config", lambda: _feed_rate_config(protocol))
    monkeypatch.setattr(deps, "get_config", lambda: _feed_rate_config(protocol))
    mock = AsyncMock()
    mock.set_feed_rate.return_value = {"ok": True}
    monkeypatch.setattr(cnc_routes, "_get_cnc_client", lambda printer: mock)

    ack = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/alpha-ack")
    assert ack.status_code == 200, ack.text

    r = await admin_client.put(f"/api/devices/{CNC_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 200, r.text
    mock.set_feed_rate.assert_awaited_once_with(100.0)


@pytest.mark.asyncio
async def test_feed_rate_accepted_for_verified_protocol(admin_client, fake_adapter):
    """Positive control: the denylist doesn't block every protocol — GRBL
    (via _cnc_config's LINUXCNC-equivalent verified set) still succeeds."""
    fake_adapter.set_feed_rate.return_value = {"ok": True}
    r = await admin_client.put(f"/api/devices/{CNC_DEVICE_ID}/feed-rate/100")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "new_feed_rate": 100.0}
    fake_adapter.set_feed_rate.assert_awaited_once_with(100.0)


@pytest.mark.asyncio
async def test_linuxcnc_estop_real_adapter_no_crash(admin_client, monkeypatch):
    """CRIT-CNC-01 regression (E-stop, the safety-critical path).

    The real LinuxCNCClient.emergency_stop() returns an EmergencyStopResponse
    pydantic model. cnc_emergency_stop() calls result.get("ok") on it AFTER the
    try/finally block, so on the UNFIXED code that .get() raises an uncaught
    AttributeError -> the request fails (HTTP 500 / propagated error), making a
    physically-successful E-stop look like a server failure. After the fix the
    route model_dump()s the result first and returns 200.

    Only cnc_routes.get_config is monkeypatched (LINUXCNC device); _get_cnc_client
    is NOT patched, so the genuine adapter is exercised. Only the adapter's own
    outbound httpx POST is faked.
    """
    monkeypatch.setattr(cnc_routes, "get_config", _cnc_config)

    orig_post = httpx.AsyncClient.post

    async def _ok_post(self, url, **kwargs):
        # admin_client is itself an httpx.AsyncClient (ASGITransport). Let its own
        # request into the app pass through; only fake the LinuxCNC device call.
        if "localhost:8080" not in str(url):
            return await orig_post(self, url, **kwargs)
        return httpx.Response(200, json={"state": "estop"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr("httpx.AsyncClient.post", _ok_post)

    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/estop")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "state": "estop"}


@pytest.mark.asyncio
async def test_linuxcnc_gcode_real_adapter_no_crash(admin_client, monkeypatch):
    """CRIT-CNC-01 regression (MDI G-code path).

    Real LinuxCNCClient.send_gcode() returns a GCodeResponse pydantic model;
    send_cnc_gcode() calls result.get("ok") on it outside the try block. Unfixed
    -> uncaught AttributeError; fixed -> 200 with the MDI result echoed back.
    """
    monkeypatch.setattr(cnc_routes, "get_config", _cnc_config)

    orig_post = httpx.AsyncClient.post

    async def _ok_post(self, url, **kwargs):
        if "localhost:8080" not in str(url):
            return await orig_post(self, url, **kwargs)
        return httpx.Response(200, json={"result": "G0 X10 executed"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr("httpx.AsyncClient.post", _ok_post)

    r = await admin_client.post(f"/api/devices/{CNC_DEVICE_ID}/cnc/gcode",
                                json={"code": "G0 X10"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "response": "G0 X10 executed"}
