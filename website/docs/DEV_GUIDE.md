# REFInet Developer Guide

**Building on top of the REFInet Gopherspace Platform**

Version 0.3.0 | March 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Architecture & Module Dependency Map](#2-architecture--module-dependency-map)
3. [Adding a New Gopher Route](#3-adding-a-new-gopher-route)
4. [Adding a New Background Task](#4-adding-a-new-background-task)
5. [Database Layer](#5-database-layer)
6. [Cryptographic Identity & Signing](#6-cryptographic-identity--signing)
7. [Authentication (SIWE / EIP-4361)](#7-authentication-siwe--eip-4361)
8. [Mesh Networking](#8-mesh-networking)
9. [EVM RPC Gateway](#9-evm-rpc-gateway)
10. [DApp Definition System](#10-dapp-definition-system)
11. [Gopher Client (Outbound)](#11-gopher-client-outbound)
12. [CLI Extensions](#12-cli-extensions)
13. [Configuration System](#13-configuration-system)
14. [Gopherroot & Static Content](#14-gopherroot--static-content)
15. [Testing](#15-testing)
16. [Error Handling Conventions](#16-error-handling-conventions)
17. [All Constants Reference](#17-all-constants-reference)
18. [Tor Transport Layer](#18-tor-transport-layer)

---

## 1. Introduction

This guide is for developers who want to **build on top of** the REFInet Gopherspace platform — adding new routes, database tables, mesh protocols, CLI commands, blockchain integrations, or entirely new subsystems.

It documents every public API, extension point, data model, and testing pattern in the codebase. Every function signature, constant value, and code example is verified against the running v0.3.0 implementation.

### Prerequisites

- Python 3.11+
- `pip install cryptography eth-account stem` (required — `stem` is the Tor controller library)
- `pip install web3 qrcode[pil]` (optional — for RPC gateway and QR codes)
- `tor` binary (optional — for hidden service mode; `brew install tor` / `sudo apt install tor`)

### Quick Start

```bash
# Install
git clone <repository>
cd REFINET-GOPHERSPACE
pip install -r requirements.txt

# Run
python3 pillar.py

# Check status (offline — no server started)
python3 pillar.py --status

# Connect
curl gopher://localhost:7070/       # REFInet (full features)
curl gopher://localhost:70/         # Standard Gopher (public content)
echo "" | nc localhost 7070

# Enable Tor (optional)
brew install tor                     # macOS (or: sudo apt install tor)
# Set "tor_enabled": true in ~/.refinet/config.json, then restart

# Test
pytest -v
```

On first run, the Pillar generates an Ed25519 identity at `~/.refinet/pid.json`, creates SQLite databases at `~/.refinet/db/`, optionally launches a Tor hidden service (if `tor_enabled: true`), and begins serving on two TCP ports — 7070 (REFInet, full features) and 70 (standard Gopher, public content only).

---

## 2. Architecture & Module Dependency Map

### Dependency Graph

Modules are layered to prevent circular imports. Each layer only imports from layers above it:

```
Layer 0: core/config.py          ← No internal imports (stdlib only)
         │
Layer 1: crypto/pid.py           ← Imports config
         crypto/signing.py       ← Imports nothing internal
         core/tor_manager.py     ← Imports config (TOR_DATA_DIR), stem
         │
Layer 2: db/schema.py            ← No imports
         db/live_db.py           ← Imports config, schema
         db/archive_db.py        ← Imports config, schema
         │
Layer 3: core/menu_builder.py    ← Imports config, crypto
         core/gopher_client.py   ← No internal imports
         core/gopherhole.py      ← Imports config, crypto, db
         core/dapp.py            ← Imports config
         │
Layer 4: auth/siwe.py            ← Imports eth_account (external)
         auth/session.py         ← Imports auth/siwe, crypto, db
         │
Layer 5: mesh/discovery.py       ← Imports config, db
         mesh/replication.py     ← Imports core/gopher_client, core/gopherhole, db
         │
Layer 6: rpc/chains.py           ← No imports
         rpc/config.py           ← Imports config, rpc/chains
         rpc/gateway.py          ← Imports rpc/chains, rpc/config, auth/session
         │
Layer 7: core/gopher_server.py   ← Imports everything above
         │
Layer 8: pillar.py               ← Entry point, imports server + mesh + archive + tor_manager
         cli/hole.py             ← Imports core/gopherhole, db
```

**Rule:** Never import from a lower layer. If `db/live_db.py` needs something from `core/gopher_server.py`, that's a design error — refactor to break the dependency.

### Lazy Imports for Optional Dependencies

Optional packages are imported with `try/except` and guarded by availability flags:

```python
# rpc/gateway.py — web3 is optional
try:
    from web3 import AsyncWeb3, AsyncHTTPProvider
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

# auth/session.py — qrcode is optional
try:
    import qrcode
except ImportError:
    qrcode = None
```

When adding a new optional dependency, follow this pattern. Check the flag before using the import and provide a clear error message.

### Single-Process Async Model

All services run concurrently in a single `asyncio` event loop. The entry point (`pillar.py:83`) launches everything via:

```python
await asyncio.gather(*tasks)
```

Tasks include:
- `refinet_server.start()` — REFInet TCP server (port 7070, all routes)
- `gopher_server.start()` — Standard Gopher TCP server (port 70, public content only)
- `periodic_archival(pid)` — Archive migration (24h cycle)
- `periodic_wal_checkpoint()` — WAL journal checkpoint (6h cycle)
- `tor.check_tor_health()` — Tor circuit monitoring (60s cycle, when Tor is active)
- `announcer.run()` — UDP multicast announcer (30s cycle)
- `listener.run()` — UDP multicast listener (continuous)
- `periodic_replication()` — Registry sync (5m cycle)
- `periodic_health_check()` — Peer pinging (60s cycle)

No threads. No subprocesses (except the Tor subprocess when Tor mode is enabled). All I/O is `async/await`.

---

## 3. Adding a New Gopher Route

### Step-by-Step

**1. Add selector matching in `core/gopher_server.py`, method `_route()` (line 181):**

```python
# In GopherServer._route(), add before the static fallback (else clause):
elif selector == "/status":
    return self._build_status_response(h, p)
```

**2. Implement the handler method on `GopherServer`:**

```python
def _build_status_response(self, hostname: str, port: int) -> str:
    uptime = int(time.time() - self.start_time)
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  PILLAR STATUS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Uptime: {uptime}s"))
    lines.append(info_line(f"  Requests served: {self.request_count}"))
    lines.append(info_line(f"  PID: {self.pid_data['pid'][:16]}..."))
    lines.append(info_line(""))
    lines.append(menu_link("  <- Back to Root", "/", hostname, port))
    lines.append(".\r\n")  # Gopher terminator — REQUIRED
    return "".join(lines)
```

**3. (Optional) Create a builder in `core/menu_builder.py` for complex menus.**

For simple routes, an inline method on `GopherServer` is fine. For routes that other code may need, create a standalone builder function in `menu_builder.py`.

### Menu Builder Functions

All functions are in `core/menu_builder.py`. Import what you need:

```python
from core.menu_builder import info_line, menu_link, text_link, html_link, search_link, separator
```

| Function | Gopher Type | Returns |
|----------|------------|---------|
| `info_line(text: str) -> str` | `i` (info) | Non-clickable text line |
| `menu_link(display, selector, host, port) -> str` | `1` (menu) | Clickable directory/submenu link |
| `text_link(display, selector, host, port) -> str` | `0` (text) | Clickable text file link |
| `html_link(display, url, host, port) -> str` | `h` (HTML) | Bridge to web URL |
| `search_link(display, selector, host, port) -> str` | `7` (search) | User input prompt |
| `separator() -> str` | `i` | 60-character horizontal line |

**Format of a Gopher line:**
```
{type}{display_text}\t{selector}\t{hostname}\t{port}\r\n
```

### Pre-built Menu Builders

For complex menus, use or extend these existing builders:

```python
build_root_menu(pid_data, hostname, port, tx_count_today=0, peers_count=0,
                is_refinet=True, onion_address=None) -> str
build_about_menu(pid_data, hostname, port, onion_address=None) -> str
build_network_menu(peers: list[dict], hostname, port) -> str
build_dapps_menu(hostname, port, dapps=None) -> str
build_directory_menu(holes: list[dict], hostname, port) -> str
build_auth_menu(hostname, port) -> str
build_rpc_menu(chain_statuses: dict, hostname, port, available=True) -> str
build_pid_document(pid_data, onion_address=None) -> str
build_transactions_document(transactions: list[dict]) -> str
build_peers_document(peers: list[dict]) -> str
build_ledger_document(pid: str, tx_count: int) -> str
```

When `onion_address` is provided, the root menu, about page, and PID document include the `.onion` address. The PID document additionally includes `tor_port_7070` and `tor_port_70` fields.

### What Happens Automatically

When you add a route, the request lifecycle in `handle_client()` automatically:
- **Rate limits** the client IP (100 req / 60s for direct connections; 500 req / 60s when Tor is active — since all Tor traffic arrives from 127.0.0.1)
- **Hashes** your response via SHA-256
- **Logs** a transaction in `daily_tx`
- **Updates** daily metrics
- **Indexes** the response in `content_index`
- **Signs** the content with the Pillar's Ed25519 key
- **Appends signature block** — `---BEGIN/END REFINET SIGNATURE---` with pid, sig, and hash

You do not need to implement any of this — just return a string from `_route()`.

### Route Gating (Dual-Port)

Routes listed in `REFINET_ROUTES` are blocked on the standard Gopher port (70). To make a new route REFInet-only, add it to the tuple in `gopher_server.py`:

```python
REFINET_ROUTES = (
    "/auth", "/rpc", "/pid", "/transactions", "/peers",
    "/ledger", "/network", "/directory.json", "/status.json",
    "/my/new/route",  # Add here to gate on port 70
)
```

Routes NOT in this tuple are available on both ports. Content routes (`/`, `/about`, `/dapps`, `/directory`, static files) are intentionally ungated so standard Gopher clients can browse public content.

### Search Routes (User Input)

For routes that accept user input (Gopher type 7), the query arrives after a tab character:

```python
elif selector.startswith("/myroute/search"):
    query = selector.split("\t", 1)[1] if "\t" in selector else ""
    if not query:
        return self._error_response("Usage: enter your search term")
    # Process query...
```

Expose the search input in menus with `search_link()`.

---

## 4. Adding a New Background Task

### Template

```python
# In your module, e.g., my_module/tasks.py
import asyncio
import logging

logger = logging.getLogger("refinet.mytask")

MY_TASK_INTERVAL_SEC = 120  # 2 minutes

async def periodic_my_task():
    """Background task: describe what it does."""
    # Optional initial delay — let other services start first
    await asyncio.sleep(10)
    logger.info(f"My task started ({MY_TASK_INTERVAL_SEC}s interval)")

    while True:
        try:
            # Do your work here
            result = do_something()
            if result:
                logger.info(f"My task completed: {result}")
        except Exception as e:
            logger.warning(f"My task error: {e}")
        await asyncio.sleep(MY_TASK_INTERVAL_SEC)
```

### Wiring Into pillar.py

In `pillar.py`, function `main()` (line 51):

```python
from my_module.tasks import periodic_my_task

async def main(host, port, enable_mesh):
    # ... existing setup ...
    tasks = [server.start()]
    tasks.append(periodic_archival(pid_data["pid"]))
    tasks.append(periodic_my_task())  # Add your task here

    if enable_mesh:
        # ... mesh tasks ...

    await asyncio.gather(*tasks)
```

### Rules

1. **Always wrap work in `try/except`** — a crashing background task kills the entire process
2. **Use `await asyncio.sleep()`** — never `time.sleep()` (it blocks the event loop)
3. **Log, don't raise** — use `logger.warning()` for errors
4. **Optional initial delay** — give the server time to start before your task runs
5. **Gate on a CLI flag if appropriate** — e.g., `--no-mesh` disables mesh tasks

---

## 5. Database Layer

### Connection Pattern

Both `db/live_db.py` and `db/archive_db.py` use the same context manager:

```python
from contextlib import contextmanager

@contextmanager
def _connect():
    ensure_dirs()                                    # Create ~/.refinet/db/ if needed
    conn = sqlite3.connect(str(LIVE_DB_PATH))       # Path → string for sqlite3
    conn.row_factory = sqlite3.Row                   # Enable row["column"] access
    conn.execute("PRAGMA journal_mode=WAL")          # Write-Ahead Logging
    conn.execute("PRAGMA foreign_keys=ON")           # Enforce FK constraints
    try:
        yield conn
    finally:
        conn.close()                                 # Always close, even on exception
```

**Usage:**
```python
with _connect() as conn:
    conn.execute("INSERT INTO my_table (col) VALUES (?)", (value,))
    conn.commit()  # Always commit after writes
```

Each call to `_connect()` opens a fresh connection. WAL mode enables concurrent readers while a write is in progress.

### Adding a New Table

**Step 1: Add the schema in `db/schema.py`**

Append to `LIVE_SCHEMA` (or `ARCHIVE_SCHEMA`):

```python
LIVE_SCHEMA = """
...existing tables...

-- My custom data store
CREATE TABLE IF NOT EXISTS my_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pid             TEXT NOT NULL,
    data            TEXT NOT NULL,
    score           REAL DEFAULT 0.0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_my_records_pid
    ON my_records (pid);
"""
```

`CREATE TABLE IF NOT EXISTS` makes the schema idempotent — safe to run on both new and existing databases.

**Step 2: Write wrapper functions in `db/live_db.py`**

```python
def insert_my_record(pid: str, data: str, score: float = 0.0) -> int:
    """Insert a record and return its id."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO my_records (pid, data, score) VALUES (?, ?, ?)",
            (pid, data, score),
        )
        conn.commit()
        return cursor.lastrowid

def get_my_records(pid: str, limit: int = 50) -> list[dict]:
    """Get records for a PID, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM my_records WHERE pid=? ORDER BY created_at DESC LIMIT ?",
            (pid, limit),
        ).fetchall()
        return [dict(r) for r in rows]
```

**Step 3: Add schema migration (if evolving an existing table)**

If you need to add a column to an existing table, add it to `_migrate_live_db()` in `db/live_db.py`:

```python
def _migrate_live_db(conn):
    """Add any columns that were added after initial schema creation."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(my_records)").fetchall()}
    migrations = [
        ("new_column", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE my_records ADD COLUMN {col_name} {col_def}")
    conn.commit()
```

### Live Database API Reference

All functions are in `db/live_db.py`:

#### Initialization
```python
def init_live_db() -> None
    # Creates all tables + runs migrations. Called on server startup.
```

#### Accounting Calendar
```python
def get_accounting_date(dt: datetime = None) -> tuple[int, int, int]
    # Returns (accounting_day, accounting_month, accounting_year)
    # 13 months × 28 days. Days 365+ map to (28, 13, year).
```

#### Transactions
```python
def record_transaction(
    dapp_id: str,             # e.g., "gopher.core" or "my_dapp.v1"
    pid: str,                 # Pillar ID
    amount: float = 0.0,
    token_type: str = "REFI", # "CIFI" or "REFI"
    selector: str = None,     # Gopher selector that triggered this
    mesh_peer_pid: str = None,
    content_hash: str = None,
    signature: str = None,
) -> str  # Returns tx_id (e.g., "tx_a1b2c3d4e5f67890")

def get_tx_count_today(pid: str) -> int
def get_recent_transactions(pid: str, limit: int = 20) -> list[dict]
```

#### Metrics
```python
def update_daily_metrics(pid: str, **kwargs) -> None
    # Upserts daily metrics. Kwargs: total_tx_count, total_volume,
    # avg_latency_ms, peers_connected, content_served, uptime_seconds
```

#### Peers
```python
def upsert_peer(pid, public_key, hostname=None, port=7070,
                pillar_name=None, protocol_version=None) -> None
def get_peers() -> list[dict]
    # Returns all peers, ordered by last_seen DESC
def update_peer_health(pid: str, latency_ms: float | None) -> None
    # Updates status: online (<2000ms), degraded (>=2000ms or 1-2 failures), offline (3+ failures)
def update_peer_onion(pid: str, onion_address: str) -> None
    # Store a peer's .onion address in the onion_address column
def get_peer_onion(pid: str) -> str | None
    # Retrieve a peer's .onion address, or None if not set
```

#### Content Index
```python
def index_content(selector, content_type, content_hash,
                  signature, pid, size_bytes=0) -> None
    # Upserts. content_type: "menu", "text", "binary", "dapp"
```

#### Gopherhole Registry
```python
def register_gopherhole(pid, selector, name, description,
                        owner_address, pubkey_hex, signature,
                        source="local", registered_at=None) -> str
    # Returns tx_hash (SHA-256 of canonical JSON).
    # Raises IntegrityError on duplicate pid+selector.

def list_gopherholes(source_filter: str = None) -> list[dict]
    # source_filter="local" for local only, None for all

def get_gopherhole(pid: str, selector: str) -> dict | None
def gopherhole_exists(pid: str, selector: str) -> bool
```

### Archive Database API Reference

All functions are in `db/archive_db.py`:

```python
def init_archive_db() -> None
def archive_yearly_summary(accounting_year, pid, total_tx_count=0,
                           total_volume=0.0, avg_latency_ms=0.0,
                           total_content_served=0, total_uptime_seconds=0,
                           peers_seen=0) -> None
def archive_monthly_snapshot(accounting_year, accounting_month, pid,
                             tx_count, volume, snapshot_data: dict,
                             content_hash=None) -> None
def get_yearly_summaries(pid: str) -> list[dict]
def migrate_to_archive(pid: str) -> int   # Returns months archived
async def periodic_archival(pid: str, interval_hours: int = 24) -> None
```

### Immutability Enforcement

Four tables are protected by SQL triggers (7 triggers total):

**`gopherholes`** — No UPDATE, No DELETE:
```sql
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
```

**`siwe_sessions`** — No DELETE (use `revoked=1` instead):
```sql
CREATE TRIGGER IF NOT EXISTS siwe_sessions_no_delete
    BEFORE DELETE ON siwe_sessions
BEGIN
    SELECT RAISE(ABORT, 'SIWE sessions are immutable — use revoked=1 instead of deleting');
END;
```

**`service_proofs`** — No UPDATE, No DELETE:
```sql
CREATE TRIGGER IF NOT EXISTS no_update_service_proofs
    BEFORE UPDATE ON service_proofs BEGIN
    SELECT RAISE(ABORT, 'service_proofs is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS no_delete_service_proofs
    BEFORE DELETE ON service_proofs BEGIN
    SELECT RAISE(ABORT, 'service_proofs is immutable — no deletes allowed');
END;
```

**`settlements`** — No UPDATE, No DELETE (FK to `service_proofs`):
```sql
CREATE TRIGGER IF NOT EXISTS no_update_settlements
    BEFORE UPDATE ON settlements BEGIN
    SELECT RAISE(ABORT, 'settlements is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS no_delete_settlements
    BEFORE DELETE ON settlements BEGIN
    SELECT RAISE(ABORT, 'settlements is immutable — no deletes allowed');
END;
```

Any `UPDATE` or `DELETE` on these tables will raise an `IntegrityError`. Design your code accordingly — these are append-only stores.

---

## 6. Cryptographic Identity & Signing

### PID Lifecycle

```
First run:  generate_pid() → save_pid() → return pid_data
Later runs: load_pid() → return pid_data
Shortcut:   get_or_create_pid() → handles both cases
```

### crypto/pid.py API

```python
def generate_pid() -> dict
    # Returns: {pid, public_key, private_key, created_at, protocol}
    # pid = SHA-256(Ed25519_public_key).hexdigest() — 64 hex chars
    # public_key / private_key = hex-encoded raw bytes

def save_pid(pid_data: dict, path: Path = PID_FILE) -> None
def load_pid(path: Path = PID_FILE) -> dict | None

def get_or_create_pid() -> dict
    # Load existing or generate + save new. This is the standard entry point.

def get_private_key(pid_data: dict) -> Ed25519PrivateKey
    # Reconstruct key object from hex-encoded private_key field

def get_short_pid(pid_data: dict) -> str
    # Returns first 16 chars of PID for display
```

### crypto/signing.py API

```python
def hash_content(data: bytes) -> str
    # SHA-256, returned as hex string

def sign_content(data: bytes, private_key: Ed25519PrivateKey) -> str
    # Ed25519 signature, returned as hex string

def verify_signature(data: bytes, signature_hex: str, public_key_hex: str) -> bool
    # Returns True if valid, False otherwise. Never raises.
```

### Signing Custom Data

To sign your own data types:

```python
from crypto.pid import get_or_create_pid, get_private_key
from crypto.signing import sign_content, verify_signature, hash_content

pid_data = get_or_create_pid()
private_key = get_private_key(pid_data)

# Sign
payload = f"{pid_data['pid']}:my_custom_data:{some_value}".encode()
signature = sign_content(payload, private_key)
content_hash = hash_content(payload)

# Verify (anyone can do this with the public key)
is_valid = verify_signature(payload, signature, pid_data["public_key"])
```

### Gopherhole Signing Convention

The signing payload for gopherholes is:
```
"{pid}:{selector}:{name}:{registered_at}"
```

This convention is defined in `core/gopherhole.py:133` (creation) and `core/gopherhole.py:166` (verification). If you create new signable record types, follow a similar `field1:field2:field3` convention.

### Verification Workflow

To verify a record is authentic:
1. Reconstruct the payload string from the record's fields
2. Call `verify_signature(payload.encode(), record["signature"], record["pubkey_hex"])`
3. Optionally verify `record["pid"] == hashlib.sha256(bytes.fromhex(record["pubkey_hex"])).hexdigest()`

Step 3 confirms the public key belongs to the claimed PID.

---

## 7. Authentication (SIWE / EIP-4361)

### Challenge-Response Flow

```
Client                                 Pillar
  │                                      │
  │  1. /auth/challenge  addr=0xABC...   │
  │ ────────────────────────────────────> │
  │                                      │  generate_challenge(address)
  │  2. EIP-4361 message + nonce         │
  │ <──────────────────────────────────── │
  │                                      │
  │  (client signs message with wallet)  │
  │                                      │
  │  3. /auth/verify  addr|sig|base64(message) │
  │ ────────────────────────────────────> │
  │                                      │  establish_session(addr, msg, sig)
  │  4. session_id (64-char hex)         │
  │ <──────────────────────────────────── │
  │                                      │
  │  5. /rpc/broadcast  session_id|...   │
  │ ────────────────────────────────────> │
  │                                      │  validate_session(session_id)
```

**Wire format note:** The message field in step 3 is base64-encoded because SIWE messages contain newlines. The Pillar auto-detects and decodes base64, with plain-text fallback for direct Gopher clients.

### auth/siwe.py API

```python
SESSION_DURATION_HOURS = 24
DOMAIN = "refinet://pillar"

def generate_challenge(address: str, pid: str) -> tuple[str, str]
    # Returns (message_text, nonce)
    # Message follows EIP-4361 format with domain, chain ID 1, timestamps

def verify_siwe_signature(message_text, signature, expected_address) -> bool
    # Uses ecrecover. Returns True/False. Raises ValueError on malformed input.

def parse_expiry(message_text: str) -> datetime
def parse_nonce(message_text: str) -> str
```

### auth/session.py API

```python
def create_challenge(address: str) -> dict
    # Returns {message, nonce, qr_base64}
    # qr_base64 is None if qrcode library not installed

def establish_session(address, message_text, signature) -> dict
    # Returns {session_id, address, expires_at, pid}
    # Raises ValueError on failure

def validate_session(session_id: str) -> dict | None
    # Returns session dict or None if invalid/expired/revoked

def revoke_session(session_id: str) -> None
    # Sets revoked=1. Never deletes.
```

### Adding Auth Guards to New Routes

To require authentication on a route:

```python
elif selector.startswith("/my/protected/route"):
    query = selector.split("\t", 1)[1] if "\t" in selector else ""
    parts = query.strip().split("|")
    session_id = parts[0].strip()

    from auth.session import validate_session
    session = validate_session(session_id)
    if not session:
        return self._error_response("Valid SIWE session required")

    # Session is valid — session["address"] is the authenticated wallet
    return self._do_protected_thing(session["address"])
```

This is the exact pattern used by `/rpc/broadcast` (line 454 in `gopher_server.py`).

---

## 8. Mesh Networking

### UDP Multicast Protocol

**Announcement message format:**
```json
{
  "type": "pillar_announce",
  "protocol": "REFInet",
  "version": "0.3.0",
  "pid": "<64-char hex>",
  "public_key": "<64-char hex>",
  "hostname": "<IP or hostname>",
  "port": 7070,
  "pillar_name": "<display name>",
  "onion_address": "<56-char>.onion",
  "timestamp": 1709654400
}
```

The `onion_address` field is optional — included only when the Pillar has an active Tor hidden service.

- Multicast group: `224.0.70.70`
- Port: `7071`
- TTL: `2` (one router hop)
- Interval: every 30 seconds

### mesh/discovery.py API

```python
def build_announce_message(pid_data, hostname, port, pillar_name,
                           onion_address=None) -> bytes
    # onion_address is included in the message when not None
def parse_announce_message(data: bytes) -> dict | None
```

**PeerAnnouncer** (lines 63-89):
```python
class PeerAnnouncer:
    def __init__(self, pid_data, hostname, port, pillar_name, onion_address=None)
    async def run(self)
        # Sends announce every DISCOVERY_INTERVAL_SEC (30s) via UDP multicast
        # Includes onion_address in announcements when set
```

**PeerListener** (lines 92-172):
```python
class PeerListener:
    def __init__(self, own_pid: str)
    async def run(self)
        # Listens for announcements, registers peers, triggers replication
        # Parses onion_address from announcements and stores via update_peer_onion()

    async def _on_new_peer_discovered(self, peer_host, peer_port, peer_pid)
        # Called when a previously unknown peer is found
        # Triggers immediate registry sync
```

**Health Monitoring** (lines 175-203):
```python
async def periodic_health_check()
    # Pings all peers every 60 seconds via TCP Gopher ping
    # Updates status: unknown → online → degraded → offline
```

### mesh/replication.py API

```python
REPLICATION_INTERVAL_SEC = 300  # 5 minutes

async def sync_peer_registry(peer_host, peer_port, peer_pid) -> int
    # Fetches /directory.json from a peer
    # Verifies Ed25519 signatures before importing
    # Returns count of newly imported gopherholes

async def replicate_all_peers() -> None
    # Syncs registries from all known peers in parallel

async def periodic_replication() -> None
    # Runs replicate_all_peers() every 5 minutes
```

### Adding a New Mesh Message Type

To add a new type of mesh communication (e.g., sharing custom data):

**1. Define the message format:**
```python
def build_custom_message(pid_data: dict, payload: dict) -> bytes:
    msg = {
        "type": "custom_data_share",
        "protocol": "REFInet",
        "pid": pid_data["pid"],
        "payload": payload,
    }
    return json.dumps(msg).encode("utf-8")
```

**2. Handle it in the listener:**
In `PeerListener.run()`, add handling for your message type:
```python
msg = parse_announce_message(data)
if msg and msg.get("type") == "custom_data_share":
    self._handle_custom_data(msg)
```

**3. Add a replication function** for pulling data (similar to `sync_peer_registry`), using the Gopher client to fetch from a custom route.

---

## 9. EVM RPC Gateway

### RPCGateway Class (`rpc/gateway.py`)

```python
WEB3_AVAILABLE: bool  # True if web3 is installed

class RPCGateway:
    def __init__(self)
        # Raises ImportError if web3 not installed

    async def get_balance(self, chain_id: int, address: str) -> int
        # Native token balance in wei

    async def get_block_number(self, chain_id: int) -> int
        # Latest block number

    async def get_token_balance(self, chain_id: int,
                                token_address: str,
                                wallet_address: str) -> int
        # ERC-20 balance via balanceOf() call, raw units

    async def estimate_gas(self, chain_id: int, tx_params: dict) -> int
        # Gas estimate for a transaction

    async def broadcast(self, chain_id: int, signed_tx_hex: str,
                        session_id: str) -> str
        # Broadcasts signed tx. Requires valid SIWE session.
        # Raises PermissionError if session invalid.
        # Returns tx hash hex.

    async def test_connection(self, chain_id: int,
                              timeout: float = 5.0) -> float | None
        # Returns latency in ms, or None on failure

    async def close(self) -> None
        # Close all cached web3 client sessions
```

### Chain Configuration (`rpc/chains.py`)

```python
DEFAULT_CHAINS = {
    1:        {"name": "Ethereum Mainnet",  "rpc": "https://eth.llamarpc.com",      "symbol": "ETH",   "explorer": "https://etherscan.io"},
    137:      {"name": "Polygon",           "rpc": "https://polygon-rpc.com",        "symbol": "MATIC", "explorer": "https://polygonscan.com"},
    42161:    {"name": "Arbitrum One",       "rpc": "https://arb1.arbitrum.io/rpc",   "symbol": "ETH",   "explorer": "https://arbiscan.io"},
    8453:     {"name": "Base",              "rpc": "https://mainnet.base.org",       "symbol": "ETH",   "explorer": "https://basescan.org"},
    11155111: {"name": "Sepolia Testnet",   "rpc": "https://rpc.sepolia.org",        "symbol": "ETH",   "explorer": "https://sepolia.etherscan.io"},
}
```

### Adding a New Chain

Add to `DEFAULT_CHAINS` in `rpc/chains.py`:

```python
10:  {"name": "Optimism", "rpc": "https://mainnet.optimism.io", "symbol": "ETH", "explorer": "https://optimistic.etherscan.io"},
```

The gateway will automatically support it for all existing operations.

### Adding a New RPC Operation

**1. Add the method to `RPCGateway`:**

```python
async def get_transaction_receipt(self, chain_id: int, tx_hash: str) -> dict:
    client_config = self._get_client(chain_id)
    w3 = client_config["primary"]
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    return dict(receipt)
```

**2. Add the route in `gopher_server.py`:**

```python
elif selector.startswith("/rpc/receipt"):
    query = selector.split("\t", 1)[1] if "\t" in selector else ""
    if not query and "?" in selector:
        query = selector.split("?", 1)[1]
    parts = query.strip().split("|")
    # ... parse chain_id, tx_hash ...
    # ... call gw.get_transaction_receipt() ...
    # ... format and return Gopher response ...
```

**3. Add a search link on the RPC menu** in `build_rpc_menu()`:

```python
lines.append(search_link("  TX Receipt", "/rpc/receipt", hostname, port))
```

### User-Configurable Endpoints (`rpc/config.py`)

```python
RPC_CONFIG_PATH = HOME_DIR / "rpc_config.json"  # ~/.refinet/rpc_config.json

def load_rpc_config() -> dict
    # Returns chain_id -> [endpoint_urls]
    # Layers: DEFAULT_CHAINS → user overrides

def save_rpc_config(config: dict) -> None
```

User config (`~/.refinet/rpc_config.json`):
```json
{
  "1": ["https://my-private-eth-rpc.example.com"],
  "137": ["https://my-polygon-rpc.example.com"]
}
```

---

## 10. DApp Definition System

### DAppDefinition Dataclass (`core/dapp.py`)

```python
@dataclass
class DAppDefinition:
    name: str                      # "Uniswap V3"
    slug: str                      # "uniswap-v3"
    version: str                   # "1.0.0"
    chain_id: int                  # 1
    contract: str                  # "0x68b3..."
    author_pid: str                # 64-char hex
    author_address: str            # "0x..."
    description: str               # Short text
    published: str                 # Date string
    abi_functions: List[str]       # Human-readable ABI lines
    docs: Dict[str, str]           # Function name → documentation
    flows: Dict[str, List[str]]    # Flow name → [step strings]
    warnings: List[str]            # Security/usage warnings
```

### .dapp File Format

```ini
[meta]
name = My DApp
slug = my-dapp
version = 1.0.0
chain_id = 1
contract = 0x1234567890abcdef1234567890abcdef12345678
author_pid = af1cc79d...
author_address = 0x0000000000000000000000000000000000000000
description = What this DApp does
published = 2026-03-01

[abi]
# Human-readable — one function per line
myFunction(uint256, address) -> bool
anotherFunction(bytes32) -> uint256

[docs]
# myFunction
Describe what myFunction does.
Gas estimate: ~50,000

# anotherFunction
Describe what anotherFunction does.

[flows]
basic_usage:
  1. Call myFunction with your value
  2. Verify the return value
  3. Call anotherFunction if needed

[warnings]
Always verify parameters before signing.
Check gas prices during high congestion.
```

### API

```python
def parse_dapp_file(filepath: str | Path) -> DAppDefinition
def list_dapp_files() -> list[Path]           # All .dapp files in gopherroot/dapps/
def load_all_dapps() -> list[DAppDefinition]  # Parse all, skip errors
```

### Hot-Reload

Drop a `.dapp` file into `gopherroot/dapps/` and it appears on the `/dapps` menu immediately. The `load_all_dapps()` function is called on every request to `/dapps`, scanning the directory each time.

---

## 11. Gopher Client (Outbound)

### GopherResponse Dataclass (`core/gopher_client.py`)

```python
@dataclass
class GopherResponse:
    host: str
    port: int
    selector: str
    raw_bytes: bytes
    content_hash: str    # SHA-256 of raw_bytes
    item_type: str       # "1" menu, "0" text, "I" image, etc.
    size_bytes: int

    @property
    def text(self) -> str          # UTF-8 decoded content
    @property
    def is_menu(self) -> bool      # True if item_type == "1"
```

### API

```python
async def fetch(host: str, port: int, selector: str,
                item_type: str = "1") -> GopherResponse
    # Fetch a Gopher resource from a remote server
    # Raises:
    #   ValueError — SSRF violation (blocked host/port)
    #   asyncio.TimeoutError — connection/read timeout (10s)
    #   ConnectionRefusedError — server unreachable

async def ping(host: str, port: int, timeout: float = 3) -> float | None
    # TCP Gopher ping. Returns latency in ms or None on failure.
```

### SSRF Policy

| Rule | Value |
|------|-------|
| Blocked hosts | Prefixes: `127.`, `0.`, `::1` |
| Allowed hosts | All LAN IPs (192.168.*, 10.*, 172.16-31.*) |
| Allowed ports | `{70, 7070, 105}` |
| Max response size | 2 MB (`2 * 1024 * 1024`) |
| Connection timeout | 10 seconds |
| Read timeout | 10 seconds per chunk |

LAN IPs are intentionally allowed — REFInet is a LAN-first protocol.

### Using the Client

```python
from core.gopher_client import fetch, ping

# Fetch content from another Pillar
response = await fetch("192.168.1.42", 7070, "/directory.json", item_type="0")
data = json.loads(response.text)

# Ping a peer
latency = await ping("192.168.1.42", 7070, timeout=5)
if latency:
    print(f"Peer is online: {latency}ms")
```

---

## 12. CLI Extensions

### Current CLI Structure

```
pillar.py
├── run                           (default — start server)
│   ├── --host 0.0.0.0
│   ├── --port 7070              (REFInet port)
│   ├── --gopher-port 70         (standard Gopher port)
│   ├── --no-gopher              (disable standard Gopher server)
│   ├── --no-mesh
│   ├── --status                 (show Pillar status and exit — offline query)
│   └── --verbose / -v
└── hole
    ├── create --name NAME --selector SELECTOR [--desc DESC] [--owner 0x...]
    ├── list [--peers] [--json]
    └── verify --pid PID --selector SELECTOR
```

The `--status` flag shows the Pillar's PID, public key, Tor hidden service key status, and peer count without starting the server. It reads from persisted state at `~/.refinet/`.

### Adding a New Subcommand Group

**1. Create your command module** (e.g., `cli/network.py`):

```python
"""REFInet Pillar — Network CLI Commands"""

import json
from db.live_db import get_peers

def cmd_network_status(args):
    """Show network status."""
    peers = get_peers()
    if args.json:
        print(json.dumps(peers, indent=2))
    else:
        print(f"\n{len(peers)} known peer(s):\n")
        for p in peers:
            print(f"  [{p['status']}] {p.get('pillar_name', '?')} @ {p['hostname']}:{p['port']}")

def register_network_subcommands(subparsers):
    """Register the 'network' subcommand group."""
    net_parser = subparsers.add_parser("network", help="Network operations")
    net_sub = net_parser.add_subparsers(dest="net_cmd")

    p_status = net_sub.add_parser("status", help="Show peer status")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_network_status)

    return net_parser
```

**2. Register in `pillar.py`:**

```python
from cli.network import register_network_subcommands
register_network_subcommands(subparsers)
```

**3. Add dispatch logic:**

```python
elif args.command == "network":
    if hasattr(args, "func"):
        args.func(args)
```

### Conventions

- Command functions are named `cmd_<group>_<action>(args)`
- Use `sys.exit(1)` for user errors, `sys.exit(2)` for verification failures
- Print to `sys.stderr` for error messages
- Support `--json` for machine-readable output where applicable

---

## 13. Configuration System

### All Constants (`core/config.py`)

```python
# Directories
HOME_DIR    = Path.home() / ".refinet"
DB_DIR      = HOME_DIR / "db"
PID_FILE    = HOME_DIR / "pid.json"
PEERS_FILE  = HOME_DIR / "peers.json"
CONFIG_FILE = HOME_DIR / "config.json"

# Gopher Server
GOPHER_HOST = "0.0.0.0"
GOPHER_PORT = 7070
GOPHER_ROOT = Path(__file__).parent.parent / "gopherroot"

# Accounting Calendar
ACCOUNTING_DAYS_PER_MONTH  = 28
ACCOUNTING_MONTHS_PER_YEAR = 13
LIVE_DB_RETENTION_MONTHS   = 13

# Mesh Discovery
MULTICAST_GROUP        = "224.0.70.70"
MULTICAST_PORT         = 7071
DISCOVERY_INTERVAL_SEC = 30

# Protocol
PROTOCOL_NAME    = "REFInet"
PROTOCOL_VERSION = "0.3.0"

# Tor Hidden Service
TOR_DATA_DIR = HOME_DIR / "tor_data"
TOR_DEFAULTS = {
    "tor_enabled": False,          # Enable Tor hidden service
    "tor_expose_port_70": True,    # Expose standard Gopher port via Tor
    "tor_socks_port": 9050,        # Tor SOCKS proxy port
    "tor_control_port": 9051,      # Tor control port for stem
}
```

### Config Loading Priority

```
Constructor arguments  >  config.json  >  Hardcoded defaults
(highest)                                  (lowest)
```

Example in `GopherServer.__init__()`:
```python
self.host = host or GOPHER_HOST                    # Constructor > default
self.port = port or self.config.get("port", GOPHER_PORT)  # Constructor > config > default
self.hostname = hostname or self.config.get("hostname", "localhost")
```

### load_config()

```python
def load_config() -> dict:
    # 1. If ~/.refinet/config.json exists and is valid JSON → return it
    # 2. Otherwise → write defaults and return them
    # 3. Never raises — always returns a usable dict
```

Default config:
```json
{
  "hostname": "localhost",
  "port": 7070,
  "pillar_name": "My REFInet Pillar",
  "description": "A sovereign node in Gopherspace",
  "protocol_version": "0.3.0",
  "tor_enabled": false,
  "tor_expose_port_70": true,
  "tor_socks_port": 9050,
  "tor_control_port": 9051
}
```

The `load_config()` function merges `TOR_DEFAULTS` via `setdefault()` on every load, so existing config files gain Tor keys automatically without requiring manual addition.

### Adding a New Configurable Parameter

**1. Add default to `load_config()`:**
```python
defaults = {
    ...existing...,
    "my_feature_enabled": True,
}
```

**2. Read it where needed:**
```python
config = load_config()
if config.get("my_feature_enabled", True):
    # Do the thing
```

**3. Document it** — users edit `~/.refinet/config.json` directly.

### RPC Config Layering

The RPC config (`rpc/config.py`) uses a two-layer approach:

```python
def load_rpc_config() -> dict:
    config = {}
    # Layer 1: Start with all DEFAULT_CHAINS
    for chain_id, chain in DEFAULT_CHAINS.items():
        config[chain_id] = [chain["rpc"]]
    # Layer 2: Override with user config
    if RPC_CONFIG_PATH.exists():
        user_config = json.load(...)
        for chain_id_str, endpoints in user_config.items():
            config[int(chain_id_str)] = endpoints
    return config
```

Result: defaults for any chain the user didn't override, user's endpoints for ones they did.

---

## 14. Gopherroot & Static Content

### Directory Structure

```
gopherroot/
├── gophermap             # Root menu (optional — dynamic route overrides this)
├── about/                # About section
├── network/              # Network info
├── news/
│   └── gophermap         # News directory listing
├── dapps/
│   └── uniswap-v3.dapp  # DApp definition files
└── holes/                # Gopherholes (user-registered content sites)
    ├── my-site/
    │   ├── gophermap     # Gopher menu for this hole
    │   └── README.txt    # Description
    └── another-site/
        ├── gophermap
        └── README.txt
```

### How Static Serving Works

When a selector doesn't match any dynamic route, `_serve_static()` (line 511) resolves it:

1. Strip leading `/` and remove `..` sequences
2. Resolve the path against `gopherroot/`
3. Verify the resolved path is within `gopherroot/` (traversal protection)
4. If it's a **file** → serve file contents
5. If it's a **directory with a `gophermap`** → serve the gophermap
6. If it's a **directory without a `gophermap`** → auto-generate a listing

### Gophermap Format

A gophermap is a plain text file where each line follows the Gopher protocol:

```
i  This is an info line (not clickable)	fake	(NULL)	0
1  Click for submenu	/some/selector	localhost	7070
0  Click for text file	/some/file.txt	localhost	7070
7  Search	/search	localhost	7070
h  Web link	URL:https://example.com	localhost	7070
.
```

| Type | Meaning |
|------|---------|
| `i` | Informational text (display only) |
| `0` | Text file |
| `1` | Directory / submenu |
| `7` | Search / user input |
| `h` | HTML link (web bridge) |
| `.` | End of menu (terminator) |

### Gopherhole Scaffolding

When `create_gopherhole()` is called, it generates two template files:

**`gophermap`** (defined in `core/gopherhole.py:24-34`):
```
i{name}	fake	(NULL)	0
i{description}	fake	(NULL)	0
i	fake	(NULL)	0
iPublished on REFInet Pillar	fake	(NULL)	0
iPillar ID: {pid}	fake	(NULL)	0
iRegistered: {registered_at}	fake	(NULL)	0
i	fake	(NULL)	0
0README	{selector}/README.txt	{host}	{port}
.
```

**`README.txt`** (defined in `core/gopherhole.py:36-51`): A markdown-style text document with navigation info.

### Path Traversal Protection

Two layers in `_serve_static()` (line 520-523):

```python
clean = selector.lstrip("/").replace("..", "")              # Layer 1: sanitize
target = (GOPHER_ROOT / clean).resolve()                    # Resolve symlinks
if not str(target).startswith(str(GOPHER_ROOT.resolve())):  # Layer 2: verify boundary
    return self._error_response(f"Not found: {selector}")
```

---

## 15. Testing

### Overview

- **484 tests** across **33 modules** (479 passed, 5 skipped)
- Framework: pytest + pytest-asyncio
- Configuration: `pytest.ini` with `asyncio_mode = auto`

### Test Modules

| Module | Tests | Coverage Area |
|--------|-------|---------------|
| `test_synergy.py` | 31 | Directory JSON signatures, multi-module integration |
| `test_gap_closure.py` | 26 | Gaps 2,3,6,7,8: status.json, base64 auth, service_proofs, settlements, license_tier |
| `test_dual_port.py` | 23 | Dual-port architecture, route gating, signature blocks |
| `test_routes.py` | 21 | TCP route integration tests, rate limiting, Tor PID/status |
| `test_discovery.py` | 20 | Mesh announcements, listener, PeerAnnouncer, onion address in announcements |
| `test_first_run.py` | 16 | PID generation, DB init, gopherhole creation, calendar |
| `test_tor_manager.py` | 15 | TorManager lifecycle, config, privkey persistence, health, restart |
| `test_gopherholes.py` | 13 | Schema, immutability triggers, signatures, JSON envelope |
| `test_gopher_client.py` | 13 | SSRF protection, GopherResponse, UTF-8 |
| `test_gophermap_parser.py` | 12 | RFC 1436 gophermap parsing |
| `test_siwe.py` | 11 | Challenge, signature verify, sessions |
| `test_dapp.py` | 10 | DApp parser: meta, ABI, docs, flows, warnings |
| `test_replication.py` | 9 | Signature verification, sync, legacy format |
| `test_gopherhole_cli.py` | 9 | Selector validation, signature verification |
| `test_rpc.py` | 5 | Chain config, gateway init |
| `test_tor_integration.py` | 2* | End-to-end Tor bootstrap + hidden service (*skipped without tor binary) |

### Shared Fixtures (`tests/conftest.py`)

```python
@pytest.fixture
def test_pid():
    """Fresh Ed25519 PID for each test."""
    return generate_pid()

@pytest.fixture
def test_private_key(test_pid):
    """Ed25519 private key object from test PID."""
    return get_private_key(test_pid)

@pytest.fixture
def memory_db():
    """In-memory SQLite with full live schema. Yields connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(LIVE_SCHEMA)
    conn.commit()
    yield conn
    conn.close()
```

### Database Isolation via Monkeypatch

When testing code that touches the filesystem (PID files, SQLite databases), redirect all paths to `tmp_path`:

```python
def test_my_feature(self, tmp_path, monkeypatch):
    # Redirect ALL cached module-level paths
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")

    # IMPORTANT: Also patch cached imports in consuming modules
    monkeypatch.setattr("core.gopherhole.GOPHER_ROOT", tmp_path / "gopherroot")
    monkeypatch.setattr("db.live_db.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("db.live_db.LIVE_DB_PATH", tmp_path / ".refinet" / "db" / "live.db")
    monkeypatch.setattr("db.archive_db.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("db.archive_db.ARCHIVE_DB_PATH", tmp_path / ".refinet" / "db" / "archive.db")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")

    # For Tor tests — isolate private key persistence:
    monkeypatch.setattr("core.tor_manager.TOR_DATA_DIR", tmp_path / "tor_data")

    (tmp_path / "gopherroot").mkdir()

    # Now initialize DBs in the isolated path
    from db.live_db import init_live_db
    from db.archive_db import init_archive_db
    init_live_db()
    init_archive_db()

    # Your test code here...
```

**Why patch both `core.config.X` and the consuming module?** Python caches module-level `from X import Y` statements. Patching `core.config.GOPHER_ROOT` doesn't affect `core.gopherhole.GOPHER_ROOT` which was imported at load time. You must patch both.

### TCP Integration Tests

The `test_routes.py` pattern starts a real GopherServer on a random port:

```python
@pytest.fixture
async def gopher_server(tmp_path, monkeypatch):
    # ... monkeypatch config paths ...
    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    tcp_server = await asyncio.start_server(
        server.handle_client, "127.0.0.1", 0
    )
    port = tcp_server.sockets[0].getsockname()[1]  # Get actual port
    yield server, port
    tcp_server.close()
    await tcp_server.wait_closed()

async def _query(port: int, selector: str, timeout: float = 5.0) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8", errors="replace")
```

### Writing Tests for a New Route

```python
# tests/test_my_route.py
import pytest
import asyncio

class TestMyRoute:
    @pytest.mark.asyncio
    async def test_my_route_returns_content(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/my/route")
        assert "EXPECTED CONTENT" in resp
        assert resp.endswith(".\r\n")

    @pytest.mark.asyncio
    async def test_my_route_handles_bad_input(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/my/route\tbad|input")
        assert "ERROR" in resp
```

### Writing Tests for a New DB Function

```python
# tests/test_my_db.py
class TestMyRecords:
    def test_insert_and_retrieve(self, memory_db):
        memory_db.execute(
            "INSERT INTO my_records (pid, data, score) VALUES (?, ?, ?)",
            ("test_pid", "hello", 1.5),
        )
        memory_db.commit()
        row = memory_db.execute(
            "SELECT * FROM my_records WHERE pid=?", ("test_pid",)
        ).fetchone()
        assert row["data"] == "hello"
        assert row["score"] == 1.5
```

### Writing Tests for Async Background Tasks

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_my_background_task():
    with patch("my_module.tasks.do_something", return_value=42):
        # Run one iteration instead of the infinite loop
        result = do_something()
        assert result == 42
```

---

## 16. Error Handling Conventions

### Never Crash the Server

Content indexing failures must never break request serving:

```python
try:
    index_content(...)
except Exception:
    pass  # Never break serving for indexing failures
```

This pattern is used in `handle_client()` (line 157). Apply it to any non-critical post-processing.

### Timeout All I/O

| Operation | Timeout | Location |
|-----------|---------|----------|
| Server selector read | 30 seconds | `gopher_server.py:126` |
| Client fetch (connect) | 10 seconds | `gopher_client.py:16` |
| Client fetch (read) | 10 seconds per chunk | `gopher_client.py:82` |
| RPC connectivity test | 5 seconds | `rpc/gateway.py:129` |
| RPC batch test | 10 seconds total | `gopher_server.py:629` |
| Peer ping | 3 seconds default | `gopher_client.py:110` |

Always use `asyncio.wait_for()` with a timeout:
```python
data = await asyncio.wait_for(reader.read(65536), timeout=10)
```

### Graceful Degradation

For optional dependencies, use `try/except ImportError`:

```python
try:
    from web3 import AsyncWeb3
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

# In your route:
if not WEB3_AVAILABLE:
    return self._error_response("Feature requires: pip install web3")
```

### Rate Limiter

The rate limiter uses 100 req/60s for direct connections and 500 req/60s when Tor is active (since all Tor traffic appears from 127.0.0.1). When rate limited, send an error and close:
```python
if not self.rate_limiter.is_allowed(addr[0]):
    writer.write(self._error_response("Rate limit exceeded.").encode("utf-8"))
    await writer.drain()
    return  # Connection closed in finally block
```

### Background Task Error Handling

Never let an exception escape the while-true loop:
```python
while True:
    try:
        do_work()
    except Exception as e:
        logger.warning(f"Task error: {e}")  # Log, don't raise
    await asyncio.sleep(interval)
```

### Config Loading

Always fall back to defaults on corruption:
```python
try:
    with open(config_path) as f:
        return json.load(f)
except (json.JSONDecodeError, OSError):
    pass  # Fall through to defaults
```

---

## 17. All Constants Reference

| Constant | Value | File | Purpose |
|----------|-------|------|---------|
| `GOPHER_HOST` | `"0.0.0.0"` | `core/config.py:22` | Server bind address |
| `GOPHER_PORT` | `7070` | `core/config.py:23` | REFInet TCP port |
| `GOPHER_ROOT` | `<project>/gopherroot` | `core/config.py:24` | Static content root |
| `HOME_DIR` | `~/.refinet` | `core/config.py:13` | Data directory |
| `DB_DIR` | `~/.refinet/db` | `core/config.py:14` | Database directory |
| `PID_FILE` | `~/.refinet/pid.json` | `core/config.py:15` | Identity storage |
| `CONFIG_FILE` | `~/.refinet/config.json` | `core/config.py:17` | User configuration |
| `MULTICAST_GROUP` | `"224.0.70.70"` | `core/config.py:37` | Peer discovery multicast |
| `MULTICAST_PORT` | `7071` | `core/config.py:38` | Peer discovery port |
| `DISCOVERY_INTERVAL_SEC` | `30` | `core/config.py:39` | Announce interval |
| `PROTOCOL_NAME` | `"REFInet"` | `core/config.py:44` | Protocol identifier |
| `PROTOCOL_VERSION` | `"0.3.0"` | `core/config.py:45` | Protocol format version |
| `ACCOUNTING_DAYS_PER_MONTH` | `28` | `core/config.py:30` | Calendar constant |
| `ACCOUNTING_MONTHS_PER_YEAR` | `13` | `core/config.py:31` | Calendar constant |
| `LIVE_DB_RETENTION_MONTHS` | `13` | `core/config.py:32` | Archive threshold |
| `HEALTH_CHECK_INTERVAL_SEC` | `60` | `mesh/discovery.py:178` | Peer ping interval |
| `REPLICATION_INTERVAL_SEC` | `300` | `mesh/replication.py:23` | Registry sync interval |
| `SESSION_DURATION_HOURS` | `24` | `auth/siwe.py:19` | SIWE session lifetime |
| `DOMAIN` | `"refinet://pillar"` | `auth/siwe.py:20` | SIWE domain |
| `GOPHER_TIMEOUT` | `10` | `core/gopher_client.py:16` | Client timeout (seconds) |
| `MAX_RESPONSE_SIZE` | `2097152` (2 MB) | `core/gopher_client.py:17` | Client response cap |
| `ALLOWED_PORTS` | `{70, 7070, 105}` | `core/gopher_client.py:20` | SSRF port allowlist |
| `REFINET_ROUTES` | `("/auth", "/rpc", ...)` | `core/gopher_server.py:96` | Routes gated on port 70 |
| `RateLimiter.max_requests` | `100` / `500` (Tor) | `core/gopher_server.py` | Rate limit threshold |
| `RateLimiter.window_seconds` | `60` | `core/gopher_server.py:68` | Rate limit window |
| Multicast TTL | `2` | `mesh/discovery.py:72` | Router hop limit |
| Server read timeout | `30.0` | `core/gopher_server.py:126` | Selector read timeout |
| RPC test timeout | `5.0` | `rpc/gateway.py:119` | Per-chain test cap |
| `TOR_DATA_DIR` | `~/.refinet/tor_data` | `core/config.py:50` | Tor data directory |
| `TOR_DEFAULTS["tor_enabled"]` | `False` | `core/config.py:52` | Enable Tor hidden service |
| `TOR_DEFAULTS["tor_expose_port_70"]` | `True` | `core/config.py:53` | Expose port 70 via Tor |
| `TOR_DEFAULTS["tor_socks_port"]` | `9050` | `core/config.py:54` | Tor SOCKS port |
| `TOR_DEFAULTS["tor_control_port"]` | `9051` | `core/config.py:55` | Tor control port |
| `TOR_TIMEOUT` | `120` | `core/tor_manager.py:28` | Tor bootstrap timeout (seconds) |
| `MAX_RESTART_ATTEMPTS` | `3` | `core/tor_manager.py:29` | Tor auto-restart limit |
| Tor health check interval | `60` | `core/tor_manager.py:227` | Circuit check interval |
| WAL checkpoint interval | `6 hours` | `pillar.py:182` | Journal checkpoint cycle |

---

## 18. Tor Transport Layer

### Overview

REFInet integrates Tor hidden services as an optional transport layer. When enabled, a Pillar generates a `.onion` address and serves all content through Tor's onion routing network. The Gopher protocol, signing system, PID, mesh, and ledger remain unchanged — Tor is purely additive at the transport layer.

### TorManager Class (`core/tor_manager.py`)

```python
class TorManager:
    def __init__(self, config: dict)
        # Reads: tor_enabled, port, standard_port, tor_expose_port_70,
        #        tor_socks_port, tor_control_port from config

    async def start(self) -> bool
        # Launch Tor subprocess via stem, wait for bootstrap (120s timeout),
        # authenticate to control port.
        # Returns True on success, False if Tor unavailable or disabled.
        # Safe to call even when Tor is not installed — returns False gracefully.

    async def create_hidden_services(self) -> str | None
        # Create ephemeral hidden service mappings for Pillar ports.
        # Returns the .onion address (without port suffix), or None on failure.
        # Reuses persisted private key if available (stable .onion across restarts).

    def get_onion_address(self) -> str | None
        # Return the .onion address if Tor hidden service is active.

    def is_active(self) -> bool
        # Return True if a hidden service is running and has an address.

    async def stop(self)
        # Remove hidden service and terminate Tor process.

    async def check_tor_health(self)
        # Background task: monitor Tor process health every 60 seconds.
        # If Tor dies, attempt restart up to MAX_RESTART_ATTEMPTS (3) times
        # with exponential backoff (10s, 20s, 40s).
```

### Lifecycle in pillar.py

```python
# Before TCP servers start:
tor = TorManager(config)
tor_active = await tor.start()       # Launch Tor subprocess
if tor_active:
    onion = await tor.create_hidden_services()  # Create .onion address
    config["onion_address"] = onion

# Bind address logic:
host_7070 = "127.0.0.1" if tor_active else host  # Loopback when Tor active
host_70 = "127.0.0.1" if tor_active and config.get("tor_expose_port_70") else host

# Pass tor_manager to GopherServer:
server = GopherServer(host=host_7070, port=port, hostname=hostname,
                      is_refinet=True, tor_manager=tor)

# Background task (conditional):
if tor_active:
    tasks.append(tor.check_tor_health())

# Shutdown (in finally block):
await tor.stop()
```

### Private Key Persistence

On first Tor launch, the hidden service private key is saved to `~/.refinet/tor_data/hs_privkey` with `0o600` permissions. On subsequent launches, this key is reloaded so the `.onion` address remains stable.

```python
# In TorManager:
def _privkey_path(self) -> Path:
    return TOR_DATA_DIR / "hs_privkey"

def _load_persisted_privkey(self) -> str | None:
    path = self._privkey_path()
    if path.exists():
        return path.read_text().strip()
    return None

def _persist_privkey(self, privkey: str):
    path = self._privkey_path()
    path.write_text(privkey)
    path.chmod(0o600)  # Owner read/write only
```

### Tor-Aware Rate Limiting

When Tor is active, all inbound traffic arrives from `127.0.0.1`. The `GopherServer` adjusts the rate limit based on Tor status:

```python
# In GopherServer.__init__():
tor_active = tor_manager and tor_manager.is_active() if tor_manager else False
max_requests = 500 if tor_active else 100
self.rate_limiter = RateLimiter(max_requests=max_requests)
```

### .onion Address in Protocol Endpoints

When Tor is active, the `.onion` address is surfaced in:

| Endpoint | How |
|----------|-----|
| Root menu (`/`) | Info line: "Tor: <address>.onion" |
| `/about` | Info lines showing .onion address and ports |
| `/pid` | Fields: `onion_address`, `tor_port_7070`, `tor_port_70` |
| `/status.json` | Fields: `tor_active`, `onion_address` |
| `/peers` | Shows .onion links for peers that have them |
| Mesh announcements | `onion_address` field in UDP JSON |

### Testing

Tor functionality is covered by:

| Module | Tests | Coverage |
|--------|-------|----------|
| `tests/test_tor_manager.py` | 15 | TorManager lifecycle, config, privkey persistence, health monitoring, restart logic |
| `tests/test_tor_integration.py` | 2 (skipped without tor) | End-to-end: Tor bootstrap, hidden service creation |
| `tests/test_routes.py` | 5 (Tor-specific) | TestTorPidDocument (3), TestTorStatusJson (2) |
| `tests/test_discovery.py` | 3 (Tor-specific) | TestOnionAddressInAnnouncement, PeerAnnouncer with onion |

Tests use `monkeypatch.setattr("core.tor_manager.TOR_DATA_DIR", tmp_path / "tor_data")` to isolate private key persistence from the real filesystem.

---

*REFInet v0.3.0 — Developer Guide*
