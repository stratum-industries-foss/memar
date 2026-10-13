"""Device URL policy: LAN devices are allowed, never-a-device targets are not.

Contrast with tests/test_ssrf.py: app.ssrf (internet egress) must keep rejecting
RFC1918/loopback; app.device_url (printers/CNC/brokers) must accept them.
"""
import pytest

from app.device_url import assert_safe_device_url
from app.models import PrinterConfig
from app.moonraker import MoonrakerClient

_METADATA = ".".join(["169", "254", "169", "254"])


@pytest.mark.parametrize("url", [
    "http://192.168.1.100:7125",   # DEPLOYMENT.md example
    "http://10.0.0.5",
    "http://172.16.3.4:5000",
    "http://127.0.0.1:7125",       # Moonraker on the same host
    "http://localhost:1883",       # MQTTPollingAdapter's own default broker
    "http://100.101.102.103",      # CGNAT / tailnet-reachable device
    "http://[fd12:3456::1]:7125",  # IPv6 ULA
])
def test_lan_device_urls_allowed(url):
    assert_safe_device_url(url)


@pytest.mark.parametrize("url", [
    f"http://{_METADATA}/latest/meta-data/",
    "http://[fd00:ec2::254]/",      # AWS IMDS over IPv6
    "http://100.100.100.200/",      # Alibaba metadata
    "http://192.0.0.192/",          # Oracle metadata
    "http://169.254.10.20/",        # link-local
    "http://[fe80::1]/",
    "http://224.0.0.1/",            # multicast
    "http://0.0.0.0/",              # unspecified
    "http://240.0.0.1/",            # reserved
    f"http://[::ffff:{_METADATA}]/",  # IPv4-mapped metadata
])
def test_never_a_device_targets_rejected(url):
    with pytest.raises(ValueError, match="unsafe IP"):
        assert_safe_device_url(url)


@pytest.mark.parametrize("url,match", [
    ("ftp://192.168.1.100", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("http:///path", "hostname"),
    ("http://no-such-host.invalid/", "Cannot resolve"),
])
def test_malformed_or_unresolvable_rejected(url, match):
    with pytest.raises(ValueError, match=match):
        assert_safe_device_url(url)


def test_moonraker_client_accepts_lan_rejects_metadata():
    MoonrakerClient(PrinterConfig(id="p", name="p", base_url="http://192.168.1.100:7125"))
    with pytest.raises(ValueError, match="unsafe IP"):
        MoonrakerClient(PrinterConfig(id="m", name="m", base_url=f"http://{_METADATA}/"))
