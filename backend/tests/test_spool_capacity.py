"""Tests for the per-printer `spool_capacity_g` field (one-click refill-to-full).

Plain in-memory model construction only — no DB, so this avoids the NixOS
greenlet/libstdc++ async-engine path. Still run via ./run-tests.sh for parity.
"""
from app.models import PrinterConfig


def _base_kwargs(**overrides):
    kwargs = {
        "id": "printer-test",
        "name": "Test Printer",
        "base_url": "http://127.0.0.1:7125",
    }
    kwargs.update(overrides)
    return kwargs


def test_spool_capacity_defaults_to_1000():
    """A config built without spool_capacity_g gets the standard 1 kg default."""
    cfg = PrinterConfig(**_base_kwargs())
    assert cfg.spool_capacity_g == 1000.0


def test_spool_capacity_propagates_to_capability():
    """capability() carries spool_capacity_g through (default and explicit)."""
    cfg = PrinterConfig(**_base_kwargs())
    assert cfg.capability().spool_capacity_g == 1000.0

    cfg2 = PrinterConfig(**_base_kwargs(spool_capacity_g=750.0))
    assert cfg2.capability().spool_capacity_g == 750.0


def test_spool_capacity_explicit_round_trips():
    """An explicit value is preserved exactly."""
    cfg = PrinterConfig(**_base_kwargs(spool_capacity_g=3000.0))
    assert cfg.spool_capacity_g == 3000.0
