"""HTTP-level tests for GET /api/printers/{id}/webcams/{uid}/stream's auth.

FOUND BY REVIEW: this route required Bearer auth (Depends(get_current_user)),
but its only real consumer is a bare <img src>, which can't carry an
Authorization header — every stream request 401'd in any real (non-dev-bypass)
deployment. Switched to single-use ticket auth (POST /api/ws/ticket),
mirroring /ws/fleet's existing ticket-only pattern. These tests cover the
auth layer only — stream_webcam's actual Moonraker-proxying logic is
untouched and out of scope here.
"""
from unittest.mock import AsyncMock

import pytest

import app.fleet as fleet
import app.main as main_module
from app.models import FarmConfig, MachineType, PrinterConfig, Protocol

PRINTER_ID = "webcam-test-1"


def _config() -> FarmConfig:
    return FarmConfig(
        printers=[
            PrinterConfig(
                id=PRINTER_ID,
                name="Test Printer",
                base_url="http://localhost:7125",
                machine_type=MachineType.FDM,
                protocol=Protocol.MOONRAKER,
                enabled=True,
            )
        ]
    )


@pytest.fixture(autouse=True)
def _config_fixture(monkeypatch):
    monkeypatch.setattr(main_module, "get_config", _config)


@pytest.mark.asyncio
async def test_stream_without_ticket_returns_401(admin_client):
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/webcams/default/stream")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_with_garbage_ticket_returns_401(admin_client):
    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/webcams/default/stream", params={"ticket": "not-a-real-ticket"})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_with_valid_ticket_reaches_proxy(admin_client, monkeypatch):
    """A valid single-use ticket should authenticate the request and reach
    stream_webcam — doesn't assert on the proxy's own behavior, just that
    auth no longer blocks it."""
    ticket_resp = await admin_client.post("/api/ws/ticket")
    assert ticket_resp.status_code == 200, ticket_resp.text
    ticket = ticket_resp.json()["ticket"]

    called = {}

    async def _fake_stream_webcam(printer, uid):
        called["printer_id"] = printer.id
        called["uid"] = uid
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("ok")

    monkeypatch.setattr(fleet, "stream_webcam", _fake_stream_webcam)

    r = await admin_client.get(f"/api/printers/{PRINTER_ID}/webcams/default/stream", params={"ticket": ticket})
    assert r.status_code == 200, r.text
    assert called == {"printer_id": PRINTER_ID, "uid": "default"}


@pytest.mark.asyncio
async def test_ticket_is_single_use(admin_client, monkeypatch):
    """A ticket consumed by one stream request must not authenticate a
    second — same single-use guarantee /ws/fleet relies on."""
    ticket_resp = await admin_client.post("/api/ws/ticket")
    ticket = ticket_resp.json()["ticket"]

    async def _fake_stream_webcam(printer, uid):
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("ok")
    monkeypatch.setattr(fleet, "stream_webcam", _fake_stream_webcam)

    first = await admin_client.get(f"/api/printers/{PRINTER_ID}/webcams/default/stream", params={"ticket": ticket})
    assert first.status_code == 200, first.text

    second = await admin_client.get(f"/api/printers/{PRINTER_ID}/webcams/default/stream", params={"ticket": ticket})
    assert second.status_code == 401, second.text
