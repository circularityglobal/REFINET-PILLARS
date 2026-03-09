"""Tests for WebSocket onboarding message handlers (Part 8).

Covers:
    - onboarding_connect: address validation, PID auto-generation, challenge issuance
    - onboarding_signature: binding creation, state advancement
    - Identity in onboarding mode: onboarding flag, no gopher_server
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from integration.websocket_bridge import WebSocketBridge


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect all disk state to a temp directory."""
    import core.config as cfg
    import crypto.pid as cpid
    import onboarding.wizard as wiz

    pid_file = tmp_path / "pid.json"
    monkeypatch.setattr(cfg, "HOME_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_DIR", tmp_path / "db")
    monkeypatch.setattr(cfg, "PID_FILE", pid_file)
    monkeypatch.setattr(cpid, "PID_FILE", pid_file)
    monkeypatch.setattr(wiz, "ONBOARDING_STATE_FILE", tmp_path / "onboarding_state.json")

    # Patch load_pid/save_pid to use our temp pid_file (avoids default arg capture)
    _original_load = cpid.load_pid.__wrapped__ if hasattr(cpid.load_pid, '__wrapped__') else None
    _original_save = cpid.save_pid.__wrapped__ if hasattr(cpid.save_pid, '__wrapped__') else None

    def _patched_load(path=None):
        return cpid.load_pid(path or pid_file)

    def _patched_save(pid_data, path=None):
        return cpid.save_pid(pid_data, path or pid_file)

    # We need load_pid/save_pid to default to our temp file.
    # Override at every call site that imports them.
    import integration.websocket_bridge as wsb
    original_load = cpid.load_pid
    original_save = cpid.save_pid

    def load_pid_tmp(path=pid_file):
        return original_load(path)

    def save_pid_tmp(pid_data, path=pid_file):
        return original_save(pid_data, path)

    monkeypatch.setattr(cpid, "load_pid", load_pid_tmp)
    monkeypatch.setattr(cpid, "save_pid", save_pid_tmp)

    cfg.ensure_dirs()
    (tmp_path / "db").mkdir(exist_ok=True)

    from db.live_db import init_live_db
    init_live_db()


@pytest.fixture
def bridge():
    """Bridge with gopher_server=None (onboarding mode)."""
    return WebSocketBridge(gopher_server=None)


# ---------------------------------------------------------------------------
# Identity in onboarding mode
# ---------------------------------------------------------------------------

class TestOnboardingIdentity:
    """Identity handler when gopher_server is None."""

    def test_identity_returns_onboarding_flag(self, bridge):
        result = bridge._handle_identity()
        assert result["status"] == "ok"
        assert result["onboarding"] is True
        assert result["pid"] is None  # No PID yet

    def test_identity_returns_pid_after_generation(self, bridge):
        from crypto.pid import generate_pid, save_pid
        pid_data = generate_pid()
        save_pid(pid_data)

        result = bridge._handle_identity()
        assert result["status"] == "ok"
        assert result["onboarding"] is True
        assert result["pid"] == pid_data["pid"]
        assert result["public_key"] == pid_data["public_key"]


# ---------------------------------------------------------------------------
# onboarding_connect
# ---------------------------------------------------------------------------

class TestOnboardingConnect:
    """onboarding_connect message handler."""

    @pytest.mark.asyncio
    async def test_invalid_address_rejected(self, bridge):
        result = await bridge._handle_onboarding_connect({"address": "not-valid"})
        assert result["status"] == "error"
        assert "Invalid EVM address" in result["error"]

    @pytest.mark.asyncio
    async def test_short_address_rejected(self, bridge):
        result = await bridge._handle_onboarding_connect({"address": "0x1234"})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generates_pid_and_challenge(self, bridge):
        address = "0x" + "aB" * 20
        with patch("auth.session.create_challenge") as mock_challenge:
            mock_challenge.return_value = {
                "message": "Sign this message",
                "nonce": "abc123",
            }
            result = await bridge._handle_onboarding_connect({"address": address})

        assert result["status"] == "ok"
        assert result["type"] == "onboarding_challenge"
        assert result["message"] == "Sign this message"
        assert result["pid"] is not None
        assert len(result["pid"]) == 64  # SHA-256 hex

        # PID should exist on disk now
        from crypto.pid import load_pid
        pid_data = load_pid()
        assert pid_data is not None
        assert pid_data["pid"] == result["pid"]

    @pytest.mark.asyncio
    async def test_uses_existing_pid(self, bridge):
        """If PID already exists, don't generate a new one."""
        from crypto.pid import generate_pid, save_pid
        existing = generate_pid()
        save_pid(existing)

        address = "0x" + "cD" * 20
        with patch("auth.session.create_challenge") as mock_challenge:
            mock_challenge.return_value = {
                "message": "challenge text",
                "nonce": "xyz789",
            }
            result = await bridge._handle_onboarding_connect({"address": address})

        assert result["status"] == "ok"
        assert result["pid"] == existing["pid"]

    @pytest.mark.asyncio
    async def test_wizard_state_updated(self, bridge):
        address = "0x" + "eF" * 20
        with patch("auth.session.create_challenge") as mock_challenge:
            mock_challenge.return_value = {
                "message": "siwe message",
                "nonce": "nonce123",
            }
            await bridge._handle_onboarding_connect({"address": address})

        from onboarding.wizard import get_onboarding_state
        state = get_onboarding_state()
        assert state["step"] == "STEP_SIWE_CHALLENGE"
        assert state["evm_address"] == address
        assert state["siwe_message"] == "siwe message"
        assert state["challenge_nonce"] == "nonce123"


