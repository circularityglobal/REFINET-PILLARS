"""
REFInet Pillar — Menu Builder

Generates Gopher menus (gophermaps) dynamically from:
  - Static files in gopherroot/
  - Live database state (transactions, metrics, peers)
  - Pillar identity and status

Gopher item types used:
  i = informational text (not a link)
  0 = text file
  1 = directory / submenu
  7 = search query
  h = HTML link (for bridging to traditional internet)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.config import GOPHER_ROOT, PROTOCOL_VERSION
from crypto.pid import get_short_pid


# ---------------------------------------------------------------------------
# Gopher Line Formatters
# ---------------------------------------------------------------------------
def info_line(text: str) -> str:
    """Informational line (type 'i') — displayed but not clickable."""
    return f"i{text}\tfake\t(NULL)\t0\r\n"


def menu_link(display: str, selector: str, host: str, port: int) -> str:
    """Directory / submenu link (type '1')."""
    return f"1{display}\t{selector}\t{host}\t{port}\r\n"


def text_link(display: str, selector: str, host: str, port: int) -> str:
    """Text file link (type '0')."""
    return f"0{display}\t{selector}\t{host}\t{port}\r\n"


def html_link(display: str, url: str, host: str, port: int) -> str:
    """HTML link (type 'h') — bridges to traditional internet."""
    return f"h{display}\tURL:{url}\t{host}\t{port}\r\n"


def binary_link(display: str, selector: str, host: str, port: int) -> str:
    """Binary file link (type '9')."""
    return f"9{display}\t{selector}\t{host}\t{port}\r\n"


def search_link(display: str, selector: str, host: str, port: int) -> str:
    """Search query (type '7')."""
    return f"7{display}\t{selector}\t{host}\t{port}\r\n"


def separator() -> str:
    return info_line("─" * 60)


# ---------------------------------------------------------------------------
# Root Menu Generator
# ---------------------------------------------------------------------------
def build_root_menu(pid_data: dict, hostname: str, port: int,
                    tx_count_today: int = 0, peers_count: int = 0,
                    is_refinet: bool = True, refinet_port: int = 7070,
                    license_tier: str = "free",
                    onion_address: str = None) -> str:
    """
    Build the root gophermap for this Pillar.

    When is_refinet=True (port 7070): full menu with all REFInet features.
    When is_refinet=False (port 70): standard Gopher content only, with a
    note directing users to the REFInet port for full access.
    """
    short_pid = get_short_pid(pid_data)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []

    # Banner
    lines.append(info_line(""))
    if is_refinet:
        lines.append(info_line("  ╔══════════════════════════════════════════╗"))
        lines.append(info_line("  ║         R E F I n e t   P I L L A R     ║"))
        lines.append(info_line("  ║      Sovereign Node in Gopherspace      ║"))
        lines.append(info_line("  ╚══════════════════════════════════════════╝"))
    else:
        # ── Standard Gopher homepage (port 7071) ──
        # Full REFINET Headquarters landing page — ecosystem overview + downloads
        return _build_public_homepage(pid_data, hostname, port, short_pid, now,
                                      refinet_port)

    lines.append(info_line(""))
    lines.append(info_line(f"  Protocol: REFInet v{PROTOCOL_VERSION}"))
    lines.append(info_line(f"  Pillar ID: {short_pid}..."))
    lines.append(info_line(f"  Status: ONLINE | {now}"))
    lines.append(info_line(f"  Transactions today: {tx_count_today}"))
    lines.append(info_line(f"  Known peers: {peers_count}"))
    lines.append(info_line(f"  License: {license_tier.upper()}"))
    if onion_address:
        lines.append(info_line(f"  Tor: {onion_address} (active)"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  NAVIGATION"))
    lines.append(separator())
    lines.append(info_line(""))

    # Navigation links — standard Gopher content
    lines.append(menu_link("  About This Pillar", "/about", hostname, port))
    lines.append(menu_link("  DApps", "/dapps", hostname, port))
    lines.append(menu_link("  News & Updates", "/news", hostname, port))
    lines.append(menu_link("  Gopherhole Directory", "/directory", hostname, port))

    # REFInet-exclusive links — only on port 7070
    lines.append(search_link("  Search REFInet", "/search", hostname, port))
    lines.append(menu_link("  Network Status", "/network", hostname, port))
    lines.append(text_link("  Pillar Identity (PID)", "/pid", hostname, port))
    lines.append(text_link("  Transaction Log", "/transactions", hostname, port))
    lines.append(menu_link("  Authentication (SIWE)", "/auth", hostname, port))
    lines.append(menu_link("  EVM RPC Gateway", "/rpc", hostname, port))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  IDENTITY & VAULT"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(menu_link("  Identity Management", "/identity", hostname, port))
    lines.append(menu_link("  Encrypted Vault", "/vault", hostname, port))
    lines.append(menu_link("  Settings", "/settings", hostname, port))
    lines.append(menu_link("  Service Health", "/health", hostname, port))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  MESH"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(text_link("  Known Peers", "/peers", hostname, port))
    lines.append(text_link("  Ledger Status", "/ledger", hostname, port))
    lines.append(menu_link("  Sync Status", "/sync", hostname, port))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  DOWNLOADS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(menu_link("  Pillar Software Downloads", "/download", hostname, port))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  Powered by REFInet \u2014 Gopher + Blockchain + AI"))
    lines.append(info_line("  Run your own Pillar: github.com/refinet"))
    lines.append(info_line(""))

    # Gopher protocol: menu ends with a period on its own line
    lines.append(".\r\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Sub-Menu Generators
# ---------------------------------------------------------------------------
# Public Homepage (Standard Gopher — port 7071)
# ---------------------------------------------------------------------------
def _build_public_homepage(pid_data: dict, hostname: str, port: int,
                           short_pid: str, now: str,
                           refinet_port: int = 7070) -> str:
    """
    Full REFINET Headquarters landing page for the standard Gopher port.
    Explains the ecosystem, provides navigation, and links to downloads.
    """
    year = datetime.now().year
    lines = []

    # ── Header ──
    lines.append(info_line(""))
    lines.append(info_line("REFINET Headquarters"))
    lines.append(info_line("====================="))
    lines.append(info_line(""))
    lines.append(info_line("Welcome to the sovereign internet."))
    lines.append(info_line(""))
    lines.append(info_line("REFInet is a decentralized network built on the Gopher protocol \u2014"))
    lines.append(info_line("the internet's simplest, most honest content delivery system."))
    lines.append(info_line("No trackers. No ads. No intermediaries. Just content."))
    lines.append(info_line(""))
    lines.append(info_line("This is gopher.refinet.app \u2014 the reference node of the REFInet"))
    lines.append(info_line("network and the canonical home of the REFInet Browser, Pillar"))
    lines.append(info_line("software, and network infrastructure."))
    lines.append(info_line(""))

    # ── What Is REFInet ──
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("WHAT IS REFINET?"))
    lines.append(info_line(""))
    lines.append(info_line("REFInet is three things:"))
    lines.append(info_line(""))
    lines.append(info_line("  PILLARS \u2014 Servers anyone can run to join the network."))
    lines.append(info_line("             Each Pillar serves Gopher content, relays"))
    lines.append(info_line("             blockchain transactions, and signs responses"))
    lines.append(info_line("             with Ed25519 cryptography. No central authority."))
    lines.append(info_line("             No permission required to run one."))
    lines.append(info_line(""))
    lines.append(info_line("  BROWSER \u2014 A free, open-source desktop application for"))
    lines.append(info_line("             macOS, Windows, and Linux. Browse Gopherspace,"))
    lines.append(info_line("             manage a multi-chain HD wallet, send encrypted"))
    lines.append(info_line("             messages, and participate in network governance"))
    lines.append(info_line("             \u2014 all from one application, under your sole"))
    lines.append(info_line("             control."))
    lines.append(info_line(""))
    lines.append(info_line("  SITES   \u2014 Content deployed by users directly onto the"))
    lines.append(info_line("             network. Every REFInet Site has three addresses:"))
    lines.append(info_line("             a Gopherhole on the Pillar network, an HTTPS"))
    lines.append(info_line("             gateway for the open web, and a @username on"))
    lines.append(info_line("             the Universal Name Service \u2014 a blockchain-native"))
    lines.append(info_line("             identity that follows you across Pillars."))
    lines.append(info_line(""))

    # ── Navigation ──
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("WHAT YOU'LL FIND HERE"))
    lines.append(info_line(""))
    lines.append(menu_link("  REFInet Browser Downloads", "/releases", hostname, port))
    lines.append(menu_link("  Run Your Own Pillar", "/pillar-setup", hostname, port))
    lines.append(menu_link("  About This Pillar", "/about", hostname, port))
    lines.append(menu_link("  Gopherhole Directory", "/directory", hostname, port))
    lines.append(menu_link("  Decentralized Applications", "/dapps", hostname, port))
    lines.append(menu_link("  News & Updates", "/news", hostname, port))
    lines.append(menu_link("  Getting Started with REFInet", "/welcome", hostname, port))
    lines.append(info_line(""))

    # ── Philosophy ──
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("THE PHILOSOPHY"))
    lines.append(info_line(""))
    lines.append(info_line("The web optimized for engagement."))
    lines.append(info_line("Gopher optimized for content."))
    lines.append(info_line("REFInet adds identity, payments, and governance \u2014"))
    lines.append(info_line("without sacrificing the simplicity that makes Gopher"))
    lines.append(info_line("worth preserving."))
    lines.append(info_line(""))
    lines.append(info_line("Your keys. Your content. Your network."))
    lines.append(info_line(""))

    # ── Download / Run ──
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("DOWNLOAD & RUN YOUR OWN PILLAR"))
    lines.append(info_line(""))
    lines.append(menu_link("  Download REFInet Browser", "/releases", hostname, port))
    lines.append(menu_link("  Download Pillar Software", "/download", hostname, port))
    lines.append(menu_link("  Pillar Setup Documentation", "/pillar-setup", hostname, port))
    lines.append(html_link("  Source Code on GitHub", "https://github.com/refinet", hostname, port))
    lines.append(info_line(""))

    # ── Footer ──
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Protocol: REFInet v{PROTOCOL_VERSION} | Pillar ID: {short_pid}..."))
    lines.append(info_line(f"  Status: ONLINE | {now}"))
    lines.append(info_line(f"  Full REFInet features on port {refinet_port}: gopher://{hostname}:{refinet_port}/"))
    lines.append(info_line(""))
    lines.append(info_line(f"gopher.refinet.app | Port {port}"))
    lines.append(info_line(f"REFInet Contributors \u2014 AGPLv3 License \u2014 {year}"))
    lines.append(info_line(""))

    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Releases Page
# ---------------------------------------------------------------------------
def build_releases_menu(hostname: str, port: int) -> str:
    """Download page for REFInet Browser and Pillar software."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("REFINET BROWSER \u2014 DOWNLOADS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("Download the REFInet Browser for your platform:"))
    lines.append(info_line(""))
    lines.append(html_link("  macOS (.dmg)", "https://github.com/refinet/releases", hostname, port))
    lines.append(html_link("  Windows (.exe)", "https://github.com/refinet/releases", hostname, port))
    lines.append(html_link("  Linux (.AppImage)", "https://github.com/refinet/releases", hostname, port))
    lines.append(info_line(""))
    lines.append(info_line("  SYSTEM REQUIREMENTS"))
    lines.append(info_line(""))
    lines.append(info_line("    macOS 12+ (Apple Silicon & Intel)"))
    lines.append(info_line("    Windows 10+ (64-bit)"))
    lines.append(info_line("    Ubuntu 20.04+ / Debian 11+ / Fedora 36+"))
    lines.append(info_line("    512MB RAM minimum"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("REFINET PILLAR SERVER"))
    lines.append(info_line(""))
    lines.append(info_line("  Run your own sovereign node on the REFInet network."))
    lines.append(info_line(""))
    lines.append(menu_link("  Pillar Setup Guide", "/pillar-setup", hostname, port))
    lines.append(html_link("  Source Code on GitHub", "https://github.com/refinet", hostname, port))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Download Page
# ---------------------------------------------------------------------------
def build_download_menu(hostname: str, port: int) -> str:
    """Pillar software download page served via Gopher."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("REFINET PILLAR \u2014 DOWNLOAD"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Current Version: {PROTOCOL_VERSION}"))
    lines.append(info_line("  Protocol: SGIS v14 (all phases complete)"))
    lines.append(info_line("  Tests: 437 passing"))
    lines.append(info_line(""))

    lines.append(separator())
    lines.append(info_line("  DOWNLOAD FILES"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(text_link("  Install Instructions", "/download/INSTALL.txt", hostname, port))
    lines.append(text_link("  SHA-256 Checksums", "/download/CHECKSUMS.txt", hostname, port))
    lines.append(info_line(""))

    lines.append(separator())
    lines.append(info_line("  QUICK INSTALL \u2014 paste into terminal"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("  pip3 install refinet-pillar[full]"))
    lines.append(info_line("  refinet-pillar run"))
    lines.append(info_line(""))
    lines.append(info_line("  \u2014 OR \u2014"))
    lines.append(info_line(""))
    lines.append(info_line("  docker run -d -p 7070:7070 -p 7075:7075 \\"))
    lines.append(info_line("    -v ~/.refinet:/home/refinet/.refinet \\"))
    lines.append(info_line("    refinet/pillar:latest"))
    lines.append(info_line(""))

    lines.append(separator())
    lines.append(info_line("  OTHER CHANNELS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(html_link("  GitHub Repository", "https://github.com/circularityglobal/REFINET-PILLARS", hostname, port))
    lines.append(html_link("  Docker Hub", "https://hub.docker.com/r/refinet/pillar", hostname, port))
    lines.append(html_link("  PyPI Package", "https://pypi.org/project/refinet-pillar", hostname, port))
    lines.append(html_link("  Documentation", "https://docs.refinet.network", hostname, port))
    lines.append(info_line(""))

    lines.append(separator())
    lines.append(info_line("  VERIFY YOUR DOWNLOAD"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  sha256sum refinet-pillar-v{PROTOCOL_VERSION}.tar.gz"))
    lines.append(info_line("  (compare with CHECKSUMS.txt above)"))
    lines.append(info_line(""))

    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Pillar Setup Page
# ---------------------------------------------------------------------------
def build_pillar_setup_menu(hostname: str, port: int) -> str:
    """Pillar setup documentation and quick start guide."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("RUN YOUR OWN REFINET PILLAR"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("A Pillar is a sovereign node in the REFInet network."))
    lines.append(info_line("Anyone can run one. No permission required."))
    lines.append(info_line(""))
    lines.append(info_line("  QUICK START"))
    lines.append(info_line(""))
    lines.append(info_line("    1. Install Python 3.11+"))
    lines.append(info_line("    2. Clone the repository:"))
    lines.append(info_line("       git clone https://github.com/circularityglobal/REFINET-PILLARS"))
    lines.append(info_line("    3. Install dependencies:"))
    lines.append(info_line("       pip install -r requirements.txt"))
    lines.append(info_line("    4. Start your Pillar:"))
    lines.append(info_line("       python main.py"))
    lines.append(info_line(""))
    lines.append(info_line("  Your Pillar will automatically:"))
    lines.append(info_line("    \u2022 Serve Gopher content on port 7070 (REFInet) and 70 (standard)"))
    lines.append(info_line("    \u2022 Generate a unique Pillar ID (Ed25519 key pair)"))
    lines.append(info_line("    \u2022 Join the mesh via multicast discovery (224.0.70.70:7071)"))
    lines.append(info_line("    \u2022 Relay and validate blockchain transactions"))
    lines.append(info_line("    \u2022 Sign all responses cryptographically"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("  SYSTEM REQUIREMENTS"))
    lines.append(info_line(""))
    lines.append(info_line("    Python 3.11+"))
    lines.append(info_line("    256MB RAM minimum"))
    lines.append(info_line("    Open ports: 7070 (REFInet), 70 (standard Gopher)"))
    lines.append(info_line("    Optional: Tor for .onion hidden service"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("  WHAT A PILLAR DOES"))
    lines.append(info_line(""))
    lines.append(info_line("    Every Pillar on the REFInet network:"))
    lines.append(info_line(""))
    lines.append(info_line("    1. Serves Gopher content \u2014 host your own gopherhole"))
    lines.append(info_line("    2. Relays transactions \u2014 bridge between users and blockchains"))
    lines.append(info_line("    3. Signs responses \u2014 Ed25519 cryptographic proof of origin"))
    lines.append(info_line("    4. Discovers peers \u2014 automatic mesh networking via multicast"))
    lines.append(info_line("    5. Hosts DApps \u2014 decentralized application runtime"))
    lines.append(info_line("    6. Authenticates users \u2014 Sign-In With Ethereum (EIP-4361)"))
    lines.append(info_line(""))
    lines.append(info_line("    No central server controls the network. Every Pillar"))
    lines.append(info_line("    is equal. The network grows as more people run Pillars."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(html_link("  Source Code on GitHub", "https://github.com/refinet", hostname, port))
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Welcome / Getting Started Page
# ---------------------------------------------------------------------------
def build_welcome_menu(hostname: str, port: int) -> str:
    """Getting started guide for new REFInet users."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("GETTING STARTED WITH REFINET"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("Welcome! Here's how to get started with the REFInet network."))
    lines.append(info_line(""))
    lines.append(info_line("  1. BROWSE"))
    lines.append(info_line("     You're already doing it. Navigate Gopherspace using"))
    lines.append(info_line("     the REFInet Browser or any standard Gopher client."))
    lines.append(info_line("     The entire Gopher protocol (RFC 1436) is supported."))
    lines.append(info_line(""))
    lines.append(info_line("  2. WALLET"))
    lines.append(info_line("     Create a multi-chain HD wallet from the Browser's"))
    lines.append(info_line("     sidebar. Supports Ethereum, Bitcoin, Solana, Stellar,"))
    lines.append(info_line("     XRP, and Hedera. Your keys never leave your device."))
    lines.append(info_line(""))
    lines.append(info_line("  3. CONNECT"))
    lines.append(info_line("     Sign in with your wallet (SIWE \u2014 EIP-4361) to"))
    lines.append(info_line("     authenticate with Pillars. Send encrypted messages"))
    lines.append(info_line("     via XMTP. No passwords, no accounts, no email."))
    lines.append(info_line(""))
    lines.append(info_line("  4. PUBLISH"))
    lines.append(info_line("     Build your own gopherhole using the built-in Site"))
    lines.append(info_line("     Builder. Create pages, start a local Gopher server,"))
    lines.append(info_line("     and publish to the network with one click."))
    lines.append(info_line(""))
    lines.append(info_line("  5. GOVERN"))
    lines.append(info_line("     Participate in DAO governance: create and vote on"))
    lines.append(info_line("     proposals, verify documents on-chain, and shape"))
    lines.append(info_line("     the future of the network."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(menu_link("  Download the Browser", "/releases", hostname, port))
    lines.append(menu_link("  Run Your Own Pillar", "/pillar-setup", hostname, port))
    lines.append(menu_link("  About This Pillar", "/about", hostname, port))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
def build_about_menu(pid_data: dict, hostname: str, port: int,
                     onion_address: str = None) -> str:
    """About page for this Pillar."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  ABOUT THIS REFINET PILLAR"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Pillar ID: {pid_data['pid']}"))
    lines.append(info_line(f"  Public Key: {pid_data['public_key'][:32]}..."))
    lines.append(info_line(f"  Created: {datetime.fromtimestamp(pid_data['created_at'])}"))
    lines.append(info_line(f"  Protocol: {pid_data.get('protocol', 'REFInet-v0.1')}"))
    if onion_address:
        lines.append(info_line(f"  Tor Address: {onion_address}"))
        lines.append(info_line("  Tor Status: active"))
    lines.append(info_line(""))
    lines.append(info_line("  This node is part of the REFInet mesh — a sovereign,"))
    lines.append(info_line("  Gopher-based network where every computer can become"))
    lines.append(info_line("  a Pillar serving content, tracking transactions, and"))
    lines.append(info_line("  running decentralized applications."))
    lines.append(info_line(""))
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


def build_network_menu(peers: list[dict], hostname: str, port: int,
                       replication_rejections_today: int = 0) -> str:
    """Network status showing known peers and replication health."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  NETWORK STATUS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Known peers: {len(peers)}"))
    if replication_rejections_today > 0:
        lines.append(info_line(f"  Replication rejections today: {replication_rejections_today}"))
    lines.append(info_line(""))

    if peers:
        for p in peers[:20]:  # Show up to 20 peers
            pid_short = p.get("pid", "unknown")[:16]
            host = p.get("hostname", "?")
            pport = p.get("port", 7070)
            name = p.get("pillar_name", "Unknown Pillar")
            status = p.get("status", "unknown")
            indicator = {"online": "[OK]", "degraded": "[!!]", "offline": "[XX]"}.get(status, "[??]")
            latency = p.get("latency_ms")
            lat_str = f" {latency}ms" if latency is not None else ""
            lines.append(info_line(f"  {indicator} {name} [{pid_short}...] @ {host}:{pport}{lat_str}"))
    else:
        lines.append(info_line("  No peers discovered yet."))
        lines.append(info_line("  Other Pillars on your network will appear here."))

    lines.append(info_line(""))
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


def build_dapps_menu(hostname: str, port: int, dapps: list = None) -> str:
    """DApps directory — lists .dapp definitions from gopherroot/dapps/."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  DECENTRALIZED APPLICATIONS"))
    lines.append(separator())
    lines.append(info_line(""))

    if dapps:
        lines.append(info_line(f"  {len(dapps)} DApp(s) available:"))
        lines.append(info_line(""))
        for dapp in dapps:
            lines.append(
                menu_link(
                    f"  {dapp.name} (v{dapp.version})",
                    f"/dapps/{dapp.slug}.dapp",
                    hostname,
                    port,
                )
            )
            if dapp.description:
                lines.append(info_line(f"    {dapp.description}"))
            lines.append(info_line(f"    Chain: {dapp.chain_id} | Contract: {dapp.contract[:16]}..."))
            lines.append(info_line(""))
    else:
        lines.append(info_line("  No DApp definitions found."))
        lines.append(info_line("  Place .dapp files in gopherroot/dapps/ to register DApps."))
        lines.append(info_line(""))

    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


def build_pid_document(pid_data: dict, pillar_name: str = "REFInet Pillar",
                       onion_address: str = None) -> str:
    """Machine-parseable PID document — one field per line, colon-delimited.

    The Browser parses this by splitting each line on the first ':'.
    Do NOT add spaces around colons or change field names without
    coordinating with the Browser's pillar-client.js.
    """
    doc = (
        f"pid:{pid_data['pid']}\n"
        f"public_key:{pid_data['public_key']}\n"
        f"created_at:{int(pid_data['created_at'])}\n"
        f"protocol:{pid_data.get('protocol', 'REFInet-v0.1')}\n"
        f"pillar_name:{pillar_name}\n"
    )
    if onion_address:
        doc += (
            f"onion_address:{onion_address}\n"
            f"tor_port_7070:{onion_address}:7070\n"
            f"tor_port_70:{onion_address}:70\n"
        )
    return doc


def build_transactions_document(transactions: list[dict]) -> str:
    """Plain text transaction log with REFInet accounting dates."""
    from db.live_db import format_accounting_date
    lines = [
        "REFInet Transaction Log",
        "=======================",
        "",
    ]
    if not transactions:
        lines.append("No transactions recorded yet.")
    else:
        for tx in transactions:
            created = tx.get("created_at", "?")
            # Format with accounting date when possible
            try:
                dt = datetime.fromisoformat(str(created))
                display_date = format_accounting_date(dt)
            except (ValueError, TypeError):
                display_date = str(created)
            lines.append(
                f"[{display_date}] "
                f"{tx.get('tx_id', '?')} | "
                f"{tx.get('dapp_id', '?')} | "
                f"{tx.get('token_type', '?')} {tx.get('amount', 0)} | "
                f"selector: {tx.get('selector', '-')}"
            )
    lines.append("")
    return "\n".join(lines)


def build_peers_document(peers: list[dict], hostname: str = "localhost",
                         port: int = 7070) -> str:
    """Gopher Type 1 menu listing known peers with navigable links.

    Each peer is rendered as a menu_link (allowing direct navigation)
    plus an info_line showing status, latency, and short PID.
    """
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  REFINET KNOWN PEERS"))
    lines.append(separator())
    lines.append(info_line(""))

    if not peers:
        lines.append(info_line("  No peers discovered yet."))
        lines.append(info_line("  Other Pillars on your network will appear here."))
    else:
        for p in peers:
            peer_name = p.get("pillar_name", "Unknown Pillar")
            peer_host = p.get("hostname", "?")
            peer_port = p.get("port", 7070)
            status = p.get("status", "unknown")
            latency = p.get("latency_ms")
            lat_str = f"{latency}ms" if latency is not None else "—"
            short_pid = p.get("pid", "?")[:16]
            peer_onion = p.get("onion_address")
            has_tor = "yes" if peer_onion else "no"

            lines.append(menu_link(
                f"  {peer_name} @ {peer_host}:{peer_port}",
                "/", peer_host, peer_port,
            ))
            if peer_onion:
                lines.append(menu_link(
                    f"    .onion: {peer_onion[:20]}...  (Tor)",
                    "/", peer_onion, 7070,
                ))
            lines.append(info_line(
                f"    Status: {status} | Latency: {lat_str} | "
                f"PID: {short_pid}... | Tor: {has_tor}"
            ))
            lines.append(info_line(""))

    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


def build_ledger_document(pid: str, tx_count: int) -> str:
    """Plain text ledger status with accounting date."""
    from db.live_db import get_accounting_date, format_accounting_date
    day, month, year = get_accounting_date()
    return (
        f"REFInet Ledger Status\n"
        f"=====================\n\n"
        f"Pillar: {pid[:16]}...\n"
        f"Accounting Period: {format_accounting_date()}\n"
        f"Transactions Today: {tx_count}\n\n"
        f"Live DB: 13 months × 28 accounting days\n"
        f"Archive DB: Yearly compressed records\n"
    )


# ---------------------------------------------------------------------------
# Gopherhole Directory
# ---------------------------------------------------------------------------
def build_directory_menu(holes: list[dict], hostname: str, port: int) -> str:
    """Gophermap listing all known gopherholes on the mesh."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  REFINET GOPHERHOLE DIRECTORY"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  {len(holes)} registered gopherhole(s) on this mesh"))
    lines.append(info_line(""))

    for hole in holes:
        pid_short = hole.get("pid", "unknown")[:8]
        lines.append(
            menu_link(
                f"  {hole['name']} [{pid_short}...]",
                hole["selector"],
                hostname,
                port,
            )
        )
        if hole.get("description"):
            lines.append(info_line(f"    {hole['description']}"))
        lines.append(
            info_line(
                f"    Registered: {hole['registered_at']} | Source: {hole['source']}"
            )
        )
        lines.append(info_line(""))

    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# SIWE Authentication Menu
# ---------------------------------------------------------------------------
def build_auth_menu(hostname: str, port: int) -> str:
    """SIWE authentication instructions and challenge request."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  REFINET SIWE AUTHENTICATION"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line("  Sign-In With Ethereum (EIP-4361)"))
    lines.append(info_line("  Authenticate with your wallet — no password required"))
    lines.append(info_line(""))
    lines.append(search_link("  Step 1 → Request challenge (enter 0x address)", "/auth/challenge", hostname, port))
    lines.append(search_link("  Step 3 → Submit signature (address|sig|message)", "/auth/verify", hostname, port))
    lines.append(info_line(""))
    lines.append(info_line("  How to authenticate:"))
    lines.append(info_line("  Step 1. Enter your EVM address (0x...) to get a challenge"))
    lines.append(info_line("  Step 2. Sign the challenge message with your wallet"))
    lines.append(info_line("  Step 3. Submit: address|signature|message_text to verify"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# RPC Gateway Menu
# ---------------------------------------------------------------------------
def build_rpc_menu(chain_statuses: dict, hostname: str, port: int,
                   available: bool = True) -> str:
    """EVM RPC gateway status showing configured chains and connectivity."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  REFINET EVM RPC GATEWAY"))
    lines.append(separator())
    lines.append(info_line(""))

    if not available:
        lines.append(info_line("  RPC gateway is not available."))
        lines.append(info_line("  Install with: pip install web3"))
        lines.append(info_line(""))
    elif not chain_statuses:
        lines.append(info_line("  No chains configured."))
        lines.append(info_line(""))
    else:
        lines.append(info_line("  Configured chains:"))
        lines.append(info_line(""))
        for chain_id, status in chain_statuses.items():
            latency = status.get("latency")
            conn = f"{latency}ms" if latency else "unreachable"
            lines.append(
                info_line(
                    f"    [{chain_id}] {status['name']} ({status['symbol']}) — {conn}"
                )
            )
        lines.append(info_line(""))
        lines.append(info_line("  Available operations:"))
        lines.append(info_line(""))
        lines.append(search_link("  Query balance (chain_id|0xAddress)", "/rpc/balance", hostname, port))
        lines.append(search_link("  Query ERC-20 balance (chain_id|token|wallet)", "/rpc/token", hostname, port))
        lines.append(search_link("  Estimate gas (chain_id|to|value_wei)", "/rpc/gas", hostname, port))
        lines.append(search_link("  Broadcast tx (session_id|chain_id|signed_tx_hex)", "/rpc/broadcast", hostname, port))
        lines.append(info_line(""))

    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Identity Management Menu (PRD: /identity)
# ---------------------------------------------------------------------------
def build_identity_menu(pid_data: dict, profiles: list[dict],
                        hostname: str, port: int) -> str:
    """Identity management — view profiles, current PID, switch profiles."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  IDENTITY MANAGEMENT"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Active PID: {pid_data['pid']}"))
    lines.append(info_line(f"  Public Key: {pid_data['public_key'][:32]}..."))
    lines.append(info_line(f"  Key Store: {pid_data.get('key_store', 'software')}"))

    priv = pid_data.get("private_key")
    encrypted = isinstance(priv, dict)
    lines.append(info_line(f"  Encrypted: {'yes' if encrypted else 'no'}"))
    lines.append(info_line(""))

    if profiles:
        lines.append(separator())
        lines.append(info_line("  PROFILES"))
        lines.append(info_line(""))
        for p in profiles:
            marker = " (active)" if p.get("active") else ""
            enc = " [encrypted]" if p.get("encrypted") else ""
            pid_short = p.get("pid", "?")[:16]
            lines.append(info_line(f"  {p['name']}{marker}{enc} — PID: {pid_short}..."))
        lines.append(info_line(""))
        lines.append(info_line("  Manage profiles: pillar.py profile {create|list|switch|delete}"))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Vault Menu (PRD: /vault)
# ---------------------------------------------------------------------------
def build_vault_menu(items: list[dict], stats: dict,
                     hostname: str, port: int) -> str:
    """Encrypted vault — list stored items, show stats."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  ENCRYPTED VAULT"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Items: {stats.get('item_count', 0)}"))
    lines.append(info_line(f"  Total size: {stats.get('total_bytes', 0)} bytes"))
    lines.append(info_line(""))

    if items:
        for item in items:
            size = item.get("size_bytes", 0)
            created = item.get("created_at", "?")
            lines.append(info_line(f"  [{item.get('mime_type', '?')}] {item['name']} "
                                   f"({size} bytes) — {created}"))
        lines.append(info_line(""))
    else:
        lines.append(info_line("  No items stored."))
        lines.append(info_line("  Use the vault API to store encrypted files."))
        lines.append(info_line(""))

    lines.append(info_line("  Vault operations require SIWE authentication."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Settings Menu (PRD: /settings)
# ---------------------------------------------------------------------------
def build_settings_menu(config: dict, hostname: str, port: int) -> str:
    """Server settings — display configurable parameters."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  PILLAR SETTINGS"))
    lines.append(separator())
    lines.append(info_line(""))

    lines.append(info_line("  SERVER"))
    lines.append(info_line(f"    Hostname: {config.get('hostname', 'localhost')}"))
    lines.append(info_line(f"    Port: {config.get('port', 7070)}"))
    lines.append(info_line(f"    Pillar Name: {config.get('pillar_name', 'REFInet Pillar')}"))
    lines.append(info_line(""))

    lines.append(info_line("  SECURITY"))
    lines.append(info_line(f"    TLS: {'enabled' if config.get('tls_enabled') else 'disabled'}"))
    lines.append(info_line(f"    Tor: {'enabled' if config.get('tor_enabled') else 'disabled'}"))
    lines.append(info_line(f"    VPN: {'enabled' if config.get('vpn_enabled') else 'disabled'}"))
    lines.append(info_line(f"    Proxy: {'enabled' if config.get('proxy_enabled') else 'disabled'}"))
    lines.append(info_line(""))

    lines.append(info_line("  NETWORK"))
    lines.append(info_line(f"    Multicast Group: 224.0.70.70:7071"))
    lines.append(info_line(f"    Discovery Interval: 30s"))
    lines.append(info_line(f"    Replication Interval: 5m"))
    lines.append(info_line(""))

    lines.append(info_line("  Edit settings: ~/.refinet/config.json"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Sync Status Menu (PRD: /sync)
# ---------------------------------------------------------------------------
def build_sync_menu(peers: list[dict], chain_length: int,
                    hostname: str, port: int) -> str:
    """P2P synchronization status — replication health, peer sync info."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line("  SYNCHRONIZATION STATUS"))
    lines.append(separator())
    lines.append(info_line(""))
    lines.append(info_line(f"  Audit chain length: {chain_length} entries"))
    lines.append(info_line(""))

    online_peers = [p for p in peers if p.get("status") == "online"]
    lines.append(info_line(f"  Peers syncing: {len(online_peers)} / {len(peers)}"))
    lines.append(info_line(""))

    if online_peers:
        lines.append(info_line("  ACTIVE SYNC PEERS"))
        lines.append(info_line(""))
        for p in online_peers[:10]:
            name = p.get("pillar_name", "Unknown")
            host = p.get("hostname", "?")
            pport = p.get("port", 7070)
            latency = p.get("latency_ms")
            lat = f"{latency}ms" if latency is not None else "—"
            lines.append(info_line(f"    {name} @ {host}:{pport} ({lat})"))
        lines.append(info_line(""))

    lines.append(info_line("  Sync protocol: Gopherhole registry replication"))
    lines.append(info_line("  Interval: every 5 minutes"))
    lines.append(info_line("  Encryption: Ed25519 signature verification"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("  ← Back to Root", "/", hostname, port))
    lines.append(info_line(""))
    lines.append(".\r\n")
    return "".join(lines)
