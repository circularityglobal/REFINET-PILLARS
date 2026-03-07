"""Tests for DApp definition format parser."""

import pytest
import tempfile
from pathlib import Path
from core.dapp import parse_dapp_file, DAppDefinition, _split_sections, _parse_meta, _parse_abi

SAMPLE_DAPP = """\
[meta]
name = Uniswap V3
slug = uniswap-v3
version = 1.0.0
chain_id = 1
contract = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45
author_pid = test_pid_123
author_address = 0xAbC123
description = Swap tokens on Uniswap V3 without a browser
published = 2025-01-01

[abi]
# Human-readable ABI
exactInputSingle((address,address,uint24,address,uint256,uint256,uint160)) -> uint256
exactOutputSingle((address,address,uint24,address,uint256,uint256,uint160)) -> uint256
multicall(bytes[]) -> bytes[]

[docs]
# exactInputSingle
Swaps an exact amount of one token for as much as possible of another.
Gas estimate: ~150,000

# exactOutputSingle
Swaps as little as possible of one token for an exact amount of another.
Gas estimate: ~160,000

[flows]
swap:
  1. Approve tokenIn spending
  2. Call exactInputSingle with your parameters
  3. Verify output token balance increased

[warnings]
Always verify slippage tolerance before signing.
High-fee pools (1%) are for exotic pairs.
"""


@pytest.fixture
def sample_dapp_file(tmp_path):
    """Write sample .dapp file and return path."""
    path = tmp_path / "uniswap-v3.dapp"
    path.write_text(SAMPLE_DAPP)
    return path


class TestDAppParser:
    """Test .dapp file parsing."""

    def test_parse_meta(self, sample_dapp_file):
        dapp = parse_dapp_file(sample_dapp_file)
        assert isinstance(dapp, DAppDefinition)
        assert dapp.name == "Uniswap V3"
        assert dapp.slug == "uniswap-v3"
        assert dapp.version == "1.0.0"
        assert dapp.chain_id == 1
        assert dapp.contract == "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"
        assert dapp.author_pid == "test_pid_123"
        assert dapp.description == "Swap tokens on Uniswap V3 without a browser"

    def test_parse_abi(self, sample_dapp_file):
        dapp = parse_dapp_file(sample_dapp_file)
        assert len(dapp.abi_functions) == 3
        assert "exactInputSingle" in dapp.abi_functions[0]
        assert "multicall" in dapp.abi_functions[2]

    def test_parse_docs(self, sample_dapp_file):
        dapp = parse_dapp_file(sample_dapp_file)
        assert "exactInputSingle" in dapp.docs
        assert "exactOutputSingle" in dapp.docs
        assert "150,000" in dapp.docs["exactInputSingle"]

    def test_parse_flows(self, sample_dapp_file):
        dapp = parse_dapp_file(sample_dapp_file)
        assert "swap" in dapp.flows
        assert len(dapp.flows["swap"]) == 3
        assert "Approve" in dapp.flows["swap"][0]

    def test_parse_warnings(self, sample_dapp_file):
        dapp = parse_dapp_file(sample_dapp_file)
        assert len(dapp.warnings) == 2
        assert "slippage" in dapp.warnings[0]

    def test_parse_empty_file(self, tmp_path):
        path = tmp_path / "empty.dapp"
        path.write_text("")
        dapp = parse_dapp_file(path)
        assert dapp.name == ""
        assert dapp.abi_functions == []

    def test_parse_meta_only(self, tmp_path):
        path = tmp_path / "minimal.dapp"
        path.write_text("[meta]\nname = Minimal\nslug = minimal\nchain_id = 137\n")
        dapp = parse_dapp_file(path)
        assert dapp.name == "Minimal"
        assert dapp.chain_id == 137


class TestSectionSplitter:
    """Test internal section splitting."""

    def test_split_sections(self):
        text = "[meta]\nname = Test\n[abi]\nfunc1\nfunc2\n"
        sections = _split_sections(text)
        assert "meta" in sections
        assert "abi" in sections

    def test_comments_preserved_in_sections(self):
        """_split_sections preserves all content; comment filtering is per-parser."""
        text = "[abi]\n# This is a comment\nfunc1\n"
        sections = _split_sections(text)
        assert "# This is a comment" in sections["abi"]
        assert "func1" in sections["abi"]

    def test_abi_parser_excludes_comments(self):
        """_parse_abi filters out comment lines."""
        text = "# This is a comment\nfunc1\nfunc2\n"
        result = _parse_abi(text)
        assert result == ["func1", "func2"]
