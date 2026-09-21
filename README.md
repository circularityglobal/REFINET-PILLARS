# REFInet Pillar

[![Tests](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/test.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/test.yml)
![Pillar Status](.github/badges/pillar-status.svg)

> Sovereign Gopher mesh node. Your cryptographic identity. Your node. Your internet.

**Protocol v0.6.0** | **786 tests passing** | **AGPLv3 License** | **Python 3.9+**

---

## Run a Pillar for Your App

Launching an app on its own domain? Add a Pillar before you go live. It runs on
your VPS or cloud, answers on `pillar.yourdomain.com`, and joins the mesh once
100,000 REFI are staked for it on XDC.

```bash
npx @refinet/pillar init --app-domain example.com --pillar-domain pillar.example.com
npx @refinet/pillar deploy --ssh root@<vps-ip>
npx @refinet/pillar bind --ssh root@<vps-ip> --address 0xYourWallet
npx @refinet/pillar stake
npx @refinet/pillar doctor
```

The full guide, including running many Pillars on your own infrastructure, is
[docs/OPERATORS.md](docs/OPERATORS.md). Until the package is published, run the
CLI from a clone: `node sdk/js/bin/refinet-pillar.js <command>`.

---

## Install in 30 Seconds

| Method | Command |
|--------|---------|
| **pip** | `pip3 install refinet-pillar[full] && refinet-pillar run` |
| **Docker** | `docker-compose up -d` |
| **systemd** | `sudo bash deploy/install.sh` |
| **Gopher** | `curl gopher://gopher.refinet.io:7070/1/download` |
| **Source** | `pip3 install -r requirements.txt && python3 pillar.py` |

---

## What Is This?

REFInet Pillar turns any computer into a **sovereign mesh node** in Gopherspace. There is no central server. No accounts to create on someone else's platform. Your Pillar is your identity, your node, and your piece of the network.

Each Pillar is:
- A **Gopher server** serving signed content on TCP port 7070 (+ optional port 70)
- A **cryptographic identity** (Pillar ID / PID) built on Ed25519
- A **mesh participant** discovering neighbors via UDP multicast and replicating registries
- A **local ledger** tracking all transactions in SQLite (13-month live + yearly archive)
- A **browser bridge** connecting wallets via SIWE (EIP-4361) and WebSocket
- A **gateway** to 10 EVM chains via built-in RPC proxy
- A **Tor hidden service** (optional) for anonymous .onion access

---

## Architecture

```
+--------------------------------------------------+
|               REFInet Pillar Node                 |
+-----------+-----------+------------+--------------+
|  Gopher   |  SQLite   |   PID &    |  Mesh + SIWE |
|  Server   |  Ledger   |  Crypto    |  Discovery   |
| TCP:7070  | Live+Arc  | Ed25519    |  Multicast   |
+-----------+-----------+------------+--------------+
|       DApp Runtime + EVM RPC Gateway (10 chains)   |
+---------------------------------------------------+
|     Browser Extension v0.4.0 (WebSocket Bridge)   |
+---------------------------------------------------+
|  Encrypted Vault | Key Proof | Shamir Recovery    |
+---------------------------------------------------+
|  Transport: Wi-Fi Mesh / LAN / Internet / Tor     |
+---------------------------------------------------+

Ports: 7070 (REFInet) | 70 (Gopher) | 7073 (TLS) | 7074 (Proxy) | 7075 (WebSocket)
```

---

## Download

| Channel | Location |
|---------|----------|
| **GitHub** | [github.com/circularityglobal/REFINET-PILLARS](https://github.com/circularityglobal/REFINET-PILLARS) |
| **PyPI** | `pip install refinet-pillar` |
| **Docker Hub** | `docker pull refinet/pillar:latest` |
| **Gopherspace** | `gopher://gopher.refinet.io:7070/download` |

---

## Docker Quick Start

```bash
docker run -d \
  -p 7070:7070 -p 70:70 -p 7075:7075 \
  -v ~/.refinet:/home/refinet/.refinet \
  refinet/pillar:latest
```

Or with docker-compose:

```bash
git clone https://github.com/circularityglobal/REFINET-PILLARS.git
cd REFINET-PILLARS
docker-compose up -d
```

---

## Browser Extension

The REFInet Pillar Bridge (v0.4.0) connects your browser to your local Pillar:

1. Open `chrome://extensions` and enable Developer Mode
2. Click "Load unpacked" and select the `browser-extension/` directory
3. Click the REFInet icon and authenticate with your Ethereum wallet

Features: SIWE authentication, EIP-6963 multi-wallet support, `window.refinet` API for DApps.

---

## CLI Reference

```bash
pillar.py run [--host HOST] [--port PORT] [--no-mesh] [--no-gopher] [-v]
pillar.py --status
pillar.py hole create|list|verify
pillar.py peer add|list|remove
pillar.py profile create|list|switch|info|delete
pillar.py recovery split|restore
```

---

## Documentation

- [Getting Started](GETTING-STARTED.md) — Full setup guide with all options
- [Platform Overview](PLATFORM_OVERVIEW.md) — Architecture deep dive
- [Developer Guide](DEV_GUIDE.md) — Module reference and API docs
- [Whitepaper](WHITEPAPER.md) — Protocol specification
- [Operator Guide](docs/OPERATORS.md) — Run a Pillar on your domain, next to your app, or at scale
- [Staking Contract](contracts/README.md) — PillarStaking on XDC: 100,000 REFI, offline fees, 14-day cooldown
- [Deployment Guide](docs/DEPLOYMENT.md) — Bootstrap node infrastructure setup
- [Security Policy](SECURITY.md) — Vulnerability reporting
- [Contributing](CONTRIBUTING.md) — How to contribute
- [Code of Conduct](CODE_OF_CONDUCT.md) — Community standards
- [Changelog](CHANGELOG.md) — Release history

---

## Project Structure

```
refinet-pillar/
├── pillar.py                # Entry point, async launcher, CLI
├── requirements.txt         # Python dependencies
├── pyproject.toml           # PyPI packaging
├── Dockerfile               # Container image
├── docker-compose.yml       # One-command deployment
├── core/                    # Gopher server, menu builder, config
├── crypto/                  # Ed25519 PID, signing, key-possession proof
├── db/                      # SQLite ledger (live + archive)
├── auth/                    # SIWE challenges, sessions
├── mesh/                    # Peer discovery, replication
├── rpc/                     # EVM JSON-RPC gateway (10 chains)
├── cli/                     # CLI subcommands
├── proxy/                   # Privacy proxy (SSRF-protected)
├── onboarding/              # First-run setup wizard & readiness checks
├── vault/                   # Encrypted personal file storage
├── integration/             # Cross-module integration
├── scripts/                 # Deployment & release scripts
├── tests/                   # pytest suite
├── browser-extension/       # Chrome extension v0.4.0
├── gopherroot/              # Served Gopher content
├── website/                 # Landing page & curl installer
├── deploy/                  # systemd, VPS (Docker + Caddy), Kubernetes
├── contracts/               # PillarStaking (Solidity, Foundry) for XDC
├── monitor/                 # Liveness monitor: the staking contract's oracle
├── sdk/                     # @refinet/pillar npm package (verify, deploy, doctor)
├── docs/                    # Operator guide, wire formats, backup guide
└── fly.toml                 # Fly.io deployment config
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. Quick version:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Run the test suite: `python -m pytest tests/ -q --timeout=60`
4. Submit a pull request

See [SECURITY.md](SECURITY.md) for vulnerability reporting and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community standards.

---

## CI/CD Pipeline Status

| Workflow | Status | Description |
|----------|--------|-------------|
| **Test Suite** | [![Tests](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/test.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/test.yml) | Multi-Python testing (3.9, 3.11, 3.12) with 60s timeout |
| **Deploy Bootstrap** | [![Deploy](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/deploy.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/deploy.yml) | Automated Fly.io deployment with health checks; skips with a notice when `FLY_API_TOKEN` is unset |
| **Release** | [![Release](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/release.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/release.yml) | Multi-platform builds (Windows, macOS, Linux, Android, PyPI, Docker) |
| **Pillar Health** | [![Health](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/health.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/health.yml) | 15-minute uptime monitoring of the bootstrap node; a node that is down is recorded in the badge, not raised as a failure |
| **Website** | [![Website](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/pages.yml/badge.svg)](https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/pages.yml) | GitHub Pages deployment; skips with a notice when Pages is not enabled (`netlify.toml` publishes the same directory) |

### Production Pipeline Quality Improvements

Recent enhancements to the CI/CD pipeline:

- ✅ **Fixed `.gitignore`**: Restored proper ignore rules for `__pycache__/`, build artifacts, and sensitive files
- ✅ **Added `pytest-timeout`**: Prevents hanging tests with 60-second timeout per test
- ✅ **Deployment health checks**: Automatic verification after Fly.io deployment
- ✅ **Environment protection**: Deployments require production environment approval
- ✅ **Graceful secret handling**: PID secrets only updated when changed
- ✅ **Multi-version testing**: Ensures compatibility across Python 3.9, 3.11, and 3.12

---

## License

AGPLv3 — See [LICENSE](LICENSE) for full text.

---

## Connect to the Mesh

Add the bootstrap node to `~/.refinet/peers.json`:

```json
[
  {
    "hostname": "gopher.refinet.io",
    "port": 7070,
    "pid": "REPLACE_WITH_64_CHAR_HEX_PID_FROM_KEYGEN",
    "public_key": "REPLACE_WITH_64_CHAR_HEX_PUBKEY_FROM_KEYGEN",
    "pillar_name": "REFInet Bootstrap Pillar"
  }
]
```

---

Run a Pillar. Join the mesh.
