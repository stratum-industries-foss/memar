"""First run: zero-config secret, unclaimed state, browser claim, setup code policy, CLI."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import delete

from app import firstrun
from app.db import AsyncSessionLocal
from app.models_db import RefreshToken, User


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMAR_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
async def unclaimed(client, data_dir):
    """Remove every account so the instance is unclaimed."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(RefreshToken))
        await db.execute(delete(User))
        await db.commit()
    return client


def _claim(username="owner", password="a-long-passphrase", code=None):
    body = {"username": username, "password": password}
    if code is not None:
        body["code"] = code
    return body


# ── JWT secret ────────────────────────────────────────────────────────────────

def test_jwt_secret_generated_once_and_private(data_dir, monkeypatch):
    monkeypatch.delenv("MEMAR_JWT_SECRET", raising=False)
    first = firstrun.load_or_create_jwt_secret()
    second = firstrun.load_or_create_jwt_secret()
    path = data_dir / "jwt-secret"
    assert first == second and len(first) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_jwt_secret_env_wins(data_dir, monkeypatch):
    monkeypatch.setenv("MEMAR_JWT_SECRET", "x" * 40)
    assert firstrun.load_or_create_jwt_secret() == "x" * 40
    assert not (data_dir / "jwt-secret").exists()


# ── Status ────────────────────────────────────────────────────────────────────

async def test_status_claimed_when_admin_exists(client):
    r = await client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.json() == {"claimed": True}


async def test_status_unclaimed_open_window(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "10")
    r = await unclaimed.get("/api/setup/status")
    body = r.json()
    assert body["claimed"] is False
    assert body["mode"] == "auto"
    assert body["code_required"] is False
    assert body["window_seconds_left"] > 0
    assert body["where_is_the_code"]


async def test_status_code_required_after_window(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "0")
    r = await unclaimed.get("/api/setup/status")
    assert r.json()["code_required"] is True


# ── Claim ─────────────────────────────────────────────────────────────────────

async def test_claim_in_open_window_then_locked(unclaimed, data_dir, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "10")
    firstrun.get_or_create_setup_code()
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    assert r.json()["must_change_password"] is False
    assert not (data_dir / "setup-code").exists()

    me = await unclaimed.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["role"] == "admin"

    again = await unclaimed.post("/api/setup/claim", json=_claim("intruder"))
    assert again.status_code == 409
    assert (await unclaimed.get("/api/setup/status")).json() == {"claimed": True}


