"""HIGH-FLEET-03: diagnostics must not read arbitrary local files at a path supplied by the
remote printer. Unit tests on the allowlist helper plus an integration test on
fetch_printer_diagnostics proving a malicious config_file/log_file is not read (default deny)."""
import pytest

import app.fleet as fleet
from app.models import (FleetPrinterStatus, HeaterStatus, JobStatus, MachineType,
                        PrinterConfig, Protocol)


def test_allowed_klipper_file_denies_by_default(monkeypatch, tmp_path):
    """No MEMAR_KLIPPER_FILE_ROOTS set → deny-all, even for a real, readable file."""
    monkeypatch.delenv("MEMAR_KLIPPER_FILE_ROOTS", raising=False)
    f = tmp_path / "printer.cfg"
    f.write_text("[printer]\n")
    assert fleet._allowed_klipper_file(str(f)) is None


def test_allowed_klipper_file_allows_within_root(monkeypatch, tmp_path):
    root = tmp_path / "printer_data"
    (root / "config").mkdir(parents=True)
    cfg = root / "config" / "printer.cfg"
    cfg.write_text("[printer]\n")
    monkeypatch.setenv("MEMAR_KLIPPER_FILE_ROOTS", str(root))
    assert fleet._allowed_klipper_file(str(cfg)) == cfg.resolve()


def test_allowed_klipper_file_denies_traversal_outside_root(monkeypatch, tmp_path):
    root = tmp_path / "printer_data"
    root.mkdir()
    secret = tmp_path / "secret.env"
    secret.write_text("MEMAR_JWT_SECRET=supersecret\n")
    monkeypatch.setenv("MEMAR_KLIPPER_FILE_ROOTS", str(root))
    assert fleet._allowed_klipper_file(str(root / ".." / "secret.env")) is None  # .. escape
    assert fleet._allowed_klipper_file(str(secret)) is None                      # sibling of root


def test_allowed_klipper_file_none_and_empty(monkeypatch):
    monkeypatch.setenv("MEMAR_KLIPPER_FILE_ROOTS", "/tmp")
    assert fleet._allowed_klipper_file(None) is None
    assert fleet._allowed_klipper_file("") is None


@pytest.mark.asyncio
async def test_diagnostics_does_not_read_remote_supplied_path(monkeypatch, tmp_path):
    """A malicious printer reporting config_file/log_file = <server secret> must NOT be read:
    with no allowlist configured (default), klipper_config stays None and recent_log_lines
    stays empty."""
    monkeypatch.delenv("MEMAR_KLIPPER_FILE_ROOTS", raising=False)
    secret = tmp_path / "server_secret.env"
    secret.write_text("MEMAR_JWT_SECRET=supersecret\n")

    printer = PrinterConfig(id="evil", name="Evil", base_url="http://evil",
                            machine_type=MachineType.FDM, protocol=Protocol.MOONRAKER)

    async def _fake_status(pr):
        return FleetPrinterStatus(
            id=pr.id, name=pr.name, base_url=pr.base_url, enabled=True, online=True,
            state="ready",
            raw={"printer_info": {"config_file": str(secret), "log_file": str(secret)}},
        )
    monkeypatch.setattr(fleet, "fetch_printer_status", _fake_status)

    diag = await fleet.fetch_printer_diagnostics(printer)
    assert diag.klipper_config is None, "remote-supplied config_file must not be parsed off local disk"
    assert diag.recent_log_lines == [], "remote-supplied log_file must not be tailed off local disk"
