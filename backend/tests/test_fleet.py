"""Tests for core fleet/printer API endpoints."""

import pytest

import app.license as licmod
from app.license import LicenseState, _tier_to_features


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_version(client):
    resp = await client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data


@pytest.mark.asyncio
async def test_printers_list_empty(auth_client):
    """Fresh DB has no printers."""
    resp = await auth_client.get("/api/printers")
    assert resp.status_code == 200
    data = resp.json()
    assert "printers" in data
    assert isinstance(data["printers"], list)


@pytest.mark.asyncio
async def test_printer_not_found(auth_client):
    resp = await auth_client.get("/api/printers/nonexistent-id/diagnostics")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_demo_endpoint_removed(client):
    """/api/auth/demo is gone for good — 404 regardless of MEMAR_DEMO_MODE.

    It used to mint a token for user_id=999, a user that never exists, so the
    token was unusable on any authenticated route.
    """
    import os
    os.environ["MEMAR_DEMO_MODE"] = "1"
    try:
        resp = await client.get("/api/auth/demo")
        assert resp.status_code == 404
    finally:
        del os.environ["MEMAR_DEMO_MODE"]


@pytest.mark.asyncio
async def test_fleet_oee(auth_client):
    resp = await auth_client.get("/api/oee")
    # 402 = license gate (webhooks/oee feature requires paid tier)
    assert resp.status_code in (200, 404, 402)


@pytest.mark.asyncio
async def test_webhooks_list(auth_client):
    resp = await auth_client.get("/api/alerts/webhooks/")
    # 402 = license gate (webhooks feature requires paid tier)
    assert resp.status_code in (200, 402)


@pytest.mark.asyncio
async def test_webhook_create(auth_client):
    resp = await auth_client.post("/api/alerts/webhooks/", json={
        "url": "https://example.com/hook",
        "events": ["printer.error", "printer.complete"],
    })
    assert resp.status_code in (200, 201, 402)


@pytest.mark.asyncio
async def test_webhook_create_invalid_url(auth_client):
    resp = await auth_client.post("/api/alerts/webhooks/", json={
        "url": "not-a-url",
        "events": ["printer.error"],
    })
    # 422 = validation error (bad URL), 402 = license gate hits before validation
    assert resp.status_code in (422, 402)


