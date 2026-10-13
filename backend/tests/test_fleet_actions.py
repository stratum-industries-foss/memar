"""HTTP-level tests for the FDM printer machine-control routes in main.py:

    POST /api/printers/actions/{action}             (batch_action)
    POST /api/printers/{printer_id}/actions/{action} (single_printer_action)
    POST /api/printers/{printer_id}/jog
    POST /api/printers/{printer_id}/temperature
    POST /api/printers/{printer_id}/gcode

Mirrors tests/test_cnc_control.py's coverage of the parallel CNC control
surface: RBAC (viewer 403, operator/admin 200), adapter-failure handling,
offline-device handling, and emergency_stop treated with the same care CNC
gives its e-stop.

Isolation: monkeypatch app.main.get_config to a fixed one-device fleet,
app.fleet.fetch_printer_status to a controlled FleetPrinterStatus (online or
offline), and app.fleet._get_client to return a MagicMock(spec=MoonrakerClient)
— the spec is required because run_batch_action explicitly does
`isinstance(client, MoonrakerClient)` before dispatching (fleet.py:745), and
mock.mock's automatic async-method detection under spec= gives us AsyncMock
methods for run_gcode/emergency_stop/pause/resume/cancel/firmware_restart
for free. No real hardware/network touched.
"""
from unittest.mock import MagicMock

import pytest

import app.fleet as fleet
import app.license as licmod
import app.main as main_module
from app.license import LicenseState, _tier_to_features
from app.models import FarmConfig, FleetPrinterStatus, HeaterStatus, JobStatus, MachineType, PrinterConfig, Protocol
from app.moonraker import MoonrakerClient

FDM_ID = "fdm-1"


def _fdm_config() -> FarmConfig:
    return FarmConfig(
        printers=[
            PrinterConfig(
                id=FDM_ID,
                name="Test FDM",
                base_url="http://localhost:7125",
                machine_type=MachineType.FDM,
                protocol=Protocol.MOONRAKER,
                enabled=True,
            )
        ]
    )


def _online_status(printer_id: str = FDM_ID, *, job_state: str = "standby", available_actions=None) -> FleetPrinterStatus:
    return FleetPrinterStatus(
        id=printer_id, name="Test FDM", base_url="http://localhost:7125",
        enabled=True, online=True, state="ready",
        nozzle=HeaterStatus(temperature=25.0, target=0.0),
        bed=HeaterStatus(temperature=25.0, target=0.0),
        job=JobStatus(state=job_state),
        available_actions=available_actions if available_actions is not None else
            ["home", "motors_off", "cooldown", "firmware_restart", "start_print"],
    )


def _offline_status(printer_id: str = FDM_ID) -> FleetPrinterStatus:
    return FleetPrinterStatus(
        id=printer_id, name="Test FDM", base_url="http://localhost:7125",
        enabled=True, online=False, state="offline",
        state_message="Connection refused", available_actions=[],
    )


@pytest.fixture(autouse=True)
def _active_license():
    """user creation (operator/viewer fixtures in conftest.py) needs the
    multi_user feature, which requires an active license — mirrors
    test_cnc_control.py's _active_license()."""
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
def fake_client(monkeypatch):
    """Swap in a mock Moonraker adapter and point main.get_config at a fixed
    one-device fleet. spec=MoonrakerClient satisfies run_batch_action's
    isinstance() gate (fleet.py:745) and automatically makes the async
    methods AsyncMock. Returned so individual tests can set return_value /
    side_effect."""
    mock = MagicMock(spec=MoonrakerClient)
    mock.run_gcode.return_value = "ok"
    mock.emergency_stop.return_value = "ok"
    mock.pause.return_value = "ok"
    mock.resume.return_value = "ok"
    mock.cancel.return_value = "ok"
    mock.firmware_restart.return_value = "ok"

    async def _get_client(printer):
        return mock

    monkeypatch.setattr(fleet, "_get_client", _get_client)
    monkeypatch.setattr(main_module, "get_config", _fdm_config)
    return mock


@pytest.fixture
def online_printer(monkeypatch, fake_client):
    """fake_client + fleet.fetch_printer_status reporting the device online
    and eligible for home/motors_off/cooldown/firmware_restart/emergency_stop."""
    async def _fetch(printer):
        return _online_status(printer.id)
    monkeypatch.setattr(fleet, "fetch_printer_status", _fetch)
    return fake_client


