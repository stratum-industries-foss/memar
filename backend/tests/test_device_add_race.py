"""Concurrent POST /api/printers/add must not duplicate devices or corrupt devices.yaml."""
import asyncio

import pytest
import yaml

import app.config as cfgmod
import app.main as mainmod


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump({"printers": []}))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    real = mainmod.get_license()
    monkeypatch.setattr(mainmod, "get_license",
                        lambda: type("L", (), {"device_limit": 100, "active": True,
                                               "__getattr__": lambda s, n: getattr(real, n)})())
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


def _body(i, id_=None):
    return {"id": id_, "name": f"P{i}", "protocol": "moonraker",
            "base_url": f"http://10.0.0.{i + 1}"}


def _ids(path):
    data = yaml.safe_load(path.read_text())
    return [p["id"] for p in data["printers"]]


async def test_same_device_concurrent_creates_exactly_one(admin_client, cfg_path):
    rs = await asyncio.gather(*[admin_client.post("/api/printers/add", json=_body(1, "dup"))
                                for _ in range(20)])
    assert all(r.status_code == 200 for r in rs)
    assert sum(r.json()["success"] for r in rs) == 1
    assert _ids(cfg_path) == ["dup"]


async def test_different_devices_concurrent_all_land(admin_client, cfg_path):
    n = 25
    rs = await asyncio.gather(*[admin_client.post("/api/printers/add", json=_body(i, f"dev{i}"))
                                for i in range(n)])
    assert all(r.json()["success"] for r in rs), [r.json() for r in rs if not r.json()["success"]]
    ids = _ids(cfg_path)
    assert len(ids) == n and len(set(ids)) == n
    assert set(ids) == {f"dev{i}" for i in range(n)}


async def test_same_name_no_id_concurrent_never_duplicates(admin_client, cfg_path):
    rs = await asyncio.gather(*[admin_client.post("/api/printers/add", json=_body(3))
                                for _ in range(15)])
    assert all(r.status_code == 200 for r in rs)
    ids = _ids(cfg_path)
    assert len(ids) == len(set(ids)) == sum(r.json()["success"] for r in rs) >= 1
