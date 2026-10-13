"""Tests for the MQTT push→poll bridge adapters (generic MQTT + Bambu LAN).

These exercise the bridge against a FAKE in-memory aiomqtt module — they prove the
adapter's loop/caching/staleness/mapping logic and factory wiring. They do NOT
prove behavior against a real Bambu printer (live schema/TLS/auth); that requires
physical hardware (see docs/BAMBU_MQTT.md for the verification runbook).
"""
import asyncio
import json
import sys
import time
import types

import pytest

from app.models import PrinterConfig, Protocol, MachineType
from app.mqtt_client import (
    BambuPollingAdapter,
    MQTTPollingAdapter,
    _map_bambu_state,
    _normalize_bambu,
    _normalize_generic,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _bambu_cfg(**kw) -> PrinterConfig:
    base = dict(
        id="bambu-1", name="X1C", base_url="192.168.1.50",
        machine_type=MachineType.FDM, protocol=Protocol.BAMBU_MQTT,
        api_key="ACCESS123", serial="01P00A0000000000",
    )
    base.update(kw)
    return PrinterConfig(**base)


def _generic_cfg(**kw) -> PrinterConfig:
    base = dict(
        id="gen-1", name="Generic", base_url="mqtt://broker:1883",
        machine_type=MachineType.FDM, protocol=Protocol.MQTT,
    )
    base.update(kw)
    return PrinterConfig(**base)


def _make_fake_aiomqtt(messages, fail_first_n=0):
    """Return (fake_module, recorder). Client yields `messages` then blocks open
    (so the subscribe loop parks rather than tight-looping on reconnect).

    fail_first_n>0 makes the first N __aenter__ calls raise ConnectionError, so the
    reconnect path in _loop can be exercised.
    """
    rec = {"subscribed": [], "published": [], "clients": 0, "kwargs": [], "failures": 0}

    class _Msg:
        def __init__(self, payload):
            self.payload = payload

    class _Messages:
        def __init__(self, msgs):
            self._msgs = list(msgs)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._msgs:
                return _Msg(self._msgs.pop(0))
            await asyncio.sleep(3600)  # keep "connection" open until cancelled
            raise StopAsyncIteration

    class _Client:
        def __init__(self, *args, **kwargs):
            rec["clients"] += 1
            rec["kwargs"].append(kwargs)
            self._args = args

        async def __aenter__(self):
            if rec["failures"] < fail_first_n:
                rec["failures"] += 1
                raise ConnectionError("simulated broker connect failure")
            self.messages = _Messages(messages)
            return self

        async def __aexit__(self, *a):
            return False

        async def subscribe(self, topic):
            rec["subscribed"].append(topic)

        async def publish(self, topic, payload):
            rec["published"].append((topic, payload))

    return types.SimpleNamespace(Client=_Client), rec


async def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


# ── Pure mapping functions ──────────────────────────────────────────────────

def test_map_bambu_states():
    assert _map_bambu_state("RUNNING") == "printing"
    assert _map_bambu_state("PAUSE") == "paused"
    assert _map_bambu_state("FAILED") == "error"
    assert _map_bambu_state("FINISH") == "ready"
    assert _map_bambu_state("IDLE") == "ready"
    assert _map_bambu_state("SOMETHING_NEW") == "idle"


def test_normalize_bambu_full_payload():
    out = _normalize_bambu({"print": {
        "gcode_state": "RUNNING", "mc_percent": 42,
        "nozzle_temper": 210.0, "nozzle_target_temper": 220.0,
        "bed_temper": 60.0, "bed_target_temper": 65.0,
        "mc_remaining_time": 30, "subtask_name": "bench.3mf",
        "layer_num": 5, "total_layer_num": 100,
        "ams": {"ams": [{"tray": [{"tray_type": "PLA"}]}]},
    }})
    assert out["online"] is True
    assert out["state"] == "printing"
    assert out["progress"] == 42
    assert out["nozzle_temperature"] == 210.0 and out["nozzle_target"] == 220.0
    assert out["bed_temperature"] == 60.0 and out["bed_target"] == 65.0
    assert out["eta_seconds"] == 1800  # 30 min → seconds
    assert out["filename"] == "bench.3mf"
    assert out["layer_num"] == 5 and out["total_layers"] == 100
    assert out["ams_material"] == "PLA"


def test_normalize_bambu_handles_missing_print_and_ams():
    out = _normalize_bambu({})
    assert out["state"] == "ready"          # default gcode_state IDLE → ready
    assert out["eta_seconds"] is None
    assert out["ams_material"] is None
    # Malformed AMS must not raise
    out2 = _normalize_bambu({"print": {"ams": {"ams": []}}})
    assert out2["ams_material"] is None


def test_normalize_generic():
    out = _normalize_generic({
        "state": "printing", "progress": 12,
        "nozzle_temp": 200, "bed_temp": 55, "filename": "x.gcode",
    })
    assert out["online"] is True and out["state"] == "printing"
    assert out["progress"] == 12
    assert out["nozzle_temperature"] == 200 and out["bed_temperature"] == 55
    assert out["filename"] == "x.gcode"


def test_normalize_generic_with_field_mapping():
    # Device publishes its own key names; the mapping pulls them into MEMAR keys.
    payload = {"st": "running", "pct": 33, "hotend": 205, "plate": 60, "job": "a.gcode"}
    mapping = {"state": "st", "progress": "pct", "nozzle_temperature": "hotend",
               "bed_temperature": "plate", "filename": "job"}
    out = _normalize_generic(payload, mapping)
    assert out["online"] is True
    assert out["state"] == "running" and out["progress"] == 33
    assert out["nozzle_temperature"] == 205 and out["bed_temperature"] == 60
    assert out["filename"] == "a.gcode"
    # Unmapped MEMAR keys come back as default/None, never KeyError.
    assert _normalize_generic({}, {"state": "missing"})["state"] == "idle"


def test_generic_adapter_uses_configured_topic_and_mapping():
    cfg = _generic_cfg(mqtt_topic="custom/printer/7/state",
                       mqtt_field_mapping={"state": "st", "progress": "pct"})
    a = MQTTPollingAdapter(cfg)
    assert a._build_topic() == "custom/printer/7/state"
    a._started = True
    a._on_message({"st": "printing", "pct": 80})
    # The adapter normalized the device payload through the configured mapping.
    assert a._latest["state"] == "printing" and a._latest["progress"] == 80


# ── Serving logic (wait / cache / staleness) — no broker ──────────────────────

async def test_serving_logic_wait_then_cache_then_stale():
    a = BambuPollingAdapter(_bambu_cfg())
    a._started = True  # bypass loop start; test the serving path directly

    st = await a.get_status()
    assert st["online"] is False and "Waiting" in st["state_message"]

    a._on_message(json.loads('{"print":{"gcode_state":"RUNNING","mc_percent":10}}'))
    st = await a.get_status()
    assert st["online"] is True and st["state"] == "printing" and st["progress"] == 10

    a._last_ts = time.monotonic() - (a.stale_after + 5)
    st = await a.get_status()
    assert st["online"] is False and "stale" in st["state_message"].lower()


# ── Bad config — offline, never raises, never starts a loop ───────────────────

@pytest.mark.parametrize("kw,needle", [
    (dict(serial=None), "serial"),
    (dict(base_url=""), "base_url"),
    (dict(api_key=None), "access code"),
])
async def test_bambu_bad_config_is_offline(kw, needle):
    a = BambuPollingAdapter(_bambu_cfg(**kw))
    st = await a.get_status()
    assert st["online"] is False
    assert needle.lower() in st["state_message"].lower()
    assert a._task is None  # no background loop started


# ── Missing aiomqtt — graceful offline, never raises (prod safety net) ────────

async def test_aiomqtt_missing_is_graceful(monkeypatch):
    # A None entry in sys.modules makes `import aiomqtt` raise ImportError,
    # simulating the live deploy where aiomqtt is not installed.
    monkeypatch.setitem(sys.modules, "aiomqtt", None)
    a = MQTTPollingAdapter(_generic_cfg())
    st = await a.get_status()
    assert st["online"] is False
    assert "aiomqtt" in st["state_message"]
    assert a._task is None


# ── Loop with a fake broker — subscribe, pushall, cache, TLS/auth wiring ──────

async def test_bambu_loop_subscribes_publishes_and_caches(monkeypatch):
    report = json.dumps({"print": {
        "gcode_state": "RUNNING", "mc_percent": 42,
        "nozzle_temper": 210.0, "bed_temper": 60.0,
        "mc_remaining_time": 30, "subtask_name": "bench.3mf",
    }})
    fake, rec = _make_fake_aiomqtt([report])
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)

    a = BambuPollingAdapter(_bambu_cfg())
    await a._ensure_started()
    try:
        assert await _wait_until(lambda: a._latest is not None), "no report cached"
        assert rec["subscribed"] == ["device/01P00A0000000000/report"]
        assert rec["published"], "pushall request not sent"
        topic, payload = rec["published"][0]
        assert topic == "device/01P00A0000000000/request"
        assert "pushall" in payload
        # LAN auth + TLS wired
        kw = rec["kwargs"][0]
        assert kw["username"] == "bblp"
        assert kw["password"] == "ACCESS123"
        assert kw["tls_context"] is not None

        st = await a.get_status()
        assert st["online"] is True and st["state"] == "printing"
        assert st["progress"] == 42 and st["eta_seconds"] == 1800
    finally:
        await a.disconnect()
    assert a._task is None and a._started is False


