"""Tests for the async Gopher client."""

import pytest
from core.gopher_client import (
    _validate_target,
    GopherResponse,
    ALLOWED_PORTS,
)


class TestSSRFProtection:
    """Test that loopback IPs are blocked while LAN IPs are allowed."""

    def test_loopback_blocked(self):
        with pytest.raises(ValueError, match="loopback"):
            _validate_target("127.0.0.1", 7070)

    def test_loopback_127_x_blocked(self):
        with pytest.raises(ValueError, match="loopback"):
            _validate_target("127.0.0.2", 7070)

    def test_zero_blocked(self):
        with pytest.raises(ValueError, match="blocked"):
            _validate_target("0.0.0.0", 7070)

    def test_lan_10_allowed(self):
        """LAN IPs must NOT be blocked — REFInet is LAN-first."""
        _validate_target("10.0.0.5", 7070)  # Should not raise

    def test_lan_192_168_allowed(self):
        _validate_target("192.168.1.100", 7070)  # Should not raise

    def test_lan_172_16_allowed(self):
        _validate_target("172.16.0.1", 7070)  # Should not raise

    def test_public_ip_allowed(self):
        _validate_target("8.8.8.8", 7070)  # Should not raise

    def test_port_not_in_allowlist(self):
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_target("192.168.1.1", 8080)

    def test_allowed_ports(self):
        for port in ALLOWED_PORTS:
            _validate_target("192.168.1.1", port)  # Should not raise


class TestGopherResponse:
    """Test GopherResponse data class."""

    def test_text_property(self):
        resp = GopherResponse(
            host="localhost",
            port=7070,
            selector="/",
            raw_bytes=b"Hello World\r\n",
            content_hash="abc",
            item_type="0",
            size_bytes=13,
        )
        assert resp.text == "Hello World\r\n"

    def test_is_menu(self):
        resp = GopherResponse(
            host="localhost",
            port=7070,
            selector="/",
            raw_bytes=b"",
            content_hash="abc",
            item_type="1",
            size_bytes=0,
        )
        assert resp.is_menu is True

    def test_is_not_menu(self):
        resp = GopherResponse(
            host="localhost",
            port=7070,
            selector="/",
            raw_bytes=b"",
            content_hash="abc",
            item_type="0",
            size_bytes=0,
        )
        assert resp.is_menu is False

    def test_utf8_decode_errors_replaced(self):
        resp = GopherResponse(
            host="localhost",
            port=7070,
            selector="/",
            raw_bytes=b"\xff\xfe",
            content_hash="abc",
            item_type="0",
            size_bytes=2,
        )
        # Should not raise, invalid bytes replaced
        text = resp.text
        assert isinstance(text, str)
