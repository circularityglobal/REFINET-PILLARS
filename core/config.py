"""
REFInet Pillar — Configuration
"""

import os
import json
from pathlib import Path


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
GOPHER_ROOT = Path(__file__).resolve().parent.parent / "gopherroot"

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
PROTOCOL_VERSION = "0.2.0"

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


def ensure_dirs():
    """Create all required directories on first run."""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
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
            # Merge Tor defaults for any missing keys
            for k, v in TOR_DEFAULTS.items():
                cfg.setdefault(k, v)
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
    with open(CONFIG_FILE, "w") as f:
        json.dump(defaults, f, indent=2)
    return defaults
