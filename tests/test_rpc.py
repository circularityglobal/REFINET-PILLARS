"""Tests for RPC gateway module."""

from rpc.chains import DEFAULT_CHAINS
from rpc.config import load_rpc_config


class TestChainConfig:
    """Test chain configuration."""

    def test_default_chains_exist(self):
        assert 1 in DEFAULT_CHAINS  # Ethereum
        assert 137 in DEFAULT_CHAINS  # Polygon
        assert 42161 in DEFAULT_CHAINS  # Arbitrum
        assert 8453 in DEFAULT_CHAINS  # Base
        assert 11155111 in DEFAULT_CHAINS  # Sepolia

    def test_chain_has_required_fields(self):
        for chain_id, chain in DEFAULT_CHAINS.items():
            assert "name" in chain
            assert "rpc" in chain
            assert "symbol" in chain
            assert chain["rpc"].startswith("https://")

    def test_load_rpc_config_defaults(self):
        config = load_rpc_config()
        # Should have all default chains
        for chain_id in DEFAULT_CHAINS:
            assert chain_id in config
            assert isinstance(config[chain_id], list)
            assert len(config[chain_id]) > 0


class TestRPCGateway:
    """Test RPC gateway initialization."""

    def test_gateway_initializes(self):
        from rpc.gateway import RPCGateway, WEB3_AVAILABLE
        if WEB3_AVAILABLE:
            gw = RPCGateway()
            assert gw.config is not None
        # If web3 not available, skip

    def test_gateway_get_client_raises_for_unknown_chain(self):
        from rpc.gateway import RPCGateway, WEB3_AVAILABLE
        if not WEB3_AVAILABLE:
            return
        gw = RPCGateway()
        import pytest
        with pytest.raises(ValueError, match="No RPC endpoint"):
            gw._get_client(999999)
