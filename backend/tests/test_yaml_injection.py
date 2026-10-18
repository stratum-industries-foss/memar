"""Hostile device names/fields must round-trip as inert data in devices.yaml."""
import pytest
import yaml

import app.config as cfgmod
import app.main as mainmod

NASTY = [
    "a: b",
    "line1\nline2: injected",
    "x\n- id: evil\n  name: pwn",
    "{a: 1, b: [2]}",
    "!!python/object/apply:os.system ['echo pwned']",
    "---\nprinters: []",
    "&anchor *alias",
    "*alias",
    "# comment",
    "name: 'q\" \\ \t end",
    "A" * 20000,
    "ünï\u2028code\u0085",
    "null", "true", "123", "~",
]


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump({"printers": []}))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    real = mainmod.get_license()
    monkeypatch.setattr(mainmod, "get_license",
                        lambda: type("L", (), {"device_limit": 1000, "active": True,
                                               "__getattr__": lambda s, n: getattr(real, n)})())
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


async def test_nasty_values_roundtrip_and_inject_nothing(admin_client, cfg_path):
    accepted = []
    for i, v in enumerate(NASTY):
        body = {"id": f"d{i}", "name": v, "protocol": "moonraker",
                "base_url": f"http://10.0.1.{i + 1}", "serial": v[:128],
                "api_key": v[:512], "mqtt_topic": v[:512],
                "mqtt_field_mapping": {v[:50]: v[:50]}}
        r = await admin_client.post("/api/printers/add", json=body)
        assert r.status_code in (200, 422), r.text
        if r.status_code == 200 and r.json()["success"]:
            accepted.append((f"d{i}", v))
    assert accepted, "nothing accepted; test is vacuous"
    raw = cfg_path.read_text()
    data = yaml.safe_load(raw)  # safe_load must succeed (no python tags)
    assert list(data) == ["printers"]
    got = {p["id"]: p for p in data["printers"]}
    assert list(got) == [i for i, _ in accepted] and len(data["printers"]) == len(accepted)
    for id_, v in accepted:
        assert got[id_]["name"] == v
    assert "evil" not in got


async def test_nasty_device_id_cannot_inject(admin_client, cfg_path):
    r = await admin_client.post("/api/printers/add", json={
        "id": "x\n- id: evil", "name": "ok", "protocol": "moonraker",
        "base_url": "http://10.0.2.1"})
    assert r.status_code in (200, 422)
    data = yaml.safe_load(cfg_path.read_text())
    ids = [p["id"] for p in data["printers"]]
    assert "evil" not in ids and len(ids) <= 1


async def test_name_only_generates_safe_id(admin_client, cfg_path):
    r = await admin_client.post("/api/printers/add", json={
        "name": "a: b\n{c}", "protocol": "moonraker", "base_url": "http://10.0.3.1"})
    assert r.status_code == 200 and r.json()["success"]
    data = yaml.safe_load(cfg_path.read_text())
    assert [p["id"] for p in data["printers"]] == ["a-b-c"]
