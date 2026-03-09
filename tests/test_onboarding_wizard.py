"""Tests for onboarding/wizard.py — first-run identity wizard."""

import json
import pytest
from unittest.mock import patch, MagicMock

from crypto.pid import generate_pid, save_pid, load_pid
from db.live_db import init_live_db
from crypto.binding import binding_exists, get_deployer_binding
from onboarding.wizard import (
    is_onboarding_complete,
    get_onboarding_state,
    save_onboarding_state,
    handle_wizard_step,
    ONBOARDING_STATE_FILE,
)


@pytest.fixture(autouse=True)
def _init_db():
    """Ensure the live DB schema is applied before every test."""
    init_live_db()


class TestIsOnboardingCompleteNoPid:
    def test_is_onboarding_complete_false_no_pid(self, tmp_path, monkeypatch):
        """No pid.json → returns False."""
        # Ensure load_pid returns None (no pid.json at tmp_path)
        pid_file = tmp_path / ".refinet" / "pid.json"
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )
        assert is_onboarding_complete() is False


class TestIsOnboardingCompleteNoBinding:
    def test_is_onboarding_complete_false_no_binding(self, tmp_path, monkeypatch):
        """pid.json exists but no binding → returns False."""
        pid_data = generate_pid()
        pid_file = tmp_path / ".refinet" / "pid.json"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        save_pid(pid_data, path=pid_file)

        # Patch load_pid as imported by wizard to read from tmp_path
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )

        assert is_onboarding_complete() is False


class TestIsOnboardingCompleteTrue:
    def test_is_onboarding_complete_true(self, tmp_path, monkeypatch):
        """pid.json exists and binding exists → returns True."""
        from eth_account import Account
        from eth_account.messages import encode_defunct
        from auth.siwe import generate_challenge
        from crypto.pid import get_private_key
        from crypto.binding import create_binding

        pid_data = generate_pid()
        pid_file = tmp_path / ".refinet" / "pid.json"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        save_pid(pid_data, path=pid_file)

        # Patch load_pid as imported by the wizard so it reads from tmp_path
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )

        account = Account.create()
        message, nonce = generate_challenge(account.address, pid_data["pid"])
        encoded = encode_defunct(text=message)
        signed = account.sign_message(encoded)
        priv_key = get_private_key(pid_data)

        create_binding(
            pid_data=pid_data,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=signed.signature.hex(),
            chain_id=1,
            private_key=priv_key,
        )

        assert is_onboarding_complete() is True


class TestWizardWelcomeStep:
    @pytest.mark.asyncio
    async def test_wizard_welcome_step_returns_gopher_menu(self):
        """handle_wizard_step returns valid Gopher string."""
        result = await handle_wizard_step("/onboarding", "", "localhost", 7070)
        # Gopher info lines start with 'i'
        assert result.startswith("i")
        assert "ONBOARDING" in result or "onboarding" in result.lower()
        # Must contain at least one menu link (type '1')
        assert "\r\n1" in result or result.startswith("1") or "\n1" in result


class TestWizardGeneratePidCreatesPidFile:
    @pytest.mark.asyncio
    async def test_wizard_generate_pid_creates_pid_file(self, tmp_path, monkeypatch):
        """Simulate STEP_GENERATE_PID, confirm pid.json written."""
        home_dir = tmp_path / ".refinet"
        home_dir.mkdir(parents=True, exist_ok=True)
        pid_file = home_dir / "pid.json"
        state_file = home_dir / "onboarding_state.json"
        monkeypatch.setattr("core.config.HOME_DIR", home_dir)
        monkeypatch.setattr("onboarding.wizard.HOME_DIR", home_dir)
        monkeypatch.setattr(
            "onboarding.wizard.ONBOARDING_STATE_FILE", state_file,
        )
        # Patch save_pid/load_pid as imported in wizard to use tmp_path
        monkeypatch.setattr(
            "onboarding.wizard.save_pid",
            lambda data: save_pid(data, path=pid_file),
        )
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )

        # Invoke the wizard with a password query on the generate-pid selector
        result = await handle_wizard_step(
            "/onboarding/generate-pid", "testpassword", "localhost", 7070
        )

        assert pid_file.exists()
        loaded = load_pid(path=pid_file)
        assert loaded is not None
        assert "pid" in loaded
        assert "public_key" in loaded
        # Private key must NOT appear in the Gopher output
        assert loaded.get("private_key") is not None
        priv_str = loaded["private_key"] if isinstance(loaded["private_key"], str) else ""
        if priv_str:
            assert priv_str not in result


