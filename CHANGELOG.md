# Changelog

All notable changes to REFInet Pillar are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] — 2026-03-09

### Fixed (Audit Remediation)
- Removed 4 hardcoded personal paths in `docs/DEPLOYMENT.md` — replaced with generic `/path/to/REFINET-PILLARS`
- Pinned `websockets>=12.0,<15` in `requirements.txt` to guard against `web3.py` transitive dependency on `websockets.legacy` (removed in v16)
- Added missing `onboarding/`, `vault/`, `website/` directories to README project structure tree
- Added 18 missing routes to PLATFORM_OVERVIEW route table (now 39 dynamic routes fully documented)
- Updated all file index line counts in PLATFORM_OVERVIEW to match actual codebase (~4,640 → ~7,984 LOC)
- Expanded test coverage table from 16 to 33 modules with verified counts (484 tests)
- Updated CONTRIBUTING.md test count from 479+ to 484+

### Added
- Fly.io deployment infrastructure (`fly.toml`, `scripts/headless_start.py`, `scripts/bootstrap_keygen.py`)
- GitHub Actions CI/CD: deploy on push to main (`deploy.yml`)
- Health monitoring workflow with 15-minute status badge (`health.yml`)
- GitHub Pages website deployment (`pages.yml`)
- Release script with checksum generation (`scripts/release.sh`)
- Placeholder status badge (`.github/badges/pillar-status.svg`)
- `CONTRIBUTING.md` — standalone contribution guide
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- `.github/PULL_REQUEST_TEMPLATE.md` — PR checklist
- `.github/FUNDING.yml` — GitHub Sponsors + crypto donations
- `.github/CODEOWNERS` — maintainer assignment
- GopherS (TLS) listener wired into `pillar.py` task group — encrypted Gopher on port 7073 with self-signed certificate
- Bootstrap peer validation rejects placeholder PIDs with clear warnings
- `cli()` entry point for `pip install refinet-pillar && refinet-pillar run`
- 484 passing tests (up from 437)

### Changed
- Dockerfile entrypoint changed to headless start script for bootstrap node
- Dockerfile reduced to single exposed port (7070)
- Version bumped to 0.3.0
- `PROTOCOL_VERSION` in `core/config.py` updated from `0.2.0` to `0.3.0`
- All documentation version references updated to 0.3.0

### Fixed
- All repository URLs corrected: `github.com/refinet/pillar` to `github.com/circularityglobal/REFINET-PILLARS`
- All subdomain references corrected: `pillar.refinet.io` to `gopher.refinet.io`
- `deploy/peers.json.example` field names fixed (`host` to `hostname`, added `public_key`)
- `website/install.sh` checksum skip message now shows visible warning
- `pyproject.toml` entry point fixed: `pillar:main` → `pillar:cli` (async main required arguments)

## [0.2.0] — 2026-03-08

### Added
- Docker support (Dockerfile + docker-compose.yml) with non-root user and volume persistence
- WebSocket CORS restriction with configurable origin allowlist
- Standardized optional dependency checks at startup (`check_dependencies()`)
- WAN peer discovery via bootstrap peer list (`~/.refinet/peers.json`)
- Peer management CLI: `pillar.py peer add/list/remove`
- Browser extension v0.4.0 with EIP-6963 multi-wallet support
- PID embedded in SIWE challenge for PID-SIWE correlation
- WebSocket bridge (`start_websocket_bridge()`) and IPC server (`start_ipc_server()`)
- `/identity.json` Gopher endpoint for browser PID retrieval
- Typed WebSocket auth messages: `identity`, `auth_challenge`, `auth_verify`, `browse_remote`
- `window.refinet` content script API: `isConnected()`, `getPID()`, `getSession()`, `browseGopher()`
- Peer PID exchange via `browse_remote` message type
- Gopher parser module extracted to `browser-extension/gopher.js`
- Multi-profile identity management: `pillar.py profile create/list/switch/info/delete`
- Shamir secret sharing recovery: `pillar.py recovery split/restore`
- Encrypted vault with AES-256-GCM
- Zero-knowledge proof authentication (Schnorr ZKP, Fiat-Shamir)
- EVM RPC gateway with 5-chain support and failover
- Systemd service with security hardening
- Gopher `/download` route with binary file serving for software distribution
- 437 passing tests (up from 387)

### Changed
- WebSocket `origins=None` replaced with configurable allowed origins + prefix matching
- Optional dependencies (web3, websockets, stem, eth-account) now use try/except + flag pattern
- RPC failover now cycles through multiple endpoints per chain

### Security
- WebSocket CORS now requires explicit origin allowlist (was open to any origin)
- SIWE domain separation: `refinet://pillar` vs `refinet://browser`
- SSRF protection on Gopher proxy (RFC 1918 + loopback blocked)
- Rate limiting: 100 req/60s per IP

## [0.1.0] — 2026-02-15

### Added
- Initial Gopher server on TCP port 7070
- Ed25519 Pillar ID (PID) generation and content signing
- SQLite ledger with 13-month live + yearly archive rotation
- DApp file parser and runtime
- Content indexing and transaction recording
- Gopherhole creation, listing, and verification CLI
- Mesh peer discovery via UDP multicast
- Registry replication between peers
- Dual-port serving (7070 REFInet + 70 standard Gopher)
- SIWE wallet authentication (EIP-4361)
- Tor hidden service integration (optional)
- 387 passing tests
