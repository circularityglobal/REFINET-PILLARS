"""
REFInet Pillar — RPC Endpoint Configuration

Manages user-configured RPC endpoints (overrides for defaults).
Stored in ~/.refinet/rpc_config.json.
"""

import json
from pathlib import Path
from core.config import HOME_DIR, ensure_dirs
from rpc.chains import DEFAULT_CHAINS

RPC_CONFIG_PATH = HOME_DIR / "rpc_config.json"


def load_rpc_config() -> dict:
    """
    Load user-configured RPC endpoints.
    Returns dict of chain_id -> list of endpoint URLs.
    Falls back to DEFAULT_CHAINS if no user config exists.
    """
    ensure_dirs()
    config = {}

    # Start with defaults
    for chain_id, chain in DEFAULT_CHAINS.items():
        config[chain_id] = [chain["rpc"]]

    # Override with user config if it exists
    if RPC_CONFIG_PATH.exists():
        try:
            with open(RPC_CONFIG_PATH) as f:
                user_config = json.load(f)
            for chain_id_str, endpoints in user_config.items():
                chain_id = int(chain_id_str)
                if isinstance(endpoints, list):
                    config[chain_id] = endpoints
                elif isinstance(endpoints, str):
                    config[chain_id] = [endpoints]
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    return config


def save_rpc_config(config: dict):
    """Save user RPC endpoint overrides."""
    ensure_dirs()
    # Convert int keys to strings for JSON
    serializable = {str(k): v for k, v in config.items()}
    with open(RPC_CONFIG_PATH, "w") as f:
        json.dump(serializable, f, indent=2)