async def test_loop_reconnects_after_connection_error(monkeypatch):
    report = json.dumps({"print": {"gcode_state": "RUNNING", "mc_percent": 11}})
    fake, rec = _make_fake_aiomqtt([report], fail_first_n=1)
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)

    a = BambuPollingAdapter(_bambu_cfg())
    a.reconnect_delay = 0.01  # don't wait the production backoff in the test
    await a._ensure_started()
    try:
        # First connect attempt raises; the loop must retry and then cache.
        assert await _wait_until(lambda: a._latest is not None, timeout=3.0)
        assert rec["failures"] == 1
        assert rec["clients"] >= 2  # failed attempt + successful reconnect
        st = await a.get_status()
        assert st["online"] is True and st["progress"] == 11
    finally:
        await a.disconnect()


async def test_loop_survives_malformed_and_nondict_payloads(monkeypatch):
    # invalid JSON, then valid-JSON-but-not-an-object, then a good report
    msgs = ["{not json", json.dumps([1, 2, 3]),
            json.dumps({"print": {"gcode_state": "RUNNING", "mc_percent": 73}})]
    fake, rec = _make_fake_aiomqtt(msgs)
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)

    a = BambuPollingAdapter(_bambu_cfg())
    await a._ensure_started()
    try:
        # The loop must skip the two bad messages and still cache the good one,
        # without dying (a dead loop would never reach _latest).
        assert await _wait_until(
            lambda: a._latest is not None and a._latest.get("progress") == 73, timeout=3.0)
        st = await a.get_status()
        assert st["online"] is True and st["state"] == "printing"
    finally:
        await a.disconnect()


