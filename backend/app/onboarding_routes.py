"""Onboarding routes for MEMAR fleet discovery and device connection testing.

Provides LAN scanning to discover Moonraker and OctoPrint instances, and connection
testing for manual device onboarding.
"""

import asyncio
import ipaddress
import json
import logging
import os
import socket
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .deps import require_role
from .device_url import assert_safe_device_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ── Pydantic Models ───────────────────────────────────────────────────────────


class DeviceFound(BaseModel):
    """A device discovered during LAN scan."""
    ip: str
    port: int
    protocol: str
    name: Optional[str] = None


class ScanResponse(BaseModel):
    """Response from LAN scan endpoint."""
    results: list[DeviceFound]
    scan_capped: bool


class TestConnectionRequest(BaseModel):
    """Request to test connection to a device."""
    protocol: str
    base_url: str
    api_key: Optional[str] = None


class TestConnectionResponse(BaseModel):
    """Response from connection test."""
    ok: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_local_subnet() -> str:
    """
    Derive the server's local subnet /24 using a UDP trick.
    Falls back to common home/lab subnets if the trick fails.

    Returns:
        A /24 subnet string like "192.168.1.0/24"
    """
    try:
        # UDP trick: connect to a public IP to learn our outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        outbound_ip = s.getsockname()[0]
        s.close()

        # Validate it's not localhost
        if outbound_ip.startswith("127."):
            raise ValueError("Got localhost IP")

        # Mask to /24
        ip_obj = ipaddress.IPv4Address(outbound_ip)
        network = ipaddress.IPv4Network(f"{outbound_ip}/24", strict=False)
        return str(network)
    except Exception as e:
        logger.warning(f"Failed to derive subnet via UDP trick: {e}. Using fallback.")
        # ONBOARD-SUBNET-FALLBACK-01: the UDP-trick failure mode (multi-NIC
        # hosts, restricted network namespaces, IPv6-only egress) has no
        # reliable single guess. 192.168.1.0/24 is the most common home
        # default but is silently WRONG for plenty of real deployments
        # (10.x, 192.168.50.x, ...) — an operator on one of those gets a scan
        # that always finds nothing, with no way to correct it. Configurable,
        # same default as before.
        return os.getenv("MEMAR_LAN_SUBNET_FALLBACK", "192.168.1.0/24")


async def probe_moonraker(
    ip: str,
    port: int = 7125,
    timeout_seconds: float = 0.75,
) -> Optional[str]:
    """
    Probe for Moonraker instance at ip:port.
    Returns the name extracted from /server/info if successful, None otherwise.
    """
    url = f"http://{ip}:{port}/server/info"
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.get(url, follow_redirects=False)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and "result" in data:
                        # Extract friendly name if available
                        result = data.get("result", {})
                        hostname = result.get("hostname", result.get("system_info", {}).get("hostname"))
                        return hostname or "moonraker"
    except Exception:
        pass
    return None


async def probe_octoprint(
    ip: str,
    ports: list[int] = None,
    timeout_seconds: float = 0.75,
) -> Optional[str]:
    """
    Probe for OctoPrint instance at ip:port (tries /api/version).
    Returns "octoprint" if successful, None otherwise.
    """
    if ports is None:
        ports = [80, 5000]

    for port in ports:
        url = f"http://{ip}:{port}/api/version"
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    resp = await client.get(url, follow_redirects=False)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and "server" in data:
                            return "octoprint"
        except Exception:
            pass
    return None


