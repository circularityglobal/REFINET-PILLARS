"""Tests for SIWE authentication module."""

import pytest
from datetime import datetime, timezone
from auth.siwe import (
    generate_challenge,
    verify_siwe_signature,
    parse_expiry,
    parse_nonce,
    DOMAIN,
    SESSION_DURATION_HOURS,
)
from eth_account import Account


class TestSIWEChallenge:
    """Test SIWE challenge generation."""

    def test_generate_challenge_format(self):
        address = "0x" + "a" * 40
        pid = "test_pid_" + "0" * 55
        message, nonce = generate_challenge(address, pid)

        assert DOMAIN in message
        assert address in message
        assert f"Nonce: {nonce}" in message
        assert "Issued At:" in message
        assert "Expiration Time:" in message
        assert "Version: 1" in message
        assert "Chain ID: 1" in message

    def test_generate_challenge_default_chain_id(self):
        """Default chain_id should be 1 (Ethereum mainnet)."""
        address = "0x" + "e" * 40
        pid = "test_pid_chain"
        message, _ = generate_challenge(address, pid)
        assert "Chain ID: 1" in message

    def test_generate_challenge_custom_chain_id(self):
        """Custom chain_id should appear in the SIWE message."""
        address = "0x" + "f" * 40
        pid = "test_pid_chain"
        # Polygon
        message, _ = generate_challenge(address, pid, chain_id=137)
        assert "Chain ID: 137" in message
        assert "Chain ID: 1\n" not in message

    def test_generate_challenge_sepolia(self):
        """Sepolia chain_id (11155111) should appear correctly."""
        address = "0x" + "a" * 40
        pid = "test_pid_chain"
        message, _ = generate_challenge(address, pid, chain_id=11155111)
        assert "Chain ID: 11155111" in message

    def test_nonce_is_unique(self):
        address = "0x" + "b" * 40
        pid = "test_pid"
        _, nonce1 = generate_challenge(address, pid)
        _, nonce2 = generate_challenge(address, pid)
        assert nonce1 != nonce2

    def test_parse_nonce(self):
        address = "0x" + "c" * 40
        message, nonce = generate_challenge(address, "pid")
        assert parse_nonce(message) == nonce

    def test_parse_expiry(self):
        address = "0x" + "d" * 40
        message, _ = generate_challenge(address, "pid")
        expiry = parse_expiry(message)
        assert isinstance(expiry, datetime)
        # Expiry should be ~24 hours from now
        now = datetime.now(timezone.utc)
        delta = expiry - now
        assert 23 * 3600 < delta.total_seconds() < 25 * 3600


class TestSIWEVerification:
    """Test SIWE signature verification using eth-account."""

    def test_valid_signature(self):
        """Sign a SIWE message with eth-account and verify it."""
        # Generate a test account
        account = Account.create()
        address = account.address
        pid = "test_pid_verification"

        message, nonce = generate_challenge(address, pid)

        # Sign the message
        from eth_account.messages import encode_defunct
        encoded = encode_defunct(text=message)
        signed = account.sign_message(encoded)

        # Verify
        assert verify_siwe_signature(message, signed.signature.hex(), address)

    def test_wrong_address_fails(self):
        """Signature should not verify against a different address."""
        account = Account.create()
        other_account = Account.create()

        message, _ = generate_challenge(account.address, "pid")

        from eth_account.messages import encode_defunct
        encoded = encode_defunct(text=message)
        signed = account.sign_message(encoded)

        # Verify against wrong address
        assert not verify_siwe_signature(
            message, signed.signature.hex(), other_account.address
        )

    def test_tampered_message_fails(self):
        """Modified message should fail verification."""
        account = Account.create()
        message, _ = generate_challenge(account.address, "pid")

        from eth_account.messages import encode_defunct
        encoded = encode_defunct(text=message)
        signed = account.sign_message(encoded)

        tampered = message.replace("Version: 1", "Version: 2")
        assert not verify_siwe_signature(
            tampered, signed.signature.hex(), account.address
        )


class TestSIWENonceReplay:
    """Test that nonce replay is rejected."""

    def test_duplicate_nonce_rejected(self, memory_db):
        """Inserting two sessions with the same nonce should fail (UNIQUE constraint)."""
        memory_db.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature, pid, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("sess_a", "0xabc", "nonce_replay", "2026-01-01", "2026-01-02",
             "sig1", "pid1", "2026-01-01"),
        )
        memory_db.commit()

        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                """INSERT INTO siwe_sessions
                   (session_id, address, nonce, issued_at, expires_at, signature, pid, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("sess_b", "0xabc", "nonce_replay", "2026-01-01", "2026-01-02",
                 "sig1", "pid1", "2026-01-01"),
            )


class TestSIWESessionSchema:
    """Test that siwe_sessions table works correctly."""

    def test_sessions_table_exists(self, memory_db):
        row = memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='siwe_sessions'"
        ).fetchone()
        assert row is not None

    def test_insert_session(self, memory_db):
        memory_db.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature, pid, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("sess123", "0xabc", "nonce1", "2026-01-01T00:00:00", "2026-01-02T00:00:00",
             "sig_hex", "pid123", "2026-01-01T00:00:00"),
        )
        memory_db.commit()
        row = memory_db.execute(
            "SELECT * FROM siwe_sessions WHERE session_id='sess123'"
        ).fetchone()
        assert row is not None
        assert row["address"] == "0xabc"

    def test_sessions_no_delete(self, memory_db):
        memory_db.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature, pid, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("sess_del", "0xabc", "n", "2026-01-01", "2026-01-02", "sig", "pid", "2026-01-01"),
        )
        memory_db.commit()

        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute("DELETE FROM siwe_sessions WHERE session_id='sess_del'")

    def test_sessions_revoke_works(self, memory_db):
        """Revoking (UPDATE revoked=1) should work since there's no update trigger."""
        memory_db.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature, pid, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("sess_rev", "0xabc", "n", "2026-01-01", "2026-01-02", "sig", "pid", "2026-01-01"),
        )
        memory_db.commit()
        memory_db.execute(
            "UPDATE siwe_sessions SET revoked=1 WHERE session_id='sess_rev'"
        )
        memory_db.commit()
        row = memory_db.execute(
            "SELECT revoked FROM siwe_sessions WHERE session_id='sess_rev'"
        ).fetchone()
        assert row["revoked"] == 1
