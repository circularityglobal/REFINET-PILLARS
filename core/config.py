"""
REFInet Pillar — Configuration
"""

import os
import sys
import json
from pathlib import Path


def _base_dir() -> Path:
    """Return the project root, handling PyInstaller frozen bundles."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
HOME_DIR = Path.home() / ".refinet"
DB_DIR = HOME_DIR / "db"
PID_FILE = HOME_DIR / "pid.json"
PEERS_FILE = HOME_DIR / "peers.json"
CONFIG_FILE = HOME_DIR / "config.json"
PROFILES_DIR = HOME_DIR / "profiles"
ACTIVE_PROFILE_FILE = HOME_DIR / "active_profile"
TLS_DIR = HOME_DIR / "tls"
VPN_DIR = HOME_DIR / "vpn"
VAULT_DIR = HOME_DIR / "vault"
IPC_SOCKET = HOME_DIR / "pillar.sock"
PID_LOCKFILE = HOME_DIR / "pillar.pid"

# ---------------------------------------------------------------------------
# Encryption / KDF (Argon2id)
# ---------------------------------------------------------------------------
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536  # 64 MB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32  # AES-256 key length

# ---------------------------------------------------------------------------
# Gopher Server
# ---------------------------------------------------------------------------
GOPHER_HOST = "0.0.0.0"
GOPHER_PORT = 7070  # Default REFInet port (classic Gopher = 70)
GOPHER_ROOT = _base_dir() / "gopherroot"

# ---------------------------------------------------------------------------
# REFInet Accounting Calendar
# 13 months × 28 days = 364 days + 1 accounting balance day
# ---------------------------------------------------------------------------
ACCOUNTING_DAYS_PER_MONTH = 28
ACCOUNTING_MONTHS_PER_YEAR = 13
LIVE_DB_RETENTION_MONTHS = 13  # Keep 13 months of live data

# ---------------------------------------------------------------------------
# Mesh / Discovery
# ---------------------------------------------------------------------------
MULTICAST_GROUP = "224.0.70.70"
MULTICAST_PORT = 7071
DISCOVERY_INTERVAL_SEC = 30

# ---------------------------------------------------------------------------
# Protocol Version
# ---------------------------------------------------------------------------
PROTOCOL_NAME = "REFInet"
from core.version import __version__ as PROTOCOL_VERSION  # noqa: E402

# ---------------------------------------------------------------------------
# Tor Hidden Service
# ---------------------------------------------------------------------------
TOR_DATA_DIR = HOME_DIR / "tor_data"
TOR_DEFAULTS = {
    "tor_enabled": False,
    "tor_expose_port_70": True,
    "tor_socks_port": 9050,
    "tor_control_port": 9051,
}

# ---------------------------------------------------------------------------
# GopherS (TLS)
# ---------------------------------------------------------------------------
GOPHERS_PORT = 7073

# ---------------------------------------------------------------------------
# Privacy Proxy
# ---------------------------------------------------------------------------
PROXY_PORT = 7074

# ---------------------------------------------------------------------------
# WebSocket Bridge
# ---------------------------------------------------------------------------
WEBSOCKET_PORT = 7075
WEBSOCKET_ALLOWED_ORIGINS = [
    "chrome-extension://",     # Chrome/Chromium browser extensions
    "moz-extension://",        # Firefox browser extensions
    "http://localhost",        # Local development
    "http://127.0.0.1",       # Local development
]

# The bridge mints sessions and signs responses, so it is an authority, and
# an authority's front door should list who may knock. These two settings
# tighten it; both default to the historical behaviour so an existing
# install (where an unpacked extension has a random id) keeps working.
#
#   websocket_extension_ids: ["abcdef..."]  — only these extensions, plus loopback
#   websocket_require_origin: true          — refuse clients that send no Origin
WEBSOCKET_DEFAULTS = {
    "websocket_extension_ids": [],
    "websocket_require_origin": False,
}


def ensure_dirs():
    """Create all required directories on first run.

    HOME_DIR holds the Pillar's private key, so it is owner-only (0700).
    """
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(HOME_DIR, 0o700)
    except OSError:
        pass  # Read-only mounts etc. — never block startup on a chmod
    DB_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load or create default config."""
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            # Merge defaults for any missing keys
            for k, v in TOR_DEFAULTS.items():
                cfg.setdefault(k, v)
            for k, v in WEBSOCKET_DEFAULTS.items():
                cfg.setdefault(k, v)
            cfg.setdefault("discovery_require_signed", False)
            return cfg
        except (json.JSONDecodeError, OSError):
            pass  # Fall through to recreate defaults
    defaults = {
        "hostname": "localhost",
        "port": GOPHER_PORT,
        "pillar_name": "My REFInet Pillar",
        "description": "A sovereign node in Gopherspace",
        "protocol_version": PROTOCOL_VERSION,
    }
    defaults.update(TOR_DEFAULTS)
    defaults.update(WEBSOCKET_DEFAULTS)
    defaults["discovery_require_signed"] = False
    with open(CONFIG_FILE, "w") as f:
        json.dump(defaults, f, indent=2)
    return defaults
