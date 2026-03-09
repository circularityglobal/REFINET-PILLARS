"""
REFInet Pillar — Encrypted Personal Vault

Provides encrypted file storage for personal credentials, keys, and documents.
Files are encrypted with AES-256-GCM using Argon2id-derived keys (reuses
the same encryption primitives as PID key storage).

Each item is stored as:
  ~/.refinet/vault/{sha256(name)}.vault  — encrypted file data
  vault_items SQLite table              — metadata (name, hash, size, pid)

All vault operations require authentication (SIWE session).
"""

from __future__ import annotations

import hashlib
import os
import uuid
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from core.config import VAULT_DIR, DB_DIR, ensure_dirs
from crypto.pid import encrypt_private_key, decrypt_private_key


LIVE_DB_PATH = DB_DIR / "live.db"


@contextmanager
def _connect():
    ensure_dirs()
    conn = sqlite3.connect(str(LIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def _item_path(name: str) -> Path:
    """Compute the filesystem path for a vault item."""
    name_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return VAULT_DIR / f"{name_hash}.vault"


def _encrypt_data(data: bytes, password: str) -> bytes:
    """Encrypt arbitrary data using the same AES-256-GCM scheme as PID encryption."""
    envelope = encrypt_private_key(data.hex(), password)
    # Serialize envelope to JSON bytes for storage
    import json
    return json.dumps(envelope).encode("utf-8")


def _decrypt_data(encrypted_bytes: bytes, password: str) -> bytes:
    """Decrypt vault data."""
    import json
    envelope = json.loads(encrypted_bytes.decode("utf-8"))
    hex_data = decrypt_private_key(envelope, password)
    return bytes.fromhex(hex_data)


def store_item(name: str, data: bytes, password: str, pid: str,
               mime_type: str = "application/octet-stream") -> dict:
    """
    Store an encrypted item in the vault.

    Args:
        name: Item name (must be unique per PID)
        data: Raw bytes to encrypt and store
        password: Encryption password
        pid: Owner's Pillar ID
        mime_type: MIME type for the stored data

    Returns:
        Dict with item_id, name, file_hash, size_bytes

    Raises:
        ValueError: If an item with the same name already exists
    """
    ensure_dirs()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    item_id = f"vault_{uuid.uuid4().hex[:16]}"
    file_path = _item_path(name)

    # Encrypt and write
    encrypted = _encrypt_data(data, password)
    file_hash = hashlib.sha256(encrypted).hexdigest()

    file_path.write_bytes(encrypted)

    # Record metadata in SQLite
    with _connect() as conn:
        try:
            conn.execute(
                """INSERT INTO vault_items
                   (item_id, name, file_hash, size_bytes, mime_type, pid)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, name, file_hash, len(data), mime_type, pid),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            file_path.unlink(missing_ok=True)
            raise ValueError(f"Vault item '{name}' already exists")

    return {
        "item_id": item_id,
        "name": name,
        "file_hash": file_hash,
        "size_bytes": len(data),
    }


def retrieve_item(name: str, password: str) -> bytes:
    """
    Retrieve and decrypt an item from the vault.

    Args:
        name: Item name
        password: Decryption password

    Returns:
        Decrypted bytes

    Raises:
        FileNotFoundError: If item doesn't exist
        ValueError: If decryption fails (wrong password)
    """
    file_path = _item_path(name)
    if not file_path.exists():
        raise FileNotFoundError(f"Vault item '{name}' not found")

    encrypted = file_path.read_bytes()
    return _decrypt_data(encrypted, password)


def list_items(pid: str = None) -> list[dict]:
    """
    List all vault items (metadata only, no decryption).

    Args:
        pid: Filter by owner PID (optional)

    Returns:
        List of dicts with item_id, name, file_hash, size_bytes, mime_type, created_at
    """
    with _connect() as conn:
        if pid:
            rows = conn.execute(
                "SELECT * FROM vault_items WHERE pid=? ORDER BY created_at DESC",
                (pid,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vault_items ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def delete_item(name: str, pid: str):
    """
    Delete a vault item (both file and metadata).

    Args:
        name: Item name
        pid: Owner's PID (must match)

    Raises:
        FileNotFoundError: If item doesn't exist
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT item_id FROM vault_items WHERE name=? AND pid=?",
            (name, pid),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Vault item '{name}' not found for this PID")

        conn.execute("DELETE FROM vault_items WHERE item_id=?", (row["item_id"],))
        conn.commit()

    file_path = _item_path(name)
    file_path.unlink(missing_ok=True)


def get_vault_stats(pid: str) -> dict:
    """Get summary statistics for a PID's vault."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as total_bytes "
            "FROM vault_items WHERE pid=?",
            (pid,),
        ).fetchone()
        return {
            "item_count": row["count"],
            "total_bytes": row["total_bytes"],
        }
