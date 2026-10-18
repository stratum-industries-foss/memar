"""URL policy for operator-configured LAN devices (printers, CNC, MQTT brokers, Spoolman).

app.ssrf.assert_safe_http_url guards INTERNET egress (webhooks, remote downloads)
and rejects RFC1918/loopback by design — keep using it there. Fleet devices are
LAN-resident by definition (DEPLOYMENT.md examples, BAMBU_MQTT.md, onboarding's
/24 scan, MQTTPollingAdapter's own mqtt://localhost default), so that guard
rejects every real device. This policy allows private/loopback/ULA/CGNAT but
still refuses targets that are never a device: cloud metadata, link-local,
multicast, unspecified, reserved. Invalid/unresolvable fails closed.

Onboarding (LAN scan and test-connection) is stricter: assert_lan_device_url
additionally refuses any address that is not RFC1918, loopback, or IPv6 ULA.

Blocking (getaddrinfo) — callers on the event loop must offload it.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

# Metadata services that are NOT covered by the link-local check below.
_METADATA_IPS = frozenset(ipaddress.ip_address(a) for a in (
    "169.254.169.254",  # AWS/GCP/Azure/OpenStack (also link-local; listed for clarity)
    "fd00:ec2::254",    # AWS IMDS over IPv6 (ULA, i.e. "private")
    "100.100.100.200",  # Alibaba Cloud (CGNAT range)
    "192.0.0.192",      # Oracle Cloud legacy
))

# Onboarding allow-list: the only non-loopback ranges a LAN device may live in.
RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_LAN_IPV6_NETWORKS = (ipaddress.IPv6Network("fc00::/7"),)  # ULA
# RFC 6598 shared space: Tailscale/Headscale and carrier-grade NAT. Allowed for a
# single device (test-connection) but never scanned.
_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")


def _parse_ip(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse an address string; strips zone ids and unwraps IPv4-mapped IPv6."""
    ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def _is_forbidden_device_ip(ip_str: str) -> bool:
    try:
        ip = _parse_ip(ip_str)
    except ValueError:
        return True  # fail closed
    if ip.is_loopback:
        return False  # same-host device (Moonraker on :7125); NB IPv6 ::1 is also is_reserved
    return (
        ip in _METADATA_IPS
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def is_lan_device_ip(ip_str: str) -> bool:
    """True for RFC1918 IPv4, loopback, or IPv6 ULA/loopback addresses only."""
    try:
        ip = _parse_ip(ip_str)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        return any(ip in net for net in RFC1918_NETWORKS) or ip in _CGNAT_NETWORK
    return any(ip in net for net in _LAN_IPV6_NETWORKS)


def _public_devices_allowed() -> bool:
    """MEMAR_ALLOW_PUBLIC_DEVICES=true: a hosted MEMAR that reaches machines through
    public addresses (port forwards). Metadata/link-local blocks still apply."""
    return os.getenv("MEMAR_ALLOW_PUBLIC_DEVICES", "").strip().lower() in ("1", "true", "yes")


def _check_scheme_and_resolve(url: str) -> list[str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname {host}: {e}") from e
    if not infos:
        raise ValueError(f"Cannot resolve hostname {host}")
    return [str(sockaddr[0]) for *_, sockaddr in infos]


def assert_safe_device_url(url: str) -> None:
    """Raise ValueError unless `url` is http(s) and every resolved address is a
    plausible device address (see module docstring)."""
    for ip_str in _check_scheme_and_resolve(url):
        if _is_forbidden_device_ip(ip_str):
            raise ValueError(f"URL resolves to unsafe IP {ip_str}")


def assert_lan_device_url(url: str) -> None:
    """Stricter policy for onboarding targets: every resolved address must be
    RFC1918, loopback, or IPv6 ULA (in addition to assert_safe_device_url's checks).
    Public addresses are rejected with an explicit message."""
    assert_safe_device_url(url)
    if _public_devices_allowed():
        return
    for ip_str in _check_scheme_and_resolve(url):
        if not is_lan_device_ip(ip_str):
            raise ValueError(
                f"URL resolves to {ip_str}, which is not a private LAN, loopback or IPv6 ULA "
                "address. Public addresses are off by default; set MEMAR_ALLOW_PUBLIC_DEVICES=true "
                "to allow them"
            )
