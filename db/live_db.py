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


def _add_missing_columns(conn, table: str, columns: list[tuple[str, str]]):
    """ALTER TABLE ADD COLUMN for any column that is not there yet."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


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
        ("evm_address", "TEXT"),
    ]
    for col_name, col_def in peer_migrations:
        if col_name not in existing_peers:
            conn.execute(f"ALTER TABLE peers ADD COLUMN {col_name} {col_def}")

    # Token state table migrations
    existing_token = {row[1] for row in conn.execute("PRAGMA table_info(token_state)").fetchall()}
    if "license_tier" not in existing_token:
        conn.execute("ALTER TABLE token_state ADD COLUMN license_tier TEXT DEFAULT 'free'")

    # Columns added in 0.5.0. Amounts move to integer base units stored as
    # TEXT: a float cannot hold 1e18 exactly, and SQLite INTEGER overflows
    # above 2^63. The old REAL columns stay so existing readers keep working.
    _add_missing_columns(conn, "daily_metrics", [
        ("requests_served", "INTEGER DEFAULT 0"),
    ])
    _add_missing_columns(conn, "daily_tx", [
        ("amount_units", "TEXT"), ("asset_chain_id", "INTEGER"),
        ("asset_address", "TEXT"), ("asset_decimals", "INTEGER"),
    ])
    _add_missing_columns(conn, "settlements", [
        ("amount_units", "TEXT"), ("asset_chain_id", "INTEGER"),
        ("asset_address", "TEXT"), ("asset_decimals", "INTEGER"),
    ])
    _add_missing_columns(conn, "token_state", [
        ("cifi_staked_units", "TEXT"), ("refi_balance_units", "TEXT"),
        ("refi_issued_units", "TEXT"),
    ])
    _add_missing_columns(conn, "peers", [("stake_units", "TEXT")])
    _add_missing_columns(conn, "service_proofs", [
        ("requester_pid", "TEXT"), ("requester_pubkey", "TEXT"),
        ("resource", "TEXT"), ("receipt_json", "TEXT"),
    ])

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
    amount_units: str | int = None,
    asset: dict = None,
) -> str:
    """
    Record a DApp transaction in the live ledger.
    Returns the generated tx_id.

    Amounts belong in *amount_units*: an integer number of the asset's
    smallest unit, stored as text. *asset* is
    ``{"chain_id": int, "address": "0x…", "decimals": int}``. The float
    ``amount`` column is kept only for readers written before 0.5.0.
    """
    tx_id = f"tx_{uuid.uuid4().hex[:16]}"
    day, month, year = get_accounting_date()
    asset = asset or {}

    with _connect() as conn:
        conn.execute(
            """INSERT INTO daily_tx
               (tx_id, dapp_id, pid, amount, amount_units, asset_chain_id,
                asset_address, asset_decimals, token_type, selector,
                mesh_peer_pid, content_hash, signature,
                accounting_day, accounting_month, accounting_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_id, dapp_id, pid, amount,
             None if amount_units is None else str(amount_units),
             asset.get("chain_id"), asset.get("address"), asset.get("decimals"),
             token_type, selector,
             mesh_peer_pid, content_hash, signature, day, month, year),
        )
        conn.commit()
    return tx_id


