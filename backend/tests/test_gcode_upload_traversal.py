"""Regression tests for gcode upload filename sanitization.

Context: a prior gap-analysis flagged "path traversal in file upload,
fleet.py". Tracing the call chain (main.upload_printer_file ->
fleet.upload_gcode -> MoonrakerClient.upload_file -> httpx multipart POST
to the REMOTE Moonraker /server/files/upload API) confirms the filename is
never opened/written on MEMAR's own local filesystem — it's only ever
placed in an in-memory multipart body sent over HTTP. So a local-fs
traversal was never actually reachable through this path.

That said, MEMAR should not forward an unsanitized `../`-laden filename to
any downstream API regardless of who is ultimately responsible for
validating it. These tests assert the defense-in-depth fix: filenames are
reduced to a bare basename (no directory components at all) before being
used anywhere in the upload path, and any code path in fleet.py that still
handles relative gcode paths (_ensure_gcodes_path / _relative_gcode_filename)
strips '..' traversal segments rather than only stripping a leading '/'.
"""

import pytest

from app.fleet import (
    _ensure_gcodes_path,
    _relative_gcode_filename,
    _sanitize_upload_filename,
    upload_gcode,
)
from app.models import PrinterConfig
from app.moonraker import MoonrakerClient


class _RecordingMoonrakerClient(MoonrakerClient):
    """Stub that records the filename/path handed to upload_file instead of
    making a real HTTP call to a remote Moonraker instance."""

    def __init__(self, printer):
        super().__init__(printer)
        self.last_upload_kwargs: dict | None = None

    async def upload_file(self, *, filename, content, root="gcodes", path=None, auto_print=False):
        self.last_upload_kwargs = {
            "filename": filename,
            "content": content,
            "root": root,
            "path": path,
            "auto_print": auto_print,
        }
        return {"item": {"path": f"gcodes/{filename}", "size": len(content)}}


def _printer() -> PrinterConfig:
    return PrinterConfig(id="p1", name="Printer 1", base_url="http://192.168.1.50:7125")


@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "../../../secrets.txt",
        "/etc/passwd",
        "..\\..\\windows\\win.ini",
        "a/../../b.gcode",
    ],
)
def test_sanitize_upload_filename_strips_traversal(raw):
    clean = _sanitize_upload_filename(raw)
    assert ".." not in clean
    assert "/" not in clean
    assert "\\" not in clean
    # Must reduce to a bare basename with no surviving directory component.
    assert clean == raw.replace("\\", "/").split("/")[-1]


@pytest.mark.parametrize("raw", ["", "   ", ".", "..", "../", "../.."])
def test_sanitize_upload_filename_rejects_empty_or_dotdot(raw):
    with pytest.raises(Exception):
        _sanitize_upload_filename(raw)


@pytest.mark.parametrize(
    "raw,expected_no_traversal",
    [
        ("../../etc/passwd", "etc/passwd"),
        ("/../secret.gcode", "secret.gcode"),
        ("sub/../../dir/file.gcode", "dir/file.gcode"),
    ],
)
def test_ensure_gcodes_path_strips_dotdot(raw, expected_no_traversal):
    result = _ensure_gcodes_path(raw)
    assert ".." not in result
    assert result == f"gcodes/{expected_no_traversal}"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "etc/passwd"),
        ("gcodes/../../etc/passwd", "etc/passwd"),
        ("sub/../file.gcode", "file.gcode"),
    ],
)
def test_relative_gcode_filename_strips_dotdot(raw, expected):
    result = _relative_gcode_filename(raw)
    assert ".." not in result
    assert result == expected


@pytest.mark.asyncio
async def test_upload_gcode_never_forwards_traversal_filename(monkeypatch):
    """End-to-end through the actual vulnerable-looking chain: a crafted
    filename must arrive at MoonrakerClient.upload_file already reduced to
    a bare basename, with no '..' or path separators surviving."""
    printer = _printer()
    fake_client = _RecordingMoonrakerClient(printer)

    async def _fake_get_client(_printer):
        return fake_client

    monkeypatch.setattr("app.fleet._get_client", _fake_get_client)

    malicious_filename = "../../etc/passwd"
    result = await upload_gcode(
        printer,
        filename=malicious_filename,
        content=b"G28\n",
        relative_path=None,
        auto_print=False,
    )

    assert fake_client.last_upload_kwargs is not None
    forwarded_filename = fake_client.last_upload_kwargs["filename"]
    assert ".." not in forwarded_filename
    assert "/" not in forwarded_filename
    assert forwarded_filename == "passwd"
    assert result.filename == "passwd"
    assert ".." not in (result.path or "")


@pytest.mark.asyncio
async def test_upload_gcode_rejects_traversal_only_filename(monkeypatch):
    """A filename that is nothing but traversal segments (e.g. '../..')
    must be rejected outright rather than silently passed through empty."""
    printer = _printer()
    fake_client = _RecordingMoonrakerClient(printer)

    async def _fake_get_client(_printer):
        return fake_client

    monkeypatch.setattr("app.fleet._get_client", _fake_get_client)

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await upload_gcode(
            printer,
            filename="../..",
            content=b"G28\n",
            relative_path=None,
            auto_print=False,
        )
    assert fake_client.last_upload_kwargs is None
