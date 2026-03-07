"""Tests for gopherhole registry replication logic."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.gopherhole import verify_gopherhole_signature
from crypto.pid import generate_pid, get_private_key
from crypto.signing import sign_content


def _make_hole_record(pid_data, selector="/holes/remote", name="Remote Site"):
    """Create a valid signed gopherhole record for testing."""
    pid = pid_data["pid"]
    registered_at = "2026-03-01"
    payload = f"{pid}:{selector}:{name}:{registered_at}"
    private_key = get_private_key(pid_data)
    signature = sign_content(payload.encode(), private_key)

    return {
        "pid": pid,
        "selector": selector,
        "name": name,
        "description": "A remote gopherhole",
        "owner_address": "",
        "pubkey_hex": pid_data["public_key"],
        "signature": signature,
        "registered_at": registered_at,
        "tx_hash": "abc123",
        "source": "local",
    }


class TestReplicationVerification:
    """Test that replication verifies signatures correctly."""

    def test_valid_record_passes_verification(self):
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        assert verify_gopherhole_signature(record) is True

    def test_tampered_record_fails_verification(self):
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        record["name"] = "Tampered"
        assert verify_gopherhole_signature(record) is False

    def test_wrong_key_fails_verification(self):
        pid_data = generate_pid()
        other_pid = generate_pid()
        record = _make_hole_record(pid_data)
        record["pubkey_hex"] = other_pid["public_key"]  # Wrong key
        assert verify_gopherhole_signature(record) is False


class TestSyncPeerRegistry:
    """Test sync_peer_registry logic."""

    @pytest.mark.asyncio
    async def test_sync_imports_new_valid_hole(self):
        """Valid signed gopherholes should be imported."""
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        json_payload = json.dumps([record]) + "\r\n.\r\n"

        mock_response = MagicMock()
        mock_response.text = json_payload

        with patch("mesh.replication.fetch", new_callable=AsyncMock, return_value=mock_response), \
             patch("mesh.replication.gopherhole_exists", return_value=False), \
             patch("mesh.replication.register_gopherhole", return_value="hash") as mock_register:

            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")

            assert count == 1
            mock_register.assert_called_once()
            call_kwargs = mock_register.call_args
            assert call_kwargs[1]["source"] == "peer_pid_abc"

    @pytest.mark.asyncio
    async def test_sync_skips_existing_hole(self):
        """Already-existing gopherholes should be skipped."""
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        json_payload = json.dumps([record]) + "\r\n.\r\n"

        mock_response = MagicMock()
        mock_response.text = json_payload

        with patch("mesh.replication.fetch", new_callable=AsyncMock, return_value=mock_response), \
             patch("mesh.replication.gopherhole_exists", return_value=True), \
             patch("mesh.replication.register_gopherhole") as mock_register:

            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")

            assert count == 0
            mock_register.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_rejects_invalid_signature(self):
        """Gopherholes with invalid signatures should be rejected."""
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        record["name"] = "Tampered"  # Tamper after signing

        json_payload = json.dumps([record]) + "\r\n.\r\n"

        mock_response = MagicMock()
        mock_response.text = json_payload

        with patch("mesh.replication.fetch", new_callable=AsyncMock, return_value=mock_response), \
             patch("mesh.replication.gopherhole_exists", return_value=False), \
             patch("mesh.replication.register_gopherhole") as mock_register:

            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")

            assert count == 0
            mock_register.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_handles_fetch_failure(self):
        """Network errors should be handled gracefully."""
        with patch("mesh.replication.fetch", new_callable=AsyncMock, side_effect=ConnectionRefusedError):
            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")
            assert count == 0

    @pytest.mark.asyncio
    async def test_sync_handles_versioned_envelope(self):
        """Versioned envelope format (schema_version 1) should be parsed correctly."""
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)

        envelope = {
            "schema_version": 1,
            "generated_at": "2026-03-01T00:00:00+00:00",
            "pillar_pid": pid_data["pid"],
            "gopherholes": [record],
        }
        json_payload = json.dumps(envelope) + "\r\n.\r\n"

        mock_response = MagicMock()
        mock_response.text = json_payload

        with patch("mesh.replication.fetch", new_callable=AsyncMock, return_value=mock_response), \
             patch("mesh.replication.gopherhole_exists", return_value=False), \
             patch("mesh.replication.register_gopherhole", return_value="hash") as mock_register:

            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")

            assert count == 1
            mock_register.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_handles_legacy_bare_array(self):
        """Legacy bare array format should still work (backward compat)."""
        pid_data = generate_pid()
        record = _make_hole_record(pid_data)
        json_payload = json.dumps([record]) + "\r\n.\r\n"

        mock_response = MagicMock()
        mock_response.text = json_payload

        with patch("mesh.replication.fetch", new_callable=AsyncMock, return_value=mock_response), \
             patch("mesh.replication.gopherhole_exists", return_value=False), \
             patch("mesh.replication.register_gopherhole", return_value="hash") as mock_register:

            from mesh.replication import sync_peer_registry
            count = await sync_peer_registry("192.168.1.10", 7070, "peer_pid_abc")

            assert count == 1
            mock_register.assert_called_once()
