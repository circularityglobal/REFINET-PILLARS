"""Tests for proxy/forward_proxy.py — Privacy Forward Proxy."""

import pytest
from proxy.forward_proxy import ForwardProxy, ALLOWED_PORTS, _resolve_or_block


class TestSSRFProtection:
    """Destinations the proxy must refuse.

    These are checked against the resolved address, not the hostname string:
    judging the string let any caller-controlled name that resolves into a
    private range through, and let the address change between the check and
    the connection.
    """

    @pytest.mark.parametrize("host", [
        "127.0.0.1", "127.1.2.3", "0.0.0.0", "10.0.0.1", "192.168.1.1",
        "172.16.0.1", "169.254.1.1", "::1",
        # Spellings the old prefix check never caught
        "2130706433",              # decimal 127.0.0.1
        "0x7f000001",              # hex 127.0.0.1
        "[::ffff:127.0.0.1]",      # IPv4-mapped IPv6
        "127.0.0.1.nip.io",        # a public name resolving to loopback
    ])
    async def test_private_destinations_are_refused(self, host):
        with pytest.raises(Exception):
            await _resolve_or_block(host, 70)

    async def test_a_public_address_is_allowed_and_pinned(self):
        pinned = await _resolve_or_block("8.8.8.8", 70)
        assert pinned == "8.8.8.8", "the checked address is the one connected to"


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
