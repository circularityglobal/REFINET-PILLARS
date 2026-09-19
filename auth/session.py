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
    parse_expiry,
    parse_nonce,
    is_binding_message,
    message_names_pid,
    PURPOSE_LOGIN,
    PURPOSE_BINDING,
    LOGIN_NONCE_TTL_SECONDS,
    BINDING_NONCE_TTL_SECONDS,
    SESSION_DURATION_HOURS,
)
from auth.wallet_sig import verify_wallet_signature
from crypto.pid import get_or_create_pid
from db.live_db import _connect, record_siwe_nonce, consume_siwe_nonce

try:
    import qrcode
except ImportError:
    qrcode = None


def create_challenge(address: str, chain_id: int = 1,
                     purpose: str = PURPOSE_LOGIN,
                     binding_type: str = "deployer",
                     company_url: str = None) -> dict:
    """
    Generate a SIWE challenge for a given EVM address.
    Returns dict with message, nonce, and optional QR base64.

    The nonce is registered as issued by this Pillar for this purpose, so
    it can be spent exactly once and cannot be redeemed anywhere else.

    Args:
        address: EVM address (0x-prefixed, 42 chars)
        chain_id: EVM chain ID for the SIWE message (default 1 = Ethereum mainnet)
        purpose: "login" (opens a session) or "binding" (binds the wallet)
        binding_type: "deployer" or "operator", for binding challenges
        company_url: optional TradeSphere company URL, listed in Resources
    """
    pid_data = get_or_create_pid()
    message, nonce = generate_challenge(address, pid_data["pid"],
                                        chain_id=chain_id, purpose=purpose,
                                        binding_type=binding_type,
                                        company_url=company_url)
    ttl = (BINDING_NONCE_TTL_SECONDS if purpose == PURPOSE_BINDING
           else LOGIN_NONCE_TTL_SECONDS)
    record_siwe_nonce(nonce, purpose, pid_data["pid"], address=address,
                      chain_id=chain_id, ttl_seconds=ttl)

    result = {
        "message": message,
        "nonce": nonce,
        "purpose": purpose,
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

    A session is only opened for a login challenge this Pillar issued:

      1. the statement must not be a wallet-binding statement — a binding
         is published in the identity document, and publishing it must
         never hand anyone a session;
      2. the message's URI must name this Pillar's PID in full;
      3. the nonce must be one this Pillar issued for "login", unspent and
         unexpired. It is spent on this attempt either way.
    """
    pid_data = get_or_create_pid()
    pid = pid_data["pid"]

    if is_binding_message(message_text):
        raise ValueError(
            "This message binds a wallet to a Pillar — it cannot open a session"
        )
    if not message_names_pid(message_text, pid):
        raise ValueError("Challenge was not issued by this Pillar")

    nonce = parse_nonce(message_text)
    ok, reason = consume_siwe_nonce(nonce, PURPOSE_LOGIN, pid)
    if not ok:
        raise ValueError(f"Challenge rejected: {reason}")

    sig_ok, sig_reason = verify_wallet_signature(
        message_text, signature, address,
        chain_id=None,  # taken from the message
    )
    if not sig_ok:
        raise ValueError(f"Signature verification failed — {sig_reason}")

    expiry = parse_expiry(message_text)
    now = datetime.now(timezone.utc)
    if now > expiry:
        raise ValueError("SIWE message has already expired")

    session_id = secrets.token_hex(32)

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
