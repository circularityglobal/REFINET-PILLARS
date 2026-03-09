"""
REFInet Pillar — Pillar ID (PID) Management

Each Pillar gets a unique cryptographic identity on first run:
  - Ed25519 keypair (fast, compact, blockchain-friendly)
  - PID = hex-encoded hash of the public key
  - Used for: signing content, verifying peers, staking proofs, license entitlement

The PID is the foundation of trust in the REFInet mesh.

Private keys are encrypted at rest using AES-256-GCM with Argon2id-derived keys.
Legacy plaintext PIDs are auto-detected and can be migrated.
"""

from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import PID_FILE, ensure_dirs

# ---------------------------------------------------------------------------
# Try importing argon2; fall back gracefully so tests/scripts that don't
# need encryption can still import the module.
# ---------------------------------------------------------------------------
try:
    from argon2.low_level import hash_secret_raw, Type
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_AVAILABLE = False


# ---------------------------------------------------------------------------
# Encryption Helpers (AES-256-GCM + Argon2id)
# ---------------------------------------------------------------------------
def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a password using Argon2id."""
    if not _ARGON2_AVAILABLE:
        raise RuntimeError("argon2-cffi is required for encrypted key storage. "
                           "Install with: pip install argon2-cffi")
    from core.config import (ARGON2_TIME_COST, ARGON2_MEMORY_COST,
                             ARGON2_PARALLELISM, ARGON2_HASH_LEN)
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    )


def encrypt_private_key(priv_hex: str, password: str) -> dict:
    """
    Encrypt a private key hex string with AES-256-GCM.

    Returns an envelope dict:
        algorithm   — "AES-256-GCM"
        kdf         — "argon2id"
        salt        — hex-encoded 16-byte salt
        nonce       — hex-encoded 12-byte nonce
        ciphertext  — hex-encoded ciphertext (includes GCM tag)
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, priv_hex.encode("utf-8"), None)
    return {
        "algorithm": "AES-256-GCM",
        "kdf": "argon2id",
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
    }


def decrypt_private_key(envelope: dict, password: str) -> str:
    """
    Decrypt an encrypted private key envelope.
    Returns the hex-encoded private key.
    Raises ValueError on wrong password or corrupted data.
    """
    salt = bytes.fromhex(envelope["salt"])
    nonce = bytes.fromhex(envelope["nonce"])
    ciphertext = bytes.fromhex(envelope["ciphertext"])
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception:
        raise ValueError("Decryption failed — wrong password or corrupted data")


def is_encrypted(pid_data: dict) -> bool:
    """Check if a PID's private key is stored encrypted."""
    return isinstance(pid_data.get("private_key"), dict)


# ---------------------------------------------------------------------------
# Key Extraction
# ---------------------------------------------------------------------------
def _key_to_bytes(private_key: Ed25519PrivateKey) -> tuple[bytes, bytes]:
    """Extract raw private and public key bytes."""
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_bytes, pub_bytes


# ---------------------------------------------------------------------------
# PID Generation
# ---------------------------------------------------------------------------
def generate_pid(password: str = None) -> dict:
    """
    Generate a new Pillar ID.

    Args:
        password: If provided, the private key will be encrypted at rest.

    Returns dict:
        pid          — hex string, SHA-256 of public key (unique node identity)
        public_key   — hex-encoded Ed25519 public key
        private_key  — hex string (plaintext) OR encrypted envelope dict
        created_at   — unix timestamp
        protocol     — protocol version string
        key_store    — "software" (future: "hsm")
    """
    private_key = Ed25519PrivateKey.generate()
    priv_bytes, pub_bytes = _key_to_bytes(private_key)

    pid_hash = hashlib.sha256(pub_bytes).hexdigest()

    priv_field = priv_bytes.hex()
    if password:
        priv_field = encrypt_private_key(priv_field, password)

    return {
        "pid": pid_hash,
        "public_key": pub_bytes.hex(),
        "private_key": priv_field,
        "created_at": int(time.time()),
        "protocol": "REFInet-v0.2",
        "key_store": "software",
    }


# ---------------------------------------------------------------------------
# PID Persistence
# ---------------------------------------------------------------------------
def save_pid(pid_data: dict, path: Path = None):
    """Persist PID to disk."""
    if path is None:
        path = PID_FILE
    ensure_dirs()
    with open(path, "w") as f:
        json.dump(pid_data, f, indent=2)


def load_pid(path: Path = None) -> dict | None:
    """Load existing PID from disk, or return None."""
    if path is None:
        path = PID_FILE
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def get_or_create_pid(password: str = None) -> dict:
    """Load existing PID or generate a new one on first run."""
    existing = load_pid()
    if existing:
        return existing
    pid_data = generate_pid(password=password)
    save_pid(pid_data)
    return pid_data


def encrypt_existing_pid(pid_data: dict, password: str) -> dict:
    """
    Encrypt an existing plaintext PID.
    Returns a new pid_data dict with the private key encrypted.
    """
    if is_encrypted(pid_data):
        raise ValueError("PID is already encrypted")
    priv_hex = pid_data["private_key"]
    encrypted = encrypt_private_key(priv_hex, password)
    result = dict(pid_data)
    result["private_key"] = encrypted
    return result


# ---------------------------------------------------------------------------
# Key Access
# ---------------------------------------------------------------------------
def get_private_key(pid_data: dict, password: str = None) -> Ed25519PrivateKey:
    """
    Reconstruct Ed25519 private key from stored PID data.
    If the key is encrypted, a password is required.
    """
    priv_field = pid_data["private_key"]
    if isinstance(priv_field, dict):
        # Encrypted key
        if not password:
            raise ValueError("PID is encrypted — password required")
        priv_hex = decrypt_private_key(priv_field, password)
    else:
        priv_hex = priv_field
    priv_bytes = bytes.fromhex(priv_hex)
    return Ed25519PrivateKey.from_private_bytes(priv_bytes)


def get_short_pid(pid_data: dict) -> str:
    """Return a short display version of the PID (first 16 chars)."""
    return pid_data["pid"][:16]
