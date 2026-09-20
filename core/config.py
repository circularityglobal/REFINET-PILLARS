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
    # Bind address. Loopback unless an operator puts a TLS proxy in front.
    "websocket_host": "127.0.0.1",
    # Exact web origins (https://app.example.com) admitted beside the
    # extension/localhost defaults — for an app paired with this Pillar.
    "websocket_allowed_origins": [],
}

# ---------------------------------------------------------------------------
# Public deployment (0.6.0) — a Pillar serving a live domain
#
# All off by default: a Pillar that sets none of these behaves exactly as
# 0.5.0 did.
# ---------------------------------------------------------------------------
HTTP_GATEWAY_PORT = 7080
PUBLIC_DEFAULTS = {
    # The domain this Pillar answers on (pillar.example.com). It is what the
    # staking contract lists as the Pillar's endpoint, and where
    # /.well-known/refinet.json must be served.
    "public_domain": "",
    # Other domains (an app's apex, say) that serve this Pillar's
    # /.well-known/refinet.json and so claim it as theirs.
    "linked_domains": [],
    # HTTP gateway: signed Gopher answers over plain HTTP, for browsers,
    # serverless functions and reverse proxies.
    "http_gateway_enabled": False,
    "http_gateway_host": "127.0.0.1",
    "http_gateway_port": HTTP_GATEWAY_PORT,
    "http_gateway_cors_origins": [],
    # Honour X-Forwarded-For. Only behind a proxy you run.
    "http_gateway_trust_proxy": False,
}

# ---------------------------------------------------------------------------
# Staking (0.6.0) — PillarStaking on XDC
# ---------------------------------------------------------------------------
REFI_TOKEN_XDC = "0x2D010d707da973E194e41D7eA52617f8F969BD23"
STAKING_DEFAULTS = {
    "staking_chain_id": 50,
    # PillarStaking addresses. Empty = staking features off. Several may be
    # listed: a Pillar staked in any of them counts, so a successor contract
    # can be introduced without stranding anyone.
    "staking_contracts": [],
    # RPC URL override; otherwise the chain table's endpoint is used.
    "staking_rpc": "",
    # Only admit peers (replicate from them) that are active on-chain.
    "mesh_require_stake": False,
    # Find peers through the contract's directory (needs staking_contracts).
    "chain_discovery_enabled": True,
}

# REFINET_* environment variables override config.json at load time without
# being written to it — how containers and VPS installs are configured.
_ENV_OVERRIDES = {
    "REFINET_PUBLIC_DOMAIN": ("public_domain", "str"),
    "REFINET_LINKED_DOMAINS": ("linked_domains", "list"),
    "REFINET_HTTP_GATEWAY": ("http_gateway_enabled", "bool"),
    "REFINET_HTTP_GATEWAY_HOST": ("http_gateway_host", "str"),
    "REFINET_HTTP_GATEWAY_PORT": ("http_gateway_port", "int"),
    "REFINET_HTTP_TRUST_PROXY": ("http_gateway_trust_proxy", "bool"),
    "REFINET_CORS_ORIGINS": ("http_gateway_cors_origins", "list"),
    "REFINET_WEBSOCKET_HOST": ("websocket_host", "str"),
    "REFINET_WEBSOCKET_ORIGINS": ("websocket_allowed_origins", "list"),
    "REFINET_STAKING_CHAIN_ID": ("staking_chain_id", "int"),
    "REFINET_STAKING_CONTRACTS": ("staking_contracts", "list"),
    "REFINET_STAKING_RPC": ("staking_rpc", "str"),
    "REFINET_MESH_REQUIRE_STAKE": ("mesh_require_stake", "bool"),
    "REFINET_CHAIN_DISCOVERY": ("chain_discovery_enabled", "bool"),
    "REFINET_PILLAR_NAME": ("pillar_name", "str"),
}


def apply_env_overrides(cfg: dict, environ=None) -> dict:
    """Overlay REFINET_* environment variables onto *cfg* (in place)."""
    environ = os.environ if environ is None else environ
    for var, (key, kind) in _ENV_OVERRIDES.items():
        raw = environ.get(var)
        if raw is None:
            continue
        raw = raw.strip()
        if kind == "bool":
            cfg[key] = raw.lower() in ("1", "true", "yes", "on")
        elif kind == "int":
            try:
                cfg[key] = int(raw)
            except ValueError:
                continue
        elif kind == "list":
            cfg[key] = [v.strip() for v in raw.split(",") if v.strip()]
        else:
            cfg[key] = raw
    return cfg


def _merge_defaults(cfg: dict) -> dict:
    for defaults in (TOR_DEFAULTS, WEBSOCKET_DEFAULTS, PUBLIC_DEFAULTS, STAKING_DEFAULTS):
        for k, v in defaults.items():
            cfg.setdefault(k, list(v) if isinstance(v, list) else v)
    cfg.setdefault("discovery_require_signed", False)
    return cfg


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
            return apply_env_overrides(_merge_defaults(cfg))
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
    # Public/staking keys are merged in memory, not written: an operator
    # opts in by adding them to config.json or setting REFINET_* variables.
    return apply_env_overrides(_merge_defaults(dict(defaults)))