# ---------------------------------------------------------------------------
# SIWE nonce registry
#
# A challenge is only valid if this Pillar issued it, for the purpose it was
# issued for, and has not been used. The nonce is spent on first use whether
# or not the signature turns out to verify.
# ---------------------------------------------------------------------------
def record_siwe_nonce(nonce: str, purpose: str, pid: str, address: str = None,
                      chain_id: int = None, ttl_seconds: int = 900) -> None:
    """Register a nonce this Pillar just issued."""
    from datetime import timedelta, timezone as _tz
    now = datetime.now(_tz.utc)
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO siwe_nonces
               (nonce, purpose, pid, address, chain_id, issued_at, expires_at, spent_at)
               VALUES (?,?,?,?,?,?,?,NULL)""",
            (nonce, purpose, pid, address, chain_id, now.isoformat(),
             (now + timedelta(seconds=ttl_seconds)).isoformat()),
        )
        conn.commit()


def consume_siwe_nonce(nonce: str, purpose: str, pid: str) -> tuple[bool, str]:
    """Spend a nonce. Returns (ok, reason).

    The nonce must exist, belong to this Pillar, have been issued for
    *purpose*, be unspent and unexpired. It is marked spent on the first
    attempt, successful or not.
    """
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    if not nonce:
        return (False, "message carries no nonce")
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM siwe_nonces WHERE nonce=?", (nonce,)
        ).fetchone()
        if row is None:
            return (False, "nonce was not issued by this Pillar")
        # Spend it before judging it — one attempt per challenge.
        conn.execute(
            "UPDATE siwe_nonces SET spent_at=? WHERE nonce=? AND spent_at IS NULL",
            (now.isoformat(), nonce),
        )
        conn.commit()
        if row["spent_at"] is not None:
            return (False, "nonce already used")
        if row["pid"] != pid:
            return (False, "nonce was issued by a different Pillar")
        if row["purpose"] != purpose:
            return (False,
                    f"nonce was issued for '{row['purpose']}', not '{purpose}'")
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_tz.utc)
        if now > expires:
            return (False, "challenge expired")
    return (True, "ok")


def purge_expired_siwe_nonces(older_than_days: int = 7) -> int:
    """Drop spent/expired nonces so the table cannot grow without bound."""
    from datetime import timedelta, timezone as _tz
    cutoff = (datetime.now(_tz.utc) - timedelta(days=older_than_days)).isoformat()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM siwe_nonces WHERE expires_at < ?", (cutoff,))
        conn.commit()
        return cur.rowcount


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
                port: int = 7070, pillar_name: str = None,
                protocol_version: str = None, evm_address: str = None):
    """Register or update a peer in the live DB."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO peers (pid, public_key, hostname, port, last_seen,
                                  pillar_name, protocol_version, evm_address)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
               ON CONFLICT(pid) DO UPDATE SET
                   hostname=excluded.hostname,
                   port=excluded.port,
                   last_seen=CURRENT_TIMESTAMP,
                   pillar_name=excluded.pillar_name,
                   protocol_version=excluded.protocol_version,
                   evm_address=COALESCE(excluded.evm_address, evm_address)""",
            (pid, public_key, hostname, port, pillar_name, protocol_version,
             evm_address),
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
def increment_requests_served(pid: str, count: int = 1) -> None:
    """Count one served request against today's rollup.

    Serving used to write a daily_tx row per request, which any stranger
    could use to fill the disk (the rate limit is per IP, and IPs are free)
    and which buried real transactions in request noise. The volume lives
    in daily_metrics instead; daily_tx is for transactions.
    """
    day, month, year = get_accounting_date()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO daily_metrics
                   (accounting_day, accounting_month, accounting_year, pid,
                    requests_served)
               VALUES (?,?,?,?,?)
               ON CONFLICT(accounting_day, accounting_month, accounting_year, pid)
               DO UPDATE SET requests_served = requests_served + ?""",
            (day, month, year, pid, count, count),
        )
        conn.commit()


