# REFInet Pillar — Getting Started

## What is REFInet Pillar?

REFInet Pillar is a **sovereign Gopher protocol node** — your own cryptographically-signed identity in a decentralized mesh network. Every Pillar:

- Has a unique **Pillar ID (PID)** derived from an Ed25519 keypair
- **Signs all content** it serves, so visitors can verify authenticity
- **Discovers and connects** to other Pillars automatically via mesh networking
- **Authenticates users** with Ethereum wallets (Sign-In with Ethereum / EIP-4361)
- **Hosts Gopherholes** — sites in Gopherspace with immutable, signed registration records
- **Bridges to the browser** via a native extension with one-click wallet signing

There is no central server. No accounts to create on someone else's platform. Your Pillar is your identity, your node, and your piece of the network.

---

## Quick Start

### Option A: Bare Metal (3 commands)

```bash
pip3 install -r requirements.txt
python3 pillar.py
```

Your Pillar is now running. Verify it:

```bash
python3 pillar.py --status
```

### Option B: Docker (1 command)

```bash
docker-compose up -d
```

Both options give you a fully operational Pillar with identity, database, mesh discovery, WebSocket bridge, and Gopher serving — all running immediately.

---

## Requirements

### Python

- **Minimum:** Python 3.9
- **Recommended:** Python 3.11+ (used in Docker image)

### Dependencies

**Core (required):**

| Package | Purpose |
|---------|---------|
| `cryptography>=41.0.0` | Ed25519 key generation and content signing |
| `argon2-cffi>=23.1.0` | Key derivation for encrypted key storage (Argon2id) |

**Optional (graceful degradation if missing):**

| Package | Purpose | What You Lose Without It |
|---------|---------|--------------------------|
| `eth-account>=0.10.0` | SIWE wallet authentication | No wallet sign-in |
| `websockets>=12.0` | Browser extension bridge | No browser extension support |
| `web3>=6.0.0` | EVM RPC gateway (5 chains) | No on-chain queries or tx broadcast |
| `stem>=1.8.2` | Tor hidden services | No .onion address |
| `qrcode[pil]>=7.4.2` | QR codes for SIWE challenges | No QR code generation |

Install everything:

```bash
pip3 install -r requirements.txt
```

The Pillar logs which optional dependencies are available at startup.

---

## What Happens on First Run

When you run `python3 pillar.py` for the first time:

1. **Identity created** — Ed25519 keypair generated, PID = SHA-256(public_key), saved to `~/.refinet/pid.json`
2. **Databases initialized** — SQLite live database (13-month rolling ledger) + archive database, both in WAL mode
3. **Config created** — Default settings written to `~/.refinet/config.json`
4. **Servers start:**

| Port | Protocol | Purpose |
|------|----------|---------|
| **7070** | Gopher (TCP) | REFInet server — full features, all routes |
| **70** | Gopher (TCP) | Standard Gopher — public content only |
| **7075** | WebSocket | Browser extension communication |
| **~/.refinet/pillar.sock** | Unix socket | Local IPC for same-machine tools |

5. **Mesh discovery begins** — Announces on multicast 224.0.70.70:7071 every 30 seconds, listens for other Pillars
6. **Background tasks run** — WAL checkpoints every 6 hours, monthly data archival

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │        Browser Extension        │
                        │  (v0.4.0 — Native Wallet Auth)  │
                        │                                 │
                        │  MetaMask / Rabby / D'Cent /    │
                        │  Coinbase / Any EVM Wallet      │
                        └───────────────┬─────────────────┘
                                        │ ws://localhost:7075
                                        │
┌───────────────┐       ┌───────────────▼─────────────────┐
│  Other Pillars │◄─────►│         YOUR PILLAR             │
│  (Mesh Peers)  │ TCP  │                                 │
│                │ 7070 │  PID: a3f7c2...                 │
└───────────────┘       │                                 │
                        │  :7070  REFInet (full features) │
┌───────────────┐       │  :70    Standard Gopher         │
│ Gopher Clients│──────►│  :7075  WebSocket Bridge        │
│ (curl, lynx)  │  TCP  │  :sock  IPC Socket              │
└───────────────┘  70   │                                 │
                        │  ~/.refinet/                    │
                        │    pid.json    (identity)       │
                        │    config.json (settings)       │
                        │    db/live.db  (ledger)         │
                        │    vault/      (encrypted)      │
                        └─────────────────────────────────┘
```

---

## CLI Reference

### Start the Pillar

```bash
python3 pillar.py                              # Start with defaults
python3 pillar.py run                          # Explicit run
python3 pillar.py run --host 0.0.0.0           # Bind to all interfaces
python3 pillar.py run --port 7070              # Set REFInet port
python3 pillar.py run --gopher-port 70         # Set standard Gopher port
python3 pillar.py run --no-gopher              # Disable port 70
python3 pillar.py run --no-mesh                # Disable peer discovery
python3 pillar.py run -v                       # Verbose (DEBUG) logging
```

### Check Status (offline)

```bash
python3 pillar.py --status
```

Shows: PID, public key, known peers, Tor status, and configuration.

### Gopherhole Management

```bash
# Create a gopherhole
python3 pillar.py hole create \
    --name "My Site" \
    --selector /holes/mysite \
    --desc "My sovereign corner of Gopherspace" \
    --owner 0xYourEthAddress

