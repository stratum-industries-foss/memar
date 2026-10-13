"""SSRF protection: IP pinning and URL validation for outbound HTTP."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _is_unsafe_ip(ip_str: str) -> bool:
    """Return True if IP is private, loopback, link-local, or metadata.
    
    Also covers multicast, reserved, and unspecified addresses. Invalid IPs
    are treated as unsafe (fail closed).
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Invalid IP = unsafe
    
    # AWS/GCP/Azure metadata endpoint
    if ip_str == "169.254.169.254":
        return True
    
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global  # e.g. 100.64.0.0/10 (CGNAT/tailnets, Alibaba metadata)
    )


def assert_safe_http_url(url: str) -> None:
    """Raise ValueError if URL scheme is not http(s) or resolves to unsafe IP.
    
    Synchronous blocking call — callers on the event loop must offload to an
    executor.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")
    
    # Resolve and check all IPs
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname {host}: {e}")
    
    if not infos:
        raise ValueError(f"Cannot resolve hostname {host}")
    
    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_unsafe_ip(ip_str):
            raise ValueError(f"URL resolves to unsafe IP {ip_str}")


def resolve_public_ip(host: str) -> str:
    """Resolve `host` to a single concrete IP, rejecting any disallowed address.

    Returns the pinned IP string. Raises HTTPException(400) if the host is empty,
    fails to resolve, or resolves to (any) loopback/link-local/private/reserved
    address. Rejecting when *any* returned address is unsafe (rather than just
    the one we pin) preserves fail-closed semantics against resolver ordering
    tricks. Blocking (getaddrinfo) — callers on the event loop must offload it.
    """
    if not host:
        raise HTTPException(status_code=400, detail="Webhook URL must have a host")
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    try:
        addrs = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=400, detail=f"Webhook host does not resolve: {host}"
        )
    if not addrs:
        raise HTTPException(
            status_code=400, detail=f"Webhook host does not resolve: {host}"
        )
    resolved = [sockaddr[0] for *_rest, sockaddr in addrs]
    for ip_str in resolved:
        if _is_unsafe_ip(ip_str):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Webhook URL resolves to a disallowed address ({ip_str}); "
                    "loopback, link-local, and private-network targets are not permitted"
                ),
            )
    # Literal already validated as itself; otherwise pin the first resolved IP.
    return host if is_literal else resolved[0]


class PinnedResolveTransport(httpx.AsyncHTTPTransport):
    """SSRF-hardened transport that closes the DNS-rebinding TOCTOU window.

    For every request it resolves the URL host ONCE, validates the resulting IP
    is public, then rewrites the request to connect to that pinned IP — so there
    is no second, independent DNS lookup between check and connect. The original
    hostname is preserved for the ``Host`` header (already built by httpx before
    the transport runs), for TLS SNI, and hence for certificate verification via
    the ``sni_hostname`` request extension, so HTTPS to legitimate public
    endpoints still verifies correctly.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        loop = asyncio.get_event_loop()
        pinned_ip = await loop.run_in_executor(None, resolve_public_ip, host)
        if pinned_ip != host:
            ext = dict(request.extensions)
            ext.setdefault("sni_hostname", host)
            request.extensions = ext
            request.url = request.url.copy_with(host=pinned_ip)
        return await super().handle_async_request(request)


# Backward compatibility aliases for webhooks.py
_is_unsafe_webhook_ip = _is_unsafe_ip
_resolve_public_ip = resolve_public_ip
