"""The chain table covers TradeSphere's networks and is operator-extensible (F17)."""

import json

import pytest

from rpc.chains import (
    CHAIN_ID_TO_NAME, CHAIN_NAME_TO_ID, DEFAULT_CHAINS, supported_chain_names,
)


class TestChainCoverage:
    @pytest.mark.parametrize("chain_id,name", [
        (43114, "avalanche"), (43113, "fuji"), (84532, "base-sepolia"),
        (50, "xdc"), (51, "apothem"),
    ])
    def test_tradesphere_networks_are_present(self, chain_id, name):
        assert CHAIN_NAME_TO_ID[name] == chain_id
        assert DEFAULT_CHAINS[chain_id]["rpc"].startswith("https://")

    @pytest.mark.parametrize("name,chain_id", [
        ("ethereum", 1), ("polygon", 137), ("arbitrum", 42161),
        ("base", 8453), ("sepolia", 11155111),
    ])
    def test_existing_names_are_unchanged(self, name, chain_id):
        """These names are wire protocol — the Browser sends them."""
        assert CHAIN_NAME_TO_ID[name] == chain_id

    def test_existing_endpoints_are_unchanged(self):
        assert DEFAULT_CHAINS[1]["rpc"] == "https://eth.llamarpc.com"
        assert DEFAULT_CHAINS[8453]["rpc"] == "https://mainnet.base.org"

    def test_every_name_resolves_to_a_configured_chain(self):
        for chain_id in CHAIN_NAME_TO_ID.values():
            assert chain_id in DEFAULT_CHAINS

    def test_error_text_lists_the_chains(self):
        names = supported_chain_names()
        assert "avalanche" in names and "ethereum" in names


class TestOperatorChains:
    def test_chains_json_adds_a_network(self, tmp_path, monkeypatch):
        from rpc import config as rpc_config
        path = tmp_path / "chains.json"
        path.write_text(json.dumps({
            "10": {"name": "Optimism", "rpc": "https://mainnet.optimism.io",
                   "symbol": "ETH", "explorer": "https://optimistic.etherscan.io",
                   "aliases": ["optimism"]},
        }))
        monkeypatch.setattr(rpc_config, "CHAINS_CONFIG_PATH", path)
        try:
            added = rpc_config.load_custom_chains()
            assert 10 in added
            assert CHAIN_NAME_TO_ID["optimism"] == 10
            assert 10 in rpc_config.load_rpc_config()
        finally:
            DEFAULT_CHAINS.pop(10, None)
            CHAIN_NAME_TO_ID.pop("optimism", None)
            CHAIN_ID_TO_NAME.pop(10, None)

    def test_malformed_chains_json_is_ignored(self, tmp_path, monkeypatch):
        from rpc import config as rpc_config
        path = tmp_path / "chains.json"
        path.write_text("{not json")
        monkeypatch.setattr(rpc_config, "CHAINS_CONFIG_PATH", path)
        assert rpc_config.load_custom_chains() == {}

    def test_rpc_config_overrides_still_work(self, tmp_path, monkeypatch):
        from rpc import config as rpc_config
        path = tmp_path / "rpc_config.json"
        path.write_text(json.dumps({"43113": ["https://my.fuji.example"]}))
        monkeypatch.setattr(rpc_config, "RPC_CONFIG_PATH", path)
        assert rpc_config.load_rpc_config()[43113] == ["https://my.fuji.example"]


def test_docs_report_the_real_chain_count():
    """Docs that count things drift; this is the F19 lesson applied here."""
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parent.parent
    actual = len(DEFAULT_CHAINS)
    for name in ("README.md", "PLATFORM_OVERVIEW.md", "WHITEPAPER.md",
                 "GETTING-STARTED.md"):
        text = (root / name).read_text(encoding="utf-8")
        for claimed in re.findall(r"(\d+) chains", text):
            assert int(claimed) == actual, (
                f"{name} says {claimed} chains, the table has {actual}")
