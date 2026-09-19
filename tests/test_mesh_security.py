"""Signed announcements (F8), Origin policy (F15) and the SSRF guard (F16)."""

import json
import time

import pytest

from crypto.pid import generate_pid, get_private_key
from integration.websocket_bridge import (
    WebSocketBridge, BlockedDestination, address_is_public,
    resolve_public_address, _match_origin,
)
from mesh.discovery import (
    PeerListener, build_announce_message, parse_announce_message,
    verify_announce_signature,
)


def _announce(pid_data, hostname="192.168.1.5", port=7070, **kw):
    return parse_announce_message(build_announce_message(
        pid_data, hostname, port, "Test Pillar", **kw))


class TestSignedAnnouncements:
    def test_announcement_is_signed_by_default(self):
        msg = _announce(generate_pid())
        assert "sig" in msg
        assert verify_announce_signature(msg) == (True, "ok")

    def test_tampered_address_fails(self):
        msg = _announce(generate_pid())
        msg["hostname"] = "10.0.0.66"
        ok, reason = verify_announce_signature(msg)
        assert not ok and reason == "signature does not verify"

    def test_another_pillars_key_cannot_sign_for_this_pid(self):
        victim, impostor = generate_pid(), generate_pid()
        msg = _announce(victim)
        forged = dict(msg, hostname="10.0.0.66")
        forged["sig"] = build_announce_message.__globals__["sign_domain"](
            "REFINET-ANNOUNCE-v1", get_private_key(impostor),
            forged["pid"], forged["hostname"], forged["port"], forged["timestamp"])
        assert not verify_announce_signature(forged)[0]

    def test_stale_announcement_is_refused(self):
        pid_data = generate_pid()
        msg = _announce(pid_data, timestamp=int(time.time()) - 600)
        ok, reason = verify_announce_signature(msg)
        assert not ok and "stale" in reason

    def test_no_wallet_address_is_announced(self):
        msg = _announce(generate_pid())
        assert "evm_address" not in msg and "binding_id" not in msg


class TestListenerPolicy:
    def test_signed_announcement_may_move_a_known_peer(self):
        pid_data = generate_pid()
        listener = PeerListener(own_pid="self")
        accept, may_move, _ = listener.accept_announcement(
            _announce(pid_data), {pid_data["pid"]})
        assert accept and may_move

    def test_unsigned_announcement_cannot_move_a_known_peer(self):
        """The LAN hijack: re-announce a real PID with your own address."""
        pid_data = generate_pid()
        msg = _announce(pid_data, hostname="10.0.0.66")
        msg.pop("sig")
        listener = PeerListener(own_pid="self")
        accept, may_move, reason = listener.accept_announcement(
            msg, {pid_data["pid"]})
        assert accept and not may_move
        assert "address not updated" in reason

    def test_unsigned_announcement_can_still_introduce_a_new_peer(self):
        """Mixed meshes: an older Pillar is still discoverable."""
        pid_data = generate_pid()
        msg = _announce(pid_data)
        msg.pop("sig")
        listener = PeerListener(own_pid="self")
        accept, may_move, _ = listener.accept_announcement(msg, set())
        assert accept and not may_move

    def test_require_signed_drops_unsigned_announcements(self):
        pid_data = generate_pid()
        msg = _announce(pid_data)
        msg.pop("sig")
        listener = PeerListener(own_pid="self", require_signed=True)
        accept, _, _ = listener.accept_announcement(msg, set())
        assert not accept

    def test_replayed_signed_announcement_is_refused(self):
        pid_data = generate_pid()
        msg = _announce(pid_data)
        listener = PeerListener(own_pid="self")
        assert listener.accept_announcement(msg, set())[0]
        accept, _, reason = listener.accept_announcement(msg, {pid_data["pid"]})
        assert not accept and reason == "replayed announcement"


class TestAddressGuard:
    @pytest.mark.parametrize("ip", [
        "127.0.0.1", "10.0.0.5", "192.168.1.5", "172.16.0.1", "169.254.1.1",
        "0.0.0.0", "::1", "fd00::1", "fe80::1", "224.0.0.1",
        "::ffff:127.0.0.1",          # IPv4-mapped loopback
    ])
    def test_private_addresses_are_blocked(self, ip):
        assert not address_is_public(ip)

    @pytest.mark.parametrize("ip", ["93.184.216.34", "1.1.1.1", "2606:4700::1111"])
    def test_public_addresses_are_allowed(self, ip):
        assert address_is_public(ip)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("host", [
        "127.0.0.1", "0x7f000001", "2130706433", "127.1", "[::ffff:127.0.0.1]",
        "localhost",
    ])
    async def test_loopback_spellings_are_all_blocked(self, host):
        """Every one of these reaches 127.0.0.1; the old prefix check missed most."""
        with pytest.raises(BlockedDestination):
            await resolve_public_address(host, 7070)

    @pytest.mark.asyncio
    async def test_browse_remote_blocks_obfuscated_loopback(self):
        bridge = WebSocketBridge(gopher_server=None)
        result = await bridge._handle_browse_remote({
            "host": "2130706433", "port": 7070, "selector": "/"})
        assert result["status"] == "error"
        assert "Blocked destination" in result["error"]

    @pytest.mark.asyncio
    async def test_a_name_starting_with_fd_is_not_blocked_for_its_spelling(self,
                                                                          monkeypatch):
        """fdroid.org was blocked by the "fd" prefix rule."""
        import socket

        async def fake_getaddrinfo(host, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("65.21.0.1", port))]

        import asyncio
        loop = asyncio.get_event_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        assert await resolve_public_address("fdroid.org", 7070) == "65.21.0.1"

    @pytest.mark.asyncio
    async def test_public_name_resolving_to_a_private_address_is_blocked(self,
                                                                         monkeypatch):
        import asyncio
        import socket

        async def fake_getaddrinfo(host, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]

        monkeypatch.setattr(asyncio.get_event_loop(), "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(BlockedDestination):
            await resolve_public_address("rebind.example", 7070)


class TestOriginPolicy:
    def test_default_admits_any_extension_as_before(self):
        bridge = WebSocketBridge(gopher_server=None)
        assert _match_origin("chrome-extension://whatever", bridge.allowed_origins)
        assert bridge.require_origin is False

    def test_pinned_extension_ids_exclude_other_extensions(self):
        bridge = WebSocketBridge(gopher_server=None, extension_ids=["abc123"])
        assert _match_origin("chrome-extension://abc123", bridge.allowed_origins)
        assert not _match_origin("chrome-extension://evil", bridge.allowed_origins)
        assert _match_origin("http://localhost", bridge.allowed_origins)

    def test_require_origin_is_opt_in(self):
        assert WebSocketBridge(gopher_server=None).require_origin is False
        assert WebSocketBridge(gopher_server=None, require_origin=True).require_origin


class TestListenerMemoryIsBounded:
    def test_announcement_tracking_does_not_grow_forever(self):
        """A stranger can mint keypairs; the replay map must stay bounded."""
        listener = PeerListener(own_pid="self")
        listener.max_tracked_pids = 50
        for _ in range(300):
            listener.accept_announcement(_announce(generate_pid()), set())
        assert len(listener._last_announce_ts) <= 50

    def test_replay_protection_still_works_for_tracked_peers(self):
        listener = PeerListener(own_pid="self")
        pid_data = generate_pid()
        msg = _announce(pid_data)
        assert listener.accept_announcement(msg, set())[0]
        assert not listener.accept_announcement(msg, {pid_data["pid"]})[0]
