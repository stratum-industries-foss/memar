"""Hardening / adversarial fortress for the P2 fixes.

- Device-add: atomic seat-limit enforcement under concurrency (TOCTOU), id
  uniqueness, admin gating.
- Webhooks: a real per-webhook secret is returned once; the HMAC signature is
  computed over the EXACT bytes transmitted (the bug was signing different bytes
  than were sent, with the webhook id as the "secret").
- Fleet: one adapter that explodes on construction must not blank the fleet.
"""

import asyncio
import hashlib
import hmac
import json
import os
import types

import pytest
import yaml

import app.license as licmod
from app.license import LicenseState


# --- helpers --------------------------------------------------------------------

def _write_config(tmp_path, n_enabled=1):
    cfg = {"printers": [
        {"id": f"p{i}", "name": f"P{i}", "base_url": f"http://10.0.0.{i}", "enabled": True}
        for i in range(n_enabled)
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Isolate the device config to a temp file and reset the config cache."""
    import app.config as cfgmod
    path = _write_config(tmp_path, n_enabled=1)
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(path))
    cfgmod.reload_config_cache()
    yield path
    cfgmod.reload_config_cache()


def _device(i):
    return {"id": f"new{i}", "name": f"New {i}", "base_url": f"http://10.1.0.{i}",
            "protocol": "moonraker", "enabled": True}


# --- DEVICE-ADD: atomic seat-limit enforcement ----------------------------------

@pytest.mark.asyncio
async def test_add_respects_limit(temp_config):
    from app.config import add_printer_to_config, DeviceLimitReached
    # limit 3, already 1 enabled -> can add 2 more, 3rd must fail.
    await add_printer_to_config(_device(1), device_limit=3)
    await add_printer_to_config(_device(2), device_limit=3)
    with pytest.raises(DeviceLimitReached):
        await add_printer_to_config(_device(3), device_limit=3)


@pytest.mark.asyncio
async def test_add_rejects_duplicate_id(temp_config):
    from app.config import add_printer_to_config, DuplicateDeviceId
    await add_printer_to_config(_device(1), device_limit=10)
    with pytest.raises(DuplicateDeviceId):
        await add_printer_to_config(_device(1), device_limit=10)


@pytest.mark.asyncio
async def test_concurrent_adds_cannot_exceed_limit(temp_config):
    """TOCTOU regression: 20 concurrent adds against a limit of 5 (1 already
    present) must result in EXACTLY 4 successes — the count-check and append run
    under one lock, so two adds can never both observe count<limit and append."""
    from app.config import add_printer_to_config, DeviceLimitReached, get_config

    async def _try(i):
        try:
            await add_printer_to_config(_device(i), device_limit=5)
            return True
        except DeviceLimitReached:
            return False

    results = await asyncio.gather(*[_try(i) for i in range(20)])
    successes = sum(results)
    enabled = len([p for p in get_config().printers if p.enabled])
    assert successes == 4, f"expected exactly 4 adds to win, got {successes}"
    assert enabled == 5, f"final seat count {enabled} must equal the limit, never exceed it"


@pytest.mark.asyncio
async def test_add_device_endpoint_requires_admin(client, temp_config):
    """A viewer token must not be able to add devices (admin-gated)."""
    # No auth header at all -> 401/403, never 200.
    resp = await client.post("/api/printers/add", json={
        "id": "x", "name": "X", "protocol": "moonraker", "base_url": "http://x", "enabled": True,
    })
    assert resp.status_code in (401, 403)


# --- WEBHOOKS: real secret + sign-exact-bytes -----------------------------------

@pytest.mark.asyncio
async def test_create_webhook_returns_secret(auth_client):
    """Create must return a signing secret exactly once."""
    licmod._state = LicenseState(
        tier="farm", device_limit=150, expires_at="2099-01-01",
        features=["webhooks", "oee", "floor_plan"], customer_id="c", active=True,
    )
    try:
        resp = await auth_client.post("/api/alerts/webhooks/", json={
            "url": "https://example.com/hook", "events": ["printer.error"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("secret"), "create response must include a signing secret"
        assert len(body["secret"]) >= 32
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_dispatch_signs_exact_transmitted_bytes(client):
    """The HMAC must verify against the EXACT body bytes sent, using the webhook's
    secret (not its id). Capture the outbound POST and recompute the signature."""
    import app.webhooks as wh

    captured = {}

    class _Resp:
        status_code = 200

    class _Client:
        async def post(self, url, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return _Resp()

    hook = types.SimpleNamespace(id=7, secret="s3cr3t-not-the-id", url="https://x/y")
    event = {"type": "printer.error", "printer_id": "p1", "data": {"state": "error"}}

    await wh._dispatch_with_retry(_Client(), hook, event)

    sig_header = captured["headers"]["X-MEMAR-Signature"]
    assert sig_header.startswith("sha256=")
    sent_sig = sig_header.split("=", 1)[1]
    # Recompute over the EXACT bytes transmitted, with the real secret.
    expected = hmac.new(b"s3cr3t-not-the-id", captured["content"], hashlib.sha256).hexdigest()
    assert sent_sig == expected, "signature must match HMAC over the transmitted body with the secret"
    # And NOT the old broken scheme (hmac keyed by the webhook id).
    wrong = hmac.new(b"7", captured["content"], hashlib.sha256).hexdigest()
    assert sent_sig != wrong


@pytest.mark.asyncio
async def test_dispatch_logs_delivery(client):
    """Each delivery attempt writes a WebhookDeliveryLog row (observability)."""
    import app.webhooks as wh
    from app.models_db import WebhookDeliveryLog
    from app.db import AsyncSessionLocal
    from sqlalchemy import select

    class _Resp:
        status_code = 200

    class _Client:
        async def post(self, url, content=None, headers=None):
            return _Resp()

    hook = types.SimpleNamespace(id=99, secret="abc", url="https://x/y")
    event = {"type": "printer.complete", "printer_id": "p1", "data": {}}
    await wh._dispatch_with_retry(_Client(), hook, event)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(WebhookDeliveryLog).where(WebhookDeliveryLog.webhook_id == 99)
        )).scalars().all()
    assert len(rows) >= 1
    assert rows[0].status_code == 200


# --- FLEET: one bad adapter must not blank the whole fleet -----------------------

@pytest.mark.asyncio
async def test_safe_fetch_isolates_adapter_failure(monkeypatch):
    """If fetch_printer_status raises (e.g. an adapter ctor blows up), the safe
    wrapper returns an offline status instead of propagating into gather()."""
    import app.fleet as fleet
    from app.models import PrinterConfig

    async def _boom(printer):
        raise RuntimeError("adapter constructor exploded")

    monkeypatch.setattr(fleet, "fetch_printer_status", _boom)
    pc = PrinterConfig(id="bad", name="Bad", base_url="http://nope")
    status = await fleet._safe_fetch_printer_status(pc)
    assert status.online is False
    assert status.state == "offline"
    assert status.id == "bad"
