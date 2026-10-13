"""Tests for onboarding routes (device discovery and connection testing)."""

import asyncio
import ipaddress
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.onboarding_routes import (
    get_local_subnet,
    probe_moonraker,
    probe_octoprint,
    scan_single_host,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_moonraker_response():
    """Sample Moonraker /server/info response."""
    return {
        "result": {
            "hostname": "printer-01",
            "version": "v0.8.0",
        }
    }


@pytest.fixture
def sample_octoprint_response():
    """Sample OctoPrint /api/version response."""
    return {
        "server": "1.9.0",
        "api": "0.1",
    }


def create_mock_response(status_code, json_data=None, text=""):
    """Helper to create mock httpx.Response with proper json() method."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or {}
    mock_response.text = text or str(json_data)
    return mock_response


# ── Subnet Detection Tests ────────────────────────────────────────────────────


def test_get_local_subnet_success():
    """Subnet derivation succeeds and returns valid /24."""
    subnet = get_local_subnet()
    # Should be a valid CIDR
    try:
        net = ipaddress.IPv4Network(subnet)
        assert str(net).endswith("/24")
    except ValueError:
        # Fallback is also valid
        assert subnet in ["192.168.1.0/24", "10.0.0.0/24"]


def test_get_local_subnet_fallback():
    """Subnet derivation falls back when socket trick fails."""
    with patch("socket.socket") as mock_socket:
        mock_socket.side_effect = OSError("No route to host")
        subnet = get_local_subnet()
        # Should return a fallback subnet
        assert subnet == "192.168.1.0/24"


def test_get_local_subnet_fallback_is_configurable(monkeypatch):
    """ONBOARD-SUBNET-FALLBACK-01: an operator whose real subnet differs from
    the 192.168.1.0/24 default must be able to override it — the old
    hardcoded fallback always guessed wrong for e.g. 10.x or 192.168.50.x
    deployments, with a scan that silently found nothing and no way to fix it."""
    monkeypatch.setenv("MEMAR_LAN_SUBNET_FALLBACK", "10.10.10.0/24")
    with patch("socket.socket") as mock_socket:
        mock_socket.side_effect = OSError("No route to host")
        subnet = get_local_subnet()
        assert subnet == "10.10.10.0/24"


# ── Moonraker Probe Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_moonraker_success(sample_moonraker_response):
    """Moonraker probe succeeds with valid /server/info response."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, sample_moonraker_response)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125)

        assert result == "printer-01"


@pytest.mark.asyncio
async def test_probe_moonraker_404():
    """Moonraker probe fails with 404."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(404)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125)

        assert result is None


@pytest.mark.asyncio
async def test_probe_moonraker_invalid_json():
    """Moonraker probe fails with invalid JSON response."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125)

        assert result is None


@pytest.mark.asyncio
async def test_probe_moonraker_timeout():
    """Moonraker probe fails with timeout."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.side_effect = asyncio.TimeoutError()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125, timeout_seconds=0.1)

        assert result is None


@pytest.mark.asyncio
async def test_probe_moonraker_network_error():
    """Moonraker probe fails with network error."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125)

        assert result is None


@pytest.mark.asyncio
async def test_probe_moonraker_missing_result_key():
    """Moonraker probe fails when 'result' key is missing."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, {"error": "something"})
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_moonraker("192.168.1.100", port=7125)

        assert result is None


# ── OctoPrint Probe Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_octoprint_success_port_80(sample_octoprint_response):
    """OctoPrint probe succeeds on port 80."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, sample_octoprint_response)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_octoprint("192.168.1.100", ports=[80, 5000])

        assert result == "octoprint"


@pytest.mark.asyncio
async def test_probe_octoprint_success_port_5000(sample_octoprint_response):
    """OctoPrint probe succeeds on port 5000."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        # Fail on port 80, succeed on port 5000
        responses = [
            create_mock_response(404),
            create_mock_response(200, sample_octoprint_response),
        ]
        mock_client.get.side_effect = responses
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_octoprint("192.168.1.100", ports=[80, 5000])

        assert result == "octoprint"


@pytest.mark.asyncio
async def test_probe_octoprint_no_ports():
    """OctoPrint probe defaults to [80, 5000] if no ports specified."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, {"server": "1.9.0", "api": "0.1"})
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_octoprint("192.168.1.100")

        assert result == "octoprint"


@pytest.mark.asyncio
async def test_probe_octoprint_404_all_ports():
    """OctoPrint probe fails if 404 on all ports."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(404)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_octoprint("192.168.1.100", ports=[80, 5000])

        assert result is None


@pytest.mark.asyncio
async def test_probe_octoprint_missing_server_key():
    """OctoPrint probe fails when 'server' key is missing."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, {"api": "0.1"})  # Missing 'server'
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = await probe_octoprint("192.168.1.100", ports=[80])

        assert result is None


# ── Single Host Scan Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_single_host_finds_moonraker():
    """Single host scan finds Moonraker."""
    semaphore = asyncio.Semaphore(10)

    with patch("app.onboarding_routes.probe_moonraker", new_callable=AsyncMock) as mock_moon:
        with patch("app.onboarding_routes.probe_octoprint", new_callable=AsyncMock) as mock_octo:
            mock_moon.return_value = "printer-01"
            mock_octo.return_value = None

            results = await scan_single_host("192.168.1.100", semaphore)

            assert len(results) == 1
            assert results[0].ip == "192.168.1.100"
            assert results[0].port == 7125
            assert results[0].protocol == "moonraker"
            assert results[0].name == "printer-01"


@pytest.mark.asyncio
async def test_scan_single_host_finds_octoprint():
    """Single host scan finds OctoPrint."""
    semaphore = asyncio.Semaphore(10)

    with patch("app.onboarding_routes.probe_moonraker", new_callable=AsyncMock) as mock_moon:
        with patch("app.onboarding_routes.probe_octoprint", new_callable=AsyncMock) as mock_octo:
            mock_moon.return_value = None
            mock_octo.return_value = "octoprint"

            results = await scan_single_host("192.168.1.100", semaphore)

            assert len(results) == 1
            assert results[0].ip == "192.168.1.100"
            assert results[0].port == 80
            assert results[0].protocol == "octoprint"
            assert results[0].name == "octoprint"


@pytest.mark.asyncio
async def test_scan_single_host_finds_both():
    """Single host scan finds both Moonraker and OctoPrint."""
    semaphore = asyncio.Semaphore(10)

    with patch("app.onboarding_routes.probe_moonraker", new_callable=AsyncMock) as mock_moon:
        with patch("app.onboarding_routes.probe_octoprint", new_callable=AsyncMock) as mock_octo:
            mock_moon.return_value = "printer-01"
            mock_octo.return_value = "octoprint"

            results = await scan_single_host("192.168.1.100", semaphore)

            assert len(results) == 2
            protocols = {r.protocol for r in results}
            assert "moonraker" in protocols
            assert "octoprint" in protocols


@pytest.mark.asyncio
async def test_scan_single_host_finds_none():
    """Single host scan finds nothing."""
    semaphore = asyncio.Semaphore(10)

    with patch("app.onboarding_routes.probe_moonraker", new_callable=AsyncMock) as mock_moon:
        with patch("app.onboarding_routes.probe_octoprint", new_callable=AsyncMock) as mock_octo:
            mock_moon.return_value = None
            mock_octo.return_value = None

            results = await scan_single_host("192.168.1.100", semaphore)

            assert len(results) == 0


# ── Endpoint Tests (Integration) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_endpoint_auth_required(client):
    """GET /scan requires admin auth."""
    resp = await client.get("/api/onboarding/scan")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_scan_endpoint_admin_only(admin_client):
    """GET /scan runs successfully with admin auth."""
    resp = await admin_client.get("/api/onboarding/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert "scan_capped" in body
    assert isinstance(body["results"], list)
    assert isinstance(body["scan_capped"], bool)


@pytest.mark.asyncio
async def test_scan_endpoint_empty_results(admin_client):
    """GET /scan returns empty results in typical Docker Compose environment."""
    # The real scan may or may not find devices on the test network.
    # We just verify the structure is correct.
    resp = await admin_client.get("/api/onboarding/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_capped"] in (True, False)


@pytest.mark.asyncio
async def test_test_connection_endpoint_auth_required(client):
    """POST /test-connection requires admin auth."""
    resp = await client.post("/api/onboarding/test-connection", json={
        "protocol": "moonraker",
        "base_url": "http://192.168.1.100:7125",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_test_connection_moonraker_success(admin_client, sample_moonraker_response):
    """POST /test-connection succeeds for valid Moonraker."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, sample_moonraker_response)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "moonraker",
            "base_url": "http://192.168.1.100:7125",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "Connected" in body["message"]


@pytest.mark.asyncio
async def test_test_connection_moonraker_404(admin_client):
    """POST /test-connection fails for Moonraker 404."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(404)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "moonraker",
            "base_url": "http://192.168.1.100:7125",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False


@pytest.mark.asyncio
async def test_test_connection_octoprint_success(admin_client, sample_octoprint_response):
    """POST /test-connection succeeds for valid OctoPrint."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, sample_octoprint_response)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "octoprint",
            "base_url": "http://192.168.1.100",
            "api_key": "secret123",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


@pytest.mark.asyncio
async def test_test_connection_octoprint_with_api_key_header(admin_client, sample_octoprint_response):
    """POST /test-connection passes X-Api-Key header for OctoPrint."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = create_mock_response(200, sample_octoprint_response)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "octoprint",
            "base_url": "http://192.168.1.100",
            "api_key": "secretkey123",
        })

        assert resp.status_code == 200
        # Verify the header was passed
        call_args = mock_client.get.call_args
        headers = call_args[1].get("headers", {})
        assert headers.get("X-Api-Key") == "secretkey123"


@pytest.mark.asyncio
async def test_test_connection_unknown_protocol(admin_client):
    """POST /test-connection fails for unknown protocol."""
    resp = await admin_client.post("/api/onboarding/test-connection", json={
        "protocol": "ftp",
        "base_url": "ftp://192.168.1.100",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "Unknown protocol" in body["message"]


@pytest.mark.asyncio
async def test_test_connection_timeout(admin_client):
    """POST /test-connection times out and returns error."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.side_effect = asyncio.TimeoutError()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "moonraker",
            "base_url": "http://192.168.1.100:7125",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "timed out" in body["message"].lower()


@pytest.mark.asyncio
async def test_test_connection_network_error(admin_client):
    """POST /test-connection handles network errors gracefully."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "moonraker",
            "base_url": "http://192.168.1.100:7125",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "error" in body["message"].lower()


@pytest.mark.asyncio
async def test_test_connection_missing_base_url(admin_client):
    """POST /test-connection rejects missing base_url."""
    resp = await admin_client.post("/api/onboarding/test-connection", json={
        "protocol": "moonraker",
    })

    assert resp.status_code in (200, 422)  # 422 if validation fails, 200 if handled gracefully
    if resp.status_code == 200:
        body = resp.json()
        assert body["ok"] is False


@pytest.mark.asyncio
async def test_test_connection_invalid_json_response(admin_client):
    """POST /test-connection handles invalid JSON response."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        resp = await admin_client.post("/api/onboarding/test-connection", json={
            "protocol": "moonraker",
            "base_url": "http://192.168.1.100:7125",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "invalid json" in body["message"].lower()


@pytest.mark.asyncio
async def test_scan_single_host_reports_octoprint_actual_port_5000():
    """BUG-HIGH-ONBOARD-01: a manual/Docker OctoPrint answering ONLY on 5000 (not 80)
    must be reported with port=5000, not a hardcoded 80."""
    semaphore = asyncio.Semaphore(10)

    async def _octo(ip, ports=None, timeout_seconds=0.75):
        # Responds only when probed on 5000 — like a Docker/manual install.
        return "octoprint" if ports == [5000] else None

    with patch("app.onboarding_routes.probe_moonraker", new_callable=AsyncMock) as mock_moon:
        with patch("app.onboarding_routes.probe_octoprint", side_effect=_octo):
            mock_moon.return_value = None
            results = await scan_single_host("192.168.1.100", semaphore)

    assert len(results) == 1
    assert results[0].protocol == "octoprint"
    assert results[0].port == 5000