def get_tx_count_today(pid: str) -> int:
    """Requests + transactions recorded today for this Pillar.

    Kept equivalent to the pre-0.5.0 number that status.json and the root
    menu report: requests come from the rollup counter, and rows written by
    DApps (and by older releases, which logged serving as 'gopher.core')
    still count.
    """
    day, month, year = get_accounting_date()
    with _connect() as conn:
        served = conn.execute(
            """SELECT requests_served AS cnt FROM daily_metrics
               WHERE accounting_day=? AND accounting_month=? AND accounting_year=?
                 AND pid=?""",
            (day, month, year, pid),
        ).fetchone()
        tx = conn.execute(
            """SELECT COUNT(*) as cnt FROM daily_tx
               WHERE accounting_day=? AND accounting_month=? AND accounting_year=?
                 AND pid=? AND dapp_id != 'gopher.core'""",
            (day, month, year, pid),
        ).fetchone()
    return ((served["cnt"] or 0) if served else 0) + (tx["cnt"] if tx else 0)


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
                         proof_hash: str, signature: str,
                         requester_pid: str = None, requester_pubkey: str = None,
                         resource: str = None, receipt_json: str = None,
                         idempotent: bool = False) -> bool:
    """Insert a service proof into the immutable ledger.

    *signature* is the requester's signature over the receipt. A proof the
    serving Pillar signed for itself is an assertion, not work anyone will
    pay for, so nothing in the serving path writes one any more.

    With *idempotent*, re-submitting a receipt that is already stored is a
    no-op rather than another row. Returns True when a row was written.
    """
    verb = "INSERT OR IGNORE INTO" if idempotent else "INSERT INTO"
    with _connect() as conn:
        cur = conn.execute(
            f"""{verb} service_proofs
                   (proof_id, pid, service, proof_hash, signature,
                    requester_pid, requester_pubkey, resource, receipt_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proof_id, pid, service, proof_hash, signature,
             requester_pid, requester_pubkey, resource, receipt_json),
        )
        conn.commit()
        return cur.rowcount > 0


def count_service_proofs_today(pid: str = None, requester_pid: str = None) -> int:
    """Receipts recorded since midnight, optionally for one requester.

    service_proofs is append-only and undeletable, so intake has to be
    bounded: signatures are cheap and identities are free.
    """
    clauses, params = ["created_at >= date('now')"], []
    if pid:
        clauses.append("pid = ?"); params.append(pid)
    if requester_pid:
        clauses.append("requester_pid = ?"); params.append(requester_pid)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM service_proofs WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0


def count_service_proofs(pid: str = None) -> int:
    """How many counter-signed receipts this Pillar holds."""
    with _connect() as conn:
        if pid:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM service_proofs WHERE pid=?", (pid,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM service_proofs").fetchone()
        return row["cnt"] if row else 0


def checkpoint_live_db():
    """Run a WAL checkpoint to prevent journal file accumulation."""
    with _connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def ensure_refinet_gopherhole(pid_data: dict) -> None:
    """Register the built-in REFInet gopherhole if not already present.

    Idempotent — safe to call on every startup.  Checks by PID + selector
    so each Pillar carries exactly one ``/holes/refinet`` registration.
    """
    pid = pid_data["pid"]
    selector = "/holes/refinet"

    if gopherhole_exists(pid, selector):
        return

    pubkey_hex = pid_data["public_key"]
    name = "REFInet"
    description = (
        "REFInet products, documentation, and community "
        "\u2014 the reference gopherhole"
    )

    day, month, year = get_accounting_date()
    registered_at = f"{year}-{month:02d}-{day:02d}"

    try:
        from crypto.unlock import get_unlocked_key
        from crypto.signing import sign_content

        private_key = get_unlocked_key(pid_data)
        signing_payload = f"{pid}:{selector}:{name}:{registered_at}"
        signature = sign_content(signing_payload.encode(), private_key)
    except (ValueError, ImportError, Exception):
        return  # Cannot sign — skip silently

    try:
        register_gopherhole(
            pid=pid,
            selector=selector,
            name=name,
            description=description,
            owner_address="",
            pubkey_hex=pubkey_hex,
            signature=signature,
            source="local",
            registered_at=registered_at,
        )
    except Exception:
        pass  # UNIQUE constraint = already exists, harmless


def gopherhole_exists(pid: str, selector: str) -> bool:
    """Check existence without fetching full record."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM gopherholes WHERE pid=? AND selector=?",
            (pid, selector),
        ).fetchone()
        return row is not None
