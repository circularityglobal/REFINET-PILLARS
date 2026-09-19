"""
REFInet Pillar — RPC Endpoint Configuration

Manages user-configured RPC endpoints (overrides for defaults).
Stored in ~/.refinet/rpc_config.json.
"""

import json
from pathlib import Path
from core.config import HOME_DIR, ensure_dirs
from rpc.chains import DEFAULT_CHAINS, register_chain

RPC_CONFIG_PATH = HOME_DIR / "rpc_config.json"
CHAINS_CONFIG_PATH = HOME_DIR / "chains.json"


def load_custom_chains() -> dict:
    """Merge operator-defined chains from ~/.refinet/chains.json.

    Lets an operator add a network without waiting for a release. Returns
    the chains that were registered.
    """
    ensure_dirs()
    if not CHAINS_CONFIG_PATH.exists():
        return {}
    try:
        with open(CHAINS_CONFIG_PATH) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    added = {}
    for chain_id_str, chain in (raw or {}).items():
        try:
            chain_id = int(chain_id_str)
        except (TypeError, ValueError):
            continue
        if not isinstance(chain, dict) or not chain.get("rpc"):
            continue
        entry = {
            "name": chain.get("name", f"Chain {chain_id}"),
            "rpc": chain["rpc"],
            "symbol": chain.get("symbol", ""),
            "explorer": chain.get("explorer", ""),
        }
        register_chain(chain_id, entry, aliases=chain.get("aliases"))
        added[chain_id] = entry
    return added


def load_rpc_config() -> dict:
    """
    Load user-configured RPC endpoints.
    Returns dict of chain_id -> list of endpoint URLs.
    Falls back to DEFAULT_CHAINS if no user config exists.
    """
    ensure_dirs()
    config = {}

    # Operator-defined chains first, so their endpoints are in the table
    load_custom_chains()

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