@pytest.mark.asyncio
async def test_floorplan_layout_get(auth_client):
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                  features=_tier_to_features("pro"), customer_id="c", active=True)
    try:
        resp = await auth_client.get("/api/floorplan/layout")
        assert resp.status_code == 200
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_floorplan_layout_reports_higgsfield_availability(auth_client, monkeypatch):
    """The AI 3D render is optional (needs the Higgsfield CLI configured
    server-side) — the frontend hides its Generate button entirely rather
    than showing one guaranteed to fail, driven by this flag."""
    import app.floorplan as floorplan_module

    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                  features=_tier_to_features("pro"), customer_id="c", active=True)
    try:
        monkeypatch.setattr(floorplan_module, "HIGGSFIELD_CLI", "")
        resp = await auth_client.get("/api/floorplan/layout")
        assert resp.status_code == 200
        assert resp.json()["higgsfield_available"] is False

        monkeypatch.setattr(floorplan_module, "HIGGSFIELD_CLI", "/usr/bin/higgsfield")
        resp2 = await auth_client.get("/api/floorplan/layout")
        assert resp2.json()["higgsfield_available"] is True
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_license_status(auth_client):
    resp = await auth_client.get("/api/license/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_settings_fleet_get(auth_client):
    resp = await auth_client.get("/api/settings/fleet")
    assert resp.status_code == 200


# --- Macro parameters: inference, metadata, execution -----------------------
#
# Klipper declares nothing about macro parameters — they exist only as Jinja
# expressions inside the macro body — so the typed-input feature rests entirely
# on inferring them from configfile.settings. These cover the inference itself,
# the (case-sensitive) join back to the object list, and the injection gate on
# the execution path.

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from app.macro_params import infer_macro_params, macro_metadata  # noqa: E402
from app.moonraker import MoonrakerClient  # noqa: E402


def test_infer_params_typed_filters():
    """The common shape: |default(x) then a cast filter."""
    params = infer_macro_params("M104 S{params.TEMP|default(200)|int}")
    assert params == {"TEMP": {"type": "int", "default": 200}}


def test_infer_params_all_reference_forms():
    """Attribute, dict-index and .get() forms all name a parameter."""
    body = (
        "{% set bed = params.BED|default(60)|int %}\n"
        "{params['SPEED']|float}\n"
        "M140 S{params.get('CHAMBER', 40)|int}\n"
    )
    params = infer_macro_params(body)
    assert params["BED"] == {"type": "int", "default": 60}
    assert params["SPEED"] == {"type": "float", "default": None}
    assert params["CHAMBER"] == {"type": "int", "default": 40}


def test_infer_params_untyped_falls_back_to_string():
    """No cast filter and no literal default -> free-text, never an error."""
    assert infer_macro_params("{params.LABEL}") == {
        "LABEL": {"type": "string", "default": None}
    }
    # A string default stays a string rather than being coerced to a number.
    assert infer_macro_params("{params.NAME|default('abc')}") == {
        "NAME": {"type": "string", "default": "abc"}
    }


def test_infer_params_non_literal_default_yields_no_default():
    """`|default(printer.extruder.target)` is valid but has no static value.

    The parameter must still be reported (so the UI offers the input); only the
    default is unknown.
    """
    params = infer_macro_params("{params.TEMP|default(printer.extruder.target)|int}")
    assert params == {"TEMP": {"type": "int", "default": None}}


def test_infer_params_macro_without_params_is_empty():
    assert infer_macro_params("G28\nG1 Z10 F600") == {}
    assert infer_macro_params("") == {}
    assert infer_macro_params(None) == {}


def test_infer_params_does_not_invent_params_from_method_calls():
    """`params.get(...)`/`params.items()` must not become parameters.

    Regression guard for the regex backtracking trap: a naive negative lookahead
    lets the engine shorten `get` to `ge` so the lookahead passes, inventing a
    parameter named "ge".
    """
    params = infer_macro_params("{params.get('X', 1)|int}{% for k in params.items() %}{% endfor %}")
    assert set(params) == {"X"}


def test_infer_params_multiple_in_one_expression_do_not_cross_contaminate():
    """A filter must bind to its own parameter, not the one before it."""
    params = infer_macro_params("{params.A|int + params.B|default(2)|float}")
    assert params["A"] == {"type": "int", "default": None}
    assert params["B"] == {"type": "float", "default": 2}


def test_infer_params_repeated_reference_merges():
    """Same param referenced twice with different filters must not raise."""
    params = infer_macro_params("{params.T|int}\nM104 S{params.T|default(5)}")
    assert params == {"T": {"type": "int", "default": 5}}


def test_macro_metadata_reads_category_and_color():
    """Klipper reports variable_* as RAW config text — quotes included."""
    params, category, color = macro_metadata(
        {
            "gcode": "M104 S{params.TEMP|default(200)|int}",
            "variable_category": "'Heating'",
            "variable_color": "'#ff8800'",
        }
    )
    assert params == {"TEMP": {"type": "int", "default": 200}}
    assert category == "Heating"
    assert color == "#ff8800"


def test_macro_metadata_rejects_hostile_color():
    """`color` lands in an inline style attribute, so it is allowlisted."""
    _, _, color = macro_metadata(
        {"gcode": "", "variable_color": "'red; background:url(//evil)'"}
    )
    assert color is None


def test_macro_metadata_tolerates_missing_or_malformed_section():
    assert macro_metadata(None) == ({}, None, None)
    assert macro_metadata("not-a-dict") == ({}, None, None)
    assert macro_metadata({}) == ({}, None, None)


def _macro_client(objects, settings):
    """MoonrakerClient stand-in for fetch_macros. spec= keeps isinstance working."""
    client = MagicMock(spec=MoonrakerClient)
    client.list_objects = AsyncMock(return_value=objects)
    client.query_objects = AsyncMock(return_value={"configfile": {"settings": settings}})
    return client


@pytest.mark.asyncio
async def test_fetch_macros_joins_settings_case_insensitively(monkeypatch):
    """objects/list reports original casing; configfile.settings is lower-cased.

    A literal lookup misses on essentially every real macro and silently returns
    no params, so the fixture deliberately mismatches the two casings.
    """
    import app.fleet as fleet_module
    from app.models import PrinterConfig

    client = _macro_client(
        ["gcode_macro PRINT_START", "gcode_macro Load_Filament", "toolhead"],
        {
            "gcode_macro print_start": {
                "gcode": "M104 S{params.TEMP|default(200)|int}\nM140 S{params.BED|default(60)|float}",
                "variable_category": "'Printing'",
                "variable_color": "'#00aaff'",
            },
            "gcode_macro load_filament": {"gcode": "G1 E50 F300"},
        },
    )
    monkeypatch.setattr(fleet_module, "_get_client", AsyncMock(return_value=client))

    macros = await fleet_module.fetch_macros(PrinterConfig(id="p", name="P", base_url="http://x"))

    assert [m.name for m in macros] == ["Load_Filament", "PRINT_START"]
    start = next(m for m in macros if m.name == "PRINT_START")
    assert start.params["TEMP"].type == "int"
    assert start.params["TEMP"].default == 200
    assert start.params["BED"].type == "float"
    assert start.category == "Printing"
    assert start.color == "#00aaff"
    # A macro that takes no parameters gets an empty dict, not None.
    assert next(m for m in macros if m.name == "Load_Filament").params == {}
    # Only one configfile query for the whole macro list.
    assert client.query_objects.await_count == 1


@pytest.mark.asyncio
async def test_fetch_macros_survives_configfile_failure(monkeypatch):
    """Metadata is optional — a configfile error must not lose the macro list."""
    import app.fleet as fleet_module
    from app.models import PrinterConfig

    client = MagicMock(spec=MoonrakerClient)
    client.list_objects = AsyncMock(return_value=["gcode_macro PRINT_START"])
    client.query_objects = AsyncMock(side_effect=RuntimeError("klipper restarting"))
    monkeypatch.setattr(fleet_module, "_get_client", AsyncMock(return_value=client))

    macros = await fleet_module.fetch_macros(PrinterConfig(id="p", name="P", base_url="http://x"))
    assert [m.name for m in macros] == ["PRINT_START"]
    assert macros[0].params == {}


# --- Macro execution --------------------------------------------------------
#
# Params travel in the request body as a KEY=VALUE map, never appended to the
# macro name in the URL — run_macro's name regex has no space, so the old
# "PRINT_START TEMP=230" path segment was rejected with a 400 and the feature
# never worked once.


def test_build_macro_command_shapes():
    from app.fleet import build_macro_command

    assert build_macro_command("HOME") == "HOME"
    assert build_macro_command("HOME", {}) == "HOME"          # no trailing space
    assert build_macro_command("PRINT_START", {"TEMP": "230"}) == "PRINT_START TEMP=230"
    assert build_macro_command("PRINT_START", {"TEMP": "230", "Z": "-0.2"}) == (
        "PRINT_START TEMP=230 Z=-0.2"
    )


def test_build_macro_command_rejects_injection():
    """Params must not terminate the command or start a new one.

    M112 is an emergency stop — the concrete harm if a newline or ';' slipped
    through into the single-line g-code string.
    """
    from fastapi import HTTPException
    from app.fleet import build_macro_command

    for bad_name in ("PRINT_START TEMP=230", "HOME;M112", "HOME\nM112", "HOME-2", ""):
        with pytest.raises(HTTPException) as exc:
            build_macro_command(bad_name)
        assert exc.value.status_code == 400, f"name {bad_name!r} was not rejected"

    bad_values = [
        "230\nM112",    # newline -> a second g-code command
        "230\r\nM112",  # CRLF
        "230;M112",     # ';' truncates the rest of the line
        "230 M112",     # space -> fabricates an extra token
        "$(id)", "`id`", "230|M112", "230&&M112", "230>out", "230<in",
        '"230"',        # quoted strings unsupported
        "",             # empty -> malformed "TEMP="
    ]
    for bad in bad_values:
        with pytest.raises(HTTPException) as exc:
            build_macro_command("PRINT_START", {"TEMP": bad})
        assert exc.value.status_code == 400, f"value {bad!r} was not rejected"

    for bad_key in ("TEMP=1", "TEMP M112", "TEMP\nM112", "TEMP;", "", "TE-MP", "1TEMP"):
        with pytest.raises(HTTPException) as exc:
            build_macro_command("PRINT_START", {bad_key: "230"})
        assert exc.value.status_code == 400, f"key {bad_key!r} was not rejected"


def test_build_macro_command_rejects_oversized_input():
    from fastapi import HTTPException
    from app.fleet import build_macro_command

    with pytest.raises(HTTPException):
        build_macro_command("HOME", {f"P{i}": "1" for i in range(33)})
    with pytest.raises(HTTPException):
        build_macro_command("HOME", {"TEMP": "9" * 129})


@pytest.mark.asyncio
async def test_macro_endpoint_body_is_optional(auth_client):
    """Both call shapes must reach the handler.

    Asserted against an unknown printer id, so 404 (raised by
    _get_printer_or_404, which runs before run_macro) is the success signal: the
    body validated and the route ran. A 422 here means the optional-body wiring
    is wrong and every no-args macro click is broken.
    """
    resp = await auth_client.post("/api/printers/nonexistent-id/macros/HOME")
    assert resp.status_code == 404, resp.text

    resp = await auth_client.post(
        "/api/printers/nonexistent-id/macros/PRINT_START",
        json={"params": {"TEMP": "230"}},
    )
    assert resp.status_code == 404, resp.text

    resp = await auth_client.post("/api/printers/nonexistent-id/macros/HOME", json={})
    assert resp.status_code == 404, resp.text
