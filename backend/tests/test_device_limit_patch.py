"""HIGH-FLEET-01: the settings PATCH path must enforce the license seat limit on the
disabled->enabled transition, exactly like the ADD path (config.py:174-175). These are
unit tests on fleet.save_printer_settings with update_printer_fields monkeypatched, so no
config file is written and no route/DB is involved."""
from pathlib import Path

import pytest

import app.fleet as fleet
import app.config as config_mod
import app.license as licmod
from app.license import LicenseState, _tier_to_features
from app.models import FarmConfig, MachineType, PrinterConfig, PrinterSettingsUpdateRequest, Protocol


def _two_device_cfg() -> FarmConfig:
    """Device 'a' enabled (consumes a seat), device 'b' disabled (the one we try to enable)."""
    return FarmConfig(printers=[
        PrinterConfig(id="a", name="A", base_url="http://a", enabled=True,
                      machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER),
        PrinterConfig(id="b", name="B", base_url="http://b", enabled=False,
                      machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER),
    ])


@pytest.mark.asyncio
async def test_enable_via_patch_blocked_over_device_limit(monkeypatch):
    """One enabled device already fills a device_limit=1 license. Enabling the disabled
    device via PATCH must raise ValueError (route maps it to HTTP 400) and must NOT write."""
    cfg = _two_device_cfg()
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    licmod._state = LicenseState(tier="maker", device_limit=1, expires_at="2099-01-01",
                                 features=_tier_to_features("maker"), customer_id=None, active=True)

    async def _must_not_write(printer_id, updates):
        raise AssertionError("update_printer_fields must not run when the seat limit blocks the enable")
    monkeypatch.setattr(fleet, "update_printer_fields", _must_not_write)

    try:
        with pytest.raises(ValueError, match="Device limit reached"):
            await fleet.save_printer_settings(cfg.printers[1], PrinterSettingsUpdateRequest(enabled=True))
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_enable_via_patch_allowed_within_device_limit(monkeypatch):
    """Guard is scoped to the disabled->enabled transition AND only fires at/over the limit —
    with a free seat, enabling must succeed and reach the writer."""
    cfg = _two_device_cfg()
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    licmod._state = LicenseState(tier="farm", device_limit=5, expires_at="2099-01-01",
                                 features=_tier_to_features("farm"), customer_id=None, active=True)

    seen = {}
    async def _fake_write(printer_id, updates):
        seen["printer_id"] = printer_id
        target = {"id": printer_id, "name": "B", "base_url": "http://b", "enabled": True}
        return target, Path("/tmp/devices.yaml"), Path("/tmp/devices.yaml.bak")
    monkeypatch.setattr(fleet, "update_printer_fields", _fake_write)

    try:
        resp = await fleet.save_printer_settings(cfg.printers[1], PrinterSettingsUpdateRequest(enabled=True))
        assert seen["printer_id"] == "b"
        assert resp.printer.enabled is True
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_resave_already_enabled_device_not_blocked(monkeypatch):
    """Re-saving an ALREADY-enabled device (no transition) must never hit the seat check,
    even at the limit — otherwise routine edits to an in-limit device would 400."""
    cfg = _two_device_cfg()
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    licmod._state = LicenseState(tier="maker", device_limit=1, expires_at="2099-01-01",
                                 features=_tier_to_features("maker"), customer_id=None, active=True)

    seen = {}
    async def _fake_write(printer_id, updates):
        seen["printer_id"] = printer_id
        target = {"id": printer_id, "name": "A", "base_url": "http://a", "enabled": True}
        return target, Path("/tmp/devices.yaml"), Path("/tmp/devices.yaml.bak")
    monkeypatch.setattr(fleet, "update_printer_fields", _fake_write)

    try:
        # cfg.printers[0] is 'a', already enabled → PATCH enabled=True is a no-op transition.
        resp = await fleet.save_printer_settings(cfg.printers[0], PrinterSettingsUpdateRequest(enabled=True))
        assert seen["printer_id"] == "a"
    finally:
        licmod._state = None
