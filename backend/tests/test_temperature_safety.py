"""HIGH-FLEET-02: the real heating command (fleet.set_temperatures) must enforce the
per-printer safe_nozzle_max_c / safe_bed_max_c, not only the unreachable dry-run path.
Unit tests on set_temperatures with run_single_command monkeypatched, so no adapter/network
is touched and we can assert the unsafe command NEVER reaches the adapter."""
import pytest

import app.fleet as fleet
from app.models import CommandResult, MachineType, PrinterConfig, Protocol, TemperatureSetRequest


def _printer(**kw) -> PrinterConfig:
    base = dict(id="p", name="P", base_url="http://p",
                machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER)
    base.update(kw)
    return PrinterConfig(**base)


@pytest.mark.asyncio
async def test_nozzle_over_per_printer_max_rejected(monkeypatch):
    """A PTFE hotend configured to 240C: a 260C request (within the global 300 cap) must be
    rejected before the adapter is called."""
    called = {"n": 0}
    async def _run(pr, cmd):
        called["n"] += 1
        return CommandResult(result="ok")
    monkeypatch.setattr(fleet, "run_single_command", _run)

    with pytest.raises(ValueError, match="exceeds configured safe_nozzle_max_c"):
        await fleet.set_temperatures(_printer(safe_nozzle_max_c=240.0),
                                     TemperatureSetRequest(nozzle_target=260))
    assert called["n"] == 0, "unsafe nozzle temperature must never reach the adapter"


@pytest.mark.asyncio
async def test_t1_nozzle_over_per_printer_max_rejected(monkeypatch):
    """The IDEX second hotend (t1_nozzle) is bounded by the same per-printer nozzle max."""
    called = {"n": 0}
    async def _run(pr, cmd):
        called["n"] += 1
        return CommandResult(result="ok")
    monkeypatch.setattr(fleet, "run_single_command", _run)

    with pytest.raises(ValueError, match="T1 nozzle temperature .* exceeds configured safe_nozzle_max_c"):
        await fleet.set_temperatures(_printer(safe_nozzle_max_c=240.0),
                                     TemperatureSetRequest(t1_nozzle=260))
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_bed_over_per_printer_max_rejected(monkeypatch):
    called = {"n": 0}
    async def _run(pr, cmd):
        called["n"] += 1
        return CommandResult(result="ok")
    monkeypatch.setattr(fleet, "run_single_command", _run)

    with pytest.raises(ValueError, match="exceeds configured safe_bed_max_c"):
        await fleet.set_temperatures(_printer(safe_bed_max_c=80.0),
                                     TemperatureSetRequest(bed_target=100))
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_target_equal_to_per_printer_max_allowed(monkeypatch):
    """Strict > means a request EXACTLY at the configured cap is allowed and reaches the adapter."""
    sent = {}
    async def _run(pr, cmd):
        sent["cmd"] = cmd
        return CommandResult(result="ok")
    monkeypatch.setattr(fleet, "run_single_command", _run)

    await fleet.set_temperatures(_printer(safe_nozzle_max_c=240.0),
                                 TemperatureSetRequest(nozzle_target=240))
    assert "M104 S240" in sent["cmd"]