async def test_cache_reflects_latest_of_multiple_messages(monkeypatch):
    msgs = [
        json.dumps({"print": {"gcode_state": "IDLE"}}),
        json.dumps({"print": {"gcode_state": "RUNNING", "mc_percent": 25}}),
        json.dumps({"print": {"gcode_state": "RUNNING", "mc_percent": 50}}),
        json.dumps({"print": {"gcode_state": "FINISH", "mc_percent": 100}}),
    ]
    fake, rec = _make_fake_aiomqtt(msgs)
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)

    a = BambuPollingAdapter(_bambu_cfg())
    await a._ensure_started()
    try:
        # Last message wins; _last_ts advances so it is not considered stale.
        assert await _wait_until(
            lambda: a._latest is not None and a._latest.get("state") == "ready", timeout=3.0)
        st = await a.get_status()
        assert st["state"] == "ready" and st["progress"] == 100
        assert a._last_ts is not None
    finally:
        await a.disconnect()


async def test_disconnect_is_safe_when_never_started():
    # Bad config → no loop ever started; disconnect() must still be a clean no-op.
    a = BambuPollingAdapter(_bambu_cfg(serial=None))
    assert a._task is None
    out = await a.disconnect()
    assert out == {"ok": True}


async def test_bambu_refuses_non_local_host():
    a = BambuPollingAdapter(_bambu_cfg(base_url="mqtt.bambulab.com"))
    st = await a.get_status()
    assert st["online"] is False
    assert "non-local" in st["state_message"].lower()
    assert a._task is None


