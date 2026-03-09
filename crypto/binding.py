"""
REFInet Pillar — Wallet-to-PID Binding

Creates and verifies the cryptographic binding between an EVM wallet
address and a Pillar's Ed25519 PID.  This is an append-only artifact:
once a binding is written to pid_bindings it cannot be updated or deleted.

The binding proves two things simultaneously:
  1. The wallet owner authorised the link (SIWE / EIP-4361 signature)
  2. The PID keypair acknowledged the link (Ed25519 pid_signature)

Neither signature alone is sufficient — both must verify for the binding
to be considered valid.
"""

from __future__ import annotations

import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auth.siwe import verify_siwe_signature, parse_nonce
from crypto.signing import sign_content, verify_signature
from db.live_db import _connect


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------
def create_binding(
    pid_data: dict,
    evm_address: str,
    siwe_message: str,
    siwe_signature: str,
    chain_id: int,
    private_key: Ed25519PrivateKey,
    binding_type: str = "deployer",
) -> dict:
    """
    Build a complete wallet-to-PID binding record and persist it.

    Args:
        pid_data:       Full PID dict (must contain ``pid``, ``public_key``).
        evm_address:    Checksummed EVM address that signed the SIWE message.
        siwe_message:   The full EIP-4361 message text the wallet signed.
        siwe_signature: The wallet's ECDSA signature over *siwe_message*.
        chain_id:       EVM chain the wallet signed on.
        private_key:    The Pillar's Ed25519 private key object.
        binding_type:   ``'deployer'`` | ``'operator'`` | ``'rotation'``.

    Returns:
        The full binding dict as stored in the database.

    Raises:
        ValueError: If the SIWE signature does not match *evm_address*.
    """
    # 1. Verify the SIWE signature matches the claimed address
    if not verify_siwe_signature(siwe_message, siwe_signature, evm_address):
        raise ValueError(
            "SIWE signature does not match the provided EVM address"
        )

    pid = pid_data["pid"]
    public_key = pid_data["public_key"]

    # 2. Compute binding_id = SHA-256(pid + evm_address.lower() + nonce)
    nonce = parse_nonce(siwe_message)
    binding_id = hashlib.sha256(
        (pid + evm_address.lower() + nonce).encode("utf-8")
    ).hexdigest()

    # 3. Ed25519-sign the binding_id with the Pillar's private key
    pid_signature = sign_content(binding_id.encode("utf-8"), private_key)

    # 4. Persist to pid_bindings (append-only)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pid_bindings
               (binding_id, pid, public_key, evm_address, chain_id,
                siwe_message, siwe_signature, pid_signature, binding_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                binding_id,
                pid,
                public_key,
                evm_address,
                chain_id,
                siwe_message,
                siwe_signature,
                pid_signature,
                binding_type,
            ),
        )
        conn.commit()

        # Read back the full record (includes server-set created_at)
        row = conn.execute(
            "SELECT * FROM pid_bindings WHERE binding_id = ?",
            (binding_id,),
        ).fetchone()

    return dict(row)


# ------------------------------------------------------------------
# Verify
# ------------------------------------------------------------------
def verify_binding(binding: dict) -> tuple[bool, str]:
    """
    Fully verify a binding record.

    Checks performed (all must pass):
      1. SIWE signature — wallet signed the message.
      2. Ed25519 pid_signature — PID keypair signed the binding_id.
      3. binding_id integrity — recomputed value matches stored value.

    Returns:
        ``(True, "valid")`` when all checks pass, otherwise
        ``(False, reason)`` describing which check failed.
    """
    # 3. (checked first because it is cheapest) Recompute binding_id
    nonce = parse_nonce(binding["siwe_message"])
    expected_id = hashlib.sha256(
        (binding["pid"] + binding["evm_address"].lower() + nonce).encode("utf-8")
    ).hexdigest()
    if expected_id != binding["binding_id"]:
        return (False, "binding_id mismatch — record may be tampered")

    # 1. Verify SIWE signature
    try:
        siwe_ok = verify_siwe_signature(
            binding["siwe_message"],
            binding["siwe_signature"],
            binding["evm_address"],
        )
    except (ValueError, ImportError) as exc:
        return (False, f"SIWE verification error: {exc}")
    if not siwe_ok:
        return (False, "SIWE signature does not match evm_address")

    # 2. Verify Ed25519 pid_signature over binding_id
    ed_ok = verify_signature(
        binding["binding_id"].encode("utf-8"),
        binding["pid_signature"],
        binding["public_key"],
    )
    if not ed_ok:
        return (False, "Ed25519 pid_signature verification failed")

    return (True, "valid")


# ------------------------------------------------------------------
# Query helpers
# ------------------------------------------------------------------
def get_deployer_binding(pid: str) -> dict | None:
    """
    Return the first (earliest) deployer binding for *pid*, or ``None``.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pid_bindings "
            "WHERE pid = ? AND binding_type = 'deployer' "
            "ORDER BY created_at ASC LIMIT 1",
            (pid,),
        ).fetchone()
    return dict(row) if row else None


def get_all_bindings(pid: str) -> list[dict]:
    """Return every binding for *pid*, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pid_bindings WHERE pid = ? ORDER BY created_at ASC",
            (pid,),
        ).fetchall()
    return [dict(r) for r in rows]


def binding_exists(pid: str) -> bool:
    """Return ``True`` if at least one binding exists for *pid*."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM pid_bindings WHERE pid = ? LIMIT 1",
            (pid,),
        ).fetchone()
    return row is not None


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------
def export_binding_proof(binding: dict) -> str:
    """
    Serialise a binding as a portable JSON proof string.

    The full record is the proof — peers use it to independently verify
    both the wallet signature (SIWE) and the PID signature (Ed25519).
    """
    return json.dumps(binding, indent=2, sort_keys=True)
