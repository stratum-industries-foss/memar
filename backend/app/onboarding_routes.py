"""Onboarding routes for MEMAR fleet discovery and device connection testing.

Provides LAN scanning to discover Moonraker and OctoPrint instances, and connection
testing for manual device onboarding. Contract: docs/internal/FIRSTRUN_CONTRACT.md.

Scan strategy: a TCP connect sweep over every host in the subnet on ports
7125-7144 (Moonraker, KIAUH multi-instance) plus 80/5000 (OctoPrint), then HTTP
identification only on the ports that accepted a connection. The whole scan runs
under a wall-clock budget; if the budget is hit, partial results are returned
with scan_capped=True.
"""

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .config import get_config, get_config_path
from .deps import require_role
from .device_url import RFC1918_NETWORKS, assert_lan_device_url, is_lan_device_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

MOONRAKER_PORTS: tuple[int, ...] = tuple(range(7125, 7145))
_MOONRAKER_PORT_SET = frozenset(MOONRAKER_PORTS)
OCTOPRINT_PORTS: tuple[int, ...] = (80, 5000)
_OCTOPRINT_PORT_SET = frozenset(OCTOPRINT_PORTS)

SCAN_BUDGET_S = 13.0          # whole scan, wall clock (contract: bounded ≤ 15 s)
SWEEP_BUDGET_FRACTION = 0.6   # share of the budget the TCP sweep may use
SWEEP_TIMEOUT_S = 0.3
SWEEP_CONCURRENCY = 512
PROBE_TIMEOUT_S = 0.75
HTTP_CONCURRENCY = 40


# ── Pydantic Models ───────────────────────────────────────────────────────────


class DeviceFound(BaseModel):
    """A device discovered during LAN scan."""
    ip: str
    port: int
    protocol: str
    name: Optional[str] = None
    already_added: bool = False
    suggested_id: str = ""


class ScanResponse(BaseModel):
    """Response from LAN scan endpoint."""
    results: list[DeviceFound]
    scan_capped: bool
    subnet: str = ""
    subnet_source: str = "fallback"  # detected | fallback | user
    in_container: bool = False
    duration_ms: int = 0


class TestConnectionRequest(BaseModel):
    """Request to test connection to a device."""
    protocol: str
    base_url: str
    api_key: Optional[str] = None


class TestConnectionResponse(BaseModel):
    """Response from connection test. `success` is an alias of `ok`."""
    ok: bool
    success: bool
    message: str
    name: Optional[str] = None


def _tc(ok: bool, message: str, name: Optional[str] = None) -> TestConnectionResponse:
    return TestConnectionResponse(ok=ok, success=ok, message=message, name=name)


# ── Subnet helpers ────────────────────────────────────────────────────────────


def validate_subnet(raw: str) -> ipaddress.IPv4Network:
    """Parse a user-supplied subnet. Must be private IPv4 with prefix /22–/30."""
    try:
        net = ipaddress.IPv4Network(raw.strip(), strict=False)
    except ValueError as e:
        raise ValueError("subnet must be an IPv4 CIDR such as 192.168.1.0/24") from e
    if not 22 <= net.prefixlen <= 30:
        raise ValueError(f"subnet prefix must be between /22 and /30, got /{net.prefixlen}")
    if not any(net.subnet_of(private) for private in RFC1918_NETWORKS):
        raise ValueError(f"subnet {net} is not private; use 10/8, 172.16/12 or 192.168/16")
    return net


