REFInet Pillar — Sovereign Mesh Node
=====================================

The Pillar is a Gopher protocol server that makes your computer a
sovereign node in the REFInet mesh network. It serves content, signs
it cryptographically, discovers peers, and replicates gopherhole
registries — all without any centralized infrastructure.

What It Does
------------

  - Serves Gopher menus and files on TCP (RFC 1436 compatible)
  - Generates an Ed25519 identity (Pillar ID) on first run
  - Signs all served content with your PID
  - Discovers peers via UDP multicast on the local network
  - Replicates gopherhole registries with verified signatures
  - Records all activity in a local SQLite ledger
  - Bridges to EVM blockchains via RPC gateway
  - Supports Tor hidden services for anonymous operation
  - Exposes a WebSocket API for the browser extension

Ports
-----

  7070  REFInet server (full features, mesh-aware)
  70    Standard Gopher server (public content only)
  7073  GopherS / TLS (encrypted Gopher)
  7074  Privacy proxy
  7075  WebSocket bridge (browser extension)

Hardware Requirements
---------------------

Any computer with Python 3.9 or later. No GPU. No special hardware.
Runs on a Raspberry Pi, a laptop, a VPS, or a mainframe.

  - CPU:     Any (single-core sufficient)
  - RAM:     64 MB minimum, 256 MB recommended
  - Disk:    50 MB for software, plus your content
  - Network: Any TCP/IP connection (LAN, Wi-Fi, Tor, VPN)

The Mesh
--------

When your Pillar starts, it announces itself on the local network via
UDP multicast. Other Pillars in range discover you automatically.
For WAN connectivity, add bootstrap peers to ~/.refinet/peers.json
or use the CLI: pillar.py peer add --host <address> --port 7070.

Every Pillar periodically fetches the gopherhole registry from its
peers and imports new entries after verifying Ed25519 signatures.
This means content registrations propagate across the entire mesh
without any central server.

License: AGPLv3
Source:  https://github.com/circularityglobal/REFINET-PILLARS