@pytest.fixture
def offline_printer(monkeypatch, fake_client):
    """fake_client + fleet.fetch_printer_status reporting the device offline —
    exercises _evaluate_action_plan's `if not status.online: blocking.append(...)`
    gate, which blocks every action EXCEPT emergency_stop (e-stop is exempt and
    always attempted — see test_emergency_stop_attempted_when_offline)."""
    async def _fetch(printer):
        return _offline_status(printer.id)
    monkeypatch.setattr(fleet, "fetch_printer_status", _fetch)
    return fake_client


# ── RBAC: viewer blocked, operator + admin succeed ───────────────────────────


@pytest.mark.asyncio
async def test_viewer_forbidden_batch_action(viewer_client, online_printer):
    r = await viewer_client.post("/api/printers/actions/home", json={"printer_ids": [FDM_ID]})
    assert r.status_code == 403, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_forbidden_single_action(viewer_client, online_printer):
    r = await viewer_client.post(f"/api/printers/{FDM_ID}/actions/home")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_operator_can_batch_action(operator_client, online_printer):
    r = await operator_client.post("/api/printers/actions/home", json={"printer_ids": [FDM_ID]})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok", result
    online_printer.run_gcode.assert_awaited_once_with("G28")


@pytest.mark.asyncio
async def test_admin_can_single_action(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/home")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok", result
    online_printer.run_gcode.assert_awaited_once_with("G28")


@pytest.mark.asyncio
async def test_unknown_action_returns_404(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/reboot_to_bios")
    assert r.status_code == 404, r.text


# ── Offline printer: blocked, not faked as success ───────────────────────────


@pytest.mark.asyncio
async def test_batch_action_blocks_offline_printer(admin_client, offline_printer):
    r = await admin_client.post("/api/printers/actions/home", json={"printer_ids": [FDM_ID]})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["allowed"] is False
    assert result["status"] == "blocked"
    assert "offline" in result["message"].lower()
    offline_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_action_blocks_offline_printer(admin_client, offline_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/cooldown")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["allowed"] is False
    assert result["status"] == "blocked"
    offline_printer.run_gcode.assert_not_awaited()


# ── Adapter/client failure: error result, not silent 200-ok ──────────────────


@pytest.mark.asyncio
async def test_batch_action_adapter_exception_surfaces_as_error(admin_client, online_printer):
    online_printer.run_gcode.side_effect = ConnectionError("printer unreachable")
    r = await admin_client.post("/api/printers/actions/home", json={"printer_ids": [FDM_ID]})
    assert r.status_code == 200, r.text  # batch endpoint always 200; per-printer status carries the error
    result = r.json()["results"][0]
    assert result["status"] == "error"
    assert "printer unreachable" in result["message"]


# ── emergency_stop: highest-severity action, same care as CNC's e-stop ───────


@pytest.mark.asyncio
async def test_emergency_stop_dispatched_for_admin(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok", result
    online_printer.emergency_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_operator_can_emergency_stop(operator_client, online_printer):
    r = await operator_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok", result
    online_printer.emergency_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_viewer_forbidden_emergency_stop(viewer_client, online_printer):
    r = await viewer_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 403, r.text
    online_printer.emergency_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_emergency_stop_attempted_when_offline(admin_client, offline_printer):
    """Safety-critical (CRIT-FLEET-01): emergency_stop is exempt from the offline
    gate and is ALWAYS attempted, never silently refused. A transient status-probe
    timeout marks a device offline; the e-stop must still reach the adapter. With
    the mock adapter succeeding, the attempt reports 'ok'. The load-bearing
    assertion is that emergency_stop was actually awaited (attempt made)."""
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    offline_printer.emergency_stop.assert_awaited_once()   # <-- the attempt happened
    assert result["status"] == "ok", result


@pytest.mark.asyncio
async def test_emergency_stop_offline_adapter_raises_is_error_not_blocked(admin_client, offline_printer):
    """When offline AND the adapter raises (a genuinely unreachable device), the
    e-stop was still ATTEMPTED — the per-printer result is 'error' (attempt failed),
    never 'blocked' (silently refused without trying). This is the exact distinction
    the CRIT-FLEET-01 fix guarantees."""
    offline_printer.emergency_stop.side_effect = RuntimeError("no route to host")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    offline_printer.emergency_stop.assert_awaited_once()
    assert result["status"] == "error", result
    assert "no route to host" in result["message"]


@pytest.mark.asyncio
async def test_emergency_stop_attempted_under_maintenance_lockout(admin_client, monkeypatch, fake_client):
    """Safety-critical (CRIT-FLEET-01): a printer in maintenance_lockout still gets
    its emergency_stop ATTEMPTED. Lockout gates every OTHER action but is exempt for
    e-stop. Builds a locked online device and confirms the adapter was called."""
    locked_cfg = FarmConfig(printers=[PrinterConfig(
        id=FDM_ID, name="Test FDM", base_url="http://localhost:7125",
        machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER,
        enabled=True, maintenance_lockout=True,
    )])
    monkeypatch.setattr(main_module, "get_config", lambda: locked_cfg)

    async def _fetch(printer):
        return _online_status(printer.id)
    monkeypatch.setattr(fleet, "fetch_printer_status", _fetch)

    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    fake_client.emergency_stop.assert_awaited_once()
    assert result["status"] == "ok", result


@pytest.mark.asyncio
async def test_emergency_stop_adapter_exception_surfaces_as_error(admin_client, online_printer):
    online_printer.emergency_stop.side_effect = RuntimeError("serial port closed")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "error"
    assert "serial port closed" in result["message"]


# ── jog ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_jog(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 10, "relative": True})
    assert r.status_code == 200, r.text
    # T46: mode / move / restore-absolute are three sequenced, individually checked commands.
    sent = [c.args[0] for c in online_printer.run_gcode.await_args_list]
    assert sent == ["G91", "G1 X10.0 F3000.0", "G90"]


@pytest.mark.asyncio
async def test_viewer_forbidden_jog(viewer_client, online_printer):
    r = await viewer_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 10})
    assert r.status_code == 403, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_jog_rejects_out_of_range_distance(admin_client, online_printer):
    """JogRequest.distance is Field(..., gt=-500, lt=500) — a 1000mm jog must
    never reach the adapter."""
    r = await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 1000})
    assert r.status_code == 422, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_jog_rejects_invalid_axis(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "Q", "distance": 10})
    assert r.status_code == 422, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_jog_adapter_exception_returns_502(admin_client, online_printer):
    """jog_printer (main.py:1249) now wraps jog() in the same try/except
    pattern as post_printer_temperature/post_printer_macro/run_gcode_console_route,
    converting an adapter failure into a clean 502 instead of letting the raw
    exception propagate out to a generic, detail-less 500."""
    online_printer.run_gcode.side_effect = ConnectionError("printer unreachable")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 10})
    assert r.status_code == 502, r.text
    assert "ConnectionError" in r.json()["detail"]


