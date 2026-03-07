"""
REFInet Pillar — Pillar ID (PID) Management

Each Pillar gets a unique cryptographic identity on first run:
  - Ed25519 keypair (fast, compact, blockchain-friendly)
  - PID = hex-encoded hash of the public key
  - Used for: signing content, verifying peers, staking proofs, license entitlement

The PID is the foundation of trust in the REFInet mesh.
"""

import json
import hashlib
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from core.config import PID_FILE, ensure_dirs


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


def generate_pid() -> dict:
    """
    Generate a new Pillar ID.

    Returns dict:
        pid          — hex string, SHA-256 of public key (unique node identity)
        public_key   — hex-encoded Ed25519 public key
        private_key  — hex-encoded Ed25519 private key (KEEP SECRET)
        created_at   — unix timestamp
    """
    private_key = Ed25519PrivateKey.generate()
    priv_bytes, pub_bytes = _key_to_bytes(private_key)

    pid_hash = hashlib.sha256(pub_bytes).hexdigest()

    return {
        "pid": pid_hash,
        "public_key": pub_bytes.hex(),
        "private_key": priv_bytes.hex(),
        "created_at": int(time.time()),
        "protocol": "REFInet-v0.1",
    }


def save_pid(pid_data: dict, path: Path = PID_FILE):
    """Persist PID to disk."""
    ensure_dirs()
    with open(path, "w") as f:
        json.dump(pid_data, f, indent=2)


def load_pid(path: Path = PID_FILE) -> dict | None:
    """Load existing PID from disk, or return None."""
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def get_or_create_pid() -> dict:
    """Load existing PID or generate a new one on first run."""
    existing = load_pid()
    if existing:
        return existing
    pid_data = generate_pid()
    save_pid(pid_data)
    return pid_data


def get_private_key(pid_data: dict) -> Ed25519PrivateKey:
    """Reconstruct Ed25519 private key from stored PID data."""
    priv_bytes = bytes.fromhex(pid_data["private_key"])
    return Ed25519PrivateKey.from_private_bytes(priv_bytes)


def get_short_pid(pid_data: dict) -> str:
    """Return a short display version of the PID (first 16 chars)."""
    return pid_data["pid"][:16]
