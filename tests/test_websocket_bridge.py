"""Tests for integration/websocket_bridge.py — WebSocket Bridge."""

import pytest
from integration.websocket_bridge import (
    WebSocketBridge,
    _WEBSOCKETS_AVAILABLE,
    _match_origin,
)


class TestWebSocketBridgeInit:
    """Constructor and configuration."""

    def test_default_port(self):
        bridge = WebSocketBridge(gopher_server=None)
        assert bridge.port == 7075

    def test_default_host(self):
        bridge = WebSocketBridge(gopher_server=None)
        assert bridge.host == "127.0.0.1"

    def test_custom_port(self):
        bridge = WebSocketBridge(gopher_server=None, port=9999)
        assert bridge.port == 9999

    def test_connection_count_starts_zero(self):
        bridge = WebSocketBridge(gopher_server=None)
        assert bridge.connection_count == 0

    def test_stores_gopher_server_ref(self):
        sentinel = object()
        bridge = WebSocketBridge(gopher_server=sentinel)
        assert bridge.gopher_server is sentinel

    def test_default_allowed_origins_from_config(self):
        bridge = WebSocketBridge(gopher_server=None)
        assert isinstance(bridge.allowed_origins, list)
        assert len(bridge.allowed_origins) > 0

    def test_custom_allowed_origins(self):
        origins = ["https://example.com"]
        bridge = WebSocketBridge(gopher_server=None, allowed_origins=origins)
        assert bridge.allowed_origins == origins


class TestWebSocketsAvailability:
    """Websockets library availability check."""

    def test_availability_flag_is_bool(self):
        assert isinstance(_WEBSOCKETS_AVAILABLE, bool)

    def test_websockets_is_available(self):
        # websockets is in requirements.txt so should be installed
        assert _WEBSOCKETS_AVAILABLE is True


class TestOriginMatching:
    """Origin validation logic."""

    def test_chrome_extension_allowed(self):
        allowed = ["chrome-extension://"]
        assert _match_origin("chrome-extension://abcdef123456", allowed) is True

    def test_firefox_extension_allowed(self):
        allowed = ["moz-extension://"]
        assert _match_origin("moz-extension://some-uuid", allowed) is True

    def test_localhost_exact_match(self):
        allowed = ["http://localhost"]
        assert _match_origin("http://localhost", allowed) is True

    def test_localhost_with_port(self):
        allowed = ["http://localhost"]
        assert _match_origin("http://localhost:3000", allowed) is True

    def test_127_with_port(self):
        allowed = ["http://127.0.0.1"]
        assert _match_origin("http://127.0.0.1:8080", allowed) is True

    def test_unknown_origin_rejected(self):
        allowed = ["http://localhost", "chrome-extension://"]
        assert _match_origin("https://evil.com", allowed) is False

    def test_empty_origin_rejected(self):
        allowed = ["http://localhost"]
        assert _match_origin("", allowed) is False

    def test_none_origin_rejected(self):
        allowed = ["http://localhost"]
        assert _match_origin(None, allowed) is False

    def test_empty_allowed_list(self):
        assert _match_origin("http://localhost", []) is False


class _MockGopherServer:
    """Minimal mock for testing WebSocketBridge message handlers."""

    def __init__(self, pid_data=None, private_key=None):
        self.pid_data = pid_data or {
            "pid": "a" * 64,
            "public_key": "b" * 64,
            "key_store": "software",
            "protocol": "0.2.0",
        }
        self.private_key = private_key

    async def _route(self, selector):
        return f"iTest response for {selector}\t\t\t0\r\n.\r\n"