# List gopherholes
python3 pillar.py hole list                    # Local only
python3 pillar.py hole list --peers            # Include mesh-discovered
python3 pillar.py hole list --json             # JSON output

# Verify a gopherhole's signature
python3 pillar.py hole verify --pid <pid> --selector /holes/mysite
```

### Peer Management

```bash
# Add a remote peer manually
python3 pillar.py peer add --host 203.0.113.10 --port 7070 --name "Alice's Pillar"

# List known peers
python3 pillar.py peer list

# Remove a peer
python3 pillar.py peer remove --pid <pid-prefix>
```

### Identity Profiles

```bash
# Create a new identity
python3 pillar.py profile create --name "Work" --encrypt

# List profiles
python3 pillar.py profile list

# Switch active identity
python3 pillar.py profile switch --name "Work"

# View profile details
python3 pillar.py profile info --name "Work"

# Delete a profile
python3 pillar.py profile delete --name "Work"
```

### Key Recovery (Shamir's Secret Sharing)

```bash
# Split your private key into 5 shares (3 needed to recover)
python3 pillar.py recovery split --threshold 3 --shares 5

# Recover from shares (interactive)
python3 pillar.py recovery restore
```

---

## Browser Extension (v0.4.0)

The REFInet Pillar Bridge is a Manifest v3 browser extension that connects your browser to your local Pillar.

### Install

1. Open Chrome/Chromium and navigate to `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the `browser-extension/` directory

### What It Does

