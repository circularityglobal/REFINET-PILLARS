# Changelog

All notable changes to REFInet Pillar are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] — Unreleased

Aligns the Pillar with the TradeSphere bridge proposal (findings F1–F20) without
breaking existing wire formats, stored records or the browser extension.

### Security
- `pid.json` is written `0600` and `~/.refinet/` is `0700` (F5)
- The key-encryption password is no longer stored in `onboarding_state.json`; it
  unlocks the key in memory only. Legacy state files are migrated on load (F5)
- An encrypted PID can now start the server: the password is read from
  `REFINET_PID_PASSWORD` or prompted for at startup

### Changed
- One version constant (`core/version.py`) feeds `pyproject.toml`,
  `PROTOCOL_VERSION` and new `pid.json` files (F14)
- `SchnorrZKP` is renamed `KeyPossessionProof` (alias kept); documentation no
  longer calls it a zero-knowledge proof (F13)

### Added
- `sig1` in the response signature trailer and the WebSocket envelope: a
  domain-separated signature over (pid, selector, time, body hash), so a signed
  answer cannot be replayed for a different request. `sig` and `hash` keep their
  original meaning (F9)
- `crypto/attestation.py`: witness attestations and service receipts (§3.3)
- `tests/fixtures/pillar-vectors.json`, regenerated with
  `python3 -m tests.vectors --write`, verified by tests on both sides of the bridge
- Opt-in namespaced gopherhole selectors: `hole create --namespaced` serves at
  `/holes/<pid16>/<slug>` so a name cannot collide with another Pillar's (F20)

### Added (Identity)
- A binding is its own EIP-4361 statement (§3.1): `I bind this wallet to
  REFINET Pillar <pid> as its <deployer|operator>`. A sign-in signature can no
  longer be turned into a binding, and a binding message can no longer open a
  session (F1)
- Challenge nonces are registered per Pillar and purpose, and spent on first
  use whether or not the signature verifies. A message published in one
  Pillar's identity document is refused by every other Pillar (F3)
- Each Pillar's SIWE messages carry its own authority and its full PID in
  `URI`/`Resources`, replacing the shared `refinet://pillar` literal (F3)
- Contract wallets (Safe, ERC-4337) verify through EIP-1271 on the chain the
  message names, when `web3` is installed (F4)
- `/identity/v3.json`: the §3.2 identity document, listing §3.1 bindings with a
  document signature. `/identity.json` still serves schema 2, unchanged
- WebSocket `rebind` message: adds a §3.1 binding to an already-onboarded
  Pillar. Bindings stay append-only; the §3.1 one becomes canonical

### Fixed
- A binding records the chain id the wallet actually signed on, instead of
  always claiming Ethereum mainnet (F2)
- Replicated registry records keep their own `registered_at`, so a record now
  survives more than one hop instead of breaking its own signature (F6)
- Registry verification checks `pid == SHA-256(pubkey)`, so a record cannot claim
  a PID whose key it does not hold (F7)

### Added (Mesh & bridge)
- Mesh announcements are signed over (pid, hostname, port, timestamp) and must
  be fresh. An unsigned announcement can still introduce an unknown peer, so
  mixed-version meshes keep working, but it can never move a known peer's
  address. `discovery_require_signed` refuses unsigned ones outright (F8)
- `websocket_extension_ids` and `websocket_require_origin` in config.json
  restrict who may open the bridge. Defaults preserve current behaviour (F15)

### Added (Ledger)
- `/proof/receipt`: accepts a requester-signed receipt (§3.3). This is now the
  only way a `service_proofs` row is created (F10). Intake is idempotent (the
  proof id is derived from the receipt, so re-submitting one is a no-op) and
  capped per requester and per day, because `service_proofs` cannot be deleted
  and signatures cost a stranger nothing
- Spent and expired SIWE challenges are swept by the periodic maintenance task,
  so the challenge registry cannot grow without bound
- Amounts are integers in the asset's base units (`amount_units` + `asset_*`
  columns, folded by `db/money.py`). The `REAL` columns remain for older
  readers and are unused for new records (F12)
- Avalanche (43114), Fuji (43113), Base Sepolia (84532), XDC (50) and Apothem
  (51), plus `~/.refinet/chains.json` so an operator can add a network without
  a release. Existing chains and endpoints are unchanged (F17)

### Changed (Ledger)
- Serving a request no longer writes a `daily_tx` row or a self-signed
  `service_proofs` row — an unbounded, undeletable log any stranger could
  fill. Volume is counted in `daily_metrics`; `tx_count_today` in status.json
  and the root menu reports the same number as before (F11)
- The rate limiter's address table is swept and capped, instead of growing for
  every address ever seen (F11)

### Fixed
- `browse_remote` resolves a host and judges the resolved address, then
  connects to the address it checked. The old string-prefix check passed
  `0x7f000001`, `2130706433`, `127.1` and `[::ffff:127.0.0.1]`, and blocked
  names like `fdroid.org` (F16)

### Removed
- Committed `__pycache__/` files and a local editor settings file (F18)
- Wallet addresses are no longer announced over multicast: a peer that wants
  one fetches `/identity.json` and verifies the binding itself (F8)

## [0.4.0] — 2026-03-09

### Changed (Website)
- All navbar links now open pop-up modals instead of scrolling to sections
- Unified all 6 documentation pages into a single Docs modal with document switcher sidebar and per-document TOC
- Replaced separate Whitepaper and Getting Started modals with the unified Docs modal
- Added "What Is It" modal (6-pillar feature grid) accessible from navbar
- Added "Community" modal (GitHub, Discord, Gopherspace cards) accessible from navbar
- Footer links converted to modal triggers matching navbar behavior
- Removed landing page "What Is It" section (content moved to modal)
- Removed SPA doc-viewer page route system in favor of modal-only navigation
- All modals share uniform branded layout (consistent header, backdrop, close button, animation)

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
