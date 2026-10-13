"""Shared slowapi Limiter instance — imported by main.py and any sub-router
that needs rate limiting so they all share the same storage backend."""

import os

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    _DEFAULT_TRUSTED_PROXIES = frozenset({"127.0.0.1", "::1"})

    def _trusted_proxies() -> "frozenset[str]":
        """Proxy socket addresses whose X-Forwarded-For we trust. Defaults to
        loopback (the common 'reverse proxy on the same host' deployment — only a
        same-host origin can present a loopback socket peer, so trusting it by
        default is safe). An operator with a non-loopback proxy sets
        MEMAR_TRUSTED_PROXIES (comma-separated); setting it to an EMPTY string
        trusts NO proxy (every request keyed by its real socket peer)."""
        raw = os.getenv("MEMAR_TRUSTED_PROXIES")
        if raw is None:
            return _DEFAULT_TRUSTED_PROXIES
        return frozenset(p.strip() for p in raw.split(",") if p.strip())

    def _client_key(request) -> str:
        """Rate-limit bucket key, resistant to X-Forwarded-For spoofing.

        X-Forwarded-For is client-controllable, so it is honoured ONLY when the
        request's socket peer is a trusted proxy. Even then we take the RIGHTMOST
        hop — the address the trusted proxy itself appended (the real client as the
        proxy saw it) — never the leftmost, which a client can forge (a well-behaved
        proxy APPENDS to XFF, so client-supplied values sit on the left). When the
        peer is not a trusted proxy, the socket address is authoritative and XFF is
        ignored. Assumes a SINGLE trusted proxy hop; front multi-proxy chains with
        one address in MEMAR_TRUSTED_PROXIES."""
        peer = get_remote_address(request)
        if peer in _trusted_proxies():
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                hops = [h.strip() for h in forwarded.split(",") if h.strip()]
                if hops:
                    return hops[-1]
        return peer

    limiter: "Limiter | None" = Limiter(key_func=_client_key)
except ImportError:
    limiter = None


def rate_limit(rule: str):
    """Returns a slowapi rate-limit decorator when available, else a no-op."""
    if limiter is not None:
        return limiter.limit(rule)

    def _noop(fn):
        return fn

    return _noop