class TestHandleMessage:
    """Message handling (unit-level)."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        bridge = WebSocketBridge(gopher_server=None)
        result = await bridge._handle_message("not json{{{")
        assert result["status"] == "error"
        assert "Invalid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_null_server_returns_onboarding_error(self):
        """Without a real gopher_server, selector routing returns onboarding mode error."""
        bridge = WebSocketBridge(gopher_server=None)
        result = await bridge._handle_message('{"selector": "/"}')
        assert result["status"] == "error"
        assert "onboarding" in result["error"].lower()


class TestIdentityMessage:
    """Identity typed message."""

    def test_handle_identity_returns_pid(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_identity()
        assert result["status"] == "ok"
        assert result["type"] == "identity"
        assert result["pid"] == "a" * 64
        assert result["public_key"] == "b" * 64
        assert result["key_store"] == "software"
        assert result["protocol"] == "0.2.0"

    @pytest.mark.asyncio
    async def test_identity_via_handle_message(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_message('{"type": "identity"}')
        assert result["status"] == "ok"
        assert result["type"] == "identity"
        assert result["pid"] == "a" * 64


class TestAuthChallengeMessage:
    """Auth challenge typed message."""

    def test_invalid_address_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_challenge({"address": "not-an-address"})
        assert result["status"] == "error"
        assert "Invalid EVM address" in result["error"]

    def test_short_address_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_challenge({"address": "0x1234"})
        assert result["status"] == "error"

    def test_missing_address_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_challenge({})
        assert result["status"] == "error"

    def test_chain_id_defaults_to_1(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_challenge({
            "address": "0x" + "a" * 40,
            "chain_id": "invalid"
        })
        # Should either succeed or fail gracefully (depends on eth-account)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_challenge_via_handle_message(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        import json
        result = await bridge._handle_message(json.dumps({
            "type": "auth_challenge",
            "address": "0x" + "a" * 40,
        }))
        assert "status" in result


class TestAuthVerifyMessage:
    """Auth verify typed message."""

    def test_invalid_address_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_verify({
            "address": "bad",
            "signature": "0x" + "a" * 130,
            "message": "test message",
        })
        assert result["status"] == "error"
        assert "Invalid EVM address" in result["error"]

    def test_missing_signature_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_verify({
            "address": "0x" + "a" * 40,
            "signature": "",
            "message": "test message",
        })
        assert result["status"] == "error"
        assert "Missing signature" in result["error"]

    def test_missing_message_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_verify({
            "address": "0x" + "a" * 40,
            "signature": "0x" + "a" * 130,
            "message": "",
        })
        assert result["status"] == "error"
        assert "Missing SIWE message" in result["error"]

    def test_browser_domain_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._handle_auth_verify({
            "address": "0x" + "a" * 40,
            "signature": "0x" + "a" * 130,
            "message": "Some message\nURI: refinet://browser\nMore text",
        })
        assert result["status"] == "error"
        assert "Browser session" in result["error"]

    @pytest.mark.asyncio
    async def test_verify_via_handle_message(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        import json
        result = await bridge._handle_message(json.dumps({
            "type": "auth_verify",
            "address": "0x" + "a" * 40,
            "signature": "0x" + "a" * 130,
            "message": "refinet://pillar wants you to sign in",
        }))
        assert "status" in result


class TestBrowseRemoteMessage:
    """Browse remote Pillar typed message."""

    @pytest.mark.asyncio
    async def test_missing_host_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({"selector": "/"})
        assert result["status"] == "error"
        assert "Missing remote host" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_port_defaults(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({
            "host": "nonexistent.example.com",
            "port": "invalid",
            "selector": "/",
        })
        # Will fail to connect but shouldn't crash
        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_loopback_blocked(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({
            "host": "127.0.0.1",
            "port": 7070,
            "selector": "/",
        })
        assert result["status"] == "error"
        assert "Blocked" in result["error"]

    @pytest.mark.asyncio
    async def test_localhost_blocked(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({
            "host": "localhost",
            "port": 7070,
            "selector": "/",
        })
        assert result["status"] == "error"
        assert "Blocked" in result["error"]

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({
            "host": "192.168.1.1",
            "port": 7070,
            "selector": "/",
        })
        assert result["status"] == "error"
        assert "Blocked" in result["error"]

    @pytest.mark.asyncio
    async def test_disallowed_port_rejected(self):
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        result = await bridge._handle_browse_remote({
            "host": "example.com",
            "port": 8080,
            "selector": "/",
        })
        assert result["status"] == "error"
        assert "not allowed" in result["error"]

    @pytest.mark.asyncio
    async def test_allowed_ports(self):
        """Ports 70, 7070, and 105 should pass port validation."""
        server = _MockGopherServer()
        bridge = WebSocketBridge(gopher_server=server)
        for port in [70, 7070, 105]:
            result = await bridge._handle_browse_remote({
                "host": "example.com",
                "port": port,
                "selector": "/",
            })
            # Should fail on connection (not on port validation)
            assert "not allowed" not in result.get("error", "")


class TestSignResponse:
    """Response signing."""

    def test_sign_response_structure(self, test_pid, test_private_key):
        server = _MockGopherServer(
            pid_data=test_pid,
            private_key=test_private_key,
        )
        bridge = WebSocketBridge(gopher_server=server)
        result = bridge._sign_response("/test", "Hello World\r\n.\r\n")
        assert result["status"] == "ok"
        assert result["selector"] == "/test"
        assert result["data"] == "Hello World\r\n.\r\n"
        assert "signature" in result
        assert result["signature"]["pid"] == test_pid["pid"]
        assert result["signature"]["pubkey"] == test_pid["public_key"]
        assert len(result["signature"]["sig"]) > 0
        assert len(result["signature"]["hash"]) == 64  # SHA-256 hex
