"""
REFInet Pillar — EVM Chain Configurations

Default RPC endpoints for supported chains. All endpoints are public,
require no API keys, and are the networks' own public RPCs wherever the
network publishes one.

Operators can add chains without waiting for a release by writing
``~/.refinet/chains.json``:

    {"10": {"name": "Optimism", "rpc": "https://mainnet.optimism.io",
            "symbol": "ETH", "explorer": "https://optimistic.etherscan.io",
            "aliases": ["optimism"]}}

``rpc/config.py`` merges that file into the table below at load time.
"""

# These name→ID mappings are part of the REFInet wire protocol.
# The Browser uses these lowercase string names when querying Pillar RPC routes.
# Do NOT rename without coordinating with Browser's evm-provider.js.
CHAIN_NAME_TO_ID = {
    "ethereum": 1,
    "polygon": 137,
    "arbitrum": 42161,
    "base": 8453,
    "sepolia": 11155111,
    # Added in 0.5.0 so a Pillar can re-read a settlement on the networks
    # TradeSphere settles on (F17). Additive: existing names are unchanged.
    "avalanche": 43114,
    "fuji": 43113,
    "base-sepolia": 84532,
    "xdc": 50,
    "apothem": 51,
}

CHAIN_ID_TO_NAME = {v: k for k, v in CHAIN_NAME_TO_ID.items()}


DEFAULT_CHAINS = {
    1: {
        "name": "Ethereum Mainnet",
        "rpc": "https://eth.llamarpc.com",
        "symbol": "ETH",
        "explorer": "https://etherscan.io",
    },
    137: {
        "name": "Polygon",
        "rpc": "https://polygon-rpc.com",
        "symbol": "MATIC",
        "explorer": "https://polygonscan.com",
    },
    42161: {
        "name": "Arbitrum One",
        "rpc": "https://arb1.arbitrum.io/rpc",
        "symbol": "ETH",
        "explorer": "https://arbiscan.io",
    },
    8453: {
        "name": "Base",
        "rpc": "https://mainnet.base.org",
        "symbol": "ETH",
        "explorer": "https://basescan.org",
    },
    11155111: {
        "name": "Sepolia Testnet",
        "rpc": "https://rpc.sepolia.org",
        "symbol": "ETH",
        "explorer": "https://sepolia.etherscan.io",
    },
    43114: {
        "name": "Avalanche C-Chain",
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "symbol": "AVAX",
        "explorer": "https://snowtrace.io",
    },
    43113: {
        "name": "Avalanche Fuji Testnet",
        "rpc": "https://api.avax-test.network/ext/bc/C/rpc",
        "symbol": "AVAX",
        "explorer": "https://testnet.snowtrace.io",
    },
    84532: {
        "name": "Base Sepolia Testnet",
        "rpc": "https://sepolia.base.org",
        "symbol": "ETH",
        "explorer": "https://sepolia.basescan.org",
    },
    50: {
        "name": "XDC Network",
        "rpc": "https://rpc.xinfin.network",
        "symbol": "XDC",
        "explorer": "https://xdcscan.io",
    },
    51: {
        "name": "XDC Apothem Testnet",
        "rpc": "https://rpc.apothem.network",
        "symbol": "TXDC",
        "explorer": "https://apothem.xdcscan.io",
    },
}


def supported_chain_names() -> str:
    """Comma-separated chain names, for error messages."""
    return ", ".join(sorted(CHAIN_NAME_TO_ID))


def register_chain(chain_id: int, chain: dict, aliases=None) -> None:
    """Add or override a chain at runtime (used by rpc/config.py)."""
    chain_id = int(chain_id)
    DEFAULT_CHAINS[chain_id] = chain
    for alias in (aliases or []):
        CHAIN_NAME_TO_ID[str(alias).lower()] = chain_id
    CHAIN_ID_TO_NAME[chain_id] = chain.get("name", str(chain_id))
