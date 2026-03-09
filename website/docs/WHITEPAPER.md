# REFInet: A Sovereign Mesh Protocol for Decentralized Computing in Gopherspace

**Version 0.3.0 | March 2026**

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [The Problem](#2-the-problem)
3. [The REFInet Vision](#3-the-refinet-vision)
4. [Architecture Overview](#4-architecture-overview)
5. [Core Capabilities](#5-core-capabilities)
   - 5.1 [Gopher Protocol Server](#51-gopher-protocol-server)
   - 5.2 [Cryptographic Identity (Pillar ID)](#52-cryptographic-identity-pillar-id)
   - 5.3 [The 13-Month Accounting Calendar](#53-the-13-month-accounting-calendar)
   - 5.4 [SQLite Ledger (Live + Archive)](#54-sqlite-ledger-live--archive)
   - 5.5 [Mesh Peer Discovery](#55-mesh-peer-discovery)
   - 5.6 [Gopherhole Registry & Replication](#56-gopherhole-registry--replication)
   - 5.7 [SIWE Authentication (EIP-4361)](#57-siwe-authentication-eip-4361)
   - 5.8 [EVM RPC Gateway](#58-evm-rpc-gateway)
   - 5.9 [DApp Definition System](#59-dapp-definition-system)
   - 5.10 [Rate Limiting & Security](#510-rate-limiting--security)
   - 5.11 [Content Indexing](#511-content-indexing)
   - 5.12 [Tor Transport Layer](#512-tor-transport-layer)
   - 5.13 [Backup & Recovery](#513-backup--recovery)
6. [Security Model](#6-security-model)
7. [Token Economics (Planned)](#7-token-economics-planned)
8. [Developer Guide](#8-developer-guide)
9. [Roadmap](#9-roadmap)
10. [Technical Specifications](#10-technical-specifications)
11. [Conclusion](#11-conclusion)

---

## 1. Abstract

REFInet is a sovereign mesh protocol that combines the simplicity of the Gopher protocol (RFC 1436) with modern cryptographic identity, blockchain connectivity, anonymous transport, and zero-configuration peer discovery into a single-process node called a **Pillar**.

Every Pillar generates an Ed25519 keypair on first boot, derives a collision-resistant Pillar ID (PID) from the public key, and begins serving content over two TCP ports — 7070 (REFInet, full features) and 70 (standard Gopher, public content). Every response is signed with the Pillar's Ed25519 key and carries a verifiable signature block. Pillars discover each other via UDP multicast on the local network, replicate cryptographically signed content registries, and proxy EVM blockchain operations — all without DNS, certificate authorities, cloud services, or a web browser.

When Tor mode is enabled, the Pillar generates a second identity — a `.onion` address derived from a Tor Ed25519 keypair — and serves content through Tor hidden services. Browser clients connecting via `.onion` addresses receive end-to-end encryption within the Tor network, with both endpoints' IP addresses hidden from each other and from all network observers. The Pillar's REFInet identity system remains unchanged: the PID is still SHA-256(Ed25519 public key), and all responses are still signed. Tor is added beneath the existing protocol, not in place of it. No port forwarding, no DNS registration, and no public IP address are required.

REFInet proposes a return to the original architecture of the internet — where every computer is a server — augmented with the cryptographic primitives, anonymous transport, and economic incentives that the early internet lacked. The result is a lightweight, offline-first, LAN-capable computing platform that scales from a single Raspberry Pi to a global mesh of sovereign, anonymous nodes.

This whitepaper describes the architecture, capabilities, and security model of REFInet as implemented in the current codebase (v0.3.0). Every technical claim in this document corresponds to running, tested code.

---

## 2. The Problem

### Centralization of Infrastructure

The modern internet depends on a small number of chokepoints:

- **DNS**: A hierarchical naming system controlled by ICANN and national registrars. Losing access to a domain means losing your identity.
- **Certificate Authorities**: HTTPS requires certificates from a trusted third party. Self-signed certificates are rejected by browsers.
- **Cloud Providers**: The majority of internet services run on AWS, Google Cloud, or Azure. An account suspension can erase an entire business overnight.
- **Web Browsers**: The web has become the de facto platform, but browsers are controlled by a handful of corporations that dictate what protocols, APIs, and content are acceptable.

This architecture was not inevitable. The original internet — including the Gopher protocol, published in RFC 1436 in 1993 — was designed as a network of peers. Any computer could serve content. Any client could access it. No intermediary was required.

### The Complexity of Existing Alternatives

Decentralized alternatives exist, but they carry significant trade-offs:

- **IPFS**: Content-addressed storage with a complex runtime, heavy bandwidth requirements, and no native identity system.
- **Tor / I2P**: Anonymity networks that provide strong privacy but lack native identity, content signing, economic incentives, or a content-serving protocol. They solve the transport problem but not the application problem.
- **Blockchain-only solutions**: Smart contracts can store state but cannot serve documents, menus, or interactive content over a simple TCP connection.
- **ActivityPub / Fediverse**: Depends on HTTPS, DNS, and web servers — the same centralized stack, just self-hosted.

None of these offer a lightweight, text-based, LAN-first platform where a single process on a single machine gives you cryptographic identity, content serving, peer discovery, a transaction ledger, and blockchain connectivity.

### What the Original Internet Lacked

Gopher was simple and elegant, but it had no:

- Cryptographic identity (anyone could impersonate a server)
- Content signing (no way to verify who served what)
- Economic incentives (no mechanism to reward operators)
- Peer discovery (you had to know the address)

REFInet adds exactly these four capabilities to the Gopher protocol, preserving its simplicity while enabling sovereign, verifiable, economically viable computing.

---

## 3. The REFInet Vision

**Every computer can be a Pillar.**

A Pillar is a REFInet node — a single Python process that runs a Gopher server, manages a SQLite ledger, announces itself to the local network, replicates content registries with peers, and connects to EVM blockchains. No installation wizard. No account creation. No API keys.

```
python3 pillar.py
```

That single command:

1. Generates or loads an Ed25519 keypair (`~/.refinet/pid.json`)
2. Initializes two SQLite databases (live + archive)
3. Optionally launches a Tor hidden service (`.onion` address for anonymous access)
4. Starts the REFInet server on TCP port 7070 (full features)
5. Starts a standard Gopher server on TCP port 70 (public content)
6. Begins UDP multicast peer discovery on 224.0.70.70:7071
7. Launches background tasks: health monitoring, Tor circuit monitoring, registry replication, data archival
8. Makes you part of Gopherspace and the REFInet mesh

Check your Pillar's status at any time without starting a server:

```
python3 pillar.py --status
```

### Design Principles

**Sovereign operation.** A Pillar requires no external service to function. No DNS, no CA, no cloud dependency, no browser. It works on an air-gapped LAN.

**Offline-first.** Every feature that does not inherently require a network connection works without one. The ledger writes locally. Content serves locally. Identity is local.

**Anonymity-capable.** When Tor mode is enabled, a Pillar serves content through a `.onion` hidden service — hiding both the operator's and the visitor's IP addresses. No port forwarding, no DNS, no public IP required. When Tor is unavailable, the Pillar falls back to direct TCP without error.

**Text-based.** Gopher is a 40-year-old protocol that serves human-readable text over TCP. It works with `curl`, `lynx`, `netcat`, or any Gopher client. No HTML, no CSS, no JavaScript, no rendering engine.

**Cryptographically identified.** Every Pillar has a unique Ed25519 identity. Every piece of served content can be hashed and signed. Every registry record is cryptographically verifiable without trusting any intermediary.

**Economically connected.** Through the EVM RPC gateway, every Pillar can query blockchain state and broadcast transactions — bridging the simplicity of Gopher with the programmable economics of Ethereum and its Layer 2 networks.

**The dual-protocol thesis:** Gopher for content (human-readable, proven for 40 years), EVM for economics (programmable money, decentralized settlement). REFInet sits at the intersection.

---

## 4. Architecture Overview

### System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                       REFInet Pillar                         │
│                     (single process)                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │  REFInet    │  │  Standard   │  │   Crypto/PID         │ │
│  │  Server     │  │  Gopher     │  │   Ed25519            │ │
│  │  TCP:7070   │  │  TCP:70     │  │   SHA-256            │ │
│  │  (all routes│  │  (public    │  │   Signature Blocks   │ │
│  │   + auth)   │  │   content)  │  │                      │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬───────────┘ │
│         │                │                     │             │
│  ┌──────┴────────────────┴─────────────────────┴──────────┐ │
│  │              Request Lifecycle (12 steps)               │ │
│  │  connect → rate-limit → route → hash → log → index     │ │
│  │  → sign → metrics → sig-block → respond → close        │ │
│  └────────────────────────┬───────────────────────────────┘ │
│                           │                                  │
│  ┌────────────┐  ┌───────┴──────┐  ┌───────────────────┐   │
│  │   Mesh     │  │   SQLite     │  │   EVM RPC         │   │
│  │  Discovery │  │   Ledger     │  │   Gateway          │   │
│  │  UDP:7071  │  │  Live+Archive│  │   Multi-chain     │   │
│  │  Multicast │  │  9 tables    │  │   Proxy           │   │
│  └──────┬─────┘  └──────────────┘  └───────────────────┘   │
│         │                                                    │
│  ┌──────┴──────────────────────────────────────────────────┐ │
│  │              Background Tasks                           │ │
│  │  Announce(30s) Health(60s) TorHealth(60s)              │ │
│  │  Replicate(5m) WALCheckpoint(6h) Archive(24h)         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────────────────────┐ │
│  │  Tor Manager     │  │  CLI (pillar.py)                 │ │
│  │  (optional)      │  │  run | --status | hole create    │ │
│  │  .onion hidden   │  │  hole list | hole verify         │ │
│  │  service via     │  └──────────────────────────────────┘ │
│  │  stem/control    │                                       │
│  └────────┬─────────┘                                       │
│           │                                                  │
└───────────┼──────────────────────────────────────────────────┘
            │              │                     │
    ┌───────┴───────┐ Local Network         EVM Chains
    │  Tor Network  │ (other Pillars)       (Ethereum,
    │  .onion route │ via UDP multicast      Polygon,
    │  (encrypted)  │                        Arbitrum,
    └───────┬───────┘                        Base, Sepolia)
            │
    Gopher Clients (direct or via Tor)
    (curl, lynx, Bombadillo, REFInet Browser)
```

### Component Map

| Subsystem | Directory | Purpose |
|-----------|-----------|---------|
| Gopher Server | `core/gopher_server.py` | TCP server, request routing, content serving |
| Menu Builder | `core/menu_builder.py` | Dynamic Gopher menu generation |
| Crypto/PID | `crypto/pid.py`, `crypto/signing.py` | Ed25519 identity, content signing & verification |
| SIWE Auth | `auth/siwe.py`, `auth/session.py` | EIP-4361 wallet authentication, session management |
| SQLite Ledger | `db/live_db.py`, `db/archive_db.py`, `db/schema.py` | Transaction ledger, metrics, peer registry |
| Mesh Discovery | `mesh/discovery.py`, `mesh/replication.py` | UDP multicast announcements, registry replication |
| EVM Gateway | `rpc/gateway.py`, `rpc/chains.py`, `rpc/config.py` | Multi-chain JSON-RPC proxy |
| DApp System | `core/dapp.py` | Plain-text DApp definition parser |
| Gopher Client | `core/gopher_client.py` | Outbound Gopher fetching with SSRF protection |
| Gophermap Parser | `core/gophermap_parser.py` | Parses Gopher menu responses into structured items |
| Tor Transport | `core/tor_manager.py` | Tor subprocess management, hidden service lifecycle |
| CLI | `cli/hole.py`, `pillar.py` | Command-line interface for administration |

### Single-Process Async Design

The entire Pillar runs as a single Python `asyncio` process. The entry point (`pillar.py`) launches all services concurrently via `asyncio.gather`:

- REFInet TCP server (port 7070 — full features)
- Standard Gopher TCP server (port 70 — public content only)
- Peer announcer (UDP multicast, 30-second cycle)
- Peer listener (UDP multicast receiver)
- Health monitor (60-second ping cycle)
- Tor health monitor (60-second circuit check, when Tor is active)
- Registry replicator (5-minute cycle)
- WAL checkpoint (6-hour cycle — prevents journal file accumulation)
- Archive migrator (24-hour cycle)

No separate daemons. No Docker containers. No orchestration. One process, one command.

---

## 5. Core Capabilities

### 5.1 Gopher Protocol Server

The foundation of every Pillar is an RFC 1436-compatible Gopher server with a dual-port architecture.

**Protocol basics.** A Gopher transaction is four steps:

1. Client opens a TCP connection
2. Client sends a selector string followed by `\r\n`
3. Server responds with content (a menu or a file)
4. Connection closes

There is no handshake, no headers, no cookies, no TLS negotiation. A Gopher request can be issued with `echo "/about" | nc localhost 7070`.

**Dual-port architecture.** Each Pillar runs two TCP servers simultaneously:

| Port | Mode | Routes Available |
|------|------|-----------------|
| **7070** | REFInet (full features) | All 23 routes — content, auth, RPC, ledger, status |
| **70** | Standard Gopher (public) | Content routes only — `/`, `/about`, `/dapps`, `/directory`, static files |

Routes in the `REFINET_ROUTES` tuple are gated on port 70: `/auth`, `/rpc`, `/pid`, `/transactions`, `/peers`, `/ledger`, `/network`, `/directory.json`, `/status.json`. Requests for gated routes on port 70 receive a clear message: *"REFInet feature. Connect on port 7070 for full access."*

This architecture enables standard Gopher clients (lynx, curl, Bombadillo) to browse public content on the traditional Gopher port, while REFInet-aware clients (the REFInet Browser, other Pillars) access the full feature set on port 7070.

**CLI control.** The standard Gopher server can be configured or disabled:

```bash
python3 pillar.py --gopher-port 8070   # Custom standard Gopher port
python3 pillar.py --no-gopher          # Disable standard Gopher server entirely
```

**Dynamic routes.** The server handles 23 distinct route patterns:

| Route | Type | Description |
|-------|------|-------------|
| `/` (empty) | Menu | Root menu with Pillar status |
| `/about` | Menu | Pillar identity and description |
| `/network` | Menu | Network status and peer list |
| `/dapps` | Menu | DApp directory |
| `/dapps/<slug>.dapp` | Menu | Individual DApp detail |
| `/directory` | Menu | Gopherhole registry (human-readable) |
| `/directory.json` | Text | Gopherhole registry (machine-readable, versioned JSON) |
| `/status.json` | Text | Machine-readable Pillar status (JSON, versioned) |
| `/auth` | Menu | Authentication landing page |
| `/auth/challenge` | Search | SIWE challenge generation |
| `/auth/verify` | Search | SIWE signature verification |
| `/rpc` | Menu | RPC gateway status with chain connectivity |
| `/rpc/balance` | Search | Native token balance query |
| `/rpc/token` | Search | ERC-20 token balance query |
| `/rpc/gas` | Search | Gas estimation |
| `/rpc/broadcast` | Search | Signed transaction broadcast (auth required) |
| `/pid` | Text | PID identity document |
| `/transactions` | Text | Recent transaction log |
| `/peers` | Text | Peer list document |
| `/ledger` | Text | Ledger status summary |
| `/search` | Search | Full-text content search |
| `/holes/*` | Static | Gopherhole content |
| `*` (fallback) | Static | Static files from `gopherroot/` |

**Static file serving.** Any file or directory placed in `gopherroot/` is automatically served. Directories containing a `gophermap` file render that map; otherwise, an auto-generated listing is produced. Directory traversal attacks are blocked by a double-layer defense: path sanitization (stripping `..`) followed by resolved-path verification against the `gopherroot` boundary.

**Response signature block.** Every response includes an Ed25519 signature block appended **after** the Gopher `.` terminator:

```
.
---BEGIN REFINET SIGNATURE---
pid:af1cc79d09d653a611a653dcd03d3efa...
sig:3a7b9c...  (Ed25519 signature hex)
hash:e4f1a2... (SHA-256 content hash)
---END REFINET SIGNATURE---
```

This placement is backward-compatible: legacy Gopher clients stop reading at the `.` terminator and never see the block. REFInet-aware clients (the Browser, other Pillars) parse the trailing block for zero-trust response verification. Any client can verify that a response was served by a specific Pillar by checking the signature against the Pillar's public key.

**Request lifecycle.** Every incoming connection follows a 12-step lifecycle:

1. **Connect** — TCP connection accepted
2. **Rate limit** — Per-IP sliding window check (100 requests / 60 seconds for direct connections; 500 requests / 60 seconds for Tor inbound — see Section 5.12)
3. **Read** — Selector read with 30-second timeout
4. **Route** — Selector dispatched to handler
5. **Hash** — Response content SHA-256 hashed
6. **Log** — Transaction recorded in SQLite ledger
7. **Metrics** — Daily metrics updated
8. **Index** — Content indexed (selector, type, hash, signature, size)
9. **Sign** — Content signed with Pillar's Ed25519 private key
10. **Signature block** — `---BEGIN/END REFINET SIGNATURE---` block appended to response
11. **Respond** — Content + signature block sent to client
12. **Close** — Connection closed in `finally` block

### 5.2 Cryptographic Identity (Pillar ID)

Every Pillar has a unique, self-generated cryptographic identity.

**Key generation.** On first run, the Pillar generates an Ed25519 keypair using the `cryptography` library. Ed25519 was chosen for its speed (fast signing and verification), compact size (32-byte keys, 64-byte signatures), and blockchain compatibility (used by Solana, NEAR, and other chains).

**Pillar ID derivation.** The PID is computed as:

```
PID = SHA-256(Ed25519_public_key)
```

This produces a 64-character hexadecimal string that uniquely identifies the Pillar. The SHA-256 hash provides collision resistance — the probability of two Pillars generating the same PID is approximately 2^(-128). No central registry is needed.

**Persistence.** The keypair is stored at `~/.refinet/pid.json`:

```json
{
  "pid": "af1cc79d09d653a611a653dcd03d3efa...",
  "public_key": "7a3b...",
  "private_key": "e4f1...",
  "created_at": 1709654400,
  "protocol": "REFInet-v0.1"
}
```

**Dual-identity model.** When Tor mode is active, a Pillar has two self-generated identities:

| Identity | Derivation | Purpose |
|----------|-----------|---------|
| **REFInet PID** | SHA-256(Ed25519 public key) | Content signing, TOFU trust, registry records |
| **.onion address** | SHA3-256(Tor Ed25519 public key) | Network routing, end-to-end encrypted transport |

Neither identity requires external registration. The PID is the Pillar's content identity — used for signing, verification, and peer recognition. The `.onion` address is the Pillar's network identity — used for anonymous routing. When Tor is active, the `/pid` document includes `onion_address`, `tor_port_7070`, and `tor_port_70` fields alongside the existing PID fields.

**Content signing.** Every response served by the Gopher server is hashed (SHA-256) and signed (Ed25519). The signature is stored in the content index and appended to the response as a `---BEGIN REFINET SIGNATURE---` block (see Section 5.1). This enables anyone with the Pillar's public key to verify that a specific piece of content was served by a specific Pillar — both in real-time (by parsing the response) and historically (by querying the content index).

**Gopherhole registration signing.** When a gopherhole is registered, the signing payload is:

```
payload = "{pid}:{selector}:{name}:{registered_at}"
signature = Ed25519_sign(payload, private_key)
```

Any peer can verify this signature using the registering Pillar's public key, confirming that the registration is authentic without trusting any intermediary.

### 5.3 The 13-Month Accounting Calendar

REFInet uses a custom accounting calendar for all time-based operations:

```
13 months × 28 days = 364 days + balance day(s)
```

**Rationale.** The Gregorian calendar has months of 28, 30, and 31 days. This makes fiscal period comparison unreliable — a "month" of data can span 28 to 31 days. The REFInet accounting calendar eliminates this variance:

- Every month is exactly 28 days (4 complete weeks)
- Every quarter is exactly 91 days (13 weeks)
- Day 365 (and day 366 in leap years) is a "balance day" mapped to the end of month 13

This is inspired by the International Fixed Calendar (the Cotsworth plan), proposed in 1902 and used internally by Kodak from 1928 to 1989.

**Usage across the platform.** The accounting calendar is used for:

- **Transaction timestamps** — Every transaction is tagged with `(accounting_day, accounting_month, accounting_year)`
- **Metrics aggregation** — Daily productivity metrics are keyed by accounting date
- **Archive retention** — The live database retains 13 months of data before archiving
- **Gopherhole registration dates** — Recorded in `YYYY-MM-DD` format using accounting dates

The conversion function maps any Gregorian datetime to an `(accounting_day, accounting_month, accounting_year)` tuple deterministically.

### 5.4 SQLite Ledger (Live + Archive)

Every Pillar maintains two SQLite databases that form a complete, local transaction ledger.

**Live Database** (`~/.refinet/db/live.db`) — 9 tables:

| Table | Purpose | Key Features |
|-------|---------|--------------|
| `daily_tx` | Every transaction on this Pillar | UUID tx_id, SHA-256 content_hash, accounting date |
| `daily_metrics` | Aggregated daily productivity stats | tx_count, volume, latency, uptime, content served |
| `peers` | Known Pillars on the mesh | PID, hostname, port, health status, latency |
| `content_index` | Every selector served, with hash and signature | Enables content verification and search |
| `token_state` | CIFI staking, REFI balances, license tier | license_tier (free/pro/enterprise), Phase 3 economics |
| `gopherholes` | Append-only content registry | Immutable via SQL triggers |
| `siwe_sessions` | Wallet authentication sessions | Write-only audit trail, never deleted |
| `service_proofs` | Append-only proof of service delivery | Ed25519 signed, immutable via SQL triggers |
| `settlements` | Inter-Pillar payment records | FK to service_proofs, immutable via SQL triggers |

**Archive Database** (`~/.refinet/db/archive.db`) — 3 tables:

| Table | Purpose |
|-------|---------|
| `yearly_summary` | Aggregated yearly metrics per Pillar |
| `monthly_snapshot` | Compressed daily data as JSON blobs with integrity hashes |
| `peer_history` | Historical peer interaction records |

**WAL journaling.** Both databases use SQLite's Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for concurrent read performance.

**Automated migration pipeline.** A background task runs every 24 hours, checking for data older than 13 accounting months. Qualifying data flows from live to archive:

1. Query monthly metrics from `daily_metrics`
2. Compute aggregate statistics (sum, average, max)
3. Serialize daily rows as a JSON snapshot
4. Hash the snapshot for integrity verification
5. Write to `monthly_snapshot` and `yearly_summary` in the archive database

**Schema migration.** The live database includes an idempotent migration system (`_migrate_live_db`) that uses `PRAGMA table_info` to detect missing columns and `ALTER TABLE ADD COLUMN` to add them. This ensures existing databases are safely upgraded when the schema evolves.

**Immutability enforcement.** Four tables are immutable by design:

- `gopherholes` — Protected by SQL triggers that `RAISE(ABORT)` on any `UPDATE` or `DELETE` operation
- `siwe_sessions` — Protected by a trigger that prevents `DELETE`; sessions are revoked by setting `revoked=1`, never removed
- `service_proofs` — Protected by SQL triggers that `RAISE(ABORT)` on any `UPDATE` or `DELETE` operation
- `settlements` — Protected by SQL triggers that `RAISE(ABORT)` on any `UPDATE` or `DELETE` operation

### 5.5 Mesh Peer Discovery

Pillars discover each other on local networks through zero-configuration UDP multicast.

**Protocol.** Every 30 seconds, each Pillar sends a JSON announcement via UDP multicast to `224.0.70.70:7071`:

```json
{
  "type": "pillar_announce",
  "protocol": "REFInet",
  "version": "0.3.0",
  "pid": "af1cc79d...",
  "public_key": "7a3b...",
  "hostname": "192.168.1.42",
  "port": 7070,
  "pillar_name": "My REFInet Pillar",
  "onion_address": "abc123...xyz.onion",
  "timestamp": 1709654400
}
```

The `onion_address` field is optional — it is included only when the Pillar has an active Tor hidden service. Peers store this address in the `onion_address` column of the `peers` table, and the `/peers` document displays `.onion` links for peers that have them.

**No infrastructure required.** There is no DNS lookup, no tracker server, no bootstrap node, no DHT. UDP multicast is a capability of the IP stack itself. Two Pillars on the same subnet will find each other within 30 seconds.

**TTL=2.** The multicast time-to-live is set to 2, meaning announcements traverse at most one router hop. This keeps discovery local — appropriate for a LAN-first protocol.

**Hostname normalization.** If a Pillar announces with `localhost` or `127.0.0.1`, the listener replaces the hostname with the actual sender IP address from the UDP packet. This ensures that peer records contain reachable addresses.

**Health monitoring.** A background task pings all known peers every 60 seconds using a TCP Gopher ping (connect, send `\r\n`, measure latency). Peer health status escalates through four states:

| Status | Condition |
|--------|-----------|
| `unknown` | Never checked (default) |
| `online` | Ping succeeded, latency < 2000ms |
| `degraded` | Ping succeeded but slow (>= 2000ms), or 1-2 consecutive failures |
| `offline` | 3+ consecutive ping failures |

**Automatic registry sync.** When a new peer is discovered for the first time, the listener immediately triggers a registry replication from that peer — importing any gopherholes the local Pillar doesn't already have.

### 5.6 Gopherhole Registry & Replication

A gopherhole is a registered content site on the REFInet mesh. The registry is an append-only, cryptographically signed ledger.

**Registration flow:**

1. User runs `pillar.py hole create --name "My Site" --selector /holes/mysite`
2. Selector is validated against the pattern `/holes/<alphanumeric-slug>`
3. Directory structure is scaffolded in `gopherroot/holes/mysite/` (gophermap + README.txt)
4. Registration payload is constructed: `{pid}:{selector}:{name}:{registered_at}`
5. Payload is signed with the Pillar's Ed25519 private key
6. A `tx_hash` is computed as `SHA-256(canonical_JSON(record))`
7. Record is inserted into the `gopherholes` table with `source='local'`
8. The gopherhole is immediately live on the mesh

**Immutability.** Registry records cannot be modified or deleted. This is enforced at four layers:

1. **SQL triggers** — `BEFORE UPDATE` and `BEFORE DELETE` triggers abort any mutation attempt
2. **UNIQUE constraint** — `UNIQUE(pid, selector)` prevents duplicate registrations
3. **Ed25519 signatures** — Each record carries a cryptographic signature that would be invalidated by any modification
4. **SHA-256 tx_hash** — The transaction hash covers all fields; any change would produce a different hash

**Cross-Pillar replication.** Every 5 minutes, a background task fetches `/directory.json` from all known peers and imports any gopherholes the local Pillar doesn't already have. The replication process is trust-gated:

1. Fetch the peer's `/directory.json` (versioned JSON envelope, schema v1)
2. For each record not already in the local registry:
   a. Reconstruct the signing payload: `{pid}:{selector}:{name}:{registered_at}`
   b. Verify the Ed25519 signature using the record's `pubkey_hex`
   c. Only import records with valid signatures
3. Record the `source` as the replicating peer's PID

Records with invalid signatures are rejected, logged via `logger.warning()`, and persisted to the `daily_tx` ledger as a transaction record with `dapp_id='mesh.replication'`. This creates a permanent, auditable trail of rejected replication attempts and ensures that only authentic, unmodified registrations propagate through the mesh.

### 5.7 SIWE Authentication (EIP-4361)

REFInet uses Sign-In with Ethereum (EIP-4361) for wallet-based authentication. No passwords. No usernames. No email addresses.

**Challenge-response flow:**

1. Client sends an EVM address to `/auth/challenge` (e.g., `0xABC...123`)
2. Server generates an EIP-4361 message with a CSPRNG nonce (`secrets.token_hex(16)`):
   ```
   refinet://pillar wants you to sign in with your Ethereum account:
   0xABC...123

   Sign in to REFInet Pillar af1cc79d...

   URI: refinet://pillar
   Version: 1
   Chain ID: 1
   Nonce: <32-char hex>
   Issued At: <ISO 8601>
   Expiration Time: <ISO 8601, +24 hours>
   ```
3. Client signs the message with their wallet's private key
4. Client submits `address|signature|base64(message_text)` to `/auth/verify` — the message is base64-encoded because SIWE messages contain newlines that cannot survive Gopher's single-line query protocol. The Pillar also accepts plain text as a fallback for direct Gopher clients where the message has no newlines.
5. Server base64-decodes the message, then recovers the signing address via `ecrecover` and compares against the claimed address
6. On success, a session is created with a 64-character random session ID (`secrets.token_hex(32)`)

**Sessions.** Each session lasts 24 hours and is stored in the `siwe_sessions` table. Sessions are write-only — they are never deleted, only revoked by setting `revoked=1`. This creates a permanent, auditable authentication trail.

**Access control.** SIWE authentication is required for transaction broadcasting via the RPC gateway. All other routes (content serving, balance queries, gas estimation) are publicly accessible without authentication.

### 5.8 EVM RPC Gateway

The RPC gateway connects every Pillar to EVM-compatible blockchains through a local JSON-RPC proxy.

**Supported chains:**

| Chain ID | Network | Symbol | Default RPC |
|----------|---------|--------|-------------|
| 1 | Ethereum Mainnet | ETH | eth.llamarpc.com |
| 137 | Polygon | MATIC | polygon-rpc.com |
| 42161 | Arbitrum One | ETH | arb1.arbitrum.io/rpc |
| 8453 | Base | ETH | mainnet.base.org |
| 11155111 | Sepolia Testnet | ETH | rpc.sepolia.org |

**Operations.** Four blockchain operations are exposed as Gopher search routes:

| Route | Operation | Auth Required |
|-------|-----------|---------------|
| `/rpc/balance` | Native token balance (in wei + converted) | No |
| `/rpc/token` | ERC-20 token balance (raw units) | No |
| `/rpc/gas` | Gas estimation for a transaction | No |
| `/rpc/broadcast` | Broadcast a signed transaction | Yes (SIWE session) |

The read/write split is intentional: anyone can query public blockchain state, but broadcasting transactions requires an authenticated session. This prevents the Pillar from being used as an anonymous transaction relay.

**Graceful degradation.** The `web3` library is an optional dependency. When not installed:

- The `/rpc` route displays a clear message: "RPC requires: pip install web3"
- All other Pillar functionality (Gopher serving, mesh discovery, registry, auth) continues normally
- No import errors, no stack traces, no crashes

**User-configurable endpoints.** Operators can override default RPC endpoints by creating `~/.refinet/rpc_config.json`:

```json
{
  "1": ["https://my-private-eth-rpc.example.com"],
  "137": ["https://my-polygon-rpc.example.com"]
}
```

**Connectivity testing.** The `/rpc` status page tests all chain connections in parallel with a 10-second total timeout. Each chain's latency (or unreachable status) is displayed. Individual chain tests are capped at 5 seconds to prevent blocking.

### 5.9 DApp Definition System

REFInet introduces a plain-text format for defining decentralized application interfaces.

**Format.** A `.dapp` file has 5 sections:

```ini
[meta]
name = Uniswap V3
slug = uniswap-v3
version = 1.0.0
chain_id = 1
contract = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45
author_pid = af1cc79d...
description = Swap tokens on Uniswap V3 without a browser

[abi]
# Human-readable ABI (not JSON)
exactInputSingle((address,address,uint24,address,uint256,uint256,uint160)) -> uint256
exactOutputSingle((address,address,uint24,address,uint256,uint256,uint160)) -> uint256
multicall(bytes[]) -> bytes[]

[docs]
# exactInputSingle
Swaps an exact amount of one token for as much as possible of another.
Gas estimate: ~150,000

[flows]
swap:
  1. Approve tokenIn spending
  2. Call exactInputSingle with your parameters
  3. Verify output token balance increased

[warnings]
Always verify slippage tolerance before signing.
High-fee pools (1%) are for exotic pairs.
```

**Design philosophy.** DApp definitions are human-readable, version-controllable, and servable over Gopher — no JSON parsing, no web3 library, no browser required. A user can read a `.dapp` file with `cat` and understand what the contract does, what functions it exposes, and what steps to follow.

**Hot-reload.** Drop a `.dapp` file into `gopherroot/dapps/` and it appears immediately on the `/dapps` menu. No restart required.

**Browsable.** Each DApp has a detail page at `/dapps/<slug>.dapp` showing its metadata, ABI functions, and warnings in a Gopher-formatted menu.

### 5.10 Rate Limiting & Security

**Rate limiting.** A per-IP sliding window rate limiter protects every Pillar:

- **Limit:** 100 requests per 60-second window per IP
- **Algorithm:** Sliding window using an in-memory `deque` per IP with timestamp tracking
- **Enforcement:** Rate-limited connections receive an error response and are immediately closed
- **Overhead:** Negligible — O(1) amortized per request

**SSRF protection.** The outbound Gopher client (used for peer registry fetching) enforces:

- **Loopback blocking:** Requests to `127.*`, `0.*`, and `::1` are rejected
- **LAN allowed:** Private network addresses (192.168.*, 10.*, 172.16-31.*) are permitted — this is a LAN-first protocol
- **Port allowlist:** Only ports 70, 7070, and 105 are allowed
- **Response size cap:** Responses exceeding 2MB are rejected

**Path traversal defense.** Static file serving uses a double-layer defense:

1. **Sanitization:** `..` sequences are stripped from the selector
2. **Resolution:** The resolved path is verified to start with the `gopherroot` directory's resolved path

**Graceful degradation.** Optional dependencies (`web3`, `eth-account`, `qrcode`) are imported with `try/except`. When missing, affected features are cleanly disabled with user-facing messages, and all other functionality continues.

### 5.11 Content Indexing

Every response served by the Gopher server is indexed in the `content_index` table:

| Field | Description |
|-------|-------------|
| `selector` | The Gopher selector (primary key) |
| `content_type` | `menu` or `text` |
| `content_hash` | SHA-256 hash of the response content |
| `signature` | Ed25519 signature of the response |
| `pid` | The serving Pillar's PID |
| `size_bytes` | Response size in bytes |
| `created_at` | First indexed timestamp |
| `updated_at` | Last update timestamp |

The index is updated on every request via `INSERT ... ON CONFLICT DO UPDATE`, ensuring it always reflects the latest state.

Content indexing never blocks serving — if indexing fails for any reason (disk full, concurrent write, unexpected error), the response is still sent to the client. This is enforced by a bare `except` with a `pass` in the request lifecycle.

The content index enables future capabilities: full-text search across served content, content verification by third parties, provenance tracking, and mesh-wide content discovery.

### 5.12 Tor Transport Layer

REFInet integrates Tor hidden services as an optional transport layer beneath the Gopher protocol. When enabled, a Pillar generates a `.onion` address and serves all content through Tor's onion routing network — providing end-to-end encryption and IP anonymity for both operator and visitor. The signing system, the PID, the mesh, the ledger, and all Gopher routes remain unchanged; Tor is purely additive at the transport layer.

**Three operating modes:**

| Mode | Bind Address | Access | Use Case |
|------|-------------|--------|----------|
| **Direct** (default) | `0.0.0.0` | LAN / port-forwarded WAN | Simple LAN operation, no Tor binary needed |
| **Tor** | `127.0.0.1` | `.onion` only | Maximum anonymity, no IP exposure |
| **Dual** | `0.0.0.0` + `.onion` | LAN direct + WAN `.onion` | LAN speed for local peers, Tor for remote |

**Module.** `core/tor_manager.py` provides the `TorManager` class with a clean lifecycle:

1. `start()` — Launch Tor subprocess via `stem.process`, wait for bootstrap (120s timeout), authenticate to control port
2. `create_hidden_services()` — Create ephemeral hidden service mappings for ports 7070 and 70 (configurable)
3. `get_onion_address()` — Return the `.onion` address for use in menus, `/pid`, `/status.json`, announcements
4. `stop()` — Remove hidden service, close control port, terminate Tor process

**Private key persistence.** On first Tor launch, the hidden service private key is saved to `~/.refinet/tor_data/hs_privkey` with `0o600` permissions (owner read/write only). On subsequent launches, this key is reloaded so the `.onion` address remains stable across restarts. If the key file is lost, a new `.onion` address is generated automatically.

**Health monitoring.** A background task pings the Tor control port every 60 seconds, checking that circuits are established. If Tor dies or circuits drop, the Pillar attempts automatic restart — up to 3 times with exponential backoff (10s, 20s, 40s). After 3 failures, the Pillar remains in direct TCP mode and logs a manual-intervention warning.

**Graceful fallback.** If the Tor binary is not installed or bootstrap fails, the Pillar falls back to direct TCP mode. It never crashes. Platform-specific install hints are logged (`brew install tor` on macOS, `sudo apt install tor` on Debian/Ubuntu).

**Tor-aware rate limiting.** All inbound Tor traffic arrives from `127.0.0.1` (the local Tor relay). A per-IP rate limit would treat every Tor visitor as a single client. To prevent this, when Tor is active the rate limiter uses an elevated shared bucket: 500 requests / 60 seconds for the `.onion` interface, compared to 100 requests / 60 seconds for direct connections.

**Configuration.** Four config keys control Tor behavior in `~/.refinet/config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `tor_enabled` | `false` | Enable Tor hidden service |
| `tor_expose_port_70` | `true` | Expose standard Gopher port via Tor |
| `tor_socks_port` | `9050` | Tor SOCKS proxy port |
| `tor_control_port` | `9051` | Tor control port for stem |

**Operator setup.** Three steps to enable Tor:

1. Install the Tor binary (`brew install tor` / `sudo apt install tor`)
2. Set `"tor_enabled": true` in `~/.refinet/config.json`
3. Start the Pillar: `python3 pillar.py`

The Pillar handles everything else — launching Tor, bootstrapping circuits, creating the hidden service, persisting the key, and surfacing the `.onion` address in the root menu, `/about`, `/pid`, `/status.json`, `/peers`, and mesh announcements.

### 5.13 Backup & Recovery

A Pillar's identity and data are stored in `~/.refinet/`. The following files should be backed up:

| File | Impact if Lost | Recovery |
|------|---------------|----------|
| `pid.json` | Pillar identity lost — new PID generated, peers won't recognize you | Back up before first Tor launch. Not recoverable without backup. |
| `tor_data/hs_privkey` | `.onion` address changes on next Tor start | New `.onion` generated automatically. Peers update via mesh announcements. |
| `db/live.db` | Transaction history, metrics, peer records, content index, gopherholes lost | Gopherholes replicated from peers. Metrics and transactions not recoverable. |
| `db/archive.db` | Historical aggregated data lost | Not recoverable without backup. |
| `config.json` | Custom configuration lost — defaults used | Recreate manually or restore from backup. |

**Priority order:** `pid.json` > `tor_data/hs_privkey` > `db/live.db` > `config.json` > `db/archive.db`

The `pid.json` file is the most critical — it contains the Ed25519 private key that defines the Pillar's identity. Without it, a new identity must be generated and all peer trust relationships reset.

---

## 6. Security Model

REFInet's security is built on defense in depth — multiple independent mechanisms, each sufficient to prevent a class of attack.

### Identity & Authentication

| Layer | Mechanism | Protects Against |
|-------|-----------|-----------------|
| Pillar identity | Ed25519 keypair + SHA-256 PID | Impersonation, identity collision |
| .onion address | SHA3-256(Tor Ed25519 pubkey) | IP-based tracking, location exposure |
| Content signing | Ed25519 signature per response | Content tampering, replay |
| Registry immutability | SQL triggers (ABORT on UPDATE/DELETE) | Record modification, deletion |
| Registry integrity | SHA-256 tx_hash per record | Bit-level tampering |
| Wallet auth | EIP-4361 SIWE with ecrecover | Unauthorized transactions |
| Session tokens | `secrets.token_hex(32)` — 256-bit CSPRNG | Session prediction, brute force |
| Nonce generation | `secrets.token_hex(16)` — 128-bit CSPRNG | Replay attacks |

### Network & Transport

| Layer | Mechanism | Protects Against |
|-------|-----------|-----------------|
| Tor transport | End-to-end encryption via onion routing | IP exposure, traffic interception, passive surveillance |
| Rate limiting | 100 req/60s per IP (direct), 500 req/60s (Tor inbound) | Denial of service, resource exhaustion |
| SSRF protection | Loopback blocking + port allowlist | Server-side request forgery |
| Path traversal | Sanitize + resolve-and-verify | Directory traversal attacks |
| Response size cap | 2MB max on outbound fetches | Resource exhaustion on client |
| Connection timeout | 30-second read timeout | Slowloris / connection exhaustion |
| Replication trust | Ed25519 signature verification before import | Poisoned registry injection |

### Audit Trail

- **Transactions** are permanently recorded in the SQLite ledger with content hashes
- **Sessions** are write-only (revoked but never deleted)
- **Gopherholes** are append-only (immutable once registered)
- **Content** is indexed with hash and signature for every served response

### Self-Authenticating Records

A key design property: any record in the gopherhole registry can be verified by anyone, without trusting the Pillar that serves it. Given a record with fields `(pid, selector, name, registered_at, signature, pubkey_hex)`:

1. Reconstruct the payload: `{pid}:{selector}:{name}:{registered_at}`
2. Verify the Ed25519 signature against `pubkey_hex`
3. Verify that `pid == SHA-256(pubkey_hex)`

If all three checks pass, the record is authentic — signed by the owner of the claimed PID. No certificate authority, no DNS, no trusted third party.

---

## 7. Token Economics (Planned)

REFInet's token system is designed but not yet activated. The database schema is in place; the economic logic will be implemented in Phase 3.

### Dual-Token Model

| Token | Purpose | Mechanism |
|-------|---------|-----------|
| **CIFI** | Staking collateral | Staked on-chain to activate a Pillar license |
| **REFI** | Activity rewards | Earned by serving content, maintaining uptime, participating in the mesh |

### Schema (Ready)

The `token_state` table already exists in the live database:

```sql
CREATE TABLE IF NOT EXISTS token_state (
    pid             TEXT PRIMARY KEY,
    cifi_staked     REAL DEFAULT 0.0,
    refi_balance    REAL DEFAULT 0.0,
    refi_issued     REAL DEFAULT 0.0,
    license_active  INTEGER DEFAULT 0,
    license_tier    TEXT DEFAULT 'free',    -- free | pro | enterprise
    license_expires DATETIME,
    blockchain_tx   TEXT,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**License tiers.** The `license_tier` column supports three tiers:

| Tier | Description |
|------|-------------|
| `free` | Default. All Pillar features available. No REFI rewards. |
| `pro` | CIFI staked. REFI earning enabled. Enhanced mesh priority. |
| `enterprise` | Higher stake threshold. Premium routing, higher REFI multiplier. |

### Service Proofs & Settlements (Ready)

Two additional append-only tables provide the foundation for the economic settlement layer:

**`service_proofs`** — Proof of work/service delivery:

```sql
CREATE TABLE IF NOT EXISTS service_proofs (
    proof_id    TEXT PRIMARY KEY,
    pid         TEXT NOT NULL,
    service     TEXT NOT NULL,        -- e.g. 'gopher.serve', 'mesh.relay'
    proof_hash  TEXT NOT NULL,        -- SHA-256 of proof payload
    signature   TEXT NOT NULL,        -- Ed25519 signature by originating PID
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**`settlements`** — Inter-Pillar payment records:

```sql
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    payer_pid     TEXT NOT NULL,
    payee_pid     TEXT NOT NULL,
    amount        REAL NOT NULL,
    token_type    TEXT NOT NULL,       -- CIFI or REFI
    proof_id      TEXT REFERENCES service_proofs(proof_id),
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Both tables are immutable — protected by SQL triggers that `RAISE(ABORT)` on any `UPDATE` or `DELETE`. Settlements require a valid `proof_id` foreign key, ensuring every payment is backed by a verifiable proof of service.

### Planned Economics

- **License activation:** A Pillar stakes CIFI on-chain. The staking transaction hash is recorded in `blockchain_tx`. The Pillar's `license_active` flag is set to 1 and `license_tier` is upgraded.
- **Activity-based issuance:** Licensed Pillars earn REFI based on content served, uptime, and mesh participation. The metrics infrastructure (`daily_metrics`) already tracks the inputs.
- **Service proof flow:** Pillar serves content → generates a `service_proof` record → settlement engine creates a `settlements` record linking payment to proof.
- **On-chain anchoring:** REFI issuance events can be anchored to EVM chains via the RPC gateway, creating a verifiable link between off-chain activity and on-chain state.

The token system is designed to incentivize running Pillars without requiring tokens to participate. Unlicensed Pillars function identically — they simply don't earn REFI.

---

## 8. Developer Guide

### Getting Started

**Prerequisites:**

- Python 3.11+
- `pip install cryptography eth-account stem` (required — `stem` is the Tor controller library)
- `pip install web3 qrcode[pil]` (optional — for RPC gateway and QR codes)
- `tor` binary (optional — for hidden service mode; `brew install tor` / `sudo apt install tor`)

**Install and run:**

```bash
git clone <repository>
cd REFINET-GOPHERSPACE
pip install -r requirements.txt
python3 pillar.py
```

**Enable Tor (optional):**

```bash
# Install Tor binary (macOS / Debian-Ubuntu)
brew install tor        # or: sudo apt install tor
# Set tor_enabled in config (created on first run at ~/.refinet/config.json)
# Then restart:
python3 pillar.py
```

On first run, the Pillar will:

1. Generate your Ed25519 identity at `~/.refinet/pid.json`
2. Create SQLite databases at `~/.refinet/db/`
3. Launch Tor hidden service if `tor_enabled: true` (generates `.onion` address)
4. Start REFInet server on port 7070 (full features)
5. Start standard Gopher server on port 70 (public content)

**Connect:**

```bash
curl gopher://localhost:7070/       # REFInet (full features)
curl gopher://localhost:70/         # Standard Gopher (public content)
lynx gopher://localhost:7070
echo "" | nc localhost 7070
```

**Check status (offline):**

```bash
python3 pillar.py --status          # Shows PID, Tor status, db stats, config
```

### Creating a Gopherhole

```bash
python3 pillar.py hole create \
  --name "My Site" \
  --selector /holes/mysite \
  --desc "Welcome to my corner of Gopherspace"
```

This creates:

- `gopherroot/holes/mysite/gophermap` — Your Gopher menu (edit this)
- `gopherroot/holes/mysite/README.txt` — Description file
- A cryptographically signed entry in the registry

**List registered gopherholes:**

```bash
python3 pillar.py hole list          # Local only
python3 pillar.py hole list --peers  # Include replicated
python3 pillar.py hole list --json   # Machine-readable
```

**Verify a gopherhole signature:**

```bash
python3 pillar.py hole verify --pid <pid> --selector /holes/mysite
```

### Writing a .dapp File

Create a file in `gopherroot/dapps/` with the `.dapp` extension:

```ini
[meta]
name = My DApp
slug = my-dapp
version = 1.0.0
chain_id = 1
contract = 0x...
description = What this DApp does

[abi]
myFunction(uint256) -> bool

[docs]
# myFunction
Description of what this function does.

[flows]
usage:
  1. First step
  2. Second step

[warnings]
Important safety note.
```

The DApp will appear at `/dapps` immediately — no restart needed.

### Configuring RPC Endpoints

Create `~/.refinet/rpc_config.json`:

```json
{
  "1": ["https://your-eth-rpc.example.com"],
  "137": ["https://your-polygon-rpc.example.com"]
}
```

Any chain ID not in the config falls back to the built-in defaults.

### Running Tests

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_routes.py  # Specific module
```

The test suite covers 236 tests across 16 modules (234 passed, 2 skipped), including end-to-end TCP route tests, dual-port route gating, response signature blocks, mesh discovery simulation, first-run initialization, gap-closure verification, crypto operations, Tor manager lifecycle, and Tor integration tests.

### Project Structure

```
REFINET-GOPHERSPACE/
├── pillar.py               # Entry point — start here (--status flag for offline query)
├── core/
│   ├── config.py           # All constants, paths, and Tor defaults
│   ├── gopher_server.py    # TCP server + routing (Tor-aware rate limiting)
│   ├── tor_manager.py      # Tor subprocess management, hidden service lifecycle
│   ├── menu_builder.py     # Dynamic Gopher menu generation (.onion-aware)
│   ├── gopher_client.py    # Outbound Gopher client (SSRF-safe)
│   ├── gopherhole.py       # Gopherhole creation and verification
│   ├── dapp.py             # .dapp file parser
│   └── gophermap_parser.py # Parses Gopher menu responses into structured items
├── crypto/
│   ├── pid.py              # Ed25519 identity management
│   └── signing.py          # Content signing and verification
├── auth/
│   ├── siwe.py             # EIP-4361 challenge/verify
│   └── session.py          # Session management
├── db/
│   ├── schema.py           # SQL schemas (live + archive)
│   ├── live_db.py          # Live database operations (onion_address column)
│   └── archive_db.py       # Archive database + migration
├── mesh/
│   ├── discovery.py        # UDP multicast announcements + health (onion-aware)
│   └── replication.py      # Registry replication
├── rpc/
│   ├── gateway.py          # EVM JSON-RPC proxy
│   ├── chains.py           # Chain configurations
│   └── config.py           # User RPC endpoint overrides
├── cli/
│   └── hole.py             # Gopherhole CLI commands
├── docs/
│   └── backup.md           # Backup & recovery guide
├── gopherroot/             # Static content root
│   ├── news/               # News directory
│   ├── dapps/              # .dapp files
│   └── holes/              # Registered gopherholes
├── tests/                  # Pytest suite (236 tests across 16 modules)
│   ├── test_routes.py      # TCP route integration tests (incl. Tor PID/status)
│   ├── test_dual_port.py   # Dual-port route gating tests
│   ├── test_tor_manager.py # Tor manager unit tests (15 tests)
│   ├── test_tor_integration.py  # Tor integration tests (requires tor binary)
│   ├── test_discovery.py   # Mesh discovery + onion announcement tests
│   ├── test_gap_closure.py # Browser-Pillar alignment tests
│   └── ...                 # 10 additional test modules
├── .gitignore              # Excludes tor_data/, __pycache__/, db files
└── requirements.txt        # Python dependencies (incl. stem>=1.8.2)
```

---

## 9. Roadmap

### Phase 1 — Foundation (Complete)

- Gopher server (RFC 1436 compatible)
- Ed25519 cryptographic identity (PID generation, content signing)
- SQLite ledger (live database, 9 tables, WAL journaling)
- 13-month accounting calendar
- Dynamic menu generation (root, about, network, dapps, directory, auth, rpc)
- Static file serving with directory traversal protection
- Gopherhole registry (append-only, immutable via SQL triggers)
- DApp definition system (.dapp format, hot-reload)
- Content indexing

### Phase 2 — Networking (Complete)

- UDP multicast peer discovery (224.0.70.70:7071, 30-second cycle)
- Peer health monitoring (60-second TCP ping, 4-state escalation)
- Gopherhole registry replication (5-minute cycle, signature-verified)
- SIWE authentication (EIP-4361 challenge-response, 24-hour sessions)
- EVM RPC gateway (5 chains, 4 operations, session-enforced broadcast)
- Outbound Gopher client (SSRF protection, port allowlist)
- CLI: `hole create`, `hole list`, `hole verify`
- Archive database + automated migration pipeline (24-hour cycle)
- Rate limiting (100 req/60s per IP, sliding window)
- Dual-port architecture (port 7070 REFInet + port 70 standard Gopher with route gating)
- Response Ed25519 signature blocks (appended after Gopher `.` terminator for zero-trust verification)
- `/status.json` machine-readable endpoint (versioned JSON, gated on port 70)
- `/auth/verify` base64 message encoding (Browser compatibility for multi-line SIWE messages)
- `service_proofs` + `settlements` tables (append-only, immutable via SQL triggers)
- `license_tier` column in `token_state` (free/pro/enterprise)
- Replication rejection persistence to `daily_tx` ledger
- Tor hidden service integration (optional, stem-based)
- `.onion` address generation and persistence (`tor_data/hs_privkey`, 0o600 permissions)
- Tor health monitoring with auto-restart (60s circuit checks, 3 retries, exponential backoff)
- Tor-aware rate limiting (500 req/min for `.onion` inbound)
- Mesh announcement of `.onion` addresses (`onion_address` field in peer announcements)
- `/pid`, `/status.json`, `/peers`, root menu, `/about` surface `.onion` address when Tor is active
- `--status` CLI flag (offline Pillar status query)
- WAL checkpoint background task (6-hour cycle)
- Backup & recovery documentation (`docs/backup.md`)
- Test suite: 236 tests across 16 modules (234 passed, 2 skipped)

### Phase 3 — Token Economics (Planned)

- CIFI staking contract deployment
- On-chain license activation (stake CIFI → `license_active=1`)
- REFI issuance engine (content served → REFI earned)
- Activity metrics → REFI conversion formulas
- Staking/unstaking flows via RPC gateway
- Token balance integration in Gopher menus

### Phase 4 — DApp Runtime (Planned)

- Interactive DApp execution over Gopher
- Step-by-step flow execution with wallet signing
- Transaction building from `.dapp` definitions
- LAM (Large Action Model) integration for AI-assisted interactions

### Phase 5 — Mesh Propagation (Planned)

- Multi-hop content routing (Lightning-network-style Gopher propagation)
- Relay incentivization (REFI rewards for forwarding)
- Content-addressed caching across Pillars
- Cross-subnet discovery via relay peers

---

## 10. Technical Specifications

### Protocol Constants

| Constant | Value | Location |
|----------|-------|----------|
| REFInet TCP port | 7070 | `core/config.py` |
| Standard Gopher TCP port | 70 | `pillar.py` |
| Multicast group | 224.0.70.70 | `core/config.py` |
| Multicast port | 7071 | `core/config.py` |
| Discovery interval | 30 seconds | `core/config.py` |
| Health check interval | 60 seconds | `mesh/discovery.py` |
| Replication interval | 300 seconds (5 min) | `mesh/replication.py` |
| Archive interval | 24 hours | `db/archive_db.py` |
| Rate limit (direct) | 100 requests / 60 seconds | `core/gopher_server.py` |
| Rate limit (Tor) | 500 requests / 60 seconds | `core/gopher_server.py` |
| Session duration | 24 hours | `auth/siwe.py` |
| Multicast TTL | 2 | `mesh/discovery.py` |
| Max response size | 2 MB | `core/gopher_client.py` |
| Connection timeout | 10 seconds (client) / 30 seconds (server) | `core/gopher_client.py`, `core/gopher_server.py` |
| Accounting days/month | 28 | `core/config.py` |
| Accounting months/year | 13 | `core/config.py` |
| Live DB retention | 13 months | `core/config.py` |
| Allowed outbound ports | 70, 7070, 105 | `core/gopher_client.py` |
| Tor bootstrap timeout | 120 seconds | `core/tor_manager.py` |
| Tor health check interval | 60 seconds | `core/tor_manager.py` |
| Tor max restart attempts | 3 | `core/tor_manager.py` |
| Tor SOCKS port (default) | 9050 | `core/config.py` |
| Tor control port (default) | 9051 | `core/config.py` |
| WAL checkpoint interval | 6 hours | `pillar.py` |
| Protocol version | 0.3.0 | `core/config.py` |

### Database Schema Summary

**Live Database — 9 tables, 4 indexes, 7 triggers:**

| Table | PK | Rows (typical) | Trigger Protection |
|-------|----|-----------------|--------------------|
| `daily_tx` | `tx_id` (UUID) | Thousands/day | None |
| `daily_metrics` | Composite (day, month, year, pid) | 1/day | None |
| `peers` | `pid` | Tens | None (includes `onion_address` column) |
| `content_index` | `selector` | Hundreds | None |
| `token_state` | `pid` | 1 | None |
| `gopherholes` | `id` (autoincrement) | Tens-hundreds | No UPDATE, No DELETE |
| `siwe_sessions` | `id` (autoincrement) | Hundreds | No DELETE |
| `service_proofs` | `proof_id` (text) | Tens-hundreds | No UPDATE, No DELETE |
| `settlements` | `settlement_id` (text) | Tens-hundreds | No UPDATE, No DELETE |

**Archive Database — 3 tables:**

| Table | PK |
|-------|----|
| `yearly_summary` | Composite (year, pid) |
| `monthly_snapshot` | Composite (year, month, pid) |
| `peer_history` | Composite (pid, year) |

### Route Map (23 Routes)

| # | Selector Pattern | Gopher Type | Handler | Port 70 |
|---|-----------------|-------------|---------|---------|
| 1 | `/` (empty) | 1 (menu) | `build_root_menu` | Yes |
| 2 | `/about` | 1 (menu) | `build_about_menu` | Yes |
| 3 | `/network` | 1 (menu) | `build_network_menu` | Gated |
| 4 | `/dapps` | 1 (menu) | `build_dapps_menu` | Yes |
| 5 | `/dapps/<slug>.dapp` | 1 (menu) | `_render_dapp_detail` | Yes |
| 6 | `/directory` | 1 (menu) | `build_directory_menu` | Yes |
| 7 | `/directory.json` | 0 (text) | JSON serialization | Gated |
| 8 | `/status.json` | 0 (text) | JSON serialization | Gated |
| 9 | `/auth` | 1 (menu) | `build_auth_menu` | Gated |
| 10 | `/auth/challenge` | 7 (search) | SIWE challenge | Gated |
| 11 | `/auth/verify` | 7 (search) | SIWE verify | Gated |
| 12 | `/rpc` | 1 (menu) | `_route_rpc_status` | Gated |
| 13 | `/rpc/balance` | 7 (search) | Native balance query | Gated |
| 14 | `/rpc/token` | 7 (search) | ERC-20 balance query | Gated |
| 15 | `/rpc/gas` | 7 (search) | Gas estimation | Gated |
| 16 | `/rpc/broadcast` | 7 (search) | Tx broadcast (auth) | Gated |
| 17 | `/pid` | 0 (text) | `build_pid_document` | Gated |
| 18 | `/transactions` | 0 (text) | `build_transactions_document` | Gated |
| 19 | `/peers` | 0 (text) | `build_peers_document` | Gated |
| 20 | `/ledger` | 0 (text) | `build_ledger_document` | Gated |
| 21 | `/search` | 7 (search) | Full-text content search | Gated |
| 22 | `/holes/*` | static | Gopherhole content | Yes |
| 23 | `*` (fallback) | static | `_serve_static` | Yes |

### Background Tasks

| Task | Interval | Purpose |
|------|----------|---------|
| Peer Announcer | 30 seconds | Broadcast presence via UDP multicast |
| Peer Listener | Continuous | Receive and register peer announcements |
| Health Monitor | 60 seconds | TCP ping all known peers, update health status |
| Registry Replicator | 5 minutes | Sync gopherhole registries from all peers |
| Tor Health Monitor | 60 seconds | Ping Tor control port, auto-restart if dead |
| WAL Checkpoint | 6 hours | Prevent journal file accumulation |
| Archive Migrator | 24 hours | Move data older than 13 months to archive DB |

### Dependencies

| Package | Version | Purpose | Required |
|---------|---------|---------|----------|
| `cryptography` | >= 41.0.0 | Ed25519 keypair operations | Yes |
| `eth-account` | >= 0.10.0 | SIWE signature verification (ecrecover) | Yes |
| `web3` | >= 6.0.0 | EVM JSON-RPC proxy | Optional |
| `qrcode[pil]` | >= 7.4.2 | QR code generation for auth challenges | Optional |
| `stem` | >= 1.8.2 | Tor controller library (hidden service management) | Yes (for Tor mode) |
| `pytest` | >= 7.0 | Test framework | Dev only |
| `pytest-asyncio` | >= 0.23.0 | Async test support | Dev only |

---

## 11. Conclusion

REFInet is a working implementation of an idea that predates the modern web: that every computer can be a server, and that networks should be built from sovereign, cryptographically identified nodes rather than centralized services.

By building on Gopher — a 40-year-old protocol that serves human-readable text over TCP — REFInet inherits a simplicity that no modern protocol can match. A Gopher transaction requires no TLS handshake, no HTTP headers, no rendering engine. It works with `curl`, `netcat`, or a 30-year-old terminal client.

By adding Ed25519 identity, SHA-256 content hashing, and SQL trigger-enforced immutable registries, REFInet makes this simplicity trustworthy. Content is self-authenticating. Records are cryptographically verifiable. No certificate authority or DNS registrar stands between a Pillar and its identity.

By connecting to EVM blockchains through a local RPC gateway, REFInet bridges this sovereign infrastructure with programmable economics. A Pillar can query balances, estimate gas, and broadcast transactions — all through the same Gopher interface that serves menus and files.

And by using UDP multicast for zero-configuration peer discovery, REFInet creates a mesh that forms organically. Two Pillars on the same network find each other within 30 seconds, exchange registry records, and verify each other's signatures — with no tracker, no bootstrap server, and no internet connection required.

By integrating Tor as an optional transport layer, a Pillar can now serve content globally via a `.onion` address — without revealing its IP, without port forwarding, without DNS — while all content remains signed by the same Ed25519 identity. The operator enables Tor with a single config flag; the Pillar handles the rest. And when Tor is unavailable, the Pillar continues operating over direct TCP without error.

**REFInet is not a proposal. It is running software.** 484 tests pass. 23 routes serve content across a dual-port architecture — standard Gopher on port 70 for backward compatibility, REFInet on port 7070 for full features. Every response carries an Ed25519 signature block for zero-trust verification. Registries replicate across peers with cryptographic verification. Wallets authenticate via EIP-4361. Five EVM chains are reachable through the gateway. Tor hidden services provide anonymous, end-to-end encrypted access for operators and visitors.

Run a Pillar. Join Gopherspace.

```
python3 pillar.py
python3 pillar.py --status    # Check your Pillar's identity and status
```

---

*REFInet v0.3.0 — Built for sovereign, anonymous computing.*
