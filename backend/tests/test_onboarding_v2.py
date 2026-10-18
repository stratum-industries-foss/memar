"""FIRSTRUN_CONTRACT onboarding/discovery tests (multi-port scan, names, subnet, policy).

All network I/O is mocked: TCP sweep via monkeypatched _tcp_open, HTTP via
httpx.MockTransport. No real sockets are opened.
"""

import asyncio
import ipaddress
import time
from types import SimpleNamespace

import httpx
import pytest

import app.config_discovery as cd
import app.onboarding_routes as orr
from app.device_url import assert_lan_device_url, assert_safe_device_url
from app.onboarding_routes import (
    DeviceFound,
    _finalize,
    _run_scan,
    get_local_subnet,
    scan_single_host,
    validate_subnet,
)

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _use_transport(monkeypatch, handler):
    """Route every httpx.AsyncClient created by app code through a MockTransport."""

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _json(payload, status=200):
    return httpx.Response(status, json=payload)


# ── Multi-port discovery ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_single_host_three_moonraker_ports_on_one_host(monkeypatch):
    """KIAUH host: 7125, 7126, 7127 all answer -> three moonraker entries."""

    async def _moon(ip, port=7125, timeout_seconds=0.75):
        return {7125: "voron", 7126: "voron", 7127: "voron"}.get(port)

    monkeypatch.setattr(orr, "probe_moonraker", _moon)

    async def _octo(ip, ports=None, timeout_seconds=0.75):
        return None

    monkeypatch.setattr(orr, "probe_octoprint", _octo)

    results = await scan_single_host(
        "192.168.1.70",
        asyncio.Semaphore(4),
        moonraker_ports=[7125, 7126, 7127],
        octoprint_ports=[],
    )
    assert [(r.port, r.protocol) for r in results] == [(7125, "moonraker"), (7126, "moonraker"), (7127, "moonraker")]


@pytest.mark.asyncio
async def test_run_scan_probes_http_only_on_tcp_open_ports(monkeypatch):
    """Twenty KIAUH instances on 7125-7144 on one host: all 20 found, and HTTP is
    only attempted on ports that accepted a TCP connect."""
    open_ports = set(range(7125, 7145))
    host = "192.168.1.70"
    other = "192.168.1.71"  # no open ports at all

    async def _tcp(ip, port, timeout_seconds):
        return ip == host and port in open_ports

    probed = []

    async def _moon(ip, port=7125, timeout_seconds=0.75):
        probed.append((ip, port))
        return f"voron-{port}"

    async def _octo(ip, ports=None, timeout_seconds=0.75):
        return None

    monkeypatch.setattr(orr, "_tcp_open", _tcp)
    monkeypatch.setattr(orr, "probe_moonraker", _moon)
    monkeypatch.setattr(orr, "probe_octoprint", _octo)

    network = ipaddress.IPv4Network("192.168.1.68/30")  # hosts .69 and .70
    results, capped = await _run_scan(network)
    assert capped is False
    assert {r.port for r in results if r.protocol == "moonraker"} == open_ports
    assert all(ip == host for ip, _ in probed)
    assert {p for _, p in probed} == open_ports
    assert other not in {ip for ip, _ in probed}


@pytest.mark.asyncio
async def test_run_scan_is_bounded_by_budget(monkeypatch):
    """A black-holed network must not run past the scan budget."""

    async def _slow(ip, port, timeout_seconds):
        await asyncio.sleep(10)
        return False

    monkeypatch.setattr(orr, "_tcp_open", _slow)
    started = time.monotonic()
    results, capped = await _run_scan(ipaddress.IPv4Network("192.168.1.0/30"), budget_s=0.5)
    elapsed = time.monotonic() - started
    assert capped is True
    assert results == []
    assert elapsed < 3.0


# ── Names ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_moonraker_name_from_printer_info_hostname(monkeypatch):
    def handler(request):
        if request.url.path == "/server/info":
            return _json({"result": {"version": "v0.9"}})
        if request.url.path == "/printer/info":
            return _json({"result": {"hostname": "voron-a", "state": "ready"}})
        return httpx.Response(404)

    _use_transport(monkeypatch, handler)
    name = await orr.probe_moonraker("192.168.1.70", port=7125)
    assert name == "voron-a"


@pytest.mark.asyncio
async def test_moonraker_name_prefers_mainsail_or_fluidd_name(monkeypatch):
    def handler(request):
        if request.url.path == "/server/info":
            return _json({"result": {"version": "v0.9"}})
        if request.url.path == "/server/database/item":
            if request.url.params.get("namespace") == "fluidd":
                return _json({"result": {"namespace": "fluidd", "value": "  Ender 3 Left  "}})
            return _json({"error": {"code": 404, "message": "Namespace not found"}}, status=404)
        if request.url.path == "/printer/info":
            return _json({"result": {"hostname": "orangepi5b"}})
        return httpx.Response(404)

    _use_transport(monkeypatch, handler)
    assert await orr.probe_moonraker("192.168.1.70", port=7126) == "Ender 3 Left"


