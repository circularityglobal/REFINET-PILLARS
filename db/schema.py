"""
REFInet Pillar — SQLite Database Schemas

Two databases per Pillar:

1. LIVE DB  — 13 months × 28 accounting days of transaction + metrics data
2. ARCHIVE DB — Yearly compressed historical records

The 13-month / 28-day calendar:
  - 13 months × 28 days = 364 days
  - 1 accounting balance day to reconcile and generate metrics
  - Clean, predictable fiscal periods
"""

LIVE_SCHEMA = """
-- =========================================================================
-- LIVE DATABASE — Active ledger (13 months retention)
-- =========================================================================

-- Every DApp transaction on this Pillar
CREATE TABLE IF NOT EXISTS daily_tx (
    tx_id           TEXT PRIMARY KEY,
    dapp_id         TEXT NOT NULL,
    pid             TEXT NOT NULL,
    amount          REAL DEFAULT 0.0,
    token_type      TEXT DEFAULT 'REFI',   -- CIFI or REFI
    selector        TEXT,                   -- Gopher selector that triggered tx
    mesh_peer_pid   TEXT,                   -- Peer involved (if any)
    content_hash    TEXT,                   -- SHA-256 of associated content
    signature       TEXT,                   -- Ed25519 signature by originating PID
    accounting_day  INTEGER NOT NULL,       -- 1..28
    accounting_month INTEGER NOT NULL,      -- 1..13
    accounting_year INTEGER NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Daily productivity metrics (aggregated per accounting day)
CREATE TABLE IF NOT EXISTS daily_metrics (
    accounting_day   INTEGER NOT NULL,      -- 1..28
    accounting_month INTEGER NOT NULL,      -- 1..13
    accounting_year  INTEGER NOT NULL,
    pid              TEXT NOT NULL,
    total_tx_count   INTEGER DEFAULT 0,
    total_volume     REAL DEFAULT 0.0,
    avg_latency_ms   REAL DEFAULT 0.0,
    peers_connected  INTEGER DEFAULT 0,
    content_served   INTEGER DEFAULT 0,     -- Number of Gopher requests served
    uptime_seconds   INTEGER DEFAULT 0,
    PRIMARY KEY (accounting_day, accounting_month, accounting_year, pid)
);

-- Peer registry — nodes this Pillar has seen
CREATE TABLE IF NOT EXISTS peers (
    pid             TEXT PRIMARY KEY,
    public_key      TEXT NOT NULL,
    hostname        TEXT,
    port            INTEGER DEFAULT 7070,
    last_seen       DATETIME,
    stake_amount    REAL DEFAULT 0.0,
    pillar_name     TEXT,
    protocol_version TEXT,
    status           TEXT DEFAULT 'unknown',    -- online | degraded | offline | unknown
    latency_ms       REAL,
    consecutive_failures INTEGER DEFAULT 0,
    last_checked     DATETIME
);

-- Content index — what this Pillar serves via Gopher
CREATE TABLE IF NOT EXISTS content_index (
    selector        TEXT PRIMARY KEY,
    content_type    TEXT NOT NULL,           -- 'menu', 'text', 'binary', 'dapp'
    content_hash    TEXT,
    signature       TEXT,
    pid             TEXT NOT NULL,           -- Creator PID
    size_bytes      INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Token balances and staking state
CREATE TABLE IF NOT EXISTS token_state (
    pid             TEXT PRIMARY KEY,
    cifi_staked     REAL DEFAULT 0.0,
    refi_balance    REAL DEFAULT 0.0,
    refi_issued     REAL DEFAULT 0.0,
    license_active  INTEGER DEFAULT 0,      -- 1 = licensed, 0 = not
    license_tier    TEXT DEFAULT 'free',    -- free | pro | enterprise
    license_expires DATETIME,
    blockchain_tx   TEXT,                    -- On-chain staking tx reference
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_daily_tx_day
    ON daily_tx (accounting_year, accounting_month, accounting_day);
CREATE INDEX IF NOT EXISTS idx_daily_tx_pid
    ON daily_tx (pid);
CREATE INDEX IF NOT EXISTS idx_daily_tx_dapp
    ON daily_tx (dapp_id);
CREATE INDEX IF NOT EXISTS idx_content_pid
    ON content_index (pid);

-- =========================================================================
-- GOPHERHOLE REGISTRY — append-only, never mutate
-- =========================================================================
CREATE TABLE IF NOT EXISTS gopherholes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pid             TEXT NOT NULL,              -- registering pillar's PID
    selector        TEXT NOT NULL,              -- gopherspace path e.g. /holes/mysite
    name            TEXT NOT NULL,              -- display name
    description     TEXT DEFAULT '',
    owner_address   TEXT DEFAULT '',            -- EVM address (optional, SIWE Phase 3)
    pubkey_hex      TEXT NOT NULL,              -- pillar's Ed25519 public key (for verification)
    signature       TEXT NOT NULL,              -- Ed25519 sig of (pid+selector+name+registered_at)
    registered_at   TEXT NOT NULL,              -- REFInet accounting date YYYY-MM-DD
    tx_hash         TEXT NOT NULL,              -- SHA-256 of the full record
    source          TEXT DEFAULT 'local',       -- 'local' or peer PID (replicated from)
    UNIQUE(pid, selector)
);

-- Immutability enforced at DB level
CREATE TRIGGER IF NOT EXISTS gopherholes_no_update
    BEFORE UPDATE ON gopherholes
BEGIN
    SELECT RAISE(ABORT, 'gopherholes registry is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS gopherholes_no_delete
    BEFORE DELETE ON gopherholes
BEGIN
    SELECT RAISE(ABORT, 'gopherholes registry is immutable — no deletes allowed');
END;

-- =========================================================================
-- SIWE SESSIONS — write-only (sessions expire but are never deleted)
-- =========================================================================
CREATE TABLE IF NOT EXISTS siwe_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL UNIQUE,     -- 32-byte random hex
    address       TEXT NOT NULL,            -- EVM address (checksummed)
    nonce         TEXT NOT NULL,            -- 16-byte random hex
    issued_at     TEXT NOT NULL,            -- ISO 8601
    expires_at    TEXT NOT NULL,            -- ISO 8601
    signature     TEXT NOT NULL,            -- EIP-4361 signature from wallet
    pid           TEXT NOT NULL,            -- Pillar that issued this session
    revoked       INTEGER DEFAULT 0,        -- 0=active, 1=revoked
    created_at    TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS siwe_sessions_no_delete
    BEFORE DELETE ON siwe_sessions
BEGIN
    SELECT RAISE(ABORT, 'SIWE sessions are immutable — use revoked=1 instead of deleting');
END;

-- =========================================================================
-- SERVICE PROOFS — append-only proof of work/service delivery
-- =========================================================================
CREATE TABLE IF NOT EXISTS service_proofs (
    proof_id    TEXT PRIMARY KEY,
    pid         TEXT NOT NULL,
    service     TEXT NOT NULL,              -- service identifier (e.g. 'gopher.serve', 'mesh.relay')
    proof_hash  TEXT NOT NULL,              -- SHA-256 of proof payload
    signature   TEXT NOT NULL,              -- Ed25519 signature by originating PID
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS no_update_service_proofs
    BEFORE UPDATE ON service_proofs
BEGIN
    SELECT RAISE(ABORT, 'service_proofs is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS no_delete_service_proofs
    BEFORE DELETE ON service_proofs
BEGIN
    SELECT RAISE(ABORT, 'service_proofs is immutable — no deletes allowed');
END;

-- =========================================================================
-- SETTLEMENTS — append-only inter-Pillar payment records
-- =========================================================================
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    payer_pid     TEXT NOT NULL,
    payee_pid     TEXT NOT NULL,
    amount        REAL NOT NULL,
    token_type    TEXT NOT NULL,            -- CIFI or REFI
    proof_id      TEXT REFERENCES service_proofs(proof_id),
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS no_update_settlements
    BEFORE UPDATE ON settlements
BEGIN
    SELECT RAISE(ABORT, 'settlements is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS no_delete_settlements
    BEFORE DELETE ON settlements
BEGIN
    SELECT RAISE(ABORT, 'settlements is immutable — no deletes allowed');
END;

-- =========================================================================
-- AUDIT LOG — blockchain-style hash chain (append-only)
-- =========================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash    TEXT NOT NULL,             -- hash of previous entry (genesis = 64 zeros)
    entry_hash   TEXT NOT NULL,             -- SHA-256(prev_hash + record_hash + table + op + timestamp)
    table_name   TEXT NOT NULL,             -- source table (e.g. 'gopherholes', 'daily_tx')
    operation    TEXT NOT NULL,             -- 'INSERT', 'UPDATE', 'DELETE'
    record_key   TEXT NOT NULL,             -- primary key of the affected record
    record_hash  TEXT NOT NULL,             -- SHA-256 of canonical JSON of the record
    pid          TEXT NOT NULL,             -- PID that created this entry
    signature    TEXT NOT NULL,             -- Ed25519 signature of entry_hash
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is immutable — no deletes allowed');
END;

CREATE INDEX IF NOT EXISTS idx_audit_log_table
    ON audit_log (table_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_entry_hash
    ON audit_log (entry_hash);

-- =========================================================================
-- VAULT ITEMS — metadata for encrypted personal file storage
-- =========================================================================
CREATE TABLE IF NOT EXISTS vault_items (
    item_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    file_hash   TEXT NOT NULL,             -- SHA-256 of the encrypted file
    size_bytes  INTEGER NOT NULL,
    mime_type   TEXT DEFAULT 'application/octet-stream',
    pid         TEXT NOT NULL,             -- owner PID
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vault_items_pid
    ON vault_items (pid);
"""

