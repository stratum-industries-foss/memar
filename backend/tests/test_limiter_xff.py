"""BUG-HIGH-LIMITER-01: the rate-limit bucket key must not be spoofable via a
client-supplied X-Forwarded-For. XFF is honoured only from a trusted proxy peer, and
then only its RIGHTMOST hop (the real client the proxy appended)."""
import types

from starlette.datastructures import Headers
from app._limiter import _client_key


def _req(peer, xff=None):
    headers = Headers({"X-Forwarded-For": xff} if xff else {})
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=peer))


def test_untrusted_peer_ignores_forwarded(monkeypatch):
    """A direct attacker (non-proxy peer) spoofing XFF is keyed by their real socket
    address — they can't rotate the key to dodge the limiter."""
    monkeypatch.delenv("MEMAR_TRUSTED_PROXIES", raising=False)  # default: loopback only
    assert _client_key(_req("9.9.9.9", xff="1.1.1.1")) == "9.9.9.9"


def test_trusted_proxy_uses_rightmost_hop(monkeypatch):
    """Behind the trusted (loopback) proxy, a client-forged leftmost XFF entry is
    ignored — the real client is the RIGHTMOST hop the proxy appended."""
    monkeypatch.delenv("MEMAR_TRUSTED_PROXIES", raising=False)
    assert _client_key(_req("127.0.0.1", xff="1.1.1.1, 8.8.8.8")) == "8.8.8.8"


def test_trusted_proxy_no_forwarded_falls_back_to_peer(monkeypatch):
    monkeypatch.delenv("MEMAR_TRUSTED_PROXIES", raising=False)
    assert _client_key(_req("127.0.0.1")) == "127.0.0.1"