async def scan_single_host(
    ip: str,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float = 0.75,
) -> list[DeviceFound]:
    """
    Scan a single host for Moonraker and OctoPrint.
    Runs under a semaphore to enforce concurrency limits.
    """
    async with semaphore:
        results = []

        # Try Moonraker on 7125
        moonraker_name = await probe_moonraker(ip, port=7125, timeout_seconds=timeout_seconds)
        if moonraker_name:
            results.append(DeviceFound(ip=ip, port=7125, protocol="moonraker", name=moonraker_name))

        # Try OctoPrint on 80 then 5000, recording WHICH port actually answers.
        # OctoPi answers on 80; manual/Docker installs commonly answer on 5000.
        # (The old code hardcoded port=80 regardless — BUG-HIGH-ONBOARD-01.)
        for octo_port in (80, 5000):
            octoprint_name = await probe_octoprint(ip, ports=[octo_port], timeout_seconds=timeout_seconds)
            if octoprint_name:
                results.append(DeviceFound(ip=ip, port=octo_port, protocol="octoprint", name=octoprint_name))
                break

        return results


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/scan",
    response_model=ScanResponse,
    dependencies=[Depends(require_role("admin"))],
    summary="Scan local network for printers",
    description="Scan the local /24 subnet for Moonraker and OctoPrint instances. Returns results even if scan is capped at 8s.",
)
async def scan_network() -> ScanResponse:
    """
    Scan the local subnet for Moonraker (7125) and OctoPrint (80/5000) instances.

    Uses asyncio.Semaphore(40) to limit concurrency and 750ms per-probe timeout.
    Hard wall-clock cap of 8s — if cap is hit, returns partial results with scan_capped=True.

    Returns a list of discovered devices with their protocol and friendly names.
    Returns empty list if no devices found (expected on Docker Compose default bridge networking).
    """
    subnet_str = get_local_subnet()
    try:
        network = ipaddress.IPv4Network(subnet_str)
    except ValueError:
        logger.error(f"Invalid subnet {subnet_str}")
        return ScanResponse(results=[], scan_capped=False)

    # Get all usable hosts (exclude network and broadcast)
    hosts = [str(ip) for ip in network.hosts()]
    if not hosts:
        # Fallback for /31 or other edge cases
        hosts = [str(ip) for ip in network.addresses() if str(ip) not in (str(network.network_address), str(network.broadcast_address))]

    semaphore = asyncio.Semaphore(40)

    # Scan all hosts with an 8s hard wall-clock cap. Use asyncio.wait (not
    # wait_for+gather) so that on timeout we can still read results from
    # whichever tasks already finished, instead of cancelling everything and
    # re-running a fresh (unstarted) batch against an impossibly short deadline.
    scan_tasks = [asyncio.ensure_future(scan_single_host(host, semaphore, timeout_seconds=0.75)) for host in hosts]
    done, pending = await asyncio.wait(scan_tasks, timeout=8.0)

    scan_capped = bool(pending)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    all_results = []
    for task in done:
        try:
            result = task.result()
        except Exception as exc:
            logger.debug(f"Scan task failed: {exc}")
            continue
        if isinstance(result, list):
            all_results.extend(result)

    return ScanResponse(results=all_results, scan_capped=scan_capped)


@router.post(
    "/test-connection",
    response_model=TestConnectionResponse,
    dependencies=[Depends(require_role("admin"))],
    summary="Test connection to a device",
    description="Validate that a device (Moonraker or OctoPrint) is reachable and responding.",
)
async def test_connection(request: TestConnectionRequest) -> TestConnectionResponse:
    """
    Test connection to a device (Moonraker or OctoPrint).

    Enforces 5s timeout. Protocol-specific validation:
    - Moonraker: GET {base_url}/server/info (unauthenticated), expects 200+valid JSON
    - OctoPrint: GET {base_url}/api/version with X-Api-Key header (if provided), expects 200+valid JSON

    Returns {ok: bool, message: str}.
    """
    protocol = request.protocol.lower().strip()
    base_url = request.base_url.strip()
    api_key = request.api_key

    if not base_url:
        return TestConnectionResponse(ok=False, message="base_url is required")

    # Cheap request-shape check first: no DNS work for a request we will reject anyway.
    if protocol not in ("moonraker", "octoprint"):
        return TestConnectionResponse(ok=False, message=f"Unknown protocol: {protocol}")

    # Devices live on the LAN (this router's own /scan returns RFC1918 hosts), so use
    # the device policy, not the internet-egress SSRF guard. Blocking DNS → thread.
    try:
        await asyncio.to_thread(assert_safe_device_url, base_url)
    except ValueError as e:
        return TestConnectionResponse(ok=False, message=f"URL validation failed: {e}")

    try:
        async with asyncio.timeout(5.0):
            async with httpx.AsyncClient(timeout=5.0) as client:
                if protocol == "moonraker":
                    url = f"{base_url}/server/info"
                    try:
                        resp = await client.get(url, follow_redirects=False)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict) and "result" in data:
                                    return TestConnectionResponse(ok=True, message="Connected")
                            except json.JSONDecodeError:
                                return TestConnectionResponse(ok=False, message="Moonraker responded with invalid JSON")
                        return TestConnectionResponse(ok=False, message=f"Moonraker returned {resp.status_code}")
                    except httpx.RequestError as e:
                        return TestConnectionResponse(ok=False, message=f"Request error: {str(e)}")

                elif protocol == "octoprint":
                    url = f"{base_url}/api/version"
                    headers = {}
                    if api_key:
                        headers["X-Api-Key"] = api_key

                    try:
                        resp = await client.get(url, headers=headers, follow_redirects=False)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict) and "server" in data:
                                    return TestConnectionResponse(ok=True, message="Connected")
                            except json.JSONDecodeError:
                                return TestConnectionResponse(ok=False, message="OctoPrint responded with invalid JSON")
                        return TestConnectionResponse(ok=False, message=f"OctoPrint returned {resp.status_code}")
                    except httpx.RequestError as e:
                        return TestConnectionResponse(ok=False, message=f"Request error: {str(e)}")

                else:
                    return TestConnectionResponse(ok=False, message=f"Unknown protocol: {protocol}")

    except asyncio.TimeoutError:
        return TestConnectionResponse(ok=False, message="Connection test timed out (5s)")
    except Exception as e:
        return TestConnectionResponse(ok=False, message=f"Error: {str(e)}")