class TestWizardSiweVerifyCreatesBinding:
    @pytest.mark.asyncio
    async def test_wizard_siwe_verify_creates_binding(self, tmp_path, monkeypatch):
        """Simulate full flow with mocked SIWE signature, confirm binding row exists."""
        from eth_account import Account
        from eth_account.messages import encode_defunct
        from auth.siwe import generate_challenge
        from crypto.pid import get_private_key

        # Set up isolated paths
        home_dir = tmp_path / ".refinet"
        home_dir.mkdir(parents=True, exist_ok=True)
        pid_file = home_dir / "pid.json"
        state_file = home_dir / "onboarding_state.json"
        monkeypatch.setattr("core.config.HOME_DIR", home_dir)
        monkeypatch.setattr("onboarding.wizard.ONBOARDING_STATE_FILE", state_file)
        monkeypatch.setattr("onboarding.wizard.HOME_DIR", home_dir)
        # Patch load_pid as imported by wizard to read from tmp_path
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )

        # Step 1: Generate PID
        pid_data = generate_pid()
        save_pid(pid_data, path=pid_file)

        # Step 2: Generate SIWE challenge
        account = Account.create()
        message, nonce = generate_challenge(account.address, pid_data["pid"])
        encoded = encode_defunct(text=message)
        signed = account.sign_message(encoded)

        # Prepare wizard state as if steps 1-3 already completed
        state = {
            "step": "STEP_SIWE_CHALLENGE",
            "pid": pid_data["pid"],
            "evm_address": account.address,
            "challenge_nonce": nonce,
            "siwe_message": message,
            "password": None,
        }
        save_onboarding_state(state)

        # Step 3: Verify SIWE — this should create the binding
        result = await handle_wizard_step(
            "/onboarding/siwe-verify",
            signed.signature.hex(),
            "localhost",
            7070,
        )

        # Binding must now exist in the database
        assert binding_exists(pid_data["pid"]) is True
        deployer = get_deployer_binding(pid_data["pid"])
        assert deployer is not None
        assert deployer["evm_address"] == account.address
        assert deployer["siwe_message"] == message
        assert "Binding Complete" in result or "CONFIRM" in result.upper() or "binding_id" in result.lower()


class TestWizardStatePersistsBetweenCalls:
    @pytest.mark.asyncio
    async def test_wizard_state_persists_between_calls(self, tmp_path, monkeypatch):
        """Advance through two steps, confirm state file updated correctly."""
        home_dir = tmp_path / ".refinet"
        home_dir.mkdir(parents=True, exist_ok=True)
        pid_file = home_dir / "pid.json"
        state_file = home_dir / "onboarding_state.json"
        monkeypatch.setattr("core.config.HOME_DIR", home_dir)
        monkeypatch.setattr("onboarding.wizard.HOME_DIR", home_dir)
        monkeypatch.setattr("onboarding.wizard.ONBOARDING_STATE_FILE", state_file)
        # Patch save_pid/load_pid as imported in wizard to use tmp_path
        monkeypatch.setattr(
            "onboarding.wizard.save_pid",
            lambda data: save_pid(data, path=pid_file),
        )
        monkeypatch.setattr(
            "onboarding.wizard.load_pid",
            lambda: load_pid(path=pid_file),
        )

        # Step 1: Welcome page — state should still be STEP_WELCOME
        await handle_wizard_step("/onboarding", "", "localhost", 7070)
        state = get_onboarding_state()
        assert state["step"] == "STEP_WELCOME"

        # Step 2: Generate PID with a password
        await handle_wizard_step(
            "/onboarding/generate-pid", "mypassword", "localhost", 7070
        )

        # State file should now reflect the advance to STEP_CONNECT_WALLET
        assert state_file.exists()
        with open(state_file) as f:
            persisted = json.load(f)
        assert persisted["step"] == "STEP_CONNECT_WALLET"
        assert persisted["pid"] is not None
        assert len(persisted["pid"]) == 64  # SHA-256 hex
