"""Unit tests for fleet._available_actions — the machine-type-aware
suppression added after the review found CNC/laser/plasma cards rendering
generic quick-action buttons (home/pause/resume/cancel/cooldown/motors_off/
firmware_restart) that always silently no-op, since run_batch_action only
ever dispatches to MoonrakerClient. Pure function, no HTTP/DB needed.
"""
from app.fleet import _available_actions


def test_fdm_online_idle_gets_generic_actions():
    actions = _available_actions(state="ready", online=True, job_state="standby", machine_type="fdm")
    assert "home" in actions
    assert "start_print" in actions


def test_fdm_printing_gets_pause_cancel():
    actions = _available_actions(state="printing", online=True, job_state="printing", machine_type="fdm")
    assert set(actions) == {"home", "motors_off", "cooldown", "firmware_restart", "pause", "cancel"}


def test_offline_gets_nothing_regardless_of_machine_type():
    assert _available_actions(state="offline", online=False, job_state=None, machine_type="fdm") == []
    assert _available_actions(state="offline", online=False, job_state=None, machine_type="cnc_mill") == []


def test_cnc_machine_types_get_no_generic_actions():
    """The actual bug fix: none of these types get home/pause/cancel/etc.
    from the generic path — real control is the dedicated /cnc/* routes."""
    for mt in ("cnc_mill", "cnc_lathe", "cnc_router", "wire_edm", "plasma", "waterjet", "laser"):
        assert _available_actions(state="printing", online=True, job_state="printing", machine_type=mt) == []
        assert _available_actions(state="ready", online=True, job_state="standby", machine_type=mt) == []


def test_unknown_machine_type_falls_back_to_generic_actions():
    """None / an unrecognized value (e.g. a future machine type not yet in
    the CNC set) doesn't accidentally get treated as CNC-suppressed."""
    actions = _available_actions(state="ready", online=True, job_state="standby", machine_type=None)
    assert "home" in actions
    actions = _available_actions(state="ready", online=True, job_state="standby", machine_type="pick_and_place")
    assert "home" in actions
