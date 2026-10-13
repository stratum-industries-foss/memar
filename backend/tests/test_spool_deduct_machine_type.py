"""Regression: spool auto-deduction must survive MachineType being an enum.

`MachineType` is a `(str, Enum)`, so `str(MachineType.FDM)` is the member repr
"MachineType.FDM" — NOT its value "fdm". `_deduct_spool_on_complete` passed that
straight into `compute_consumption`, whose dispatch lowercases and matches
against ("fdm", "idex", ...). Nothing matched, so it returned
(None, "not_applicable"), the `grams_used is not None` guard failed, and
`spool_remaining_g` was NEVER written back.

User-visible effect: while printing, fleet.py live-subtracts the in-flight
filament for display, but that subtraction only applies in the "printing"/
"paused" states. The instant the job completed the display fell back to the
untouched configured value — so "material used" appeared to reset/go stale after
every print, and spool_log stayed empty forever.
"""
import pytest
from types import SimpleNamespace

from app import webhooks
from app.models import MachineType


class _FakeDB:
    """Swallows the SpoolLog audit write; we assert on the deduction itself."""

    def __init__(self, sink):
        self.sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.sink.append(row)

    async def commit(self):
        return None


@pytest.fixture
def harness(monkeypatch):
    """Wire _deduct_spool_on_complete to in-memory config + capture writes."""
    written: dict = {}
    rows: list = []

    printer_cfg = SimpleNamespace(
        id="printer-1",
        spool_remaining_g=750.0,
        filament_diameter_mm=1.75,
        wire_used_mm_per_job=None,
    )

    async def _fake_update(printer_id, updates):
        written[printer_id] = updates
        return ({}, None, None)

    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(printers=[printer_cfg]),
    )
    monkeypatch.setattr("app.config.update_printer_fields", _fake_update)
    monkeypatch.setattr(webhooks, "AsyncSessionLocal", lambda: _FakeDB(rows))

    return SimpleNamespace(written=written, rows=rows, cfg=printer_cfg)


def _completed_printer(machine_type, filament_used_mm=4857.57, material="PLA"):
    """A just-completed FDM job, shaped like fetch_fleet's status object."""
    return SimpleNamespace(
        id="printer-1",
        capability=SimpleNamespace(
            machine_type=machine_type,
            current_material=material,
            build_volume={"x": 235.0, "y": 235.0},
        ),
        job=SimpleNamespace(
            filename="part.gcode",
            filament_used_mm=filament_used_mm,
            total_layer=None,
        ),
    )


@pytest.mark.asyncio
async def test_enum_machine_type_still_deducts(harness):
    """The real code path: capability.machine_type is a MachineType member."""
    await webhooks._deduct_spool_on_complete(_completed_printer(MachineType.FDM))

    assert "printer-1" in harness.written, (
        "spool_remaining_g was never written back — the enum fell through "
        "compute_consumption's dispatch to 'not_applicable' again"
    )
    # 4857.57mm of ø1.75mm PLA (1.24 g/cm3) ~= 14.49g  ->  750 - 14.49
    assert harness.written["printer-1"]["spool_remaining_g"] == pytest.approx(735.5, abs=0.2)


@pytest.mark.asyncio
async def test_plain_string_machine_type_still_works(harness):
    """Adapters that hand back a bare string must keep working."""
    await webhooks._deduct_spool_on_complete(_completed_printer("fdm"))
    assert harness.written["printer-1"]["spool_remaining_g"] == pytest.approx(735.5, abs=0.2)


@pytest.mark.asyncio
async def test_audit_row_records_grams(harness):
    """SpoolLog must capture the computed grams, not a None placeholder."""
    await webhooks._deduct_spool_on_complete(_completed_printer(MachineType.IDEX))

    assert len(harness.rows) == 1
    row = harness.rows[0]
    assert row.filament_used_g == 14
    assert row.spool_before_g == 750
    assert row.spool_after_g == 736  # round(735.5) — banker's rounding
    assert row.source == "auto"
    assert "fdm_length" in (row.note or "")


@pytest.mark.asyncio
async def test_machine_type_without_mass_model_is_skipped(harness):
    """A laser has no filament model — log the row, never touch the spool."""
    await webhooks._deduct_spool_on_complete(_completed_printer(MachineType.LASER))

    assert "printer-1" not in harness.written
    assert len(harness.rows) == 1
    assert harness.rows[0].filament_used_g is None
