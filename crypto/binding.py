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

A binding is its own statement, never a login (§3.1):

    I bind this wallet to REFINET Pillar <64-hex pid> as its deployer

``create_binding`` refuses any other statement. Before 0.5.0 a binding was
made from an ordinary sign-in signature, which meant any wallet that had
ever signed in had handed the operator a binding for that wallet. Those
older rows still exist and still verify — they are marked ``legacy`` — but
no new one can be made that way, and only §3.1 bindings are published in
the v3 identity document.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auth.siwe import (
    parse_nonce,
    parse_chain_id,
    parse_binding_statement,
    message_names_pid,
    PURPOSE_BINDING,
)
from crypto.signing import (
    DOMAIN_BINDING, verify_signature, sign_domain, verify_domain,
)
from db.live_db import _connect, consume_siwe_nonce


def compute_binding_id(pid: str, evm_address: str, nonce: str) -> str:
    """binding_id = SHA-256(pid || address.lower() || nonce)."""
    return hashlib.sha256(
        (pid + evm_address.lower() + nonce).encode("utf-8")
    ).hexdigest()


def sign_binding_id(binding_id: str, private_key: Ed25519PrivateKey) -> str:
    """The Pillar's counter-signature over a §3.1 binding."""
    return sign_domain(DOMAIN_BINDING, private_key, binding_id)