async def test_generic_loop_subscribes_default_topic(monkeypatch):
    report = json.dumps({"state": "printing", "progress": 7})
    fake, rec = _make_fake_aiomqtt([report])
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)

    a = MQTTPollingAdapter(_generic_cfg())
    await a._ensure_started()
    try:
        assert await _wait_until(lambda: a._latest is not None)
        assert rec["subscribed"] == ["machines/gen-1/status"]
        assert not rec["published"]  # generic does not publish
        st = await a.get_status()
        assert st["online"] is True and st["state"] == "printing" and st["progress"] == 7
    finally:
        await a.disconnect()


# ── Factory wiring ────────────────────────────────────────────────────────────

async def test_factory_wiring():
    from app.fleet import _build_client
    assert isinstance(_build_client(_bambu_cfg()), BambuPollingAdapter)
    assert isinstance(_build_client(_generic_cfg()), MQTTPollingAdapter)
    modbus = _build_client(PrinterConfig(
        id="mb", name="mb", base_url="x", protocol=Protocol.MODBUS))
    st = await modbus.get_status()
    assert st["online"] is False and "not yet supported" in st["state_message"]


# ── Eviction lifecycle — _get_client must disconnect() evicted adapters ───────

async def test_get_client_eviction_disconnects_stale(monkeypatch):
    from app import fleet

    class _FakeStale:
        def __init__(self):
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True
            return {"ok": True}

    stale = _FakeStale()
    fleet._client_cache.clear()
    fleet._client_cache["p1:bambu_mqtt:OLD:oldkey"] = stale
    monkeypatch.setattr(fleet, "_build_client", lambda p: object())
    try:
        cfg = _bambu_cfg(id="p1", base_url="NEW", api_key="newkey")
        await fleet._get_client(cfg)
        assert stale.disconnected is True
    finally:
        fleet._client_cache.clear()


# ── End-to-end through the fleet status mapper ────────────────────────────────

async def test_end_to_end_generic_status_to_fleet():
    from app import fleet
    a = BambuPollingAdapter(_bambu_cfg())
    a._started = True
    a._on_message(json.loads(
        '{"print":{"gcode_state":"RUNNING","mc_percent":55,'
        '"nozzle_temper":215,"nozzle_target_temper":220,'
        '"bed_temper":60,"bed_target_temper":60,'
        '"mc_remaining_time":20,"subtask_name":"part.3mf",'
        '"layer_num":42,"total_layer_num":300}}'
    ))
    fs = await fleet._generic_status_to_fleet(_bambu_cfg(), a)
    assert fs.online is True
    assert fs.state == "printing"
    assert fs.job.progress == 55
    assert fs.job.eta_seconds == 1200
    assert fs.job.filename == "part.3mf"
    assert fs.nozzle.temperature == 215 and fs.nozzle.target == 220
    assert fs.bed.temperature == 60
    # layer fields must propagate through _generic_status_to_fleet (audit #2 fix)
    assert fs.job.current_layer == 42
    assert fs.job.total_layer == 300