# ---------------------------------------------------------------------------
# onboarding_signature
# ---------------------------------------------------------------------------

class TestOnboardingSignature:
    """onboarding_signature message handler."""

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self, bridge):
        result = await bridge._handle_onboarding_signature({"signature": ""})
        assert result["status"] == "error"
        assert "Missing signature" in result["error"]

    @pytest.mark.asyncio
    async def test_no_pid_returns_error(self, bridge):
        result = await bridge._handle_onboarding_signature({"signature": "0xabc"})
        assert result["status"] == "error"
        assert "No PID found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_challenge_returns_error(self, bridge):
        from crypto.pid import generate_pid, save_pid
        save_pid(generate_pid())

        result = await bridge._handle_onboarding_signature({"signature": "0xabc"})
        assert result["status"] == "error"
        assert "No challenge pending" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_binding(self, bridge):
        """Full flow: connect → sign → binding created."""
        from crypto.pid import generate_pid, save_pid
        pid_data = generate_pid()
        save_pid(pid_data)

        address = "0x" + "11" * 20
        siwe_msg = "Sign-In with Ethereum message"

        # Set up wizard state as if onboarding_connect was called
        from onboarding.wizard import save_onboarding_state
        save_onboarding_state({
            "step": "STEP_SIWE_CHALLENGE",
            "pid": pid_data["pid"],
            "evm_address": address,
            "siwe_message": siwe_msg,
            "challenge_nonce": "test-nonce",
        })

        fake_binding = {
            "binding_id": "bind_" + "a" * 60,
            "pid": pid_data["pid"],
            "evm_address": address,
            "chain_id": 1,
            "binding_type": "deployer",
            "created_at": "2026-03-09",
        }

        with patch("crypto.binding.create_binding", return_value=fake_binding):
            result = await bridge._handle_onboarding_signature({"signature": "0xfakesig"})

        assert result["status"] == "ok"
        assert result["type"] == "onboarding_complete"
        assert result["binding_id"] == fake_binding["binding_id"]
        assert result["pid"] == pid_data["pid"]
        assert result["evm_address"] == address

        # State should be COMPLETE
        from onboarding.wizard import get_onboarding_state
        state = get_onboarding_state()
        assert state["step"] == "COMPLETE"
        assert state["binding_id"] == fake_binding["binding_id"]


# ---------------------------------------------------------------------------
# End-to-end via _handle_message
# ---------------------------------------------------------------------------

class TestOnboardingViaHandleMessage:
    """Test that onboarding types route correctly through _handle_message."""

    @pytest.mark.asyncio
    async def test_onboarding_connect_via_handle_message(self, bridge):
        address = "0x" + "22" * 20
        msg = json.dumps({"type": "onboarding_connect", "address": address})

        with patch("auth.session.create_challenge") as mock_challenge:
            mock_challenge.return_value = {"message": "msg", "nonce": "n"}
            result = await bridge._handle_message(msg)

        assert result["type"] == "onboarding_challenge"
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_onboarding_signature_via_handle_message(self, bridge):
        msg = json.dumps({"type": "onboarding_signature", "signature": ""})
        result = await bridge._handle_message(msg)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_selector_blocked_in_onboarding_mode(self, bridge):
        msg = json.dumps({"selector": "/status"})
        result = await bridge._handle_message(msg)
        assert result["status"] == "error"
        assert "onboarding" in result["error"].lower()
