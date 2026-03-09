"""
REFInet Pillar — SIWE Session Management

Manages authenticated sessions over Gopher protocol.
Sessions are stored in SQLite and are write-only (revoked, never deleted).
"""

from __future__ import annotations

import secrets
import io
import base64
from datetime import datetime, timezone

from auth.siwe import (
    generate_challenge,
    verify_siwe_signature,
    parse_expiry,
    parse_nonce,
    SESSION_DURATION_HOURS,
)
from crypto.pid import get_or_create_pid
from db.live_db import _connect

try:
    import qrcode
except ImportError:
    qrcode = None


def create_challenge(address: str, chain_id: int = 1) -> dict:
    """
    Generate a SIWE challenge for a given EVM address.
    Returns dict with message, nonce, and optional QR base64.

    Args:
        address: EVM address (0x-prefixed, 42 chars)
        chain_id: EVM chain ID for the SIWE message (default 1 = Ethereum mainnet)
    """
    pid_data = get_or_create_pid()
    message, nonce = generate_challenge(address, pid_data["pid"],
                                        chain_id=chain_id)

    result = {
        "message": message,
        "nonce": nonce,
        "qr_base64": None,
    }

    # Generate QR code if qrcode library is available
    if qrcode:
        qr = qrcode.make(message)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        result["qr_base64"] = base64.b64encode(buf.getvalue()).decode()

    return result


def establish_session(address: str, message_text: str, signature: str) -> dict:
    """
    Verify signature and create a session.
    Returns session dict or raises ValueError.
    """
    pid_data = get_or_create_pid()

    if not verify_siwe_signature(message_text, signature, address):
        raise ValueError("Signature verification failed — address mismatch")

    expiry = parse_expiry(message_text)
    now = datetime.now(timezone.utc)
    if now > expiry:
        raise ValueError("SIWE message has already expired")

    session_id = secrets.token_hex(32)
    nonce = parse_nonce(message_text)

    with _connect() as conn:
        # Reject replayed nonces — each nonce must be used exactly once
        existing = conn.execute(
            "SELECT 1 FROM siwe_sessions WHERE nonce = ?", (nonce,)
        ).fetchone()
        if existing:
            raise ValueError("Nonce already used — possible replay attack")

        conn.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature,
                pid, revoked, created_at)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (
                session_id,
                address,
                nonce,
                now.isoformat(),
                expiry.isoformat(),
                signature,
                pid_data["pid"],
                now.isoformat(),
            ),
        )
        conn.commit()

    return {
        "session_id": session_id,
        "address": address,
        "expires_at": expiry.isoformat(),
        "pid": pid_data["pid"],
    }


def validate_session(session_id: str) -> dict | None:
    """
    Validate an existing session.
    Returns session dict or None if invalid/expired/revoked.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM siwe_sessions WHERE session_id=? AND revoked=0",
            (session_id,),
        ).fetchone()

    if not row:
        return None

    expiry = datetime.fromisoformat(row["expires_at"])
    now = datetime.now(timezone.utc)
    # Handle timezone-naive datetimes from DB
    if expiry.tzinfo is None:
        from datetime import timezone as tz
        expiry = expiry.replace(tzinfo=tz.utc)
    if now > expiry:
        return None  # Expired — don't delete, just reject

    return dict(row)


def revoke_session(session_id: str):
    """Mark a session as revoked (write-only — sets revoked=1, never deletes)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE siwe_sessions SET revoked=1 WHERE session_id=?",
            (session_id,),
        )
        conn.commit()


def establish_session_zkp(public_key_hex: str, proof: dict) -> dict:
    """
    Create a session from a verified ZKP proof.
    Alternative to SIWE for cryptographic (non-wallet) authentication.

    Args:
        public_key_hex: Ed25519 public key of the authenticated party
        proof: Verified ZKP proof dict

    Returns:
        Session dict with session_id, expires_at
    """
    import hashlib
    from datetime import timedelta

    pid_data = get_or_create_pid()
    session_id = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=SESSION_DURATION_HOURS)

    # Derive a pseudo-address from public key for session storage
    pseudo_address = "0x" + hashlib.sha256(
        bytes.fromhex(public_key_hex)
    ).hexdigest()[:40]

    with _connect() as conn:
        conn.execute(
            """INSERT INTO siwe_sessions
               (session_id, address, nonce, issued_at, expires_at, signature,
                pid, revoked, created_at)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (
                session_id,
                pseudo_address,
                proof.get("challenge", "zkp"),
                now.isoformat(),
                expiry.isoformat(),
                proof.get("response", ""),
                pid_data["pid"],
                now.isoformat(),
            ),
        )
        conn.commit()

    return {
        "session_id": session_id,
        "address": pseudo_address,
        "expires_at": expiry.isoformat(),
        "pid": pid_data["pid"],
        "auth_method": "zkp",
    }