# ── temperature ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_set_temperature(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 200, "bed_target": 60})
    assert r.status_code == 200, r.text
    online_printer.run_gcode.assert_awaited_once()
    sent = online_printer.run_gcode.await_args.args[0]
    assert "M104 S200.0" in sent
    assert "M140 S60.0" in sent


@pytest.mark.asyncio
async def test_viewer_forbidden_temperature(viewer_client, online_printer):
    r = await viewer_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 200})
    assert r.status_code == 403, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_rejects_unsafe_nozzle_target(admin_client, online_printer):
    """350C is within JogRequest's Pydantic bound (le=400) but outside
    SettingsValidator.SAFE_RANGES['nozzle_temp'] (150-300) — must 400 before
    ever reaching the adapter."""
    r = await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 350})
    assert r.status_code == 400, r.text
    assert "outside safe range" in r.json()["detail"]
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_rejects_pydantic_out_of_range(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 500})
    assert r.status_code == 422, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_adapter_exception_returns_502(admin_client, online_printer):
    online_printer.run_gcode.side_effect = ConnectionError("printer unreachable")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 200})
    assert r.status_code == 502, r.text
    assert "printer unreachable" in r.json()["detail"] or "ConnectionError" in r.json()["detail"]


# ── gcode (raw MDI console) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gcode_empty_command_rejected(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": ""})
    assert r.status_code == 400, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_gcode_missing_script_rejected(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={})
    assert r.status_code == 400, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_gcode_valid_command_dispatched(admin_client, online_printer):
    r = await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": "G28"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    online_printer.run_gcode.assert_awaited_once_with("G28")


@pytest.mark.asyncio
async def test_viewer_forbidden_gcode(viewer_client, online_printer):
    r = await viewer_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": "G28"})
    assert r.status_code == 403, r.text
    online_printer.run_gcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_gcode_adapter_exception_reported_not_faked_success(admin_client, online_printer):
    """FINDING: fleet.run_gcode_console (fleet.py:1877) catches adapter
    exceptions internally and returns {"ok": False, "error": ...} with HTTP 200
    — unlike jog/temperature/macro, which raise HTTPException(502). The failure
    is correctly reported (ok is explicitly False, never faked as success), but
    the HTTP-status convention is inconsistent with the rest of the write path.
    Documents ACTUAL behavior — see session report."""
    online_printer.run_gcode.side_effect = ConnectionError("printer unreachable")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": "G28"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "printer unreachable" in body["error"]


