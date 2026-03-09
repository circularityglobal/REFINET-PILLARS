"""Tests for proxy/forward_proxy.py — Privacy Forward Proxy."""

import pytest
from proxy.forward_proxy import ForwardProxy, ALLOWED_PORTS, _is_blocked_host, _BLOCKED_PREFIXES


class TestSSRFProtection:
    """SSRF blocked address ranges."""

    def test_loopback_blocked(self):
        assert _is_blocked_host("127.0.0.1")

    def test_loopback_127_x_blocked(self):
        assert _is_blocked_host("127.1.2.3")

    def test_zero_blocked(self):
        assert _is_blocked_host("0.0.0.0")

    def test_private_10_blocked(self):
        assert _is_blocked_host("10.0.0.1")

    def test_private_192_168_blocked(self):
        assert _is_blocked_host("192.168.1.1")

    def test_private_172_16_blocked(self):
        assert _is_blocked_host("172.16.0.1")

    def test_link_local_blocked(self):
        assert _is_blocked_host("169.254.1.1")

    def test_ipv6_loopback_blocked(self):
        assert _is_blocked_host("::1")

    def test_public_ip_allowed(self):
        assert not _is_blocked_host("8.8.8.8")

    def test_public_domain_not_blocked(self):
        assert not _is_blocked_host("example.com")


class TestPortAllowlist:
    """Allowed outbound ports."""

    def test_port_70_allowed(self):
        assert 70 in ALLOWED_PORTS

    def test_port_7070_allowed(self):
        assert 7070 in ALLOWED_PORTS

    def test_port_105_allowed(self):
        assert 105 in ALLOWED_PORTS

    def test_port_80_not_allowed(self):
        assert 80 not in ALLOWED_PORTS

    def test_port_443_not_allowed(self):
        assert 443 not in ALLOWED_PORTS


class TestForwardProxyInit:
    """Proxy constructor and defaults."""

    def test_default_host_and_port(self):
        proxy = ForwardProxy()
        assert proxy.host == "127.0.0.1"
        assert proxy.port == 7074

    def test_custom_config(self):
        proxy = ForwardProxy(host="0.0.0.0", port=9999, strip_metadata=False)
        assert proxy.host == "0.0.0.0"
        assert proxy.port == 9999
        assert proxy.strip_metadata is False

    def test_request_count_starts_zero(self):
        proxy = ForwardProxy()
        assert proxy.request_count == 0

    def test_tor_socks_port_none_by_default(self):
        proxy = ForwardProxy()
        assert proxy.tor_socks_port is None


class TestParseRequest:
    """Request parsing."""

    def test_host_port_selector(self):
        proxy = ForwardProxy()
        host, port, sel = proxy._parse_request("example.com:70/about")
        assert host == "example.com"
        assert port == 70
        assert sel == "/about"

    def test_host_selector_default_port(self):
        proxy = ForwardProxy()
        host, port, sel = proxy._parse_request("example.com/about")
        assert host == "example.com"
        assert port == 7070
        assert sel == "/about"

    def test_host_only(self):
        proxy = ForwardProxy()
        host, port, sel = proxy._parse_request("example.com")
        assert host == "example.com"
        assert port == 7070
        assert sel == ""
