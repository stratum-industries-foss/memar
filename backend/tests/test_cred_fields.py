"""Credential-field tests: serial (settable) + api_key (write-only, never leaked).

Covers the secret-leak fix (GET/POST /settings must never return api_key — they
return api_key_set instead), the write-only "blank = keep" semantics, serial
persistence via the settings endpoint, and the add-printer endpoint accepting both.
All exercised through the real HTTP endpoints with a temp devices.yaml.
"""
import pytest
import yaml

import app.config as cfgmod
from app.main import _redact_printer


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """devices.yaml with a Bambu device that already has serial + api_key set."""
    cfg = {"printers": [
        {
            "id": "bambu1", "name": "Bambu X1C", "base_url": "192.168.1.50",
            "protocol": "bambu_mqtt", "serial": "01P00A0000000000",
            "api_key": "SECRET_ACCESS_CODE", "enabled": True,
        },
        {"id": "plain1", "name": "Plain", "base_url": "http://10.0.0.9", "enabled": True},
    ]}
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


def _stored(printer_id: str):
    return next(p for p in cfgmod.get_config().printers if p.id == printer_id)


# ── Unit: the redaction helper ────────────────────────────────────────────────

def test_redact_printer_strips_key_and_sets_flag():
    out = _redact_printer({"id": "x", "api_key": "s3cr3t", "serial": "ABC"})
    assert "api_key" not in out
    assert out["api_key_set"] is True
    assert out["serial"] == "ABC"  # serial is not secret — preserved
    out2 = _redact_printer({"id": "y", "api_key": None})
    assert out2["api_key_set"] is False


# ── GET /settings must never return the access code ───────────────────────────

async def test_get_settings_never_returns_api_key(admin_client, temp_config):
    resp = await admin_client.get("/api/printers/bambu1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "api_key" not in body, "SECRET LEAK: api_key returned in settings response"
    assert body["api_key_set"] is True
    assert body["serial"] == "01P00A0000000000"  # serial is shown (not secret)


async def test_get_settings_api_key_set_false_when_absent(admin_client, temp_config):
    body = (await admin_client.get("/api/printers/plain1/settings")).json()
    assert "api_key" not in body
    assert body["api_key_set"] is False


# ── POST /settings: serial settable, response still redacted ──────────────────

async def test_post_settings_updates_serial_and_stays_redacted(admin_client, temp_config):
    resp = await admin_client.post(
        "/api/printers/bambu1/settings", json={"serial": "99NEWSERIAL99"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "api_key" not in body.get("printer", {}), "SECRET LEAK in save response"
    assert _stored("bambu1").serial == "99NEWSERIAL99"


# ── Write-only "blank = keep": omitting api_key preserves it ──────────────────

async def test_post_omitting_api_key_preserves_existing(admin_client, temp_config):
    assert _stored("bambu1").api_key == "SECRET_ACCESS_CODE"
    # Update only serial; api_key is NOT in the body → must be preserved.
    await admin_client.post("/api/printers/bambu1/settings", json={"serial": "KEEP"})
    assert _stored("bambu1").api_key == "SECRET_ACCESS_CODE"


async def test_post_with_api_key_sets_it(admin_client, temp_config):
    await admin_client.post(
        "/api/printers/bambu1/settings", json={"api_key": "ROTATED_CODE"})
    assert _stored("bambu1").api_key == "ROTATED_CODE"


async def test_post_explicit_null_clears_api_key(admin_client, temp_config):
    # The "Clear access code" UI affordance sends api_key: null explicitly.
    assert _stored("bambu1").api_key == "SECRET_ACCESS_CODE"
    resp = await admin_client.post(
        "/api/printers/bambu1/settings", json={"api_key": None})
    assert resp.status_code == 200, resp.text
    assert _stored("bambu1").api_key is None
    # still redacted in the response
    assert "api_key" not in resp.json().get("printer", {})


# ── Add endpoint accepts serial + api_key (API path; no UI modal yet) ─────────

async def test_post_settings_persists_mqtt_topic_and_mapping(admin_client, temp_config):
    resp = await admin_client.post("/api/printers/plain1/settings", json={
        "mqtt_topic": "shop/printer/plain1/status",
        "mqtt_field_mapping": {"state": "st", "progress": "pct"},
    })
    assert resp.status_code == 200, resp.text
    stored = _stored("plain1")
    assert stored.mqtt_topic == "shop/printer/plain1/status"
    assert stored.mqtt_field_mapping == {"state": "st", "progress": "pct"}


async def test_add_printer_persists_serial_and_api_key(admin_client, temp_config):
    resp = await admin_client.post("/api/printers/add", json={
        "id": "bambu2", "name": "Bambu P1", "protocol": "bambu_mqtt",
        "base_url": "192.168.1.51", "serial": "02P11B1111111111",
        "api_key": "ADDED_CODE", "enabled": True,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json().get("success") is True
    # The add response carries no printer dict, so it cannot leak the key.
    assert "api_key" not in resp.text
    stored = _stored("bambu2")
    assert stored.serial == "02P11B1111111111"
    assert stored.api_key == "ADDED_CODE"
