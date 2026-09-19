"""
REFInet Pillar — In-process key unlock cache

An encrypted PID needs its password once per process. The password is
never written to disk: it is used to decrypt the key, and the decrypted
key object is held here, in memory, for the life of the process.

Plaintext PIDs bypass the cache entirely (``get_unlocked_key`` falls back
to ``get_private_key``), so their behaviour is unchanged.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from crypto.pid import get_private_key, is_encrypted

_UNLOCKED: dict[str, Ed25519PrivateKey] = {}


def unlock(pid_data: dict, password: str | None) -> Ed25519PrivateKey:
    """Decrypt the PID's key with *password* and cache it for this process.

    Raises ValueError on a wrong or missing password.
    """
    key = get_private_key(pid_data, password=password)
    _UNLOCKED[pid_data["pid"]] = key
    return key


def is_unlocked(pid_data: dict) -> bool:
    """True when the key is usable without a password right now."""
    return not is_encrypted(pid_data) or pid_data["pid"] in _UNLOCKED


def get_unlocked_key(pid_data: dict) -> Ed25519PrivateKey:
    """Return the Pillar's private key without asking for a password.

    Plaintext PIDs are read directly. Encrypted PIDs must have been passed
    to ``unlock`` earlier in this process; otherwise ValueError is raised
    with the same message ``get_private_key`` uses.
    """
    if not is_encrypted(pid_data):
        return get_private_key(pid_data)
    key = _UNLOCKED.get(pid_data["pid"])
    if key is None:
        raise ValueError("PID is encrypted — password required")
    return key


def lock_all() -> None:
    """Forget every unlocked key (tests, and explicit lock)."""
    _UNLOCKED.clear()
