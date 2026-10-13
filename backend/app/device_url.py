"""URL policy for operator-configured LAN devices (printers, CNC, MQTT brokers, Spoolman).

app.ssrf.assert_safe_http_url guards INTERNET egress (webhooks, remote downloads)
and rejects RFC1918/loopback by design — keep using it there. Fleet devices are
LAN-resident by definition (DEPLOYMENT.md examples, BAMBU_MQTT.md, onboarding's
/24 scan, MQTTPollingAdapter's own mqtt://localhost default), so that guard
rejects every real device. This policy allows private/loopback/ULA/CGNAT but
still refuses targets that are never a device: cloud metadata, link-local,
multicast, unspecified, reserved. Invalid/unresolvable fails closed.

Blocking (getaddrinfo) — callers on the event loop must offload it.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Metadata services that are NOT covered by the link-local check below.
_METADATA_IPS = frozenset(ipaddress.ip_address(a) for a in (
    "169.254.169.254",  # AWS/GCP/Azure/OpenStack (also link-local; listed for clarity)
    "fd00:ec2::254",    # AWS IMDS over IPv6 (ULA, i.e. "private")
    "100.100.100.200",  # Alibaba Cloud (CGNAT range)
    "192.0.0.192",      # Oracle Cloud legacy
))


def _is_forbidden_device_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    except ValueError:
        return True  # fail closed
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return False  # same-host device (Moonraker on :7125); NB IPv6 ::1 is also is_reserved
    return (
        ip in _METADATA_IPS
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def assert_safe_device_url(url: str) -> None:
    """Raise ValueError unless `url` is http(s) and every resolved address is a
    plausible device address (see module docstring)."""
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
    for *_, sockaddr in infos:
        ip_str = str(sockaddr[0])
        if _is_forbidden_device_ip(ip_str):
            raise ValueError(f"URL resolves to unsafe IP {ip_str}")