@pytest.mark.asyncio
async def test_finalize_keeps_distinct_ui_names_without_port_suffix():
    raw = [
        DeviceFound(ip="192.168.1.70", port=7125, protocol="moonraker", name="Ender 3 Left"),
        DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="Ender 3 Right"),
        DeviceFound(ip="192.168.1.70", port=7127, protocol="moonraker", name="orangepi5b"),
        DeviceFound(ip="192.168.1.70", port=7128, protocol="moonraker", name="orangepi5b"),
    ]
    names = [r.name for r in await _finalize(raw, [], set())]
    assert names == ["Ender 3 Left", "Ender 3 Right", "orangepi5b:7127", "orangepi5b:7128"]


@pytest.mark.asyncio
async def test_finalize_names_single_and_multi_instance():
    raw = [
        DeviceFound(ip="192.168.1.70", port=7125, protocol="moonraker", name="voron"),
        DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="voron"),
        DeviceFound(ip="192.168.1.71", port=7125, protocol="moonraker", name=None),
        DeviceFound(ip="192.168.1.72", port=80, protocol="octoprint", name=None),
    ]
    out = await _finalize(raw, [], set())
    names = {(r.ip, r.port): r.name for r in out}
    assert names[("192.168.1.70", 7125)] == "voron:7125"
    assert names[("192.168.1.70", 7126)] == "voron:7126"
    assert names[("192.168.1.71", 7125)] == "Klipper 192.168.1.71:7125"
    assert names[("192.168.1.72", 80)] == "OctoPrint 192.168.1.72:80"


@pytest.mark.asyncio
async def test_finalize_octoprint_profile_name(monkeypatch):
    async def _profile(ip, port):
        return "Bench Ender"

    monkeypatch.setattr(orr, "_octoprint_profile_name", _profile)
    out = await _finalize([DeviceFound(ip="10.0.0.5", port=5000, protocol="octoprint")], [], set())
    assert out[0].name == "Bench Ender"


# ── already_added and suggested_id ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_already_added_matches_host_and_port_only():
    raw = [
        DeviceFound(ip="192.168.1.70", port=7125, protocol="moonraker", name="a"),
        DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="b"),
    ]
    out = await _finalize(raw, [("192.168.1.70", 7126)], set())
    flags = {r.port: r.already_added for r in out}
    assert flags == {7125: False, 7126: True}


@pytest.mark.asyncio
async def test_suggested_id_slug_and_uniqueness():
    raw = [
        DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="a"),
        DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="a"),  # duplicate
    ]
    out = await _finalize(raw, [], {"klipper-192-168-1-70-7126"})
    ids = [r.suggested_id for r in out]
    assert ids[0] == "klipper-192-168-1-70-7126-2"
    assert ids[1] == "klipper-192-168-1-70-7126-3"
    assert len(set(ids)) == len(ids)


def test_unique_printer_id_slugifies():
    taken: set[str] = set()
    assert orr.unique_printer_id("Klipper 192.168.1.70:7126", taken) == "klipper-192-168-1-70-7126"
    assert orr.unique_printer_id("", taken) == "printer"


# ── Subnet detection and validation ───────────────────────────────────────────


class _FakeUdp:
    def __init__(self, local_ip):
        self._ip = local_ip

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connect(self, addr):
        pass

    def getsockname(self):
        return (self._ip, 0)

    def close(self):
        pass


def test_detected_subnet_reports_detected(monkeypatch):
    monkeypatch.setattr(orr.socket, "socket", lambda *a, **k: _FakeUdp("192.168.1.70"))
    assert orr._detect_subnet() == ("192.168.1.0/24", "detected")
    assert get_local_subnet() == "192.168.1.0/24"


def test_public_outbound_address_falls_back(monkeypatch):
    monkeypatch.setattr(orr.socket, "socket", lambda *a, **k: _FakeUdp("203.0.113.9"))
    monkeypatch.delenv("MEMAR_LAN_SUBNET_FALLBACK", raising=False)
    assert orr._detect_subnet() == ("192.168.1.0/24", "fallback")


