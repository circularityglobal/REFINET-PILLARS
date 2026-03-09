"""
REFInet Pillar — Live Database Manager

Manages the 13-month rolling transaction ledger.
All DApp transactions, metrics, peer records, and content indexes live here.

Accounting calendar:
  - 13 months × 28 days = 364 days
  - Day 365 = accounting balance day (reconciliation)
"""

from __future__ import annotations

import sqlite3
import uuid
import time
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

from core.config import DB_DIR, ensure_dirs, ACCOUNTING_DAYS_PER_MONTH, ACCOUNTING_MONTHS_PER_YEAR
from db.schema import LIVE_SCHEMA


LIVE_DB_PATH = DB_DIR / "live.db"


@contextmanager
def _connect():
    ensure_dirs()
    conn = sqlite3.connect(str(LIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_live_db():
    """Create the live database and all tables, migrating if needed."""
    with _connect() as conn:
        conn.executescript(LIVE_SCHEMA)
        conn.commit()
        _migrate_live_db(conn)


def _migrate_live_db(conn):
    """Add any columns that were added after initial schema creation."""
    # Peers table migrations
    existing_peers = {row[1] for row in conn.execute("PRAGMA table_info(peers)").fetchall()}
    peer_migrations = [
        ("status", "TEXT DEFAULT 'unknown'"),
        ("latency_ms", "REAL"),
        ("consecutive_failures", "INTEGER DEFAULT 0"),
        ("last_checked", "DATETIME"),
        ("onion_address", "TEXT"),
    ]
    for col_name, col_def in peer_migrations:
        if col_name not in existing_peers:
            conn.execute(f"ALTER TABLE peers ADD COLUMN {col_name} {col_def}")

    # Token state table migrations
    existing_token = {row[1] for row in conn.execute("PRAGMA table_info(token_state)").fetchall()}
    if "license_tier" not in existing_token:
        conn.execute("ALTER TABLE token_state ADD COLUMN license_tier TEXT DEFAULT 'free'")

    conn.commit()


# ---------------------------------------------------------------------------
# Accounting Calendar Helpers
# ---------------------------------------------------------------------------
def get_accounting_date(dt: datetime = None) -> tuple[int, int, int]:
    """
    Convert a datetime to REFInet accounting (day, month, year).

    REFInet calendar:
      - Year starts Jan 1
      - 13 months of 28 days each
      - Day 365 (or 366 in leap year) = balance day (mapped to month 13, day 28)

    Returns: (accounting_day, accounting_month, accounting_year)
    """
    if dt is None:
        dt = datetime.now()

    year = dt.year
    day_of_year = dt.timetuple().tm_yday  # 1..365/366

    if day_of_year > 364:
        # Balance day(s) — map to end of month 13
        return (28, 13, year)

    # Zero-index for calculation
    zero_day = day_of_year - 1
    month = (zero_day // ACCOUNTING_DAYS_PER_MONTH) + 1
    day = (zero_day % ACCOUNTING_DAYS_PER_MONTH) + 1

    return (day, month, year)


def format_accounting_date(dt: datetime = None) -> str:
    """Human-readable string combining Gregorian and REFInet accounting date.

    Example: ``"2026-03-02 (REFInet Y2026 M3 D2)"``
    """
    if dt is None:
        dt = datetime.now()
    day, month, year = get_accounting_date(dt)
    gregorian = dt.strftime("%Y-%m-%d")
    return f"{gregorian} (REFInet Y{year} M{month} D{day})"


# ---------------------------------------------------------------------------
# Transaction Recording
# ---------------------------------------------------------------------------
def record_transaction(
    dapp_id: str,
    pid: str,
    amount: float = 0.0,
    token_type: str = "REFI",
    selector: str = None,
    mesh_peer_pid: str = None,
    content_hash: str = None,
    signature: str = None,
) -> str:
    """
    Record a DApp transaction in the live ledger.
    Returns the generated tx_id.
    """
    tx_id = f"tx_{uuid.uuid4().hex[:16]}"
    day, month, year = get_accounting_date()

    with _connect() as conn:
        conn.execute(
            """INSERT INTO daily_tx
               (tx_id, dapp_id, pid, amount, token_type, selector,
                mesh_peer_pid, content_hash, signature,
                accounting_day, accounting_month, accounting_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_id, dapp_id, pid, amount, token_type, selector,
             mesh_peer_pid, content_hash, signature, day, month, year),
        )
        conn.commit()
    return tx_id


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def update_daily_metrics(pid: str, **kwargs):
    """
    Upsert daily metrics for the current accounting day.
    kwargs can include: total_tx_count, total_volume, avg_latency_ms,
                        peers_connected, content_served, uptime_seconds
    """
    day, month, year = get_accounting_date()
    with _connect() as conn:
        # Check if row exists
        row = conn.execute(
            """SELECT * FROM daily_metrics
               WHERE accounting_day=? AND accounting_month=? AND accounting_year=? AND pid=?""",
            (day, month, year, pid),
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO daily_metrics
                   (accounting_day, accounting_month, accounting_year, pid,
                    total_tx_count, total_volume, avg_latency_ms,
                    peers_connected, content_served, uptime_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (day, month, year, pid,
                 kwargs.get("total_tx_count", 0),
                 kwargs.get("total_volume", 0.0),
                 kwargs.get("avg_latency_ms", 0.0),
                 kwargs.get("peers_connected", 0),
                 kwargs.get("content_served", 0),
                 kwargs.get("uptime_seconds", 0)),
            )
        else:
            sets = []
            vals = []
            for key in ("total_tx_count", "total_volume", "avg_latency_ms",
                         "peers_connected", "content_served", "uptime_seconds"):
                if key in kwargs:
                    sets.append(f"{key} = ?")
                    vals.append(kwargs[key])
            if sets:
                vals.extend([day, month, year, pid])
                conn.execute(
                    f"UPDATE daily_metrics SET {', '.join(sets)} "
                    "WHERE accounting_day=? AND accounting_month=? AND accounting_year=? AND pid=?",
                    vals,
                )

        conn.commit()


# ---------------------------------------------------------------------------
# Peer Management
# ---------------------------------------------------------------------------
def upsert_peer(pid: str, public_key: str, hostname: str = None,
                port: int = 7070, pillar_name: str = None, protocol_version: str = None):
    """Register or update a peer in the live DB."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO peers (pid, public_key, hostname, port, last_seen, pillar_name, protocol_version)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
               ON CONFLICT(pid) DO UPDATE SET
                   hostname=excluded.hostname,
                   port=excluded.port,
                   last_seen=CURRENT_TIMESTAMP,
                   pillar_name=excluded.pillar_name,
                   protocol_version=excluded.protocol_version""",
            (pid, public_key, hostname, port, pillar_name, protocol_version),
        )
        conn.commit()


def get_peers() -> list[dict]:
    """Return all known peers."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM peers ORDER BY last_seen DESC").fetchall()
        return [dict(r) for r in rows]


def reset_peer_statuses_to_unknown():
    """Mark all peers as unknown on startup so health checks start fresh."""
    with _connect() as conn:
        conn.execute("UPDATE peers SET status='unknown', latency_ms=NULL")
        conn.commit()


def update_peer_health(pid: str, latency_ms: float | None):
    """
    Update a peer's health status after a ping check.

    Status logic:
      online   — ping succeeded, latency < 2000ms
      degraded — ping succeeded but slow (>= 2000ms), or 1-4 consecutive failures
      offline  — 5+ consecutive failures
      unknown  — never checked (default)
    """
    with _connect() as conn:
        if latency_ms is not None:
            status = "online" if latency_ms < 2000 else "degraded"
            conn.execute(
                """UPDATE peers SET
                       status=?, latency_ms=?, consecutive_failures=0,
                       last_checked=CURRENT_TIMESTAMP
                   WHERE pid=?""",
                (status, latency_ms, pid),
            )
        else:
            row = conn.execute(
                "SELECT consecutive_failures FROM peers WHERE pid=?", (pid,)
            ).fetchone()
            failures = (row["consecutive_failures"] or 0) + 1 if row else 1
            status = "offline" if failures >= 5 else "degraded"
            conn.execute(
                """UPDATE peers SET
                       status=?, latency_ms=NULL, consecutive_failures=?,
                       last_checked=CURRENT_TIMESTAMP
                   WHERE pid=?""",
                (status, failures, pid),
            )
        conn.commit()


def update_peer_onion(pid: str, onion_address: str):
    """Store a peer's .onion address."""
    with _connect() as conn:
        conn.execute(
            "UPDATE peers SET onion_address = ? WHERE pid = ?",
            (onion_address, pid),
        )
        conn.commit()


def get_peer_onion(pid: str) -> str | None:
    """Retrieve a peer's .onion address, or None if not set."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT onion_address FROM peers WHERE pid = ?", (pid,)
        ).fetchone()
        return row["onion_address"] if row and row["onion_address"] else None


# ---------------------------------------------------------------------------
# Content Index
# ---------------------------------------------------------------------------
def index_content(selector: str, content_type: str, content_hash: str,
                  signature: str, pid: str, size_bytes: int = 0):
    """Index a piece of served content."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO content_index
               (selector, content_type, content_hash, signature, pid, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(selector) DO UPDATE SET
                   content_hash=excluded.content_hash,
                   signature=excluded.signature,
                   size_bytes=excluded.size_bytes,
                   updated_at=CURRENT_TIMESTAMP""",
            (selector, content_type, content_hash, signature, pid, size_bytes),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Query Helpers
# ---------------------------------------------------------------------------
def get_tx_count_today(pid: str) -> int:
    """Get transaction count for the current accounting day."""
    day, month, year = get_accounting_date()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM daily_tx WHERE accounting_day=? AND accounting_month=? AND accounting_year=? AND pid=?",
            (day, month, year, pid),
        ).fetchone()
        return row["cnt"] if row else 0


def get_replication_rejections_today() -> int:
    """Count replication rejections recorded today."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM daily_tx "
            "WHERE dapp_id='mesh.replication' AND created_at >= date('now')"
        ).fetchone()
        return row["cnt"] if row else 0


def search_content(query: str, limit: int = 20) -> list[dict]:
    """Search the content index and gopherholes by substring match."""
    results = []
    pattern = f"%{query}%"
    with _connect() as conn:
        # Search content_index
        rows = conn.execute(
            "SELECT selector, content_type FROM content_index "
            "WHERE selector LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
        for r in rows:
            results.append({"selector": r["selector"], "name": r["selector"],
                            "source": "content_index"})

        # Search gopherholes
        rows = conn.execute(
            "SELECT selector, name, description FROM gopherholes "
            "WHERE name LIKE ? OR description LIKE ? ORDER BY registered_at DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
        for r in rows:
            results.append({"selector": r["selector"], "name": r["name"],
                            "source": "gopherholes"})
    return results


def get_recent_transactions(pid: str, limit: int = 20) -> list[dict]:
    """Get most recent transactions for this Pillar."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_tx WHERE pid=? ORDER BY created_at DESC LIMIT ?",
            (pid, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Gopherhole Registry
# ---------------------------------------------------------------------------
def register_gopherhole(pid: str, selector: str, name: str, description: str,
                        owner_address: str, pubkey_hex: str, signature: str,
                        source: str = "local", registered_at: str = None) -> str:
    """
    Append a gopherhole record. Raises if pid+selector already exists.
    tx_hash = SHA-256 of canonical JSON of all fields.
    Returns the tx_hash.

    If registered_at is provided, it is used as-is (ensures the signature
    and DB record use the same date). Otherwise computed from accounting calendar.
    """
    if not registered_at:
        day, month, year = get_accounting_date()
        registered_at = f"{year}-{month:02d}-{day:02d}"

    record = {
        "pid": pid,
        "selector": selector,
        "name": name,
        "description": description,
        "owner_address": owner_address,
        "pubkey_hex": pubkey_hex,
        "signature": signature,
        "registered_at": registered_at,
        "source": source,
    }
    tx_hash = hashlib.sha256(
        json.dumps(record, sort_keys=True).encode()
    ).hexdigest()

    with _connect() as conn:
        conn.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, name, description, owner_address, pubkey_hex,
             signature, registered_at, tx_hash, source),
        )
        conn.commit()
    return tx_hash


def list_gopherholes(source_filter: str = None) -> list[dict]:
    """
    Returns all gopherholes. Optionally filter by source='local' or peer PID.
    """
    with _connect() as conn:
        if source_filter:
            rows = conn.execute(
                "SELECT * FROM gopherholes WHERE source=? ORDER BY registered_at DESC",
                (source_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM gopherholes ORDER BY registered_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_gopherhole(pid: str, selector: str) -> dict | None:
    """Fetch a specific gopherhole by pid+selector."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM gopherholes WHERE pid=? AND selector=?",
            (pid, selector),
        ).fetchone()
        return dict(row) if row else None


def get_license_tier(pid: str) -> str:
    """Return the license tier for a Pillar. Defaults to 'free'."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT license_tier FROM token_state WHERE pid=?", (pid,)
        ).fetchone()
        return row["license_tier"] if row else "free"


def insert_service_proof(proof_id: str, pid: str, service: str,
                         proof_hash: str, signature: str):
    """Insert a service proof into the immutable ledger."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO service_proofs (proof_id, pid, service, proof_hash, signature)
               VALUES (?, ?, ?, ?, ?)""",
            (proof_id, pid, service, proof_hash, signature),
        )
        conn.commit()


def checkpoint_live_db():
    """Run a WAL checkpoint to prevent journal file accumulation."""
    with _connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def gopherhole_exists(pid: str, selector: str) -> bool:
    """Check existence without fetching full record."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM gopherholes WHERE pid=? AND selector=?",
            (pid, selector),
        ).fetchone()
        return row is not None
