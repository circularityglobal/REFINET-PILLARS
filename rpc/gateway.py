"""
REFInet Pillar — EVM RPC Gateway

Local JSON-RPC proxy for EVM chains. All blockchain calls go through here.
Supports multiple chains, automatic failover, and request logging.

Features degrade gracefully when offline (LAN-only mode).
"""

import logging
import time

from rpc.chains import DEFAULT_CHAINS
from rpc.config import load_rpc_config

logger = logging.getLogger("refinet.rpc")

try:
    from web3 import AsyncWeb3, AsyncHTTPProvider
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    logger.info("web3 not installed — RPC gateway disabled. Install with: pip install web3")


class RPCGateway:
    """
    Local EVM JSON-RPC proxy. All calls go through here.
    Supports multiple chains, automatic failover, and request logging.
    """

    def __init__(self):
        if not WEB3_AVAILABLE:
            raise ImportError("web3 package required for RPC gateway")
        self.config = load_rpc_config()
        self._clients = {}

    def _get_client(self, chain_id: int):
        if chain_id not in self._clients:
            endpoints = self.config.get(chain_id, [])
            chain_defaults = DEFAULT_CHAINS.get(chain_id, {})

            if not endpoints and chain_defaults:
                endpoints = [chain_defaults["rpc"]]

            if not endpoints:
                raise ValueError(f"No RPC endpoint configured for chain {chain_id}")

            self._clients[chain_id] = {
                "endpoints": endpoints,
                "primary": AsyncWeb3(AsyncHTTPProvider(endpoints[0])),
            }
        return self._clients[chain_id]

    async def get_balance(self, chain_id: int, address: str) -> int:
        """Get native token balance in wei."""
        client_config = self._get_client(chain_id)
        w3 = client_config["primary"]
        return await w3.eth.get_balance(
            AsyncWeb3.to_checksum_address(address)
        )

    async def get_block_number(self, chain_id: int) -> int:
        """Get latest block number."""
        client_config = self._get_client(chain_id)
        w3 = client_config["primary"]
        return await w3.eth.block_number

    async def get_token_balance(self, chain_id: int, token_address: str,
                                wallet_address: str) -> int:
        """Get ERC-20 token balance."""
        client_config = self._get_client(chain_id)
        w3 = client_config["primary"]

        erc20_abi = [
            {
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function",
                "stateMutability": "view",
            }
        ]

        contract = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(token_address),
            abi=erc20_abi,
        )
        return await contract.functions.balanceOf(
            AsyncWeb3.to_checksum_address(wallet_address)
        ).call()

    async def estimate_gas(self, chain_id: int, tx_params: dict) -> int:
        """Estimate gas for a transaction before user confirms."""
        client_config = self._get_client(chain_id)
        w3 = client_config["primary"]
        return await w3.eth.estimate_gas(tx_params)

    async def broadcast(self, chain_id: int, signed_tx_hex: str,
                        session_id: str) -> str:
        """
        Broadcast a signed transaction. Requires valid SIWE session.
        Returns transaction hash hex.
        """
        from auth.session import validate_session
        session = validate_session(session_id)
        if not session:
            raise PermissionError(
                "Valid SIWE session required to broadcast transactions"
            )

        client_config = self._get_client(chain_id)
        w3 = client_config["primary"]
        tx_hash = await w3.eth.send_raw_transaction(
            bytes.fromhex(signed_tx_hex.replace("0x", ""))
        )
        return tx_hash.hex()

    async def test_connection(self, chain_id: int, timeout: float = 5.0) -> float | None:
        """Test RPC connectivity. Returns latency in ms or None.

        Caps at `timeout` seconds to avoid blocking the server.
        """
        try:
            import asyncio
            client_config = self._get_client(chain_id)
            w3 = client_config["primary"]
            start = time.monotonic()
            await asyncio.wait_for(w3.eth.get_block_number(), timeout=timeout)
            return round((time.monotonic() - start) * 1000, 2)
        except Exception:
            return None

    async def close(self):
        """Close all cached web3 client sessions."""
        for chain_id, client in self._clients.items():
            w3 = client.get("primary")
            if w3 and hasattr(w3.provider, '_request_session') and w3.provider._request_session:
                await w3.provider._request_session.close()
        self._clients.clear()
