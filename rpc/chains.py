"""
REFInet Pillar — EVM Chain Configurations

Default RPC endpoints for supported chains.
All endpoints are public and don't require API keys.
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
}