def test_failed_detection_reports_fallback(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no route")

    monkeypatch.setattr(orr.socket, "socket", _boom)
    monkeypatch.setenv("MEMAR_LAN_SUBNET_FALLBACK", "10.10.0.0/24")
    assert orr._detect_subnet() == ("10.10.0.0/24", "fallback")


@pytest.mark.parametrize("raw", ["8.8.8.0/24", "203.0.113.0/24", "192.168.1.0/16", "192.168.1.0/21", "192.168.1.0/31", "not-a-cidr"])
def test_validate_subnet_rejects(raw):
    with pytest.raises(ValueError):
        validate_subnet(raw)


def test_validate_subnet_accepts_private_range():
    assert str(validate_subnet("192.168.1.0/24")) == "192.168.1.0/24"
    assert str(validate_subnet("10.0.0.0/22")) == "10.0.0.0/22"


def test_in_container_detection(monkeypatch, tmp_path):
    monkeypatch.setattr(orr.os.path, "exists", lambda p: p == "/.dockerenv")
    assert orr._in_container() is True

    monkeypatch.setattr(orr.os.path, "exists", lambda p: False)
    fake_cgroup = tmp_path / "cgroup"
    fake_cgroup.write_text("0::/system.slice/init.scope\n")
    real_read = orr.Path.read_text
    monkeypatch.setattr(orr.Path, "read_text", lambda self, *a, **k: fake_cgroup.read_text() if str(self) == "/proc/1/cgroup" else real_read(self, *a, **k))
    assert orr._in_container() is False


# ── Scan endpoint ─────────────────────────────────────────────────────────────


def _patch_configured(monkeypatch, tmp_path, printers):
    cfg_file = tmp_path / "devices.yaml"
    cfg_file.write_text("printers: []\n")
    monkeypatch.setattr(orr, "get_config_path", lambda: cfg_file)
    monkeypatch.setattr(orr, "get_config", lambda: SimpleNamespace(printers=printers))


@pytest.mark.asyncio
async def test_scan_endpoint_subnet_param_validation(admin_client):
    for bad in ("8.8.8.0/24", "192.168.0.0/16", "192.168.1.0/31", "junk"):
        resp = await admin_client.get("/api/onboarding/scan", params={"subnet": bad})
        assert resp.status_code == 422, bad


@pytest.mark.asyncio
async def test_scan_endpoint_reports_subnet_metadata(admin_client, monkeypatch, tmp_path):
    async def _fake_run(network, budget_s=orr.SCAN_BUDGET_S):
        assert str(network) == "192.168.1.0/24"
        return [DeviceFound(ip="192.168.1.70", port=7126, protocol="moonraker", name="voron")], False

    monkeypatch.setattr(orr, "_run_scan", _fake_run)
    _patch_configured(monkeypatch, tmp_path, [SimpleNamespace(id="voron-main", base_url="http://192.168.1.70:7126")])

    resp = await admin_client.get("/api/onboarding/scan", params={"subnet": "192.168.1.0/24"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["subnet"] == "192.168.1.0/24"
    assert body["subnet_source"] == "user"
    assert isinstance(body["in_container"], bool)
    assert isinstance(body["duration_ms"], int)
    assert body["scan_capped"] is False
    (item,) = body["results"]
    assert item["already_added"] is True
    assert item["name"] == "voron"
    assert item["suggested_id"] == "klipper-192-168-1-70-7126"


@pytest.mark.asyncio
async def test_scan_endpoint_suggested_id_avoids_configured_id(admin_client, monkeypatch, tmp_path):
    async def _fake_run(network, budget_s=orr.SCAN_BUDGET_S):
        return [DeviceFound(ip="192.168.1.70", port=7125, protocol="moonraker", name="x")], False

    monkeypatch.setattr(orr, "_run_scan", _fake_run)
    _patch_configured(monkeypatch, tmp_path, [SimpleNamespace(id="klipper-192-168-1-70-7125", base_url="http://192.168.1.99:7125")])
    resp = await admin_client.get("/api/onboarding/scan", params={"subnet": "192.168.1.0/24"})
    (item,) = resp.json()["results"]
    assert item["already_added"] is False
    assert item["suggested_id"] == "klipper-192-168-1-70-7125-2"


# ── Test-connection ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_connection_ok_and_success_alias_with_name(admin_client, monkeypatch):
    def handler(request):
        if request.url.path == "/server/info":
            return _json({"result": {"version": "v0.9"}})
        if request.url.path == "/printer/info":
            return _json({"result": {"hostname": "voron-a"}})
        return httpx.Response(404)

    _use_transport(monkeypatch, handler)
    resp = await admin_client.post("/api/onboarding/test-connection", json={
        "protocol": "moonraker", "base_url": "http://192.168.1.70:7125",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["success"] is True
    assert body["name"] == "voron-a"


@pytest.mark.asyncio
async def test_test_connection_failure_reports_both_flags(admin_client, monkeypatch):
    _use_transport(monkeypatch, lambda request: httpx.Response(404))
    resp = await admin_client.post("/api/onboarding/test-connection", json={
        "protocol": "moonraker", "base_url": "http://192.168.1.70:7125",
    })
    body = resp.json()
    assert body["ok"] is False and body["success"] is False
    assert "name" in body


@pytest.mark.asyncio
async def test_test_connection_rejects_public_target(admin_client):
    resp = await admin_client.post("/api/onboarding/test-connection", json={
        "protocol": "moonraker", "base_url": "http://8.8.8.8:7125",
    })
    body = resp.json()
    assert body["ok"] is False and body["success"] is False
    assert "not a private LAN" in body["message"]


def test_lan_policy_allows_private_and_refuses_public():
    assert_lan_device_url("http://192.168.1.70:7125")
    assert_lan_device_url("http://10.1.2.3:80")
    assert_lan_device_url("http://127.0.0.1:7125")
    assert_lan_device_url("http://[fd12:3456::1]:7125")
    with pytest.raises(ValueError, match="not a private LAN"):
        assert_lan_device_url("http://93.184.216.34:80")
    with pytest.raises(ValueError):
        assert_lan_device_url("http://[2606:4700::1111]:80")


def test_device_policy_keeps_metadata_and_link_local_blocks():
    for url in ("http://169.254.169.254/", "http://169.254.1.1/", "http://[fe80::1]/"):
        with pytest.raises(ValueError):
            assert_safe_device_url(url)
        with pytest.raises(ValueError):
            assert_lan_device_url(url)


# ── Config discovery ──────────────────────────────────────────────────────────


def _make_printer_dir(base, num, port):
    d = base / f"printer_{num}_data" / "config"
    d.mkdir(parents=True)
    (d / "moonraker.conf").write_text(f"[server]\nhost: 0.0.0.0\nport: {port}\n", encoding="utf-8")
    return d


def test_discover_sorts_printer_dirs_numerically(tmp_path, monkeypatch):
    for num, port in [(10, 7135), (2, 7127), (1, 7126)]:
        _make_printer_dir(tmp_path, num, port)
    monkeypatch.setattr(cd, "_is_systemd_service_enabled", lambda n: True)
    monkeypatch.setattr(cd, "_fetch_printer_name_from_moonraker", lambda port, n: None)
    monkeypatch.setattr(cd, "_extract_printer_name_from_config", lambda p: None)

    printers = cd.discover_printer_instances(tmp_path)
    assert [p["id"] for p in printers] == ["printer-1", "printer-2", "printer-10"]
    assert [p["base_url"] for p in printers] == [
        "http://127.0.0.1:7126", "http://127.0.0.1:7127", "http://127.0.0.1:7135",
    ]


def test_latin1_bytes_do_not_drop_printer(tmp_path, monkeypatch):
    d = _make_printer_dir(tmp_path, 1, 7125)
    (d / "moonraker.conf").write_bytes(b"# Atelier \xe9 cell\n[server]\nhost: 0.0.0.0\nport: 7125\n")
    (d / "printer.cfg").write_bytes(
        b"# Name: Atelier \xe9 P1\n[printer]\nkinematics: cartesian\n"
        b"[stepper_x]\nposition_max: 250\n[extruder]\nnozzle_diameter: 0.4\n"
    )
    monkeypatch.setattr(cd, "_is_systemd_service_enabled", lambda n: True)
    monkeypatch.setattr(cd, "_fetch_printer_name_from_moonraker", lambda port, n: None)

    printers = cd.discover_printer_instances(tmp_path)
    assert len(printers) == 1
    assert printers[0]["name"].startswith("Atelier")
    assert printers[0]["build_volume"]["x"] == 250.0

    hw = cd.parse_printer_cfg(d / "printer.cfg")
    assert hw["x_max"] == 250.0
    assert hw["nozzle_diameter"] == 0.4


def test_tailscale_cgnat_allowed_for_single_device_public_needs_opt_in(monkeypatch):
    from app import device_url as du
    assert du.is_lan_device_ip("100.101.102.103")
    monkeypatch.setattr(du, "_check_scheme_and_resolve", lambda url: ["93.184.216.34"])
    monkeypatch.setattr(du, "assert_safe_device_url", lambda url: None)
    monkeypatch.delenv("MEMAR_ALLOW_PUBLIC_DEVICES", raising=False)
    with pytest.raises(ValueError, match="MEMAR_ALLOW_PUBLIC_DEVICES"):
        du.assert_lan_device_url("http://printer.example.com:7125")
    monkeypatch.setenv("MEMAR_ALLOW_PUBLIC_DEVICES", "true")
    du.assert_lan_device_url("http://printer.example.com:7125")


def test_scan_subnet_never_cgnat():
    with pytest.raises(ValueError):
        orr.validate_subnet("100.64.1.0/24")