# ── Audit logging ─────────────────────────────────────────────────────────
# Mirrors test_cnc_control.py's "Audit logging" section for the CNC surface.
# Prior to this, none of these five routes wrote to AuditLog at all.


@pytest.mark.asyncio
async def test_fdm_control_actions_are_audit_logged(admin_client, online_printer):
    """Every FDM control endpoint gets a per-printer audit row. batch_action
    logs once per printer in result.results (so a multi-device batch gets one
    row per device, not one row for the whole call); jog/temperature/gcode
    log their own single-printer row via try/finally."""
    await admin_client.post("/api/printers/actions/home", json={"printer_ids": [FDM_ID]})
    await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 10})
    await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 200})
    await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": "G28"})

    events = (await admin_client.get("/api/admin/audit")).json()
    actions = {e["action"] for e in events}
    assert "fdm_home" in actions
    assert "fdm_emergency_stop" in actions
    assert "fdm_jog" in actions
    assert "fdm_set_temperature" in actions
    assert "fdm_gcode" in actions
    assert all(
        e["resource"] == f"printer:{FDM_ID}"
        for e in events if e["action"].startswith("fdm_")
    )


@pytest.mark.asyncio
async def test_fdm_failed_emergency_stop_is_still_audit_logged(admin_client, online_printer):
    """Safety-critical: a failed emergency_stop must still leave an audit
    trail — same guarantee as test_cnc_control.py's
    test_failed_estop_is_still_audit_logged. This holds for the batch path
    only because run_batch_action catches the adapter exception internally
    and reports status="error" rather than raising (confirmed by
    test_emergency_stop_adapter_exception_surfaces_as_error above); batch_action
    has no finally, so a total run_batch_action failure (not per-printer, e.g.
    a config error) before any results exist would log nothing — accepted,
    since run_batch_action is built not to throw that way."""
    online_printer.emergency_stop.side_effect = RuntimeError("serial port closed")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/actions/emergency_stop")
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "error"

    events = (await admin_client.get("/api/admin/audit", params={"action": "fdm_emergency_stop"})).json()
    assert any(
        e["resource"] == f"printer:{FDM_ID}" and "serial port closed" in (e.get("detail") or "")
        for e in events
    )


@pytest.mark.asyncio
async def test_fdm_failed_jog_is_still_audit_logged(admin_client, online_printer):
    """jog/temperature/gcode use their own try/finally directly (not the
    batch per-printer loop), mirroring cnc_routes' single-device
    audit-even-on-failure pattern."""
    online_printer.run_gcode.side_effect = ConnectionError("printer unreachable")
    r = await admin_client.post(f"/api/printers/{FDM_ID}/jog", json={"axis": "X", "distance": 10})
    assert r.status_code == 502, r.text

    events = (await admin_client.get("/api/admin/audit", params={"action": "fdm_jog"})).json()
    assert any(e["resource"] == f"printer:{FDM_ID}" for e in events)


@pytest.mark.asyncio
async def test_fdm_rejected_unsafe_temperature_is_still_audit_logged(admin_client, online_printer):
    """FOUND BY REVIEW: SettingsValidator's safety-range check originally ran
    before the try/finally, so a rejected unsafe-temperature request left no
    audit trail — the one place this route's own validation, not the
    adapter, produces the failure. Now inside the try, so it's covered too."""
    r = await admin_client.post(f"/api/printers/{FDM_ID}/temperature", json={"nozzle_target": 350})
    assert r.status_code == 400, r.text

    events = (await admin_client.get("/api/admin/audit", params={"action": "fdm_set_temperature"})).json()
    assert any(e["resource"] == f"printer:{FDM_ID}" for e in events)


@pytest.mark.asyncio
async def test_fdm_rejected_empty_gcode_is_still_audit_logged(admin_client, online_printer):
    """FOUND BY REVIEW: the empty-script 400 originally raised before the
    try/finally, so a rejected empty-gcode attempt left no audit trail. Now
    inside the try, so it's covered too."""
    r = await admin_client.post(f"/api/printers/{FDM_ID}/gcode", json={"script": ""})
    assert r.status_code == 400, r.text

    events = (await admin_client.get("/api/admin/audit", params={"action": "fdm_gcode"})).json()
    assert any(e["resource"] == f"printer:{FDM_ID}" for e in events)
