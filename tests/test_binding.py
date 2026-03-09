"""Tests for crypto/binding.py — wallet-to-PID binding creation and verification."""

import json
import sqlite3
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from crypto.pid import generate_pid, get_private_key
from crypto.binding import (
    create_binding,
    verify_binding,
    get_deployer_binding,
    get_all_bindings,
    export_binding_proof,
)
from auth.siwe import generate_challenge
from db.live_db import init_live_db


@pytest.fixture(autouse=True)
def _init_db():
    """Ensure the live DB schema is applied before every test."""
    init_live_db()


def _make_signed_challenge(pid_data, account, chain_id=1):
    """Helper: generate a SIWE challenge and sign it with *account*."""
    message, nonce = generate_challenge(account.address, pid_data["pid"],
                                        chain_id=chain_id)
    encoded = encode_defunct(text=message)
    signed = account.sign_message(encoded)
    return message, signed.signature.hex()


class TestCreateBindingValid:
    def test_create_binding_valid(self, test_pid, test_private_key):
        """Create binding with valid SIWE signature and valid Ed25519 key,
        verify both signatures pass."""
        account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        binding = create_binding(
            pid_data=test_pid,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=sig_hex,
            chain_id=1,
            private_key=test_private_key,
            binding_type="deployer",
        )

        assert binding["pid"] == test_pid["pid"]
        assert binding["evm_address"] == account.address
        assert binding["binding_type"] == "deployer"
        assert binding["siwe_message"] == message
        assert binding["created_at"] is not None

        # Both signatures must verify
        ok, reason = verify_binding(binding)
        assert ok is True
        assert reason == "valid"


class TestCreateBindingWrongAddress:
    def test_create_binding_wrong_address(self, test_pid, test_private_key):
        """Wrong EVM address raises ValueError."""
        account = Account.create()
        other_account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        with pytest.raises(ValueError, match="SIWE signature does not match"):
            create_binding(
                pid_data=test_pid,
                evm_address=other_account.address,
                siwe_message=message,
                siwe_signature=sig_hex,
                chain_id=1,
                private_key=test_private_key,
            )


class TestVerifyBindingTamperedPidSig:
    def test_verify_binding_tampered_pid_sig(self, test_pid, test_private_key):
        """Tamper with pid_signature, verify returns (False, reason)."""
        account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        binding = create_binding(
            pid_data=test_pid,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=sig_hex,
            chain_id=1,
            private_key=test_private_key,
        )

        tampered = dict(binding)
        tampered["pid_signature"] = "ff" * 64  # invalid Ed25519 sig
        ok, reason = verify_binding(tampered)
        assert ok is False
        assert "pid_signature" in reason.lower() or "ed25519" in reason.lower()


class TestVerifyBindingTamperedSiweSig:
    def test_verify_binding_tampered_siwe_sig(self, test_pid, test_private_key):
        """Tamper with siwe_signature, verify returns (False, reason)."""
        account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        binding = create_binding(
            pid_data=test_pid,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=sig_hex,
            chain_id=1,
            private_key=test_private_key,
        )

        tampered = dict(binding)
        # Flip some bytes in the SIWE signature
        tampered["siwe_signature"] = "00" + sig_hex[2:]
        ok, reason = verify_binding(tampered)
        assert ok is False
        assert "siwe" in reason.lower() or "signature" in reason.lower()


class TestBindingImmutable:
    def test_binding_immutable(self, test_pid, test_private_key, memory_db):
        """Attempt UPDATE on pid_bindings raises sqlite3.IntegrityError."""
        account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        binding = create_binding(
            pid_data=test_pid,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=sig_hex,
            chain_id=1,
            private_key=test_private_key,
        )

        # Verify the trigger blocks UPDATE using the memory_db fixture
        memory_db.execute(
            """INSERT INTO pid_bindings
               (binding_id, pid, public_key, evm_address, chain_id,
                siwe_message, siwe_signature, pid_signature, binding_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (binding["binding_id"], binding["pid"], binding["public_key"],
             binding["evm_address"], binding["chain_id"],
             binding["siwe_message"], binding["siwe_signature"],
             binding["pid_signature"], binding["binding_type"]),
        )
        memory_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                "UPDATE pid_bindings SET binding_type='operator' "
                "WHERE binding_id=?",
                (binding["binding_id"],),
            )


class TestGetDeployerBindingReturnsFirst:
    def test_get_deployer_binding_returns_first(self, test_pid, test_private_key):
        """Create two bindings, confirm deployer binding is the earliest."""
        account1 = Account.create()
        msg1, sig1 = _make_signed_challenge(test_pid, account1)
        binding1 = create_binding(
            pid_data=test_pid,
            evm_address=account1.address,
            siwe_message=msg1,
            siwe_signature=sig1,
            chain_id=1,
            private_key=test_private_key,
            binding_type="deployer",
        )

        account2 = Account.create()
        msg2, sig2 = _make_signed_challenge(test_pid, account2)
        binding2 = create_binding(
            pid_data=test_pid,
            evm_address=account2.address,
            siwe_message=msg2,
            siwe_signature=sig2,
            chain_id=1,
            private_key=test_private_key,
            binding_type="deployer",
        )

        deployer = get_deployer_binding(test_pid["pid"])
        assert deployer is not None
        assert deployer["binding_id"] == binding1["binding_id"]

        all_bindings = get_all_bindings(test_pid["pid"])
        assert len(all_bindings) == 2


class TestExportBindingProofIsValidJson:
    def test_export_binding_proof_is_valid_json(self, test_pid, test_private_key):
        """export_binding_proof returns parseable JSON with all required fields."""
        account = Account.create()
        message, sig_hex = _make_signed_challenge(test_pid, account)

        binding = create_binding(
            pid_data=test_pid,
            evm_address=account.address,
            siwe_message=message,
            siwe_signature=sig_hex,
            chain_id=1,
            private_key=test_private_key,
        )

        proof_str = export_binding_proof(binding)
        proof = json.loads(proof_str)

        required_fields = [
            "binding_id", "pid", "public_key", "evm_address",
            "chain_id", "siwe_message", "siwe_signature",
            "pid_signature", "binding_type", "created_at",
        ]
        for field in required_fields:
            assert field in proof, f"Missing required field: {field}"

        # Proof must round-trip verify
        ok, reason = verify_binding(proof)
        assert ok is True
