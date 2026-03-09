"""
REFInet Pillar — Blockchain-Style Hash Chain Audit Log

Every significant database operation is appended to an immutable,
cryptographically linked audit log. Each entry contains:
  - prev_hash: hash of the previous entry (forming a chain)
  - entry_hash: SHA-256(prev_hash + record_hash + table + op + timestamp)
  - signature: Ed25519 signature of entry_hash by the Pillar's PID

The chain can be verified end-to-end at any time:
  verify_chain() walks from entry 1, checking each link.

Genesis entry uses prev_hash = "0" * 64 (64-char zero hash).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from core.config import DB_DIR, ensure_dirs

LIVE_DB_PATH = DB_DIR / "live.db"
GENESIS_HASH = "0" * 64


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


def get_last_hash() -> str:
    """Fetch the most recent entry_hash from the audit log, or genesis hash."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row["entry_hash"] if row else GENESIS_HASH


def _compute_entry_hash(prev_hash: str, record_hash: str, table_name: str,
                        operation: str, timestamp: str) -> str:
    """Compute the entry hash that links this entry to the chain."""
    payload = f"{prev_hash}:{record_hash}:{table_name}:{operation}:{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_record_hash(record_data: dict) -> str:
    """Compute a deterministic hash of a record's data."""
    canonical = json.dumps(record_data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_audit_entry(table_name: str, operation: str, record_key: str,
                       record_data: dict, pid: str, private_key) -> str:
    """
    Append a new entry to the audit chain.

    Args:
        table_name: Source table (e.g., 'gopherholes', 'daily_tx')
        operation: SQL operation ('INSERT', 'UPDATE', 'DELETE')
        record_key: Primary key of the affected record
        record_data: Dict of the record's field values
        pid: Pillar ID creating this entry
        private_key: Ed25519PrivateKey for signing

    Returns:
        The entry_hash of the new audit entry.
    """
    from crypto.signing import sign_content

    timestamp = datetime.now(timezone.utc).isoformat()
    record_hash = _compute_record_hash(record_data)

    with _connect() as conn:
        # Get the previous hash (must be atomic with insert)
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = row["entry_hash"] if row else GENESIS_HASH

        # Compute chain link
        entry_hash = _compute_entry_hash(
            prev_hash, record_hash, table_name, operation, timestamp
        )

        # Sign the entry hash
        signature = sign_content(entry_hash.encode("utf-8"), private_key)

        conn.execute(
            """INSERT INTO audit_log
               (prev_hash, entry_hash, table_name, operation, record_key,
                record_hash, pid, signature, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (prev_hash, entry_hash, table_name, operation, record_key,
             record_hash, pid, signature, timestamp),
        )
        conn.commit()

    return entry_hash


def verify_chain(limit: int = 0) -> tuple[bool, int, str]:
    """
    Verify the integrity of the entire audit chain.

    Args:
        limit: Maximum entries to verify (0 = all)

    Returns:
        (is_valid, entries_verified, error_message)
    """
    with _connect() as conn:
        query = "SELECT * FROM audit_log ORDER BY seq ASC"
        if limit > 0:
            query += f" LIMIT {limit}"
        rows = conn.execute(query).fetchall()

    if not rows:
        return (True, 0, "")

    expected_prev = GENESIS_HASH
    verified = 0

    for row in rows:
        # Check prev_hash linkage
        if row["prev_hash"] != expected_prev:
            return (False, verified,
                    f"Chain broken at seq {row['seq']}: "
                    f"expected prev_hash={expected_prev[:16]}..., "
                    f"got {row['prev_hash'][:16]}...")

        # Recompute entry_hash
        recomputed = _compute_entry_hash(
            row["prev_hash"], row["record_hash"],
            row["table_name"], row["operation"], row["created_at"]
        )
        if recomputed != row["entry_hash"]:
            return (False, verified,
                    f"Hash mismatch at seq {row['seq']}: "
                    f"stored={row['entry_hash'][:16]}..., "
                    f"computed={recomputed[:16]}...")

        expected_prev = row["entry_hash"]
        verified += 1

    return (True, verified, "")


def verify_entry_signature(entry: dict, public_key_hex: str) -> bool:
    """Verify the Ed25519 signature on an audit entry."""
    from crypto.signing import verify_signature
    return verify_signature(
        entry["entry_hash"].encode("utf-8"),
        entry["signature"],
        public_key_hex,
    )


def get_recent_entries(limit: int = 20) -> list[dict]:
    """Get the most recent audit log entries."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_chain_length() -> int:
    """Return the total number of entries in the audit chain."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM audit_log").fetchone()
        return row["cnt"]