def _in_container() -> bool:
    """True when running inside Docker/containerd (the detected subnet is then the container network)."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "docker" in cgroup or "containerd" in cgroup


def _detect_subnet() -> tuple[str, str]:
    """Return (subnet, source) where source is 'detected' or 'fallback'.

    Detection uses the UDP connect trick to learn the outbound interface address.
    A public outbound address is never scanned: it falls back.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packets are sent for a UDP connect
            outbound_ip = s.getsockname()[0]
        if outbound_ip.startswith("127."):
            raise ValueError("got localhost IP")
        if not is_lan_device_ip(outbound_ip) or ipaddress.ip_address(outbound_ip) in ipaddress.IPv4Network("100.64.0.0/10"):
            raise ValueError(f"outbound address {outbound_ip} is not private")
        return str(ipaddress.IPv4Network(f"{outbound_ip}/24", strict=False)), "detected"
    except Exception as e:
        logger.warning(f"Failed to derive subnet via UDP trick: {e}. Using fallback.")

    # ONBOARD-SUBNET-FALLBACK-01: no reliable single guess exists; configurable.
    default = "192.168.1.0/24"
    configured = os.getenv("MEMAR_LAN_SUBNET_FALLBACK", default)
    try:
        return str(validate_subnet(configured)), "fallback"
    except ValueError as e:
        logger.warning(f"Ignoring invalid MEMAR_LAN_SUBNET_FALLBACK={configured!r}: {e}")
        return default, "fallback"


def get_local_subnet() -> str:
    """Derive the server's local subnet /24 (see _detect_subnet)."""
    return _detect_subnet()[0]


# ── Probes ────────────────────────────────────────────────────────────────────


