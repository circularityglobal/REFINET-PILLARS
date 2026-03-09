"""
End-to-end synergy tests simulating Browser → Pillar interactions.

These tests verify the contract between the REFInet Browser and Pillar:
  - Signature blocks contain all required fields
  - /pid is machine-parseable
  - /status.json matches the expected schema
  - /directory.json entries have verifiable signatures
  - /peers returns Gopher Type 1 menu format
  - /search route works
  - Chain name mappings are correct
  - Service proofs are generated
  - License tier is surfaced
  - Rate limiter exposes stats
  - Peer status reset on startup
  - Accounting date formatting
  - WAL checkpoint functions exist
  - DApp count helper works
"""

import asyncio
import base64
import hashlib
import json
import sqlite3
import uuid

import pytest

from core.gopher_server import GopherServer, RateLimiter
from crypto.pid import generate_pid, get_private_key
from crypto.signing import hash_content, sign_content, verify_signature
from db.live_db import (
    get_accounting_date,
    format_accounting_date,
    get_license_tier,
    insert_service_proof,
    reset_peer_statuses_to_unknown,
    search_content,
    get_replication_rejections_today,
    checkpoint_live_db,
    init_live_db,
    upsert_peer,
    get_peers,
    index_content,
    record_transaction,
)
from db.archive_db import checkpoint_archive_db
from db.schema import LIVE_SCHEMA
from rpc.chains import CHAIN_NAME_TO_ID, CHAIN_ID_TO_NAME, DEFAULT_CHAINS
from core.dapp import get_dapp_count
from core.menu_builder import (
    build_pid_document,
    build_peers_document,
    build_root_menu,
    build_network_menu,
    build_transactions_document,
    build_ledger_document,
)
from datetime import datetime


