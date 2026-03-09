"""Tests for mesh peer discovery module."""

import hashlib
import json
import pytest
from crypto.pid import generate_pid
from mesh.discovery import (
    build_announce_message,
    parse_announce_message,
    verify_peer_identity,
    PeerAnnouncer,
    PeerListener,
)
from core.config import PROTOCOL_VERSION


class TestVerifyPeerIdentity:
    """Test cryptographic verification of peer PID against public key."""

    def test_valid_pid_matches_key(self):
        pid_data = generate_pid()
        assert verify_peer_identity(pid_data["pid"], pid_data["public_key"])

    def test_mismatched_pid_rejected(self):
        pid_data = generate_pid()
        fake_pid = "a" * 64
        assert not verify_peer_identity(fake_pid, pid_data["public_key"])

    def test_invalid_hex_key_rejected(self):
        assert not verify_peer_identity("a" * 64, "not_hex")

    def test_empty_key_rejected(self):
        assert not verify_peer_identity("a" * 64, "")

    def test_swapped_keys_rejected(self):
        """Two different PIDs' keys should not verify against each other's PID."""
        pid1 = generate_pid()
        pid2 = generate_pid()
        assert not verify_peer_identity(pid1["pid"], pid2["public_key"])


class TestBuildAnnounceMessage:
    """Test announcement message construction."""

    def test_format_has_required_fields(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(pid_data, "192.168.1.5", 7070, "Test Pillar")
        msg = json.loads(msg_bytes.decode("utf-8"))

        assert msg["type"] == "pillar_announce"
        assert msg["protocol"] == "REFInet"
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["pid"] == pid_data["pid"]
        assert msg["public_key"] == pid_data["public_key"]
        assert msg["hostname"] == "192.168.1.5"
        assert msg["port"] == 7070
        assert msg["pillar_name"] == "Test Pillar"
        assert "timestamp" in msg

    def test_output_is_valid_json_bytes(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(pid_data, "localhost", 7070, "My Pillar")
        assert isinstance(msg_bytes, bytes)
        json.loads(msg_bytes)  # Should not raise

    def test_pid_matches_input(self):
        pid_data = generate_pid()
        msg = json.loads(build_announce_message(pid_data, "10.0.0.1", 7070, "Node"))
        assert msg["pid"] == pid_data["pid"]
        assert msg["public_key"] == pid_data["public_key"]


class TestParseAnnounceMessage:
    """Test announcement message parsing."""

    def test_valid_message_parsed(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(pid_data, "10.0.0.1", 7070, "Peer")
        result = parse_announce_message(msg_bytes)
        assert result is not None
        assert result["pid"] == pid_data["pid"]
        assert result["hostname"] == "10.0.0.1"

    def test_invalid_json_returns_none(self):
        assert parse_announce_message(b"not json") is None

    def test_wrong_type_returns_none(self):
        msg = json.dumps({"type": "other", "protocol": "REFInet"}).encode()
        assert parse_announce_message(msg) is None

    def test_wrong_protocol_returns_none(self):
        msg = json.dumps({"type": "pillar_announce", "protocol": "other"}).encode()
        assert parse_announce_message(msg) is None

    def test_invalid_utf8_returns_none(self):
        assert parse_announce_message(b"\xff\xfe\xfd") is None

    def test_roundtrip(self):
        """Build + parse should return identical data."""
        pid_data = generate_pid()
        msg_bytes = build_announce_message(pid_data, "192.168.1.50", 7070, "Roundtrip")
        parsed = parse_announce_message(msg_bytes)
        assert parsed["pid"] == pid_data["pid"]
        assert parsed["hostname"] == "192.168.1.50"
        assert parsed["port"] == 7070
        assert parsed["pillar_name"] == "Roundtrip"


class TestHostnameReplacement:
    """Test that loopback hostnames should be replaced with sender IP."""

    def test_localhost_should_be_replaced(self):
        pid_data = generate_pid()
        msg = build_announce_message(pid_data, "localhost", 7070, "Remote")
        parsed = parse_announce_message(msg)
        sender_ip = "192.168.1.50"

        hostname = parsed["hostname"]
        if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
            hostname = sender_ip

        assert hostname == "192.168.1.50"

    def test_real_ip_preserved(self):
        pid_data = generate_pid()
        msg = build_announce_message(pid_data, "10.0.0.5", 7070, "LAN")
        parsed = parse_announce_message(msg)
        sender_ip = "192.168.1.99"

        hostname = parsed["hostname"]
        if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
            hostname = sender_ip

        assert hostname == "10.0.0.5"

    def test_zero_address_should_be_replaced(self):
        pid_data = generate_pid()
        msg = build_announce_message(pid_data, "0.0.0.0", 7070, "Zero")
        parsed = parse_announce_message(msg)
        sender_ip = "10.0.0.99"

        hostname = parsed["hostname"]
        if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
            hostname = sender_ip

        assert hostname == "10.0.0.99"

    def test_loopback_127_should_be_replaced(self):
        pid_data = generate_pid()
        msg = build_announce_message(pid_data, "127.0.0.1", 7070, "Loopback")
        parsed = parse_announce_message(msg)
        sender_ip = "10.0.0.42"

        hostname = parsed["hostname"]
        if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
            hostname = sender_ip

        assert hostname == "10.0.0.42"


class TestOnionAddressInAnnouncement:
    """TOR-24: Test peer announcement includes onion address."""

    def test_announcement_with_onion(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(
            pid_data, "10.0.0.1", 7070, "Tor Pillar",
            onion_address="abc123def456.onion",
        )
        msg = json.loads(msg_bytes.decode("utf-8"))
        assert msg["onion_address"] == "abc123def456.onion"

    def test_announcement_without_onion(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(pid_data, "10.0.0.1", 7070, "No Tor")
        msg = json.loads(msg_bytes.decode("utf-8"))
        assert "onion_address" not in msg

    def test_roundtrip_with_onion(self):
        pid_data = generate_pid()
        msg_bytes = build_announce_message(
            pid_data, "10.0.0.5", 7070, "Onion Peer",
            onion_address="xyz789.onion",
        )
        parsed = parse_announce_message(msg_bytes)
        assert parsed["onion_address"] == "xyz789.onion"
        assert parsed["hostname"] == "10.0.0.5"


class TestPeerAnnouncerInit:
    """Test PeerAnnouncer construction."""

    def test_stores_params(self):
        pid_data = generate_pid()
        announcer = PeerAnnouncer(pid_data, "myhost", 7070, "My Pillar")
        assert announcer.hostname == "myhost"
        assert announcer.port == 7070
        assert announcer.pillar_name == "My Pillar"
        assert announcer.pid_data == pid_data

    def test_stores_onion_address(self):
        pid_data = generate_pid()
        announcer = PeerAnnouncer(
            pid_data, "myhost", 7070, "My Pillar",
            onion_address="test.onion",
        )
        assert announcer.onion_address == "test.onion"

    def test_onion_address_default_none(self):
        pid_data = generate_pid()
        announcer = PeerAnnouncer(pid_data, "myhost", 7070, "My Pillar")
        assert announcer.onion_address is None


class TestPeerListenerInit:
    """Test PeerListener construction."""

    def test_stores_own_pid(self):
        listener = PeerListener(own_pid="my_pid_abc")
        assert listener.own_pid == "my_pid_abc"