def _hostport(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _host_port_of(base_url: str) -> tuple[str, int]:
    """(hostname, port) of a base_url; port defaults to 80/443 by scheme."""
    try:
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "", 0
    return host, port


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_remote_name(value) -> str:
    """A name supplied by another device is untrusted: text only, no control
    characters, at most 64 characters. Anything else becomes empty."""
    if not isinstance(value, str):
        return ""
    return _CONTROL_RE.sub("", value).strip()[:64]


async def _fetch_moonraker_hostname(client: httpx.AsyncClient, base: str) -> Optional[str]:
    """Moonraker /printer/info hostname, or None. Best effort; never raises."""
    try:
        resp = await client.get(f"{base}/printer/info", follow_redirects=False)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and isinstance(data.get("result"), dict):
                host = data["result"].get("hostname")
                if host and str(host).strip():
                    return str(host).strip()
    except Exception:
        pass
    return None


# Names people give printers in the Klipper web UIs, stored in Moonraker's database.
_UI_NAME_KEYS = (
    ("mainsail", "general.printername"),
    ("fluidd", "uiSettings.general.instanceName"),
)


async def _fetch_moonraker_ui_name(client: httpx.AsyncClient, base: str) -> Optional[str]:
    """Printer name set in Mainsail or Fluidd, or None. Best effort; never raises."""
    for namespace, key in _UI_NAME_KEYS:
        try:
            resp = await client.get(
                f"{base}/server/database/item",
                params={"namespace": namespace, "key": key},
                follow_redirects=False,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            value = data.get("result", {}).get("value") if isinstance(data, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()[:64]
        except Exception:
            continue
    return None


async def _fetch_octoprint_profile_name(
    client: httpx.AsyncClient, base: str, headers: dict
) -> Optional[str]:
    """OctoPrint current printer-profile name from /api/printerprofiles, or None."""
    try:
        resp = await client.get(f"{base}/api/printerprofiles", headers=headers, follow_redirects=False)
        if resp.status_code != 200:
            return None
        data = resp.json()
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            return None
        chosen = next(
            (p for p in profiles.values() if isinstance(p, dict) and p.get("current")),
            None,
        )
        if chosen is None and isinstance(profiles.get("_default"), dict):
            chosen = profiles["_default"]
        name = str(chosen.get("name") or "").strip() if chosen else ""
        return name or None
    except Exception:
        return None


async def probe_moonraker(
    ip: str,
    port: int = 7125,
    timeout_seconds: float = PROBE_TIMEOUT_S,
) -> Optional[str]:
    """
    Identify a Moonraker instance at ip:port via /server/info.

    Returns the host name from /printer/info ("" when the instance reports none),
    or None if the port is not a Moonraker instance.
    """
    base = f"http://{ip}:{port}"
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.get(f"{base}/server/info", follow_redirects=False)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if not (isinstance(data, dict) and "result" in data):
                    return None
                hostname = await _fetch_moonraker_ui_name(client, base)
                if not hostname:
                    hostname = await _fetch_moonraker_hostname(client, base)
                if not hostname and isinstance(data["result"], dict):
                    hostname = data["result"].get("hostname")
                return _clean_remote_name(hostname)
    except Exception:
        return None


async def probe_octoprint(
    ip: str,
    ports: list[int] = None,
    timeout_seconds: float = PROBE_TIMEOUT_S,
) -> Optional[str]:
    """
    Probe for OctoPrint instance at ip:port (tries /api/version).
    Returns "octoprint" if successful, None otherwise.
    """
    if ports is None:
        ports = list(OCTOPRINT_PORTS)

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


async def _octoprint_profile_name(ip: str, port: int) -> Optional[str]:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
                return await _fetch_octoprint_profile_name(client, f"http://{ip}:{port}", {})
    except Exception:
        return None


async def scan_single_host(
    ip: str,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float = PROBE_TIMEOUT_S,
    moonraker_ports: Optional[list[int]] = None,
    octoprint_ports: Optional[list[int]] = None,
) -> list[DeviceFound]:
    """
    HTTP-identify Moonraker and OctoPrint on the given ports of one host.

    Defaults: Moonraker on 7125 only, OctoPrint on 80 and 5000. The full scan
    passes only the ports that accepted a TCP connect. Names are raw here
    (Moonraker hostname or None); scan_network applies the final naming.
    """
    mports = (7125,) if moonraker_ports is None else tuple(moonraker_ports)
    oports = OCTOPRINT_PORTS if octoprint_ports is None else tuple(octoprint_ports)

    async with semaphore:
        results: list[DeviceFound] = []

        # Probe the ports of this host concurrently; order of results is preserved.
        moon_names = await asyncio.gather(
            *(probe_moonraker(ip, port=mport, timeout_seconds=timeout_seconds) for mport in mports)
        )
        for mport, name in zip(mports, moon_names):
            if name is not None:
                results.append(DeviceFound(ip=ip, port=mport, protocol="moonraker", name=name or None))

        # One OctoPrint entry per host: the first answering port (80 before 5000).
        octo_found = await asyncio.gather(
            *(probe_octoprint(ip, ports=[oport], timeout_seconds=timeout_seconds) for oport in oports)
        )
        for oport, found in zip(oports, octo_found):
            if found:
                results.append(DeviceFound(ip=ip, port=oport, protocol="octoprint", name=None))
                break

        return results


# ── Scan orchestration ────────────────────────────────────────────────────────


async def _tcp_open(ip: str, port: int, timeout_seconds: float) -> bool:
    writer = None
    try:
        async with asyncio.timeout(timeout_seconds):
            _, writer = await asyncio.open_connection(ip, port)
        return True
    except Exception:
        return False
    finally:
        if writer is not None:
            writer.close()


async def _gather_within(tasks: Sequence[asyncio.Future], deadline: float) -> tuple[list[asyncio.Future], bool]:
    """Wait for tasks until the loop-time deadline. Returns (done, capped)."""
    if not tasks:
        return [], False
    loop = asyncio.get_running_loop()
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - loop.time()))
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return list(done), bool(pending)


_scan_lock = asyncio.Lock()


async def _run_scan(network: ipaddress.IPv4Network, budget_s: float = SCAN_BUDGET_S) -> tuple[list[DeviceFound], bool]:
    """TCP sweep then HTTP identification, both under the budget. Returns (results, capped)."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    sweep_deadline = start + budget_s * SWEEP_BUDGET_FRACTION
    scan_deadline = start + budget_s

    hosts = [str(h) for h in network.hosts()]

    # Phase 1: TCP connect sweep. Port-major order so that if the budget is hit,
    # every host has already been checked on 7125 (the common case).
    open_ports: dict[str, set[int]] = {}
    sweep_sem = asyncio.Semaphore(SWEEP_CONCURRENCY)

    async def _check(ip: str, port: int) -> None:
        async with sweep_sem:
            if await _tcp_open(ip, port, SWEEP_TIMEOUT_S):
                open_ports.setdefault(ip, set()).add(port)

    sweep_ports = [7125, *OCTOPRINT_PORTS, *MOONRAKER_PORTS[1:]]
    sweep_tasks = [asyncio.ensure_future(_check(ip, p)) for p in sweep_ports for ip in hosts]
    _, sweep_capped = await _gather_within(sweep_tasks, sweep_deadline)

    # Phase 2: HTTP identification on open ports only.
    http_sem = asyncio.Semaphore(HTTP_CONCURRENCY)
    http_tasks = []
    for ip in sorted(open_ports, key=ipaddress.ip_address):
        ports = open_ports[ip]
        http_tasks.append(asyncio.ensure_future(scan_single_host(
            ip,
            http_sem,
            timeout_seconds=PROBE_TIMEOUT_S,
            moonraker_ports=sorted(p for p in ports if p in _MOONRAKER_PORT_SET),
            octoprint_ports=sorted(p for p in ports if p in _OCTOPRINT_PORT_SET),
        )))
    done, http_capped = await _gather_within(http_tasks, scan_deadline)

    results: list[DeviceFound] = []
    for task in done:
        if task.cancelled() or task.exception() is not None:
            logger.debug("Scan host task failed or cancelled")
            continue
        results.extend(task.result())
    return results, sweep_capped or http_capped


def _configured_printers() -> tuple[list[tuple[str, int]], set[str]]:
    """Configured (host, port) endpoints and printer ids. Never triggers config generation."""
    endpoints: list[tuple[str, int]] = []
    ids: set[str] = set()
    try:
        if not get_config_path().exists():
            return endpoints, ids
        cfg = get_config()
    except Exception as e:
        logger.debug(f"Could not read configured printers: {e}")
        return endpoints, ids
    for printer in cfg.printers:
        ids.add(printer.id)
        host, port = _host_port_of(printer.base_url)
        if host:
            endpoints.append((host, port))
    return endpoints, ids


def slugify_id(text: str) -> str:
    """Lowercase slug for a printer id: [a-z0-9-], max 48 chars, never empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    return slug or "printer"


def unique_printer_id(text: str, taken: set[str]) -> str:
    """Slugify `text` and suffix -2, -3, ... until it is not in `taken`.

    The chosen id is added to `taken` so that repeated calls stay unique.
    """
    base = slugify_id(text)
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


async def _finalize(
    results: list[DeviceFound],
    configured_endpoints: list[tuple[str, int]],
    configured_ids: set[str],
) -> list[DeviceFound]:
    """Apply final names, already_added and suggested_id."""
    results = sorted(results, key=lambda x: (ipaddress.ip_address(x.ip), x.port, x.protocol))

    # Same name on one host (KIAUH instances all report the OS hostname): add the port.
    # Names set in Mainsail/Fluidd are usually distinct and are kept as they are.
    name_count = Counter((r.ip, r.name) for r in results if r.protocol == "moonraker" and r.name)
    for r in results:
        if r.protocol == "moonraker":
            if r.name and name_count[(r.ip, r.name)] > 1:
                r.name = f"{r.name}:{r.port}"
            elif not r.name:
                r.name = f"Klipper {_hostport(r.ip, r.port)}"

    octo = [r for r in results if r.protocol == "octoprint"]
    octo_names = await asyncio.gather(*(_octoprint_profile_name(r.ip, r.port) for r in octo))
    for r, name in zip(octo, octo_names):
        r.name = name or f"OctoPrint {_hostport(r.ip, r.port)}"

    taken = set(configured_ids)
    for r in results:
        r.already_added = any(h == r.ip.lower() and p == r.port for h, p in configured_endpoints)
        prefix = "klipper" if r.protocol == "moonraker" else "octoprint"
        r.suggested_id = unique_printer_id(f"{prefix}-{r.ip}-{r.port}", taken)
    return results


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/scan",
    response_model=ScanResponse,
    dependencies=[Depends(require_role("admin"))],
    summary="Scan local network for printers",
    description=(
        "Scan a private IPv4 subnet (detected, configured or given as `subnet`, /22–/30) for "
        "Moonraker (every port 7125–7144) and OctoPrint (80, 5000). Bounded to ~13 s; "
        "scan_capped=true when partial."
    ),
)
async def scan_network(
    subnet: Optional[str] = Query(
        default=None,
        max_length=64,
        description="Private IPv4 CIDR to scan, /22–/30. Omit to auto-detect.",
    ),
) -> ScanResponse:
    if _scan_lock.locked():
        raise HTTPException(status_code=429, detail="A network scan is already running. Wait for it to finish.")
    async with _scan_lock:
        return await _scan_network_locked(subnet)