# ---------------------------------------------------------------------------
# Server fixture (reusable across test classes)
# ---------------------------------------------------------------------------
@pytest.fixture
async def gopher_server(tmp_path, monkeypatch):
    """Start a GopherServer on a random port for testing."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    (tmp_path / "gopherroot" / "dapps").mkdir()
    (tmp_path / "gopherroot" / "news").mkdir()

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    tcp_server = await asyncio.start_server(
        server.handle_client, "127.0.0.1", 0
    )
    port = tcp_server.sockets[0].getsockname()[1]
    yield server, port
    tcp_server.close()
    await tcp_server.wait_closed()


async def _query(port: int, selector: str, timeout: float = 5.0) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1.1  Signature block contains pubkey: field
# ---------------------------------------------------------------------------
class TestSignatureBlock:
    @pytest.mark.asyncio
    async def test_signature_block_has_pubkey(self, gopher_server):
        server, port = gopher_server
        resp = await _query(port, "")
        assert "---BEGIN REFINET SIGNATURE---" in resp
        assert "pubkey:" in resp

    @pytest.mark.asyncio
    async def test_pubkey_is_64_hex_chars(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "")
        for line in resp.splitlines():
            if line.startswith("pubkey:"):
                pubkey = line.split(":", 1)[1]
                assert len(pubkey) == 64
                int(pubkey, 16)  # validates hex

    @pytest.mark.asyncio
    async def test_pubkey_hashes_to_pid(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "")
        fields = {}
        for line in resp.splitlines():
            if ":" in line and not line.startswith("i") and not line.startswith("1"):
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()
        if "pubkey" in fields and "pid" in fields:
            computed_pid = hashlib.sha256(
                bytes.fromhex(fields["pubkey"])
            ).hexdigest()
            assert computed_pid == fields["pid"]


# ---------------------------------------------------------------------------
# 1.2  /pid machine-parseable
# ---------------------------------------------------------------------------
class TestPidDocument:
    @pytest.mark.asyncio
    async def test_pid_has_five_fields(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/pid")
        # Strip signature block
        body = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        fields = {}
        for line in body.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
        assert "pid" in fields
        assert "public_key" in fields
        assert "created_at" in fields
        assert "protocol" in fields
        assert "pillar_name" in fields

    @pytest.mark.asyncio
    async def test_pid_field_is_64_hex(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/pid")
        body = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        for line in body.splitlines():
            if line.startswith("pid:"):
                pid_val = line.split(":", 1)[1]
                assert len(pid_val) == 64
                int(pid_val, 16)

    def test_build_pid_document_standalone(self):
        pid_data = generate_pid()
        doc = build_pid_document(pid_data, pillar_name="Test Pillar")
        lines = doc.strip().splitlines()
        assert any(l.startswith("pillar_name:") for l in lines)
        assert any(l.startswith("public_key:") for l in lines)


# ---------------------------------------------------------------------------
# 1.3  /status.json schema
# ---------------------------------------------------------------------------
class TestStatusJsonSchema:
    @pytest.mark.asyncio
    async def test_status_json_all_required_keys(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/status.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        required = [
            "schema_version", "pid", "public_key", "pillar_name",
            "protocol_version", "uptime_seconds", "tx_count_today",
            "peers_online", "port", "timestamp", "license_tier",
            "dapp_count", "accounting_date", "rate_limiter",
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"
        assert data["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_accounting_date_in_status(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/status.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        acct = data["accounting_date"]
        assert "day" in acct
        assert "month" in acct
        assert "year" in acct


# ---------------------------------------------------------------------------
# 2.2  /peers Gopher Type 1 menu
# ---------------------------------------------------------------------------
class TestPeersMenu:
    @pytest.mark.asyncio
    async def test_peers_has_gopher_structure(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/peers")
        # Should contain info lines (start with 'i') and end with '.\r\n'
        assert resp.startswith("i")
        assert ".\r\n" in resp

    def test_peers_menu_with_peers(self):
        peers = [
            {
                "pid": "a" * 64,
                "hostname": "peer1.example.com",
                "port": 7070,
                "pillar_name": "Test Peer",
                "status": "online",
                "latency_ms": 42.5,
            }
        ]
        doc = build_peers_document(peers, hostname="localhost", port=7070)
        # Should contain a menu_link line (starts with '1')
        assert "\t" in doc
        assert "peer1.example.com" in doc
        assert "Test Peer" in doc
        assert "online" in doc


# ---------------------------------------------------------------------------
# 2.5  Chain name ↔ ID mapping
# ---------------------------------------------------------------------------
class TestChainMapping:
    def test_chain_name_to_id_all_five(self):
        assert CHAIN_NAME_TO_ID["ethereum"] == 1
        assert CHAIN_NAME_TO_ID["polygon"] == 137
        assert CHAIN_NAME_TO_ID["arbitrum"] == 42161
        assert CHAIN_NAME_TO_ID["base"] == 8453
        assert CHAIN_NAME_TO_ID["sepolia"] == 11155111
        assert len(CHAIN_NAME_TO_ID) == 5

    def test_chain_id_to_name_reverse(self):
        for name, cid in CHAIN_NAME_TO_ID.items():
            assert CHAIN_ID_TO_NAME[cid] == name

    def test_default_chains_ids_match(self):
        for cid in CHAIN_NAME_TO_ID.values():
            assert cid in DEFAULT_CHAINS


# ---------------------------------------------------------------------------
# 3.1  Service proofs
# ---------------------------------------------------------------------------
class TestServiceProofs:
    def test_insert_service_proof(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.DB_DIR", tmp_path)
        init_live_db()
        proof_id = str(uuid.uuid4())
        insert_service_proof(
            proof_id=proof_id,
            pid="test_pid",
            service="gopher.serve",
            proof_hash="abcd1234",
            signature="sig1234",
        )
        # Verify it was inserted
        import db.live_db as ldb
        with ldb._connect() as conn:
            row = conn.execute(
                "SELECT * FROM service_proofs WHERE proof_id=?", (proof_id,)
            ).fetchone()
            assert row is not None
            assert row["service"] == "gopher.serve"

    @pytest.mark.asyncio
    async def test_serving_generates_proof(self, gopher_server):
        server, port = gopher_server
        await _query(port, "/about")
        import db.live_db as ldb
        with ldb._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM service_proofs"
            ).fetchone()["cnt"]
            assert count >= 1


# ---------------------------------------------------------------------------
# 3.2  License tier
# ---------------------------------------------------------------------------
class TestLicenseTier:
    def test_get_license_tier_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.DB_DIR", tmp_path)
        init_live_db()
        tier = get_license_tier("nonexistent_pid")
        assert tier == "free"

    def test_license_tier_in_root_menu(self):
        pid_data = generate_pid()
        menu = build_root_menu(pid_data, "localhost", 7070, license_tier="pro")
        assert "PRO" in menu


# ---------------------------------------------------------------------------
# 3.5  Peer status reset
# ---------------------------------------------------------------------------
class TestPeerReset:
    def test_reset_peer_statuses(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.DB_DIR", tmp_path)
        init_live_db()
        pid_data = generate_pid()
        upsert_peer(
            pid=pid_data["pid"],
            public_key=pid_data["public_key"],
            hostname="peer.test",
            port=7070,
        )
        # Manually set to online
        import db.live_db as ldb
        with ldb._connect() as conn:
            conn.execute(
                "UPDATE peers SET status='online' WHERE pid=?",
                (pid_data["pid"],),
            )
            conn.commit()

        reset_peer_statuses_to_unknown()
        peers = get_peers()
        assert len(peers) >= 1
        # Find our specific peer and check it was reset
        our_peer = [p for p in peers if p["pid"] == pid_data["pid"]][0]
        assert our_peer["status"] == "unknown"


# ---------------------------------------------------------------------------
# 3.6  /search route
# ---------------------------------------------------------------------------
class TestSearchRoute:
    @pytest.mark.asyncio
    async def test_search_returns_menu(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/search")
        assert "SEARCH" in resp

    @pytest.mark.asyncio
    async def test_search_with_query(self, gopher_server):
        server, port = gopher_server
        # Index some content first
        index_content(
            selector="/test/hello",
            content_type="text",
            content_hash="abc123",
            signature="sig",
            pid=server.pid_data["pid"],
        )
        resp = await _query(port, "/search\thello")
        assert "hello" in resp.lower() or "/test/hello" in resp


# ---------------------------------------------------------------------------
# 3.4  Replication rejections
# ---------------------------------------------------------------------------
class TestReplicationRejections:
    def test_network_menu_shows_rejections(self):
        menu = build_network_menu([], "localhost", 7070,
                                   replication_rejections_today=3)
        assert "3" in menu
        assert "rejection" in menu.lower()

    def test_network_menu_hides_zero_rejections(self):
        menu = build_network_menu([], "localhost", 7070,
                                   replication_rejections_today=0)
        assert "rejection" not in menu.lower()


# ---------------------------------------------------------------------------
# 4.1  Accounting date formatting
# ---------------------------------------------------------------------------
class TestAccountingDate:
    def test_get_accounting_date_returns_tuple(self):
        day, month, year = get_accounting_date()
        assert 1 <= day <= 28
        assert 1 <= month <= 13
        assert year >= 2024

    def test_format_accounting_date(self):
        dt = datetime(2026, 3, 2)
        formatted = format_accounting_date(dt)
        assert "2026-03-02" in formatted
        assert "REFInet" in formatted
        assert "Y2026" in formatted

    def test_known_date(self):
        # Jan 1 = day 1, month 1
        dt = datetime(2026, 1, 1)
        day, month, year = get_accounting_date(dt)
        assert day == 1
        assert month == 1
        assert year == 2026


# ---------------------------------------------------------------------------
# 4.2  WAL checkpoint
# ---------------------------------------------------------------------------
class TestWALCheckpoint:
    def test_checkpoint_live_db_callable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.DB_DIR", tmp_path)
        init_live_db()
        # Should not raise
        checkpoint_live_db()

    def test_checkpoint_archive_db_callable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.DB_DIR", tmp_path)
        from db.archive_db import init_archive_db
        init_archive_db()
        checkpoint_archive_db()


# ---------------------------------------------------------------------------
# 4.3  RateLimiter stats
# ---------------------------------------------------------------------------
class TestRateLimiterStats:
    def test_get_stats_initial(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        stats = rl.get_stats()
        assert stats["active_ips"] == 0
        assert stats["blocked_last_minute"] == 0

    def test_blocked_count_increments(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.is_allowed("1.2.3.4")
        rl.is_allowed("1.2.3.4")
        # Third request should be blocked
        assert not rl.is_allowed("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")
        stats = rl.get_stats()
        assert stats["blocked_last_minute"] == 2
        assert stats["active_ips"] == 1


# ---------------------------------------------------------------------------
# 3.3  DApp count
# ---------------------------------------------------------------------------
class TestDAppCount:
    def test_get_dapp_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path)
        (tmp_path / "dapps").mkdir()
        (tmp_path / "dapps" / "test1.dapp").write_text(
            "[meta]\nname=Test\nslug=test1\nversion=1.0.0\nchain_id=1\n"
            "contract=0x0000000000000000000000000000000000000000\n"
            "author_pid=abc\nauthor_address=0x0\ndescription=A test\n"
        )
        assert get_dapp_count() >= 1


# ---------------------------------------------------------------------------
# End-to-end: /directory.json signature verification
# ---------------------------------------------------------------------------
class TestDirectoryJsonSignatures:
    @pytest.mark.asyncio
    async def test_directory_json_entries_have_sig_fields(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/directory.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        assert data["schema_version"] == 1
        # Entries may be empty, but the schema must be correct
        for entry in data.get("gopherholes", []):
            assert "pubkey_hex" in entry
            assert "signature" in entry
            assert len(entry["pubkey_hex"]) == 64
            assert len(entry["signature"]) > 0
