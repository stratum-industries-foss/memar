"""Tests for SSRF protection module."""
import pytest
from app.ssrf import assert_safe_http_url, _is_unsafe_ip


class TestIsUnsafeIp:
    """Tests for _is_unsafe_ip function."""

    def test_loopback_unsafe(self):
        assert _is_unsafe_ip("127.0.0.1") is True
        assert _is_unsafe_ip("::1") is True

    def test_private_unsafe(self):
        assert _is_unsafe_ip("192.168.1.1") is True
        assert _is_unsafe_ip("10.0.0.1") is True
        assert _is_unsafe_ip("172.16.0.1") is True

    def test_link_local_unsafe(self):
        assert _is_unsafe_ip("169.254.1.1") is True

    def test_metadata_unsafe(self):
        assert _is_unsafe_ip("169.254.169.254") is True

    def test_multicast_unsafe(self):
        assert _is_unsafe_ip("224.0.0.1") is True

    def test_shared_address_space_unsafe(self):
        # 100.64.0.0/10 is neither is_private nor is_reserved, but it is not
        # internet-routable: CGNAT, Tailscale/Headscale tailnets, Alibaba metadata.
        assert _is_unsafe_ip("100.64.0.1") is True
        assert _is_unsafe_ip("100.100.100.200") is True

    def test_public_safe(self):
        assert _is_unsafe_ip("8.8.8.8") is False
        assert _is_unsafe_ip("1.1.1.1") is False
        assert _is_unsafe_ip("142.250.80.46") is False  # google.com

    def test_invalid_ip_unsafe(self):
        assert _is_unsafe_ip("not-an-ip") is True
        assert _is_unsafe_ip("") is True


class TestAssertSafeHttpUrl:
    """Tests for assert_safe_http_url function."""

    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            assert_safe_http_url("file:///etc/passwd")

    def test_rejects_javascript_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            assert_safe_http_url("javascript:alert(1)")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            assert_safe_http_url("ftp://example.com/file")

    def test_rejects_no_hostname(self):
        with pytest.raises(ValueError, match="hostname"):
            assert_safe_http_url("http:///path")

    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="unsafe IP"):
            assert_safe_http_url("http://localhost/path")

    def test_rejects_127_ip(self):
        with pytest.raises(ValueError, match="unsafe IP"):
            assert_safe_http_url("http://127.0.0.1/path")

    def test_rejects_private_ip(self):
        with pytest.raises(ValueError, match="unsafe IP"):
            assert_safe_http_url("http://192.168.1.1/path")

    def test_rejects_metadata_ip(self):
        with pytest.raises(ValueError, match="unsafe IP"):
            assert_safe_http_url("http://169.254.169.254/latest/meta-data/")