def is_legacy_binding(binding: dict) -> bool:
    """True when this row was made from a pre-0.5.0 sign-in message."""
    return parse_binding_statement(binding.get("siwe_message", "")) is None


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------
def create_binding(
    pid_data: dict,
    evm_address: str,
    siwe_message: str,
    siwe_signature: str,
    chain_id: int = None,
    private_key: Ed25519PrivateKey = None,
    binding_type: str = "deployer",
    consume_nonce: bool = True,
) -> dict:
    """
    Build a complete wallet-to-PID binding record and persist it.

    Args:
        pid_data:       Full PID dict (must contain ``pid``, ``public_key``).
        evm_address:    EVM address that signed the SIWE message.
        siwe_message:   The full §3.1 binding message the wallet signed.
        siwe_signature: The wallet's signature over *siwe_message*.
        chain_id:       Ignored when the message states one (it always does);
                        kept for callers that pass it explicitly.
        private_key:    The Pillar's Ed25519 private key object.
        binding_type:   ``'deployer'`` | ``'operator'``. Must match the
                        role named in the message's statement.
        consume_nonce:  Spend the binding nonce from the challenge registry.

    Returns:
        The full binding dict as stored in the database.

    Raises:
        ValueError: If the message is not a §3.1 binding statement for this
        PID and role, if its nonce was not issued for a binding, or if the
        wallet signature does not verify.
    """
    pid = pid_data["pid"]
    public_key = pid_data["public_key"]

    # 1. The statement is the discriminator — a login can never become a binding
    parsed = parse_binding_statement(siwe_message)
    if parsed is None:
        raise ValueError(
            "Not a binding message: the statement must read "
            f"'I bind this wallet to REFINET Pillar <pid> as its <role>'"
        )
    stated_pid, stated_role = parsed
    if stated_pid != pid:
        raise ValueError("Binding message names a different Pillar")
    if stated_role != binding_type:
        raise ValueError(
            f"Binding message says '{stated_role}' but '{binding_type}' was requested"
        )
    if not message_names_pid(siwe_message, pid):
        raise ValueError("Binding message URI does not name this Pillar")

    # 2. The challenge must be one this Pillar issued for a binding
    nonce = parse_nonce(siwe_message)
    if consume_nonce:
        ok, reason = consume_siwe_nonce(nonce, PURPOSE_BINDING, pid)
        if not ok:
            raise ValueError(f"Binding challenge rejected: {reason}")

    # 3. The wallet signature: ecrecover, then EIP-1271 for contract wallets
    #    on the chain the message names.
    message_chain_id = parse_chain_id(siwe_message, default=chain_id or 1)
    from auth.wallet_sig import verify_wallet_signature
    sig_ok, sig_reason = verify_wallet_signature(
        siwe_message, siwe_signature, evm_address, chain_id=message_chain_id)
    if not sig_ok:
        raise ValueError(
            f"SIWE signature does not match the provided EVM address — {sig_reason}"
        )

    # 4. binding_id, and the Pillar's domain-separated counter-signature
    binding_id = compute_binding_id(pid, evm_address, nonce)
    pid_signature = sign_binding_id(binding_id, private_key)

    # 5. Persist to pid_bindings (append-only)
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
                message_chain_id,
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
      1. binding_id integrity — recomputed value matches stored value.
      2. SIWE signature — wallet signed the message.
      3. Ed25519 pid_signature — PID keypair signed the binding_id.
         §3.1 bindings are signed under the REFINET-BINDING-v1 domain;
         pre-0.5.0 rows signed the bare binding_id and are accepted as
         ``valid (legacy)``.
      4. For §3.1 bindings: the statement names this record's PID and its
         binding_type.

    Returns:
        ``(True, "valid")`` / ``(True, "valid (legacy)")`` when all checks
        pass, otherwise ``(False, reason)``.
    """
    # 1. (checked first because it is cheapest) Recompute binding_id
    nonce = parse_nonce(binding["siwe_message"])
    expected_id = compute_binding_id(
        binding["pid"], binding["evm_address"], nonce)
    if expected_id != binding["binding_id"]:
        return (False, "binding_id mismatch — record may be tampered")

    legacy = is_legacy_binding(binding)

    # 4. The statement must name this PID and role (§3.1 records only)
    if not legacy:
        stated_pid, stated_role = parse_binding_statement(binding["siwe_message"])
        if stated_pid != binding["pid"]:
            return (False, "binding statement names a different PID")
        if stated_role != (binding.get("binding_type") or "deployer"):
            return (False, "binding statement names a different role")

    # 2. Verify the wallet signature
    try:
        from auth.wallet_sig import verify_wallet_signature
        siwe_ok, reason = verify_wallet_signature(
            binding["siwe_message"],
            binding["siwe_signature"],
            binding["evm_address"],
            chain_id=binding.get("chain_id"),
            # Verifying a stored record must not depend on a network call;
            # contract wallets are re-checked on creation, not on display.
            allow_contract=False,
        )
    except (ValueError, ImportError) as exc:
        return (False, f"SIWE verification error: {exc}")
    if not siwe_ok:
        return (False, f"SIWE signature does not match evm_address — {reason}")

    # 3. Verify the Ed25519 counter-signature over binding_id
    if legacy:
        ed_ok = verify_signature(
            binding["binding_id"].encode("utf-8"),
            binding["pid_signature"],
            binding["public_key"],
        )
    else:
        ed_ok = verify_domain(
            DOMAIN_BINDING, binding["pid_signature"], binding["public_key"],
            binding["binding_id"],
        )
    if not ed_ok:
        return (False, "Ed25519 pid_signature verification failed")

    return (True, "valid (legacy)" if legacy else "valid")


# ------------------------------------------------------------------
# Query helpers
# ------------------------------------------------------------------
def get_deployer_binding(pid: str) -> dict | None:
    """
    Return the canonical deployer binding for *pid*, or ``None``.

    The earliest §3.1 binding is canonical. A Pillar that has only the
    older login-statement binding keeps returning that one, so nothing
    changes until its operator re-signs.
    """
    bindings = [b for b in get_all_bindings(pid)
                if (b.get("binding_type") or "deployer") == "deployer"]
    if not bindings:
        return None
    for b in bindings:
        if not is_legacy_binding(b):
            return b
    return bindings[0]


def get_all_bindings(pid: str) -> list[dict]:
    """Return every binding for *pid*, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pid_bindings WHERE pid = ? ORDER BY created_at ASC, rowid ASC",
            (pid,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_v1_bindings(pid: str) -> list[dict]:
    """Every §3.1 binding for *pid*, oldest first (what identity v3 publishes)."""
    return [b for b in get_all_bindings(pid) if not is_legacy_binding(b)]


def binding_exists(pid: str) -> bool:
    """Return ``True`` if at least one binding exists for *pid*."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM pid_bindings WHERE pid = ? LIMIT 1",
                (pid,),
            ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


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


def build_identity_v3(pid: str, public_key: str, authority: str,
                      bindings: list[dict], private_key: Ed25519PrivateKey,
                      protocol: str = None) -> dict:
    """Build and sign the §3.2 identity document (schema_version 3).

    Only §3.1 bindings appear here: publishing a binding message is safe
    precisely because nothing accepts it as a session.
    """
    from crypto.signing import DOMAIN_IDENTITY, canonical_json, hash_content
    from core.version import __version__

    doc = {
        "schema_version": 3,
        "protocol": protocol or __version__,
        "pid": pid,
        "public_key": public_key,
        "authority": authority,
        "bindings": [
            {
                "binding_id": b["binding_id"],
                "type": b.get("binding_type") or "deployer",
                "evm_address": b["evm_address"],
                "chain_id": b["chain_id"],
                "siwe_message": b["siwe_message"],
                "siwe_signature": b["siwe_signature"],
                "pid_signature": b["pid_signature"],
                "created_at": str(b["created_at"]),
            }
            for b in bindings
        ],
    }
    doc["document_signature"] = sign_domain(
        DOMAIN_IDENTITY, private_key, hash_content(canonical_json(doc)))
    return doc


def verify_identity_v3(doc: dict) -> tuple[bool, str]:
    """Verify a v3 identity document's own signature and key-to-PID match."""
    from crypto.signing import (
        DOMAIN_IDENTITY, canonical_json, hash_content, verify_domain as _vd,
        pid_matches_key,
    )
    try:
        if doc.get("schema_version") != 3:
            return (False, "not a v3 identity document")
        if not pid_matches_key(doc["pid"], doc["public_key"]):
            return (False, "public key does not hash to pid")
        body = {k: v for k, v in doc.items() if k != "document_signature"}
        ok = _vd(DOMAIN_IDENTITY, doc["document_signature"], doc["public_key"],
                 hash_content(canonical_json(body)))
        return (True, "valid") if ok else (False, "document signature does not verify")
    except (KeyError, TypeError) as exc:
        return (False, f"malformed document: {exc}")


def build_binding_vector(private_key, pid: str, public_key: str,
                         wallet_key: str, chain_id: int, nonce: str,
                         issued_at: str, company_url: str, authority: str,
                         created_at: str) -> dict:
    """Build the deterministic binding + identity-v3 test vector.

    Used by ``python3 -m tests.vectors --write``; no database involved.
    """
    from datetime import datetime
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from auth.siwe import generate_binding_challenge

    account = Account.from_key(wallet_key)
    message, _ = generate_binding_challenge(
        account.address, pid, chain_id=chain_id, binding_type="deployer",
        company_url=company_url, authority=authority, nonce=nonce,
        issued_at=datetime.fromisoformat(issued_at),
    )
    signature = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    binding_id = compute_binding_id(pid, account.address, nonce)
    binding = {
        "binding_id": binding_id,
        "pid": pid,
        "public_key": public_key,
        "evm_address": account.address,
        "chain_id": chain_id,
        "siwe_message": message,
        "siwe_signature": signature,
        "pid_signature": sign_binding_id(binding_id, private_key),
        "binding_type": "deployer",
        "created_at": created_at,
    }
    identity = build_identity_v3(
        pid=pid, public_key=public_key, authority=authority,
        bindings=[binding], private_key=private_key)
    return {
        "wallet_address": account.address,
        "nonce": nonce,
        "binding": binding,
        "identity_v3": identity,
    }