**Native Wallet Connection** — detects your installed EVM wallets (MetaMask, Rabby, D'Cent, Coinbase Wallet, Brave Wallet, Trust Wallet, OKX, TokenPocket, and any EIP-6963 compatible wallet) and signs SIWE challenges with one click. No WalletConnect. No third-party projectIDs. Direct EIP-1193 provider communication.

**Authentication Flow:**
1. Click the extension icon, then "Sign In"
2. Your installed wallets appear automatically
3. Click your wallet — it connects, signs the SIWE challenge, and verifies with your Pillar
4. Your browser is now cryptographically linked to your Pillar identity (PID-SIWE correlation)

**Gopher Browser** — browse Gopherspace through your Pillar, with Ed25519 signature verification on all responses.

**Page API** — web pages can interact with your Pillar via `window.refinet`:

```javascript
// Check if connected to a Pillar
const connected = await window.refinet.isConnected();

// Get Pillar identity
const { pid, public_key } = await window.refinet.getPID();

// Get authenticated session
const { address, pid, expires_at } = await window.refinet.getSession();

// Browse Gopherspace
const { data, signature } = await window.refinet.browseGopher("/about");

// Get verified peer PIDs
const pids = await window.refinet.getKnownPIDs();

// Trigger wallet auth from a dApp
const { address, pid } = await window.refinet.connectWallet({ chainId: 1 });
```

Pages can detect the extension via the `refinet-ready` event:

```javascript
window.addEventListener("refinet-ready", (e) => {
  console.log("REFInet extension v" + e.detail.version + " detected");
});
```

---

## Capabilities

### Sovereign Identity
- Ed25519 keypair with PID = SHA-256(public_key)
- All served content signed — visitors verify you are who you claim to be
- Multiple identity profiles with encrypted key storage (AES-256-GCM, Argon2id KDF)
- Shamir's Secret Sharing for key recovery (k-of-n threshold)

### SIWE Authentication (EIP-4361)
- Sign-In with Ethereum — prove wallet ownership to your Pillar
- Session management with 24-hour expiry, write-only audit trail
- PID embedded in every SIWE challenge — cryptographic proof that the browser user IS the Pillar operator
- Domain separation: `refinet://pillar` vs `refinet://browser` prevents cross-domain attacks

### Mesh Networking
- **Automatic discovery:** UDP multicast (224.0.70.70:7071) announces your Pillar every 30 seconds
- **WAN peers:** Add remote peers manually or via `~/.refinet/peers.json` bootstrap file
- **Health checks:** Background monitoring of peer status, latency, and consecutive failures
- **Registry replication:** Gopherholes sync between peers every 5 minutes with Ed25519 signature verification — tampered records are rejected

### Gopherhole Hosting
- Create signed sites in Gopherspace: `pillar hole create --name "My Site" --selector /holes/mysite`
- **Immutable registry:** Database triggers prevent updates or deletions — append-only
- Signature-based verification: anyone can verify your gopherhole's authenticity
- Static content served from `gopherroot/` with hot-reload

### EVM RPC Gateway
Requires `web3` package. Query blockchains directly from Gopher:

- **Supported chains:** Ethereum (1), Polygon (137), Arbitrum (42161), Base (8453), Sepolia (11155111)
- **Endpoints:** `/rpc/balance`, `/rpc/token`, `/rpc/gas`, `/rpc/broadcast`
- Transaction broadcast requires a valid SIWE session
- Configurable RPC endpoints via `~/.refinet/rpc.json` with automatic failover

### Encrypted Vault
- Per-item AES-256-GCM encryption with Argon2id key derivation
- Store arbitrary data with MIME type tracking
- File naming uses SHA-256 hashes — no metadata leakage
- Requires SIWE session for access

### Tor Hidden Services
Requires `stem` package and the Tor binary:

- Automatic .onion address generation from Ed25519 Tor keypair
- Dual-port forwarding (7070 + optionally 70) through Tor
- Enable in config: set `tor_enabled: true` in `~/.refinet/config.json`
- Health monitoring with auto-restart (max 3 attempts)

### Privacy Proxy (Port 7074)
- Forward proxy for anonymized Gopher requests
- SSRF protection: blocks loopback, RFC 1918, and link-local addresses
- Port whitelist: only 70, 7070, 105 allowed
- Optional Tor SOCKS5 routing
- Audit logging to transaction ledger

### DApp Framework
- Define DApps as `.dapp` files in `gopherroot/dapps/`
- Sections: `[meta]`, `[abi]`, `[docs]`, `[flows]`, `[warnings]`
- Hot-reload on every request — no restart needed
- Discoverable via `/dapps` route

### Cryptographic Authentication
- Schnorr ZKP: prove knowledge of private key without revealing it
- Membership attestation: prove your PID is a member of a set (authenticated, not anonymous)
- Session establishment from verified proof (alternative to SIWE)

### 13-Month Accounting Calendar
- 13 months x 28 days = 364 days + 1 balance day
- Deterministic, predictable accounting periods
- 13-month rolling live database with automatic archival of oldest month

---

## Configuration

### Main Config (`~/.refinet/config.json`)

```json
{
  "hostname": "localhost",
  "port": 7070,
  "pillar_name": "My REFInet Pillar",
  "description": "A sovereign node in Gopherspace",
  "protocol_version": "0.2.0",
  "tor_enabled": false,
  "tor_expose_port_70": true,
  "tor_socks_port": 9050,
  "tor_control_port": 9051
}
```

### Bootstrap Peers (`~/.refinet/peers.json`)

```json
[
  {
    "host": "203.0.113.10",
    "port": 7070,
    "name": "Alice's Pillar",
    "pid": "a3f7c2..."
  }
]
```

### Port Reference

| Port | Protocol | Purpose | Configurable |
|------|----------|---------|-------------|
| 7070 | TCP/Gopher | REFInet (full features) | `--port` flag |
| 70 | TCP/Gopher | Standard Gopher (public only) | `--gopher-port` flag |
| 7071 | UDP/Multicast | Mesh peer discovery | In code |
| 7073 | TCP/TLS | GopherS (encrypted Gopher) | In code |
| 7074 | TCP/HTTP | Privacy proxy | In code |
| 7075 | TCP/WebSocket | Browser extension bridge | In code |

---

## Deployment

### Development

```bash
git clone <repo>
cd REFINET-PILLARS
pip3 install -r requirements.txt
python3 pillar.py
```

### Docker

```bash
docker-compose up -d                    # Start
docker logs -f pillar                   # View logs
docker exec pillar python3 pillar.py --status   # Check status
```

Data persists in a Docker volume mapped to `/home/refinet/.refinet`.

### Production (systemd)

```bash
sudo bash deploy/install.sh
sudo systemctl start refinet-pillar
sudo systemctl enable refinet-pillar    # Auto-start on boot
sudo journalctl -u refinet-pillar -f    # Tail logs
```

The install script creates a `refinet` system user, copies the app to `/opt/refinet`, and registers a systemd service with security hardening (read-only filesystem, no privilege escalation, 512MB memory cap).

---

## Data Directory

Everything lives in `~/.refinet/`:

```
~/.refinet/
  pid.json              # Your identity (Ed25519 keypair + PID)
  config.json           # Configuration
  peers.json            # Bootstrap peer list
  active_profile        # Current profile name
  db/
    live.db             # 13-month rolling transaction ledger (WAL mode)
    archive.db          # Historical yearly records
  profiles/             # Multi-identity storage
  vault/                # Encrypted items (AES-256-GCM)
  tls/                  # TLS certificates (GopherS)
  tor_data/             # Tor hidden service keys
```

---

## Testing

```bash
python3 -m pytest tests/ -v
```

**Current status:** 437 passed, 5 skipped

The 5 skips are expected:
- 2 skips: Tor binary not installed on the test machine
- 3 skips: TLS 1.3 requires OpenSSL (macOS ships LibreSSL)

---

## Project Stats

- **Codebase:** 14,000+ lines of Python across 76+ files
- **Browser extension:** 8 files (Manifest v3)
- **Test suite:** 29 test files, 437 passing tests
- **Gopher routes:** 30+ endpoints
- **Database tables:** 10+
- **Supported EVM chains:** 5
- **Optional dependencies:** 5 (all gracefully degrade)
- **Ports:** 6 (+ Unix socket)
