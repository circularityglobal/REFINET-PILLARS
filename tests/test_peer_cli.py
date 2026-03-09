"""Tests for cli/peer.py — Peer management CLI and bootstrap loading."""

import json
import pytest
from pathlib import Path
from mesh.discovery import load_bootstrap_peers
from db.live_db import init_live_db


class TestLoadBootstrapPeers:
    """Test bootstrap peer loading from JSON file."""

    def test_missing_file_returns_zero(self, tmp_path):
        result = load_bootstrap_peers(tmp_path / "nonexistent.json")
        assert result == 0

    def test_empty_array(self, tmp_path, memory_db):
        peers_file = tmp_path / "peers.json"
        peers_file.write_text("[]")
        result = load_bootstrap_peers(peers_file)
        assert result == 0

    def test_loads_valid_peers(self, tmp_path):
        init_live_db()
        from crypto.pid import generate_pid
        pid_data = generate_pid()
        peers = [
            {
                "hostname": "10.0.0.5",
                "port": 7070,
                "pid": pid_data["pid"],
                "public_key": pid_data["public_key"],
                "pillar_name": "Remote Pillar",
            }
        ]
        peers_file = tmp_path / "peers.json"
        peers_file.write_text(json.dumps(peers))
        result = load_bootstrap_peers(peers_file)
        assert result == 1

    def test_skips_peers_without_hostname(self, tmp_path, memory_db):
        peers = [{"pid": "a" * 64}]  # No hostname
        peers_file = tmp_path / "peers.json"
        peers_file.write_text(json.dumps(peers))
        result = load_bootstrap_peers(peers_file)
        assert result == 0

    def test_skips_peers_without_pid(self, tmp_path, memory_db):
        peers = [{"hostname": "10.0.0.5"}]  # No pid
        peers_file = tmp_path / "peers.json"
        peers_file.write_text(json.dumps(peers))
        result = load_bootstrap_peers(peers_file)
        assert result == 0

    def test_invalid_json_returns_zero(self, tmp_path):
        peers_file = tmp_path / "peers.json"
        peers_file.write_text("not json{{{")
        result = load_bootstrap_peers(peers_file)
        assert result == 0

    def test_non_array_json_returns_zero(self, tmp_path):
        peers_file = tmp_path / "peers.json"
        peers_file.write_text('{"hostname": "10.0.0.5"}')
        result = load_bootstrap_peers(peers_file)
        assert result == 0

    def test_loads_multiple_peers(self, tmp_path):
        init_live_db()
        peers = [
            {"hostname": "10.0.0.1", "pid": "a" * 64, "port": 7070},
            {"hostname": "10.0.0.2", "pid": "b" * 64, "port": 7070},
            {"hostname": "10.0.0.3", "pid": "c" * 64, "port": 7070},
        ]
        peers_file = tmp_path / "peers.json"
        peers_file.write_text(json.dumps(peers))
        result = load_bootstrap_peers(peers_file)
        assert result == 3

    def test_default_port_when_omitted(self, tmp_path):
        init_live_db()
        peers = [{"hostname": "10.0.0.1", "pid": "a" * 64}]
        peers_file = tmp_path / "peers.json"
        peers_file.write_text(json.dumps(peers))
        result = load_bootstrap_peers(peers_file)
        assert result == 1
