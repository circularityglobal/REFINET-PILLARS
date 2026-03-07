# REFInet Pillar — Sovereign Gopher Mesh Node

> **Protocol v0.2.0** — Phase 1 & Phase 2 complete (incl. Tor hidden service integration)

## What Is This?

REFInet Pillar turns any computer (old or new) into a **sovereign mesh node** in Gopherspace.

Each Pillar is:
- A **Gopher server** serving hierarchical menus and content on TCP port 7070 (+ optional port 70)
- A **local ledger** tracking all DApp transactions in SQLite (13-month live + yearly archive)
- A **cryptographic identity** (Pillar ID / PID) for signing content and verifying peers
- A **mesh participant** discovering neighbors via UDP multicast and replicating registries
- A **Tor hidden service** (optional) for anonymous .onion access without exposing your IP
- A **gateway** to enterprise LAM + blockchain SDKs (via CIFI staking → REFI issuance)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-org/refinet-pillar.git
cd refinet-pillar

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch your Pillar
python3 pillar.py

# Your node is now live in Gopherspace on port 7070
# PID generated and stored in ~/.refinet/pid.json

# Optional: Enable Tor hidden service (set tor_enabled in config)
# Edit ~/.refinet/config.json → "tor_enabled": true
python3 pillar.py

# Check status of a running Pillar
python3 pillar.py --status
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│               REFInet Pillar Node                │
├──────────┬──────────┬───────────┬───────────────┤
│  Gopher  │  SQLite  │   PID &   │  Mesh + SIWE  │
│  Server  │  Ledger  │  Crypto   │  Discovery    │
│TCP:7070  │ Live+Arc │ Ed25519   │  Multicast    │
├──────────┴──────────┴───────────┴───────────────┤
│       DApp Runtime + EVM RPC Gateway             │
├──────────────────────────────────────────────────┤
│         Token Layer (CIFI → REFI) [Phase 3]      │
├──────────────────────────────────────────────────┤
│     Tor Hidden Service (.onion) [optional]        │
├──────────────────────────────────────────────────┤
│  Transport: Wi-Fi Mesh / LAN / Internet / Tor    │
└──────────────────────────────────────────────────┘
```

## Connecting via Gopher Client

```bash
# Using curl
curl gopher://localhost:7070/

# Using lynx
lynx gopher://localhost:7070

# Using any Gopher client
# Host: localhost  Port: 7070  Selector: (empty)
```

## Project Structure

```
refinet-pillar/
├── pillar.py              # Main entry point, CLI, async launcher, Tor lifecycle
├── requirements.txt       # Python dependencies
├── core/
│   ├── gopher_server.py   # Gopher protocol server (dual-port, rate limiting)
│   ├── menu_builder.py    # Dynamic gophermap generation (Tor-aware)
│   ├── config.py          # Pillar configuration and Tor defaults
│   ├── tor_manager.py     # Tor hidden service management via stem
│   ├── dapp.py            # .dapp file parser
│   ├── gopherhole.py      # Gopherhole creation & verification
│   ├── gopher_client.py   # Async Gopher client (SSRF-protected)
│   └── gophermap_parser.py # RFC 1436 menu parser
├── db/
│   ├── live_db.py         # 13-month live transaction DB + peer onion tracking
│   ├── archive_db.py      # Yearly compressed archive DB
│   └── schema.py          # SQLite schemas (7 live tables + 3 archive)
├── crypto/
│   ├── pid.py             # Pillar ID generation & management
│   └── signing.py         # Content signing & verification
├── mesh/
│   ├── discovery.py       # Peer discovery via multicast + health monitoring
│   └── replication.py     # Gopherhole registry sync between peers
├── auth/
│   ├── siwe.py            # EIP-4361 SIWE challenge/verify
│   └── session.py         # Session token management
├── rpc/
│   ├── gateway.py         # EVM JSON-RPC proxy (5 chains)
│   ├── chains.py          # Default chain configurations
│   └── config.py          # User-configurable RPC endpoints
├── cli/
│   └── hole.py            # Gopherhole CLI subcommands
├── docs/
│   └── backup.md          # Backup and recovery guide
├── tests/                 # 236 tests across 16 modules
└── gopherroot/            # Served content directory
    ├── gophermap          # Root menu
    ├── dapps/             # DApp definitions
    └── holes/             # Gopherhole content
```

## Roadmap

- **Phase 1** ✅ Gopher server + SQLite + PID + DApp system + content indexing
- **Phase 2** ✅ Mesh discovery, peer replication, SIWE auth, EVM RPC, Tor hidden service, dual-port, CLI
- **Phase 3** CIFI staking → REFI issuance + license activation
- **Phase 4** DApp runtime + LAM integration
- **Phase 5** Lightning-network-style Gopher propagation

## License

Open source. Run a Pillar. Join the mesh.