ARCHIVE_SCHEMA = """
-- =========================================================================
-- ARCHIVE DATABASE — Compressed yearly records
-- =========================================================================

-- Yearly summary per Pillar
CREATE TABLE IF NOT EXISTS yearly_summary (
    accounting_year  INTEGER NOT NULL,
    pid              TEXT NOT NULL,
    total_tx_count   INTEGER DEFAULT 0,
    total_volume     REAL DEFAULT 0.0,
    avg_latency_ms   REAL DEFAULT 0.0,
    total_content_served INTEGER DEFAULT 0,
    total_uptime_seconds INTEGER DEFAULT 0,
    peers_seen       INTEGER DEFAULT 0,
    PRIMARY KEY (accounting_year, pid)
);

-- Compressed monthly snapshots (one row per month, data as JSON blob)
CREATE TABLE IF NOT EXISTS monthly_snapshot (
    accounting_year  INTEGER NOT NULL,
    accounting_month INTEGER NOT NULL,
    pid              TEXT NOT NULL,
    tx_count         INTEGER DEFAULT 0,
    volume           REAL DEFAULT 0.0,
    snapshot_data    TEXT,                   -- JSON blob of compressed daily data
    content_hash     TEXT,                   -- Hash of the snapshot for verification
    PRIMARY KEY (accounting_year, accounting_month, pid)
);

-- Historical peer records
CREATE TABLE IF NOT EXISTS peer_history (
    pid              TEXT NOT NULL,
    accounting_year  INTEGER NOT NULL,
    first_seen       DATETIME,
    last_seen        DATETIME,
    total_interactions INTEGER DEFAULT 0,
    PRIMARY KEY (pid, accounting_year)
);
"""
