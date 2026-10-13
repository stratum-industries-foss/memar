"""Shared fixtures for MEMAR backend tests."""

import ipaddress
import os
import socket
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set test env before importing app — must happen before any app module loads.
os.environ["MEMAR_JWT_SECRET"] = "test-secret-not-for-production"
os.environ["MEMAR_ADMIN_USER"] = "admin"
os.environ["MEMAR_ADMIN_PASSWORD"] = "testpass123"
# sqlite+aiosqlite:///:memory: — db.py prepends the protocol prefix.
os.environ["MEMAR_DB_PATH"] = ":memory:"
os.environ["MEMAR_DATA_DIR"] = "/tmp/memar_test"
# Disable the license heartbeat in tests — it now defaults to the hosted worker,
# and the test suite must never reach out over the network.
os.environ["MEMAR_LICENSE_HEARTBEAT_URL"] = ""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from app.main import app
from app.db import init_db, AsyncSessionLocal
from app.auth import ensure_admin_user

# Disable slowapi rate limiting so login tests don't exhaust the 10/min cap.
if hasattr(app.state, "limiter"):
    app.state.limiter.enabled = False


# ── Hermetic DNS ──────────────────────────────────────────────────────────────
# app.ssrf.assert_safe_http_url (and the device adapters that call it in their
# constructors) resolve the target host. Tests use placeholder hosts ("evil",
# "broker", "host", "example.com"), so their outcome used to depend on the CI
# box's resolver: NXDOMAIN in a sandbox, a wildcard/hijacked answer elsewhere,
# real answers only with network. Here: IP literals and localhost resolve
# locally, the placeholder names resolve to ONE fixed global IP, and every other
# name is NXDOMAIN. The real SSRF guard still runs on the answer — nothing in
# app/ssrf.py is bypassed or relaxed.
_REAL_GETADDRINFO = socket.getaddrinfo
_FAKE_PUBLIC_IP = "93.184.215.14"  # is_global (ex-example.com address); never contacted — HTTP is mocked.
_FAKE_PUBLIC_HOSTS = frozenset({"evil", "broker", "host", "example.com"})


def _hermetic_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    name = host.decode() if isinstance(host, bytes) else host
    if name is None or name.lower() == "localhost":
        return _REAL_GETADDRINFO(host, port, family, type, proto, flags)
    try:
        ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        pass
    else:  # IP literal: numeric parse only, the resolver is never consulted
        return _REAL_GETADDRINFO(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)
    if name.lower().rstrip(".") in _FAKE_PUBLIC_HOSTS:
        return _REAL_GETADDRINFO(_FAKE_PUBLIC_IP, port, family, type, proto, flags | socket.AI_NUMERICHOST)
    raise socket.gaierror(socket.EAI_NONAME, f"hermetic test DNS: {name!r} is not a known test host")


@pytest.fixture(autouse=True)
def _hermetic_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _hermetic_getaddrinfo)


@pytest_asyncio.fixture()
async def client():
    """Unauthenticated ASGI test client with a PRISTINE in-memory DB per test.

    The engine is shared across the session, and SQLite :memory: keeps rows
    between tests — so telemetry/log/billing tables would otherwise accumulate
    and make order-sensitive assertions (latest-row, counts) flaky. Drop + create
    before each test gives true isolation."""
    from app.db import engine
    from app.models_db import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_admin_user(db)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture()
async def admin_client(client):
    """Authenticated client (admin token obtained via real login)."""
    resp = await client.post("/api/auth/login", json={
        "username": os.environ["MEMAR_ADMIN_USER"],
        "password": os.environ["MEMAR_ADMIN_PASSWORD"],
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# Keep legacy alias so any existing tests using auth_client still work.
auth_client = admin_client


async def _login_as(username: str, password: str) -> AsyncClient:
    """Independent authenticated client (separate from admin_client) sharing
    the same in-process app + DB engine. Shared helper for role-based-access
    tests across multiple test modules (see test_cnc_control.py for the
    original pattern this was lifted from)."""
    ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    resp = await ac.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return ac


@pytest_asyncio.fixture
async def operator_client(admin_client):
    """Authenticated client for a freshly-created 'operator' role user.

    Requires the 'multi_user' license feature to be active (user creation is
    feature-gated) — tests using this fixture must also activate a license,
    e.g. via a local autouse fixture setting app.license._state."""
    r = await admin_client.post(
        "/api/admin/users",
        json={"username": "op1", "password": "secret123", "role": "operator"},
    )
    assert r.status_code == 201, r.text
    ac = await _login_as("op1", "secret123")
    yield ac
    await ac.aclose()


@pytest_asyncio.fixture
async def viewer_client(admin_client):
    """Authenticated client for a freshly-created 'viewer' role user. See
    operator_client for the multi_user license-feature requirement."""
    r = await admin_client.post(
        "/api/admin/users",
        json={"username": "view1", "password": "secret123", "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    ac = await _login_as("view1", "secret123")
    yield ac
    await ac.aclose()