async def _scan_network_locked(subnet: Optional[str]) -> ScanResponse:
    started = time.monotonic()

    if subnet is not None and subnet.strip():
        try:
            network = validate_subnet(subnet)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        subnet_str, source = str(network), "user"
    else:
        subnet_str, source = _detect_subnet()
        network = ipaddress.IPv4Network(subnet_str)

    results, capped = await _run_scan(network)
    configured_endpoints, configured_ids = _configured_printers()
    results = await _finalize(results, configured_endpoints, configured_ids)

    return ScanResponse(
        results=results,
        scan_capped=capped,
        subnet=subnet_str,
        subnet_source=source,
        in_container=_in_container(),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


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

    Enforces 5s timeout. Target must be private RFC1918, loopback or IPv6 ULA.
    - Moonraker: GET {base_url}/server/info (unauthenticated), expects 200+valid JSON
    - OctoPrint: GET {base_url}/api/version with X-Api-Key header (if provided), expects 200+valid JSON

    Returns {ok, success, message, name}. `success` is an alias of `ok`.
    """
    protocol = request.protocol.lower().strip()
    base_url = request.base_url.strip()
    api_key = request.api_key

    if not base_url:
        return _tc(False, "base_url is required")

    # Cheap request-shape check first: no DNS work for a request we will reject anyway.
    if protocol not in ("moonraker", "octoprint"):
        return _tc(False, f"Unknown protocol: {protocol}")

    # Blocking DNS → thread.
    try:
        await asyncio.to_thread(assert_lan_device_url, base_url)
    except ValueError as e:
        return _tc(False, f"URL validation failed: {e}")

    base = base_url.rstrip("/")
    host, port = _host_port_of(base)
    hostport = _hostport(host, port)

    try:
        async with asyncio.timeout(5.0):
            async with httpx.AsyncClient(timeout=5.0) as client:
                if protocol == "moonraker":
                    url = f"{base}/server/info"
                    try:
                        resp = await client.get(url, follow_redirects=False)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict) and "result" in data:
                                    name = await _fetch_moonraker_hostname(client, base)
                                    return _tc(True, "Connected", name or f"Klipper {hostport}")
                            except json.JSONDecodeError:
                                return _tc(False, "Moonraker responded with invalid JSON")
                        return _tc(False, f"Moonraker returned {resp.status_code}")
                    except httpx.RequestError as e:
                        return _tc(False, f"Request error: {str(e)}")

                else:  # octoprint
                    url = f"{base}/api/version"
                    headers = {}
                    if api_key:
                        headers["X-Api-Key"] = api_key

                    try:
                        resp = await client.get(url, headers=headers, follow_redirects=False)
                        if resp.status_code == 200:
                            try:
                                data = resp.json()
                                if isinstance(data, dict) and "server" in data:
                                    name = await _fetch_octoprint_profile_name(client, base, headers)
                                    return _tc(True, "Connected", name or f"OctoPrint {hostport}")
                            except json.JSONDecodeError:
                                return _tc(False, "OctoPrint responded with invalid JSON")
                        return _tc(False, f"OctoPrint returned {resp.status_code}")
                    except httpx.RequestError as e:
                        return _tc(False, f"Request error: {str(e)}")

    except asyncio.TimeoutError:
        return _tc(False, "Connection test timed out (5s)")
    except Exception as e:
        return _tc(False, f"Error: {str(e)}")