async def test_code_mode_requires_valid_code(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_MODE", "code")
    code = firstrun.get_or_create_setup_code()

    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 403 and r.json()["detail"] == "code_required"

    r = await unclaimed.post("/api/setup/claim", json=_claim(code="WRNG-CODE"))
    assert r.status_code == 403 and r.json()["detail"] == "code_invalid"

    # case- and dash-insensitive
    pretty = f"{code[:4]}-{code[4:]}".lower()
    r = await unclaimed.post("/api/setup/claim", json=_claim(code=pretty))
    assert r.status_code == 201, r.text


async def test_auto_mode_after_window_needs_code(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "0")
    code = firstrun.get_or_create_setup_code()
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 403 and r.json()["detail"] == "code_required"
    r = await unclaimed.post("/api/setup/claim", json=_claim(code=code))
    assert r.status_code == 201


async def test_wrong_code_rejected_even_in_open_mode(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_MODE", "open")
    firstrun.get_or_create_setup_code()
    r = await unclaimed.post("/api/setup/claim", json=_claim(code="AAAA-AAAA"))
    assert r.status_code == 403
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 201


@pytest.mark.parametrize("body,fragment", [
    (_claim(password="short"), "at least 10"),
    (_claim(username="a"), "Username"),
    (_claim(username="bad name!"), "Username"),
    (_claim(username="owner", password="owner"), "at least 10"),
])
async def test_claim_validation(unclaimed, monkeypatch, body, fragment):
    monkeypatch.setenv("MEMAR_SETUP_MODE", "open")
    r = await unclaimed.post("/api/setup/claim", json=body)
    assert r.status_code == 422
    assert fragment in str(r.json()["detail"])


async def test_unknown_mode_fails_closed(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_MODE", "yolo")
    firstrun.get_or_create_setup_code()
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 403


async def test_airgap_licence_defaults_to_code(unclaimed, monkeypatch):
    import app.license as licmod
    monkeypatch.delenv("MEMAR_SETUP_MODE", raising=False)
    monkeypatch.setattr(licmod, "get_license", lambda: type("L", (), {"tier": "airgap_standard"})())
    assert firstrun.setup_mode() == "code"
    firstrun.get_or_create_setup_code()
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 403 and r.json()["detail"] == "code_required"
    monkeypatch.setenv("MEMAR_SETUP_MODE", "open")  # explicit setting still wins
    assert firstrun.setup_mode() == "open"


# ── Bootstrap ─────────────────────────────────────────────────────────────────

async def test_bootstrap_without_password_creates_no_default_admin(unclaimed, data_dir, monkeypatch, capsys):
    from app.auth import ensure_admin_user
    monkeypatch.delenv("MEMAR_ADMIN_PASSWORD", raising=False)
    async with AsyncSessionLocal() as db:
        await ensure_admin_user(db)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        assert (await db.execute(select(User))).first() is None
    out = capsys.readouterr().out
    assert "/setup?code=" in out
    assert (data_dir / "setup-code").exists()
    # default credential no longer works
    r = await unclaimed.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 401


def test_setup_link_uses_host_port_in_container(monkeypatch):
    monkeypatch.delenv("MEMAR_PUBLIC_URL", raising=False)
    monkeypatch.setattr(firstrun, "in_container", lambda: True)
    monkeypatch.setenv("MEMAR_PORT", "8000")
    monkeypatch.setenv("MEMAR_HOST_PORT", "9100")
    links = firstrun.setup_links("ABCD2345")
    assert links[0][1] == "http://localhost:9100/setup?code=ABCD-2345"
    monkeypatch.setenv("MEMAR_PUBLIC_URL", "https://memar.shop.lan/")
    assert firstrun.setup_links("ABCD2345") == [("Open", "https://memar.shop.lan/setup?code=ABCD-2345")]


def test_code_alphabet_and_format(data_dir):
    code = firstrun.new_setup_code()
    assert len(code) == 8 and set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert firstrun.verify_setup_code(firstrun.format_code(code).lower())
    assert not firstrun.verify_setup_code("")
    assert stat.S_IMODE((data_dir / "setup-code").stat().st_mode) == 0o600


# ── Other first-run fixes ─────────────────────────────────────────────────────

async def test_add_printer_without_id_generates_unique_ids(admin_client, tmp_path, monkeypatch):
    import yaml
    import app.config as cfgmod
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump({"printers": []}))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    body = {"name": "Voron 2.4", "protocol": "moonraker", "base_url": "http://192.168.1.70:7125"}
    try:
        r1 = (await admin_client.post("/api/printers/add", json=body)).json()
        body["base_url"] = "http://192.168.1.70:7126"
        r2 = (await admin_client.post("/api/printers/add", json=body)).json()
    finally:
        monkeypatch.undo()
        cfgmod.reload_config_cache()
    assert r1["success"] and r2["success"], (r1, r2)
    assert r1["id"] == "voron-2-4" and r2["id"] == "voron-2-4-2"


async def test_readyz_checks_database(client):
    r = await client.get("/api/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_forgot_password_never_returns_link(client, monkeypatch):
    monkeypatch.setenv("MEMAR_ENV", "development")
    r = await client.post("/api/auth/forgot-password", json={"username": "admin"})
    assert "reset_link" not in r.json()
    assert "reset_token" not in r.text


async def test_csp_allows_bundled_fonts(client):
    r = await client.get("/api/version")
    assert "font-src 'self' data:" in r.headers.get("content-security-policy", "")


# ── CLI (separate process, file DB) ───────────────────────────────────────────

def _cli(args, tmp_path, **env):
    e = {**os.environ, "MEMAR_DATA_DIR": str(tmp_path), "MEMAR_DB_PATH": str(tmp_path / "m.db"),
         "MEMAR_LOG_DIR": str(tmp_path / "logs"), **env}
    e.pop("MEMAR_ADMIN_PASSWORD", None)
    return subprocess.run([sys.executable, "-m", "app.admin_cli", *args],
                          cwd=Path(__file__).parents[1], env=e, capture_output=True, text=True, timeout=60)


def test_cli_setup_link_and_reset(tmp_path):
    r = _cli(["setup-link"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "/setup?code=" in r.stdout
    assert (tmp_path / "setup-code").exists()

    r = _cli(["status"], tmp_path)
    assert "claimed: no" in r.stdout

    r = _cli(["reset-admin"], tmp_path)  # no tty, no --yes
    assert r.returncode == 2

    r = _cli(["reset-admin", "--yes"], tmp_path)
    assert r.returncode == 0 and "/setup?code=" in r.stdout


# ── Auto mode: client address and persisted window ───────────────────────────

@pytest.mark.parametrize("ip,private", [
    ("127.0.0.1", True), ("192.168.1.20", True), ("10.0.0.5", True), ("172.31.9.9", True),
    ("100.101.102.103", True), ("::1", True), ("fd12::1", True), ("::ffff:192.168.1.2", True),
    ("8.8.8.8", False), ("203.0.113.7", False), ("2606:4700::1", False), ("", False),
    (None, False), ("not-an-ip", False), ("172.32.0.1", False),
])
def test_is_private_client(ip, private):
    assert firstrun.is_private_client(ip) is private


async def test_auto_window_public_client_needs_code(unclaimed, data_dir, monkeypatch):
    """Inside the window, a public address still has to present the code."""
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "10")
    code = firstrun.get_or_create_setup_code()
    assert firstrun.code_required("192.168.1.9") is False
    assert firstrun.code_required("203.0.113.7") is True
    assert firstrun.code_required(None) is True

    public = {"X-Forwarded-For": "203.0.113.7"}
    # The test transport's peer is loopback, which the limiter trusts as a proxy,
    # so the forwarded address is the one the policy sees.
    r = await unclaimed.get("/api/setup/status", headers=public)
    assert r.json()["code_required"] is True
    r = await unclaimed.post("/api/setup/claim", json=_claim(), headers=public)
    assert r.status_code == 403 and r.json()["detail"] == "code_required"
    r = await unclaimed.post("/api/setup/claim", json=_claim(code=code), headers=public)
    assert r.status_code == 201, r.text


async def test_auto_window_does_not_restart_with_the_process(unclaimed, data_dir, monkeypatch):
    """The window start is persisted; a restart (new process) keeps the old clock."""
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "10")
    assert firstrun.window_seconds_left() > 0
    start_file = data_dir / "setup-window-start"
    assert start_file.exists()
    # Pretend the first start was an hour ago, as a restarted process would read it.
    import time as _t
    start_file.write_text(str(int(_t.time()) - 3600))
    assert firstrun.window_seconds_left() == 0
    assert firstrun.code_required("192.168.1.9") is True
    r = await unclaimed.post("/api/setup/claim", json=_claim())
    assert r.status_code == 403 and r.json()["detail"] == "code_required"
    # reset-admin / a successful claim clears the window with the code.
    firstrun.clear_setup_code()
    assert not start_file.exists()


async def test_status_window_is_rounded(unclaimed, monkeypatch):
    monkeypatch.setenv("MEMAR_SETUP_WINDOW_MIN", "10")
    left = (await unclaimed.get("/api/setup/status")).json()["window_seconds_left"]
    assert left % 60 == 0 and 0 < left <= 600


async def test_claim_429_after_repeated_wrong_codes_returns_429_after_repeated_wrong_codes(unclaimed, monkeypatch):
    from app import firstrun
    monkeypatch.setenv("MEMAR_SETUP_MODE", "code")
    firstrun.get_or_create_setup_code()
    from app import setup_failures as sf
    body = {"username": "owner", "password": "a-long-passphrase", "code": "WRNG-CODE"}
    statuses = []
    for _ in range(sf.PER_CLIENT_MAX + 1):
        statuses.append((await unclaimed.post("/api/setup/claim", json=body)).status_code)
    assert statuses[:sf.PER_CLIENT_MAX] == [403] * sf.PER_CLIENT_MAX
    assert statuses[-1] == 429
