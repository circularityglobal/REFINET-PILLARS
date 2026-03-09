# REFInet Pillar — Platform Overview

> A sovereign Gopher mesh node with blockchain integration. Turn any machine into a cryptographically identified, decentralized content node in Gopherspace.

**Protocol:** REFInet v0.3.0
**Language:** Python 3.12 (fully async)
**Current Phase:** Phase 1 complete, Phase 2 complete (incl. Tor hidden service integration)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Tech Stack](#2-tech-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [Component Deep Dives](#4-component-deep-dives)
5. [Route Map](#5-route-map)
6. [Database Schema Reference](#6-database-schema-reference)
7. [Networking and Ports](#7-networking-and-ports)
8. [Security Model](#8-security-model)
9. [CLI Reference](#9-cli-reference)
10. [Configuration and State](#10-configuration-and-state)
11. [Test Coverage](#11-test-coverage)
12. [Roadmap Status](#12-roadmap-status)
13. [File Index](#13-file-index)

---

## 1. Executive Summary

REFInet Pillar is a **sovereign mesh node** that operates in Gopherspace — a text-based, menu-driven protocol predating the modern web (RFC 1436). Each Pillar instance is:

- A **Gopher protocol server** serving hierarchical menus and files over TCP
- A **local transaction ledger** tracking all activity in SQLite with a custom 13-month accounting calendar
- A **cryptographic identity** (Pillar ID) based on Ed25519 for signing content and verifying peers
- A **mesh participant** that discovers neighbors via UDP multicast and replicates registries
- A **blockchain gateway** connecting to EVM chains via JSON-RPC with wallet-based authentication (SIWE)
- A **DApp directory** hosting plain-text decentralized application definitions

The platform is designed for **offline-first, LAN-capable, sovereign operation** — no central servers, no DNS dependency, no browser required.

### What's Built Today

| Capability | Status | Notes |
|-----------|--------|-------|
| Gopher protocol server (TCP 7070) | Complete | RFC 1436 compliant, dynamic + static routing |
| SQLite ledger (live + archive) | Complete | 13-month rolling live DB, yearly archive with automated migration pipeline |
| Pillar ID / Ed25519 cryptography | Complete | Key generation, content signing, verification |
| Mesh peer discovery (UDP multicast) | Complete | Auto-discovery on LAN, 30s announcement interval |
| Gopherhole registry replication | Complete | Signature-verified sync every 5 minutes |
| SIWE authentication (EIP-4361) | Complete | Challenge generation, session management, enforced on broadcast |
| EVM RPC gateway (multi-chain) | Complete | 5 chains, 4 Gopher-routed operations, graceful degradation |
| Content indexing | Complete | Every served response indexed by selector, hash, and signature |
| Rate limiting | Complete | Per-IP sliding window (100/500 req/60s), Tor-aware DoS protection |
| DApp definition system | Complete | Parser, directory listing, detail views |
| Gopherhole creation and management | Complete | CLI + API, immutable append-only registry |
| Tor hidden service (.onion) | Complete | Optional anonymous transport via stem/Tor, persistent .onion address |
| Dual-port architecture | Complete | Port 7070 (full features) + port 70 (public Gopher) with route gating |
| CLI interface | Complete | Server start, --status, gopherhole create/list/verify |

### What's Not Built Yet

- CIFI staking and REFI token issuance (Phase 3)
- License activation via staking (Phase 3)
- DApp runtime execution engine (Phase 4)
- LAM (Large Action Model) integration (Phase 4)
- Lightning-network-style Gopher propagation (Phase 5)

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Async runtime | `asyncio` (native) |
| Protocol | Gopher (RFC 1436) over TCP |
| Database | SQLite with WAL journaling |
| Cryptography | Ed25519 signing/verification via `cryptography` library |
| Blockchain | EVM compatible via `web3.py` + `eth-account` |
| Authentication | SIWE / EIP-4361 (Sign-In With Ethereum) |
| Peer discovery | UDP multicast (224.0.70.70:7071) |
| Testing | pytest + pytest-asyncio |
| Optional | `qrcode[pil]` for QR code generation |
| Optional | `stem` for Tor hidden service management |

### Dependencies (`requirements.txt`)

```
cryptography>=41.0.0     # Ed25519 key generation and signing
pytest>=7.0              # Test framework
pytest-asyncio>=0.23.0   # Async test support
eth-account>=0.10.0      # SIWE signature verification (ecrecover)
web3>=6.0.0              # EVM RPC client (optional — graceful degradation)
qrcode[pil]>=7.4.2       # QR code generation for SIWE challenges
stem>=1.8.0              # Tor hidden service management (optional)
```

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    REFInet Pillar Node                       │
├──────────┬──────────┬────────────┬────────────┬────────────┤
│  Gopher  │  SQLite  │   PID &    │    Mesh    │   SIWE     │
│  Server  │  Ledger  │  Crypto    │  Discovery │   Auth     │
│ TCP:7070 │ Live+Arc │  Ed25519   │  Multicast │  EIP-4361  │
├──────────┴──────────┴────────────┴────────────┴────────────┤
│                   DApp Runtime Layer                        │
│            (.dapp definitions + menu rendering)             │
├─────────────────────────────────────────────────────────────┤
│                  EVM RPC Gateway Layer                       │
│     Ethereum · Polygon · Arbitrum · Base · Sepolia          │
├─────────────────────────────────────────────────────────────┤
│               Token Layer (CIFI → REFI)                     │
│                  [Phase 3 — planned]                         │
├─────────────────────────────────────────────────────────────┤
│              Tor Hidden Service Layer (optional)             │
│       .onion address · stem subprocess · auto-restart        │
├─────────────────────────────────────────────────────────────┤
│    Transport: Wi-Fi Mesh / LAN / Internet / Tor (.onion)    │
└─────────────────────────────────────────────────────────────┘
```

### Component Map

```
pillar.py (entry point)
  │
  ├── core/gopher_server.py    ←── TCP server, request routing, transaction logging
  │     ├── core/menu_builder.py    ←── Dynamic Gopher menu generation
  │     ├── core/dapp.py            ←── .dapp file parser
  │     ├── core/gopherhole.py      ←── Gopherhole creation & verification
  │     └── core/gopher_client.py   ←── Async client for peer communication
  │
  ├── db/live_db.py            ←── 13-month rolling ledger + queries
  │     ├── db/schema.py            ←── Full SQLite schema (live + archive)
  │     └── db/archive_db.py        ←── Yearly compressed archive
  │
  ├── crypto/pid.py            ←── Pillar ID generation & persistence
  │     └── crypto/signing.py       ←── Ed25519 content signing & verification
  │
  ├── mesh/discovery.py        ←── UDP multicast peer announcer & listener
  │     └── mesh/replication.py     ←── Gopherhole registry sync between peers
  │
  ├── auth/siwe.py             ←── EIP-4361 challenge generation & verification
  │     └── auth/session.py         ←── Session token management (immutable store)
  │
  ├── core/tor_manager.py      ←── Tor subprocess management, hidden service lifecycle
  │
  ├── rpc/gateway.py           ←── EVM JSON-RPC proxy (multi-chain)
  │     ├── rpc/chains.py           ←── Default chain configurations
  │     └── rpc/config.py           ←── User-configurable RPC endpoints
  │
  ├── cli/hole.py              ←── Gopherhole CLI subcommands
  │
  └── docs/backup.md           ←── Backup and recovery guide
```

---

## 4. Component Deep Dives

### 4.1 Gopher Server

**File:** `core/gopher_server.py` (916 lines)

The heart of the Pillar. An async TCP server implementing the Gopher protocol (RFC 1436).

**Request lifecycle:**
1. Client connects to TCP port 7070
2. Rate limiter checks per-IP request count (100 req/60s direct, 500 req/60s Tor inbound)
3. Client sends selector string + CRLF (e.g., `/dapps\r\n`)
4. Server routes selector to the appropriate handler
5. Response is generated (dynamic menu or static file)
6. Response content is SHA-256 hashed
7. Transaction is logged to SQLite live DB (`daily_tx` table)
8. Daily metrics are updated (`daily_metrics` table)
9. Content is indexed in `content_index` table (selector, type, hash, signature)
10. Response is sent to client
11. Connection closes

**Key behaviors:**
- Empty selector or `/` serves the root menu with Pillar status
- Directory traversal protection via path sanitization and `resolve()` checks
- Auto-generates directory listings when no `gophermap` file exists
- Tracks `request_count` and `start_time` for uptime metrics
- All routes return Gopher-formatted text (type-prefixed lines ending in `\r\n`)

**Server startup banner:**
```
  ╔══════════════════════════════════════════╗
  ║         R E F I n e t   P I L L A R     ║
  ╚══════════════════════════════════════════╝

  Gopher server listening on ('0.0.0.0', 7070)
  Pillar ID: a1b2c3d4e5f6...
  You are now part of Gopherspace.
```

### 4.2 Database Layer

**Files:** `db/schema.py` (192 lines), `db/live_db.py` (481 lines), `db/archive_db.py` (207 lines)

Two SQLite databases per Pillar, both using WAL journaling for concurrent reads:

**Live DB** (`~/.refinet/db/live.db`) — Rolling 13-month transaction ledger
- `daily_tx` — Every request/transaction with content hash and signature
- `daily_metrics` — Aggregated daily productivity per accounting day
- `peers` — Known mesh nodes with last-seen timestamps
- `content_index` — What this Pillar serves (selector → hash mapping)
- `token_state` — CIFI staking and REFI balance tracking
- `gopherholes` — Immutable append-only gopherhole registry (enforced by triggers)
- `siwe_sessions` — Write-only auth session store (never deleted, only revoked)

**Archive DB** (`~/.refinet/db/archive.db`) — Yearly compressed history
- `yearly_summary` — Annual aggregates per node
- `monthly_snapshot` — Monthly data compressed as JSON blobs
- `peer_history` — Historical peer interaction records

**REFInet Accounting Calendar:**
- 13 months x 28 days = 364 days of live data
- Day 365 = accounting balance day (reconciliation)
- Every month has exactly 28 days — no irregular month lengths
- Accounting date computed from standard datetime via `get_accounting_date()`

### 4.3 Cryptographic Identity (PID)

**Files:** `crypto/pid.py`, `crypto/signing.py`

Each Pillar has a unique, persistent cryptographic identity:

- **Pillar ID (PID):** `SHA-256(Ed25519_public_key)` — 64-character hex string
- **Keypair:** Ed25519 (32-byte private key, 32-byte public key)
- **Storage:** `~/.refinet/pid.json` — generated once on first run, persisted forever
- **Short PID:** First 16 characters, used for display

**Content signing flow:**
1. Hash content with SHA-256 → `content_hash`
2. Sign content bytes with Ed25519 private key → `signature` (hex)
3. Anyone with the public key can verify: `verify_signature(data, signature_hex, pubkey_hex)`

**Used for:**
- Gopherhole registration (signs `pid:selector:name:registered_at`)
- Transaction records in the ledger
- Peer verification during discovery
- Replication trust (reject records with invalid signatures)

### 4.4 Mesh Networking

**Files:** `mesh/discovery.py`, `mesh/replication.py`

Fully decentralized peer discovery — no DNS, no central registry.

**Peer Discovery (UDP Multicast):**
- **Announcer:** Broadcasts JSON announcement every 30 seconds to `224.0.70.70:7071`
- **Listener:** Receives announcements, registers new peers in SQLite
- **Announcement payload:**
  ```json
  {
    "type": "pillar_announce",
    "protocol": "REFInet",
    "version": "0.3.0",
    "pid": "<64-char hex>",
    "public_key": "<hex>",
    "hostname": "192.168.1.42",
    "port": 7070,
    "pillar_name": "My Pillar",
    "timestamp": 1709337600,
    "onion_address": "abc123...xyz.onion"
  }
  ```
- `onion_address` is optional — only included when Tor is enabled and a hidden service is active
- Localhost hostnames (`127.0.0.1`, `0.0.0.0`) are replaced with the actual sender IP
- New peers trigger immediate registry sync

**Registry Replication:**
- Every 5 minutes, fetches `/directory.json` from all known peers
- Parses JSON array of gopherhole records
- **Verifies Ed25519 signature** on each record before importing
- Rejects records with invalid signatures (logged as warnings)
- Marks imported records with `source=<peer_pid>` to track provenance
- Parallel sync via `asyncio.gather()` across all peers

### 4.5 Authentication (SIWE)

**Files:** `auth/siwe.py`, `auth/session.py`

Wallet-based authentication using the EIP-4361 Sign-In With Ethereum standard.

**Challenge-response flow:**
1. Client requests `/auth/challenge?address=0x...`
2. Server generates SIWE message with random nonce (16-byte hex)
3. Client signs the message with their Ethereum wallet
4. Server verifies signature via ecrecover
5. Session token created (64-char hex, 24-hour TTL)
6. Session stored in `siwe_sessions` table (immutable — never deleted)

**SIWE message format:**
```
refinet://pillar wants you to sign in with your Ethereum account:
0x<address>

Sign in to REFInet Pillar a1b2c3d4e5f6...

URI: refinet://pillar
Version: 1
Chain ID: 1
Nonce: <32-char hex>
Issued At: <ISO 8601>
Expiration Time: <ISO 8601>
```

**Session properties:**
- 24-hour duration
- Can be revoked (sets `revoked=1`) but never deleted
- Required for RPC transaction broadcasting
- Optional QR code generation for mobile wallet signing

### 4.6 EVM RPC Gateway

**Files:** `rpc/gateway.py`, `rpc/chains.py`, `rpc/config.py`

Local JSON-RPC proxy to EVM blockchains. All chain interactions go through this gateway.

**Supported chains:**

| Chain ID | Network | Symbol | Default RPC |
|----------|---------|--------|-------------|
| 1 | Ethereum Mainnet | ETH | `https://eth.llamarpc.com` |
| 137 | Polygon | MATIC | `https://polygon-rpc.com` |
| 42161 | Arbitrum One | ETH | `https://arb1.arbitrum.io/rpc` |
| 8453 | Base | ETH | `https://mainnet.base.org` |
| 11155111 | Sepolia Testnet | ETH | `https://rpc.sepolia.org` |

**Available methods:**
- `get_balance(chain_id, address)` — Native token balance in wei
- `get_block_number(chain_id)` — Latest block number
- `get_token_balance(chain_id, token_address, wallet_address)` — ERC-20 balance
- `estimate_gas(chain_id, tx_params)` — Gas estimation
- `broadcast(chain_id, signed_tx_hex, session_id)` — Broadcast signed transaction (**requires valid SIWE session** — `session_id` is mandatory)
- `test_connection(chain_id, timeout)` — Connectivity test, returns latency in ms

**Gopher-accessible operations** (via type-7 search queries):
- `/rpc/balance` — Query native token balance
- `/rpc/token` — Query ERC-20 token balance
- `/rpc/gas` — Estimate gas for a transaction
- `/rpc/broadcast` — Submit a signed transaction (authenticated)

**Design choices:**
- `web3` is an optional dependency — gateway degrades gracefully if not installed
- `eth-account` is optional — auth routes return clean error messages if missing
- RPC endpoints configurable via `~/.refinet/rpc_config.json`
- Connection tests capped at 10 seconds total (parallel across all chains)
- All public endpoints, no API keys required

### 4.7 DApp System

**File:** `core/dapp.py`

Decentralized application definitions in a plain-text `.dapp` format. Stored in `gopherroot/dapps/`.

**File format (INI-like sections):**
```
[meta]
name = Uniswap V3
slug = uniswap-v3
chain_id = 1
contract = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45
author_pid = af1cc79d...

[abi]
exactInputSingle((...)) -> uint256
exactOutputSingle((...)) -> uint256
multicall(bytes[]) -> bytes[]

[docs]
[exactInputSingle] — Swaps exact amount of one token for another. Gas: ~150k

[flows]
swap:
  1. Approve tokenIn spending
  2. Call exactInputSingle with parameters
  3. Verify output token balance increased

[warnings]
Always verify slippage tolerance before signing.
```

**Parsed into `DAppDefinition` dataclass:**
- `name`, `slug`, `version`, `chain_id`, `contract`, `author_pid`, `description`, `published`
- `abi_functions` — list of human-readable ABI signatures
- `docs` — per-function documentation
- `flows` — step-by-step interaction instructions
- `warnings` — security notices

### 4.8 Gopherhole Registry

**Files:** `core/gopherhole.py`, `cli/hole.py`

Gopherholes are registered content sites on the REFInet mesh.

**Creation flow:**
1. Validate selector format: `/holes/<slug>` (alphanumeric, dash, underscore, 1-64 chars)
2. Scaffold directory under `gopherroot/holes/<slug>/`
3. Generate starter files (`gophermap` + `README.txt`)
4. Sign registration payload with Ed25519: `pid:selector:name:registered_at`
5. Compute tx_hash as SHA-256 of the full record
6. Insert into immutable `gopherholes` table (append-only, enforced by triggers)
7. Return registration record

**Immutability guarantees:**
- SQLite triggers prevent UPDATE and DELETE on `gopherholes` table
- Records can only be inserted, never modified or removed
- `UNIQUE(pid, selector)` prevents duplicate registrations

### 4.9 Menu Builder

**File:** `core/menu_builder.py`

Generates dynamic Gopher menus from database state and Pillar identity.

**Gopher line types used:**
| Type | Code | Example |
|------|------|---------|
| Informational | `i` | Non-clickable text, banners |
| Text file | `0` | Downloadable text documents |
| Directory/Menu | `1` | Clickable submenu navigation |
| Search query | `7` | Input prompt (e.g., address entry) |
| HTML link | `h` | Bridge to HTTP resources |

**Menu generators:**
- `build_root_menu()` — Banner, navigation links, live metrics (tx count, peers, uptime)
- `build_about_menu()` — Pillar identity and version info
- `build_network_menu()` — Peer list with hostnames and ports
- `build_dapps_menu()` — DApp directory with descriptions
- `build_directory_menu()` — Human-readable gopherhole registry
- `build_auth_menu()` — SIWE authentication options
- `build_rpc_menu()` — Chain connectivity status with latency
- `build_pid_document()` — Full PID identity document
- `build_transactions_document()` — Recent transaction log
- `build_peers_document()` — Detailed peer information
- `build_ledger_document()` — Ledger status and metrics

---

## 5. Route Map

All routes are handled by `GopherServer._route()` in `core/gopher_server.py`.

### Dynamic Routes (generated from DB state)

| Selector | Handler | Description |
|----------|---------|-------------|
| `""` or `/` | `build_root_menu()` | Root menu with Pillar status, tx count, peer count |
| `/about` | `build_about_menu()` | Pillar identity and version info |
| `/network` | `build_network_menu()` | Network status and peer list |
| `/dapps` | `build_dapps_menu()` | DApp directory listing |
| `/dapps/<slug>.dapp` | `_render_dapp_detail()` | Individual DApp detail page |
| `/directory` | `build_directory_menu()` | Gopherhole registry (human-readable Gopher menu) |
| `/directory.json` | Versioned JSON envelope | Gopherhole registry (machine-readable, browser contract v1) |
| `/auth` | `build_auth_menu()` | Authentication menu |
| `/auth/challenge` | `create_challenge()` | SIWE challenge generation (accepts `?address=0x...` or tab-separated query) |
| `/auth/verify` | `establish_session()` | SIWE signature verification — accepts `address\|signature\|message`, returns session token |
| `/rpc` | `_route_rpc_status()` | EVM RPC gateway status with per-chain latency |
| `/rpc/balance` | `gw.get_balance()` | Native token balance query (input: `chain_id\|0xAddress`) |
| `/rpc/token` | `gw.get_token_balance()` | ERC-20 token balance query (input: `chain_id\|token\|wallet`) |
| `/rpc/gas` | `gw.estimate_gas()` | Gas estimation (input: `chain_id\|to\|value_wei`) |
| `/rpc/broadcast` | `gw.broadcast()` | Broadcast signed tx (**requires SIWE session**; input: `session_id\|chain_id\|signed_tx_hex`) |
| `/pid` | `build_pid_document()` | Pillar identity document (full PID + public key) |
| `/transactions` | `build_transactions_document()` | Recent transaction log |
| `/peers` | `build_peers_document()` | Known peer details |
| `/ledger` | `build_ledger_document()` | Ledger status and metrics |
| `/search` | `_route_search()` | Full-text search across content index (type-7 query input) |
| `/status.json` | JSON response | Machine-readable Pillar status (PID, version, uptime, peers, tx count) |
| `/releases` | `build_releases_menu()` | Release history and download links |
| `/download` | `build_download_menu()` | Download landing page |
| `/download/<file>` | `_serve_binary()` | Binary file download (8KB chunked, path-traversal protected) |
| `/pillar-setup` | `build_pillar_setup_menu()` | Pillar setup instructions |
| `/welcome` | `build_welcome_menu()` | Welcome / onboarding landing |
| `/pillar/status` | `_build_pillar_status_response()` | Detailed pillar status |
| `/identity` | `build_identity_menu()` | Pillar identity (text format) |
| `/identity.json` | JSON envelope | Deployer binding identity (JSON for browser extension) |
| `/identity/verify` | Deployer binding verification | Verify a PID against public key |
| `/vault` | `build_vault_menu()` | Encrypted vault access |
| `/settings` | `build_settings_menu()` | Pillar configuration |
| `/sync` | `build_sync_menu()` | Replication sync status |
| `/health` | Health check | Node health summary |
| `/health/services` | JSON service status | Per-service health breakdown (machine-readable) |
| `/onboarding/readiness` | Readiness check | First-run readiness status |
| `/onboarding/readiness/install` | Install helper | Guided dependency installation |
| `/auth/zkp-challenge` | ZKP challenge | Zero-knowledge proof challenge generation |
| `/auth/zkp-verify` | ZKP verify | Zero-knowledge proof verification |

### Static Routes (served from `gopherroot/`)

| Selector | Source | Description |
|----------|--------|-------------|
| `/news/*` | `gopherroot/news/` | News and updates |
| `/holes/<slug>/*` | `gopherroot/holes/<slug>/` | Gopherhole content |
| Any other | `gopherroot/<path>` | Serves files or auto-generates directory listing |

---

## 6. Database Schema Reference

### Live Database — 7 Tables

#### `daily_tx` — Transaction Ledger

| Column | Type | Description |
|--------|------|-------------|
| `tx_id` | TEXT PK | Unique transaction ID |
| `dapp_id` | TEXT NOT NULL | DApp identifier (e.g., `gopher.core`) |
| `pid` | TEXT NOT NULL | Pillar that generated this transaction |
| `amount` | REAL | Transaction amount (default 0.0) |
| `token_type` | TEXT | `CIFI` or `REFI` (default `REFI`) |
| `selector` | TEXT | Gopher selector that triggered the transaction |
| `mesh_peer_pid` | TEXT | Peer involved (if any) |
| `content_hash` | TEXT | SHA-256 of the response content |
| `signature` | TEXT | Ed25519 signature |
| `accounting_day` | INTEGER | 1-28 |
| `accounting_month` | INTEGER | 1-13 |
| `accounting_year` | INTEGER | REFInet accounting year |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_daily_tx_day`, `idx_daily_tx_pid`, `idx_daily_tx_dapp`

#### `daily_metrics` — Aggregated Productivity

| Column | Type | Description |
|--------|------|-------------|
| `accounting_day` | INTEGER | 1-28 (composite PK) |
| `accounting_month` | INTEGER | 1-13 (composite PK) |
| `accounting_year` | INTEGER | (composite PK) |
| `pid` | TEXT | (composite PK) |
| `total_tx_count` | INTEGER | Transactions this day |
| `total_volume` | REAL | Volume this day |
| `avg_latency_ms` | REAL | Average response latency |
| `peers_connected` | INTEGER | Peers seen |
| `content_served` | INTEGER | Gopher requests served |
| `uptime_seconds` | INTEGER | Server uptime |

#### `peers` — Peer Registry

| Column | Type | Description |
|--------|------|-------------|
| `pid` | TEXT PK | Peer's Pillar ID |
| `public_key` | TEXT NOT NULL | Ed25519 public key |
| `hostname` | TEXT | Network hostname/IP |
| `port` | INTEGER | Gopher port (default 7070) |
| `last_seen` | DATETIME | Last announcement time |
| `stake_amount` | REAL | CIFI staked (default 0.0) |
| `pillar_name` | TEXT | Display name |
| `protocol_version` | TEXT | Protocol version string |
| `onion_address` | TEXT | Tor .onion address (nullable, set via `update_peer_onion()`) |
| `status` | TEXT | `online`, `degraded`, `offline`, or `unknown` (default) |
| `latency_ms` | REAL | Last measured ping latency in milliseconds |
| `consecutive_failures` | INTEGER | Count of consecutive failed pings (default 0) |
| `last_checked` | DATETIME | Last health check timestamp |

#### `content_index` — Served Content

| Column | Type | Description |
|--------|------|-------------|
| `selector` | TEXT PK | Gopher selector path |
| `content_type` | TEXT NOT NULL | `menu`, `text`, `binary`, or `dapp` |
| `content_hash` | TEXT | SHA-256 hash |
| `signature` | TEXT | Ed25519 signature |
| `pid` | TEXT NOT NULL | Creator PID |
| `size_bytes` | INTEGER | Content size |
| `created_at` | DATETIME | Creation time |
| `updated_at` | DATETIME | Last update time |

#### `token_state` — Token Balances and Staking

| Column | Type | Description |
|--------|------|-------------|
| `pid` | TEXT PK | Pillar ID |
| `cifi_staked` | REAL | Amount of CIFI staked |
| `refi_balance` | REAL | Current REFI balance |
| `refi_issued` | REAL | Total REFI ever issued |
| `license_active` | INTEGER | 1 = licensed, 0 = not |
| `license_expires` | DATETIME | License expiry date |
| `blockchain_tx` | TEXT | On-chain staking tx reference |
| `updated_at` | DATETIME | Last update |

#### `gopherholes` — Immutable Registry

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `pid` | TEXT NOT NULL | Registering Pillar's PID |
| `selector` | TEXT NOT NULL | Gopherspace path (e.g., `/holes/mysite`) |
| `name` | TEXT NOT NULL | Display name |
| `description` | TEXT | Description |
| `owner_address` | TEXT | EVM address (optional, for Phase 3 SIWE) |
| `pubkey_hex` | TEXT NOT NULL | Pillar's Ed25519 public key |
| `signature` | TEXT NOT NULL | Ed25519 signature of `pid+selector+name+registered_at` |
| `registered_at` | TEXT NOT NULL | Registration date (YYYY-MM-DD) |
| `tx_hash` | TEXT NOT NULL | SHA-256 of the full record |
| `source` | TEXT | `local` or peer PID (replicated from) |

**Constraints:** `UNIQUE(pid, selector)`
**Triggers:** `gopherholes_no_update` (blocks UPDATE), `gopherholes_no_delete` (blocks DELETE)

#### `siwe_sessions` — Auth Sessions

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `session_id` | TEXT UNIQUE | 32-byte random hex token |
| `address` | TEXT NOT NULL | EVM address (checksummed) |
| `nonce` | TEXT NOT NULL | 16-byte random hex |
| `issued_at` | TEXT NOT NULL | ISO 8601 timestamp |
| `expires_at` | TEXT NOT NULL | ISO 8601 timestamp |
| `signature` | TEXT NOT NULL | EIP-4361 wallet signature |
| `pid` | TEXT NOT NULL | Issuing Pillar's PID |
| `revoked` | INTEGER | 0 = active, 1 = revoked |
| `created_at` | TEXT NOT NULL | Creation timestamp |

**Trigger:** `siwe_sessions_no_delete` (blocks DELETE — use `revoked=1` instead)

### Archive Database — 3 Tables

#### `yearly_summary`
Composite PK: `(accounting_year, pid)` — Annual aggregates (tx count, volume, latency, content served, uptime, peers seen).

#### `monthly_snapshot`
Composite PK: `(accounting_year, accounting_month, pid)` — Monthly data with `snapshot_data` as JSON blob and `content_hash` for verification.

#### `peer_history`
Composite PK: `(pid, accounting_year)` — Historical peer records (first_seen, last_seen, total_interactions).

---

## 7. Networking and Ports

| Service | Protocol | Address | Port | Purpose |
|---------|----------|---------|------|---------|
| Gopher Server | TCP | 0.0.0.0 (configurable) | 7070 (configurable) | Full-feature content serving |
| Public Gopher | TCP | 0.0.0.0 (configurable) | 70 (optional) | Route-gated public Gopher endpoint |
| Tor Hidden Service | TCP | 127.0.0.1 (loopback) | 7070 via .onion | Anonymous access via Tor network |
| Mesh Discovery | UDP Multicast | 224.0.70.70 | 7071 | Peer announcement and detection |
| RPC Gateway | HTTPS | Per-chain endpoints | Various | EVM blockchain JSON-RPC access |

### Background Tasks

| Task | Interval | Purpose |
|------|----------|---------|
| Peer Announcer | 30s | Broadcasts this Pillar via UDP multicast |
| Peer Listener | Continuous | Listens for peer announcements |
| Registry Replication | 5 min | Syncs gopherhole registries with known peers |
| Peer Health Check | 60s | Pings all known peers, updates status/latency |
| Tor Health Monitor | 60s | Checks Tor subprocess, auto-restarts (up to 3 retries) |
| WAL Checkpoint | 6h | `PRAGMA wal_checkpoint(TRUNCATE)` prevents journal accumulation |
| Archive Migration | 24h | Migrates expired months from live DB to archive DB (13-month retention) |

### Gopher Client Restrictions (`core/gopher_client.py`)
- **SSRF protection:** Blocks loopback addresses (127.x, ::1)
- **Allowed ports:** 70, 7070, 105 only
- **Max response:** 2 MB
- **Timeout:** 10 seconds
- **LAN IPs:** Allowed (192.168.x, 10.x, 172.16-31.x)

---

## 8. Security Model

### Cryptographic Identity
- Every Pillar has a unique Ed25519 keypair generated on first run
- PID = SHA-256(public_key) — deterministic, unforgeable identity
- Content is signed by the creator's private key, verifiable by anyone with the public key

### Immutable Registries
- `gopherholes` table: SQLite triggers prevent UPDATE and DELETE at the database engine level
- `siwe_sessions` table: SQLite trigger prevents DELETE — sessions can only be revoked (revoked=1)
- All modifications are append-only, creating a verifiable audit trail

### Signature Verification
- Gopherhole records are Ed25519-signed during creation
- During replication, every record is verified before import — invalid signatures are rejected
- Content hashes (SHA-256) are stored with every transaction

### Authentication
- SIWE (EIP-4361) provides wallet-based authentication without passwords
- Challenge-response flow with random nonces prevents replay attacks
- Sessions expire after 24 hours
- RPC transaction broadcasting requires a valid, non-expired, non-revoked session

### Rate Limiting
- Per-IP sliding window: 100 requests per 60 seconds for direct connections
- Tor-aware: 500 requests per 60 seconds for `127.0.0.1` (Tor inbound) — higher limit since all Tor traffic shares one IP
- In-memory `deque`-based tracker — lightweight, no external dependencies
- Exceeded clients receive a Gopher error response and connection is closed
- Prevents basic DoS attacks without blocking legitimate traffic

### Network Security
- Gopher client blocks loopback addresses (SSRF protection)
- Only ports 70, 7070, and 105 are allowed for outbound Gopher connections
- Path traversal protection via `resolve()` and prefix checks on static file serving
- Directory listing excludes dotfiles and gophermap files

### Tor Transport Security
- Hidden service private key stored at `~/.refinet/tor_data/hs_privkey` with `0o600` permissions
- Persistent .onion address — same key reused across restarts
- Dual identity model: PID (SHA-256 of Ed25519 pubkey) for content signing, .onion (SHA3-256 of Tor Ed25519 pubkey) for routing
- Three operating modes: Direct (0.0.0.0 binding), Tor-only (127.0.0.1 loopback), Dual (LAN + .onion)
- Tor subprocess managed via `stem` library with automatic restart on failure (up to 3 retries)

### Graceful Degradation
- `web3` is optional: RPC gateway shows "not available" message if not installed
- `eth-account` is optional: Auth routes return clean error if not installed (no stack traces)
- `stem` is optional: Tor features disabled if not installed, server runs in direct mode
- Archive migration runs silently if no expired data exists

---

## 9. CLI Reference

### Start Server (default)

```bash
python3 pillar.py [--host 0.0.0.0] [--port 7070] [--no-mesh] [--verbose] [--status]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `7070` | Gopher port |
| `--no-mesh` | disabled | Disable peer discovery |
| `--verbose`, `-v` | disabled | Debug-level logging |
| `--status` | — | Print Pillar status (PID, port, peers, uptime) and exit |

> **Tor:** Enable via `config.json` — set `"tor_enabled": true`. There is no `--tor` CLI flag; Tor is a persistent config setting.

### Explicit Server Start

```bash
python3 pillar.py run [--host 0.0.0.0] [--port 7070] [--no-mesh] [--verbose]
```

### Gopherhole Management

```bash
# Create a new gopherhole
python3 pillar.py hole create --name "My Site" --selector /holes/mysite [--desc "Description"] [--owner 0x...]

# List registered gopherholes
python3 pillar.py hole list [--peers] [--json]

# Verify a gopherhole's signature
python3 pillar.py hole verify --pid <pid> --selector /holes/mysite
```

### Connecting with Gopher Clients

```bash
curl gopher://localhost:7070/          # Using curl
lynx gopher://localhost:7070           # Using lynx
```

---

## 10. Configuration and State

### Directory Layout

```
~/.refinet/
├── pid.json              # Ed25519 keypair and PID (generated once, never delete)
├── config.json           # Pillar configuration (hostname, port, name, Tor settings)
├── peers.json            # Known peer list (optional)
├── rpc_config.json       # Custom RPC endpoints per chain (optional)
├── tor_data/             # Tor hidden service data (created when --tor is used)
│   ├── hs_privkey        # Tor Ed25519 private key (0o600 permissions)
│   └── hostname          # .onion address file
└── db/
    ├── live.db           # 13-month rolling transaction ledger
    └── archive.db        # Yearly compressed historical records
```

### Default Configuration (`~/.refinet/config.json`)

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

### Constants (`core/config.py`)

| Constant | Value | Description |
|----------|-------|-------------|
| `GOPHER_HOST` | `0.0.0.0` | Default bind address |
| `GOPHER_PORT` | `7070` | Default Gopher port |
| `ACCOUNTING_DAYS_PER_MONTH` | `28` | Days per accounting month |
| `ACCOUNTING_MONTHS_PER_YEAR` | `13` | Months per accounting year |
| `LIVE_DB_RETENTION_MONTHS` | `13` | Months of live data retained |
| `MULTICAST_GROUP` | `224.0.70.70` | UDP multicast group |
| `MULTICAST_PORT` | `7071` | UDP multicast port |
| `DISCOVERY_INTERVAL_SEC` | `30` | Peer announcement interval |
| `PROTOCOL_NAME` | `REFInet` | Protocol identifier |
| `PROTOCOL_VERSION` | `0.3.0` | Current protocol version |
| `TOR_DATA_DIR` | `~/.refinet/tor_data` | Tor hidden service data directory |
| `TOR_DEFAULTS.tor_enabled` | `False` | Tor disabled by default |
| `TOR_DEFAULTS.tor_expose_port_70` | `True` | Expose port 70 via Tor when enabled |
| `TOR_DEFAULTS.tor_socks_port` | `9050` | Tor SOCKS proxy port |
| `TOR_DEFAULTS.tor_control_port` | `9051` | Tor control port |

---

## 11. Test Coverage

**Framework:** pytest + pytest-asyncio
**Config:** `pytest.ini` at project root

| Test Module | Tests | Coverage Area |
|-------------|-------|--------------|
| `tests/test_routes.py` | 41 | End-to-end TCP route integration + rate limiting |
| `tests/test_websocket_bridge.py` | 40 | WebSocket bridge (connection, auth, messaging) |
| `tests/test_synergy.py` | 31 | Cross-component integration (Tor + mesh, dual-port + replication, full stack) |
| `tests/test_gap_closure.py` | 26 | Edge cases and gap coverage (error paths, boundary conditions, concurrency) |
| `tests/test_discovery.py` | 25 | Mesh peer discovery (announce/parse, hostname replacement, health monitoring) |
| `tests/test_dual_port.py` | 23 | Dual-port architecture (port 7070 + port 70, route gating, search on port 70) |
| `tests/test_forward_proxy.py` | 22 | Forward proxy + SSRF protection |
| `tests/test_recovery.py` | 18 | Shamir secret recovery (split, restore) |
| `tests/test_first_run.py` | 16 | First-run initialization (PID generation, DB creation, gopherhole scaffolding) |
| `tests/test_tor_manager.py` | 15 | TorManager lifecycle (start/stop, auto-restart, privkey persistence, health checks) |
| `tests/test_siwe.py` | 15 | SIWE challenge generation and signature verification |
| `tests/test_onboarding_ws.py` | 14 | Onboarding wizard WebSocket integration |
| `tests/test_profiles.py` | 13 | Profile management (create, switch, delete) |
| `tests/test_gopherholes.py` | 13 | Gopherhole creation, validation, signature verification, peer health |
| `tests/test_gopher_client.py` | 13 | Async Gopher client (fetch, ping, SSRF protection) |
| `tests/test_encrypted_channel.py` | 13 | Encrypted channel communication |
| `tests/test_zkp.py` | 12 | Zero-knowledge proof auth (challenge, verify) |
| `tests/test_vpn_manager.py` | 12 | VPN manager lifecycle |
| `tests/test_gophermap_parser.py` | 12 | Gopher menu parsing (all item types, edge cases) |
| `tests/test_hsm.py` | 10 | Hardware security module integration |
| `tests/test_download_route.py` | 10 | Download route (gophermap, binary, path traversal) |
| `tests/test_dapp.py` | 10 | DApp definition parsing (metadata, ABI, docs, flows, warnings) |
| `tests/test_vault.py` | 9 | Encrypted vault operations |
| `tests/test_tls.py` | 9 | TLS/GopherS listener |
| `tests/test_replication.py` | 9 | Peer registry synchronization and signature verification |
| `tests/test_peer_cli.py` | 9 | Peer CLI subcommands |
| `tests/test_gopherhole_cli.py` | 9 | CLI commands for gopherhole management |
| `tests/test_refinet_gopherhole.py` | 8 | REFInet-specific gopherhole features |
| `tests/test_onboarding_wizard.py` | 7 | Onboarding wizard flow |
| `tests/test_binding.py` | 7 | Binding/port allocation |
| `tests/test_ipc_socket.py` | 6 | IPC socket communication |
| `tests/test_rpc.py` | 5 | RPC gateway connectivity and chain support |
| `tests/test_tor_integration.py` | 2 | Tor integration smoke tests (requires Tor binary — skipped in CI) |

**Total: 484 tests across 33 modules (479 passed, 5 skipped)** | **Fixtures:** `tests/conftest.py` provides async test fixtures, temporary databases, and mock peer data.

---

## 12. Roadmap Status

| Phase | Description | Status | What It Delivers |
|-------|-------------|--------|-----------------|
| **Phase 1** | Gopher server + SQLite + PID | **Complete** | TCP Gopher server, SQLite ledger (live + archive), Ed25519 PID generation, content signing, menu system, static file serving, DApp definitions, gopherhole registry |
| **Phase 2** | Mesh discovery, replication & Tor | **Complete** | UDP multicast peer discovery, gopherhole registry replication with signature verification, SIWE authentication (challenge + verify), EVM RPC gateway, CLI tools, peer health monitoring, versioned `/directory.json` browser contract, Tor hidden service integration (.onion), dual-port architecture (7070 + 70), `/search` route, `--status` command |
| **Phase 3** | CIFI staking → REFI issuance + license activation | Planned | Token economics, on-chain staking, license management, REFI token issuance |
| **Phase 4** | DApp runtime + LAM integration | Planned | Execute DApp flows (not just display), Large Action Model integration for smart contract interaction |
| **Phase 5** | Lightning-network-style Gopher propagation | Planned | Cross-network content routing, hop-by-hop gossip protocol (`/gossip` route), payment channels for content delivery |

**Known limitations (deferred):**
- Gossip protocol for multi-hop propagation not yet implemented — replication only reaches directly discovered peers (Phase 5)
- `token_state` table exists in schema but is not populated until Phase 3 (CIFI staking)
- Replication conflict logging is ephemeral (log output only, not persisted to ledger)
- Tor integration requires `stem` library and `tor` binary installed on the host

---

## 13. File Index

| File | Lines | Purpose |
|------|-------|---------|
| `pillar.py` | 617 | Main entry point, CLI parsing, async service launcher, Tor lifecycle |
| `core/config.py` | 126 | Constants, paths, ports, protocol version, Tor defaults, directory init |
| `core/gopher_server.py` | 1,323 | Async TCP Gopher server, route handling, tx logging, rate limiting, dual-port |
| `core/menu_builder.py` | 974 | Dynamic Gopher menu generation (all menu types, Tor-aware, RPC links) |
| `core/dapp.py` | 164 | DApp definition parser (`.dapp` file format) |
| `core/gopherhole.py` | 174 | Gopherhole creation, validation, signature verification |
| `core/gopher_client.py` | 138 | Async Gopher client for peer communication, SSRF protection |
| `core/gophermap_parser.py` | 106 | RFC 1436 Gopher menu parser (structured items from raw text) |
| `core/tor_manager.py` | 304 | Tor subprocess management, hidden service lifecycle, auto-restart |
| `db/schema.py` | 330 | Full SQLite schema definitions (live + archive, with triggers) |
| `db/live_db.py` | 536 | Live DB operations, accounting calendar, queries, peer onion tracking |
| `db/archive_db.py` | 221 | Archive DB operations (yearly summary, monthly snapshots, migration) |
| `crypto/pid.py` | 234 | PID generation, Ed25519 keypair management, persistence |
| `crypto/signing.py` | 47 | SHA-256 hashing, Ed25519 signing and verification |
| `mesh/discovery.py` | 321 | UDP multicast peer announcer, listener, health monitoring |
| `mesh/replication.py` | 142 | Gopherhole registry sync between peers |
| `auth/siwe.py` | 90 | EIP-4361 SIWE challenge generation and verification |
| `auth/session.py` | 198 | Session token creation, validation, revocation |
| `rpc/gateway.py` | 142 | EVM JSON-RPC proxy (multi-chain, async) |
| `rpc/chains.py` | 53 | Default chain configurations (5 EVM chains) |
| `rpc/config.py` | 52 | User-configurable RPC endpoint management |
| `cli/hole.py` | 109 | Gopherhole CLI subcommands (create, list, verify) |
| `onboarding/server.py` | 201 | Onboarding Gopher route handlers |
| `onboarding/wizard.py` | 559 | First-run setup wizard logic |
| `onboarding/readiness_step.py` | 114 | Dependency readiness check steps |
| `vault/storage.py` | 200 | Encrypted vault storage backend |
| `integration/websocket_bridge.py` | 509 | WebSocket bridge for browser extension |
| `docs/backup.md` | 43 | Backup and recovery guide |
| `tests/test_routes.py` | 516 | End-to-end TCP route integration tests (41 tests) |
| `tests/test_websocket_bridge.py` | 364 | WebSocket bridge tests (40 tests) |
| `tests/test_synergy.py` | 486 | Cross-component integration tests (31 tests) |
| `tests/test_gap_closure.py` | 347 | Edge case and gap coverage tests (26 tests) |
| `tests/test_discovery.py` | 220 | Mesh peer discovery tests (25 tests) |
| `tests/test_dual_port.py` | 231 | Dual-port architecture tests (23 tests) |
| `tests/test_forward_proxy.py` | 105 | Forward proxy tests (22 tests) |
| `tests/test_recovery.py` | 116 | Shamir secret recovery tests (18 tests) |
| `tests/test_first_run.py` | 199 | First-run initialization tests (16 tests) |
| `tests/test_tor_manager.py` | 186 | TorManager lifecycle tests (15 tests) |
| `tests/test_siwe.py` | 207 | SIWE auth tests (15 tests) |
| `tests/test_onboarding_ws.py` | 277 | Onboarding WebSocket tests (14 tests) |
| `tests/test_profiles.py` | 132 | Profile management tests (13 tests) |
| `tests/test_gopherholes.py` | 366 | Gopherhole tests (13 tests) |
| `tests/test_gopher_client.py` | 99 | Gopher client tests (13 tests) |
| `tests/test_encrypted_channel.py` | 139 | Encrypted channel tests (13 tests) |
| `tests/test_zkp.py` | 102 | ZKP auth tests (12 tests) |
| `tests/test_vpn_manager.py` | 84 | VPN manager tests (12 tests) |
| `tests/test_gophermap_parser.py` | 97 | Gopher menu parser tests (12 tests) |
| `tests/test_hsm.py` | 59 | HSM integration tests (10 tests) |
| `tests/test_download_route.py` | 186 | Download route tests (10 tests) |
| `tests/test_dapp.py` | 127 | DApp definition tests (10 tests) |
| `tests/test_vault.py` | 112 | Encrypted vault tests (9 tests) |
| `tests/test_tls.py` | 94 | TLS/GopherS tests (9 tests) |
| `tests/test_replication.py` | 175 | Replication tests (9 tests) |
| `tests/test_peer_cli.py` | 85 | Peer CLI tests (9 tests) |
| `tests/test_gopherhole_cli.py` | 104 | Gopherhole CLI tests (9 tests) |
| `tests/test_refinet_gopherhole.py` | 171 | REFInet gopherhole tests (8 tests) |
| `tests/test_onboarding_wizard.py` | 242 | Onboarding wizard tests (7 tests) |
| `tests/test_binding.py` | 227 | Binding/port tests (7 tests) |
| `tests/test_ipc_socket.py` | 56 | IPC socket tests (6 tests) |
| `tests/test_rpc.py` | 50 | RPC gateway tests (5 tests) |
| `tests/test_tor_integration.py` | 83 | Tor integration smoke tests (2 tests, requires `tor` binary) |
| `gopherroot/gophermap` | — | Static root menu |
| `gopherroot/dapps/uniswap-v3.dapp` | — | Example DApp definition (Uniswap V3 swap) |
| **Total source** | **~7,984** | Excluding tests and content files |
