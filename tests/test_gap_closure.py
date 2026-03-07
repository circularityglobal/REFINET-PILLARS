"""Tests for Browser-Pillar gap closure (GAPs 2, 3, 6, 7, 8, 11, 12)."""

import asyncio
import base64
import json
import sqlite3
import pytest
from core.gopher_server import GopherServer, REFINET_ROUTES
from db.schema import LIVE_SCHEMA


@pytest.fixture
async def gopher_server(tmp_path, monkeypatch):
    """Start a GopherServer on a random port for testing."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    (tmp_path / "gopherroot" / "news").mkdir()

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    tcp_server = await asyncio.start_server(
        server.handle_client, "127.0.0.1", 0
    )
    port = tcp_server.sockets[0].getsockname()[1]
    yield server, port
    tcp_server.close()
    await tcp_server.wait_closed()


@pytest.fixture
async def standard_server(tmp_path, monkeypatch):
    """Start a standard Gopher server (is_refinet=False) for testing."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    (tmp_path / "gopherroot" / "news").mkdir()

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost",
                          is_refinet=False)
    tcp_server = await asyncio.start_server(
        server.handle_client, "127.0.0.1", 0
    )
    port = tcp_server.sockets[0].getsockname()[1]
    yield server, port
    tcp_server.close()
    await tcp_server.wait_closed()


async def _query(port: int, selector: str, timeout: float = 5.0) -> str:
    """Send a Gopher request and return the response text."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# GAP 2: Response Ed25519 Signature Block
# ---------------------------------------------------------------------------
class TestResponseSignatureBlock:
    """Every response should include an Ed25519 signature block."""

    @pytest.mark.asyncio
    async def test_signature_block_present(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/about")
        assert "---BEGIN REFINET SIGNATURE---" in resp
        assert "---END REFINET SIGNATURE---" in resp

    @pytest.mark.asyncio
    async def test_signature_block_has_pid(self, gopher_server):
        server, port = gopher_server
        resp = await _query(port, "/about")
        # Extract pid from sig block
        sig_block = resp.split("---BEGIN REFINET SIGNATURE---")[1]
        assert f"pid:{server.pid_data['pid']}" in sig_block

    @pytest.mark.asyncio
    async def test_signature_block_has_sig_and_hash(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/about")
        sig_block = resp.split("---BEGIN REFINET SIGNATURE---")[1]
        assert "sig:" in sig_block
        assert "hash:" in sig_block

    @pytest.mark.asyncio
    async def test_signature_block_after_gopher_terminator(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "")
        # The Gopher terminator ".\r\n" should come before the sig block
        term_pos = resp.find(".\r\n")
        sig_pos = resp.find("---BEGIN REFINET SIGNATURE---")
        assert term_pos < sig_pos

    @pytest.mark.asyncio
    async def test_signature_block_on_root_menu(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "")
        assert "---BEGIN REFINET SIGNATURE---" in resp

    @pytest.mark.asyncio
    async def test_content_before_sig_block_is_valid_menu(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "")
        content = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        # Should end with the Gopher terminator
        assert content.endswith(".")
        # Should contain menu items
        assert "R E F I n e t" in content


# ---------------------------------------------------------------------------
# GAP 3: /auth/verify Base64 Message Text
# ---------------------------------------------------------------------------
class TestAuthVerifyBase64:
    """The /auth/verify route should accept base64-encoded messages."""

    @pytest.mark.asyncio
    async def test_verify_error_format_message(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/auth/verify\tbadformat")
        assert "base64(message_text)" in resp or "Format:" in resp

    @pytest.mark.asyncio
    async def test_verify_rejects_bad_address(self, gopher_server):
        _, port = gopher_server
        msg_b64 = base64.b64encode(b"test message").decode()
        resp = await _query(port, f"/auth/verify\tnotanaddress|sig|{msg_b64}")
        assert "Invalid EVM address" in resp

    @pytest.mark.asyncio
    async def test_verify_accepts_pipe_format(self, gopher_server):
        """Test that the pipe-delimited format with base64 message is parsed."""
        _, port = gopher_server
        address = "0x" + "a" * 40
        sig = "0x" + "b" * 130
        msg_text = "Sign-In With Ethereum\nNonce: abc123"
        msg_b64 = base64.b64encode(msg_text.encode()).decode()
        resp = await _query(port, f"/auth/verify\t{address}|{sig}|{msg_b64}")
        # Will fail auth (wrong sig) but should NOT fail on format parsing
        assert "Invalid EVM address" not in resp
        # Should get to the verification step (may fail with auth error)
        assert "Authentication failed" in resp or "Authentication requires" in resp

    @pytest.mark.asyncio
    async def test_verify_accepts_plain_text_fallback(self, gopher_server):
        """Test backward compat: plain text message (not base64) still works."""
        _, port = gopher_server
        address = "0x" + "a" * 40
        sig = "0x" + "b" * 130
        plain_msg = "Simple test message no newlines"
        resp = await _query(port, f"/auth/verify\t{address}|{sig}|{plain_msg}")
        # Should get past format parsing to auth verification
        assert "Invalid EVM address" not in resp
        assert "Authentication failed" in resp or "Authentication requires" in resp


# ---------------------------------------------------------------------------
# GAP 8: /status.json Route
# ---------------------------------------------------------------------------
class TestStatusJson:
    """Test the /status.json machine-readable endpoint."""

    @pytest.mark.asyncio
    async def test_status_json_returns_valid_json(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/status.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_status_json_has_required_fields(self, gopher_server):
        _, port = gopher_server
        resp = await _query(port, "/status.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        assert data["schema_version"] == 1
        assert "pid" in data
        assert "public_key" in data
        assert "uptime_seconds" in data
        assert "tx_count_today" in data
        assert "peers_online" in data
        assert "protocol_version" in data
        assert "timestamp" in data
        assert "pillar_name" in data
        assert "port" in data

    @pytest.mark.asyncio
    async def test_status_json_pid_matches_server(self, gopher_server):
        server, port = gopher_server
        resp = await _query(port, "/status.json")
        raw = resp.split("---BEGIN REFINET SIGNATURE---")[0].strip()
        if raw.endswith("."):
            raw = raw[:-1].strip()
        data = json.loads(raw)
        assert data["pid"] == server.pid_data["pid"]
        assert data["public_key"] == server.pid_data["public_key"]

    @pytest.mark.asyncio
    async def test_status_json_gated_on_port_70(self, standard_server):
        _, port = standard_server
        resp = await _query(port, "/status.json")
        assert "Connect on port 7070" in resp

    def test_status_json_in_refinet_routes(self):
        assert "/status.json" in REFINET_ROUTES


# ---------------------------------------------------------------------------
# GAP 7: service_proofs + settlements Tables
# ---------------------------------------------------------------------------
class TestServiceProofsSchema:
    """Test that service_proofs and settlements tables are created correctly."""

    def test_service_proofs_table_exists(self, memory_db):
        tables = [r[0] for r in memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "service_proofs" in tables

    def test_settlements_table_exists(self, memory_db):
        tables = [r[0] for r in memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "settlements" in tables

    def test_service_proofs_columns(self, memory_db):
        cols = {row[1] for row in memory_db.execute(
            "PRAGMA table_info(service_proofs)"
        ).fetchall()}
        assert "proof_id" in cols
        assert "pid" in cols
        assert "service" in cols
        assert "proof_hash" in cols
        assert "signature" in cols
        assert "created_at" in cols

    def test_settlements_columns(self, memory_db):
        cols = {row[1] for row in memory_db.execute(
            "PRAGMA table_info(settlements)"
        ).fetchall()}
        assert "settlement_id" in cols
        assert "payer_pid" in cols
        assert "payee_pid" in cols
        assert "amount" in cols
        assert "token_type" in cols
        assert "proof_id" in cols
        assert "created_at" in cols

    def test_service_proofs_immutable_no_update(self, memory_db):
        memory_db.execute(
            "INSERT INTO service_proofs (proof_id, pid, service, proof_hash, signature) "
            "VALUES ('p1', 'pid1', 'test', 'hash1', 'sig1')"
        )
        memory_db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            memory_db.execute(
                "UPDATE service_proofs SET service='changed' WHERE proof_id='p1'"
            )

    def test_service_proofs_immutable_no_delete(self, memory_db):
        memory_db.execute(
            "INSERT INTO service_proofs (proof_id, pid, service, proof_hash, signature) "
            "VALUES ('p2', 'pid1', 'test', 'hash2', 'sig2')"
        )
        memory_db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            memory_db.execute("DELETE FROM service_proofs WHERE proof_id='p2'")

    def test_settlements_immutable_no_update(self, memory_db):
        memory_db.execute(
            "INSERT INTO service_proofs (proof_id, pid, service, proof_hash, signature) "
            "VALUES ('p3', 'pid1', 'test', 'hash3', 'sig3')"
        )
        memory_db.execute(
            "INSERT INTO settlements (settlement_id, payer_pid, payee_pid, amount, token_type, proof_id) "
            "VALUES ('s1', 'payer1', 'payee1', 10.0, 'REFI', 'p3')"
        )
        memory_db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            memory_db.execute(
                "UPDATE settlements SET amount=999 WHERE settlement_id='s1'"
            )

    def test_settlements_immutable_no_delete(self, memory_db):
        memory_db.execute(
            "INSERT INTO service_proofs (proof_id, pid, service, proof_hash, signature) "
            "VALUES ('p4', 'pid1', 'test', 'hash4', 'sig4')"
        )
        memory_db.execute(
            "INSERT INTO settlements (settlement_id, payer_pid, payee_pid, amount, token_type, proof_id) "
            "VALUES ('s2', 'payer1', 'payee1', 5.0, 'CIFI', 'p4')"
        )
        memory_db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            memory_db.execute("DELETE FROM settlements WHERE settlement_id='s2'")

    def test_settlements_foreign_key(self, memory_db):
        """Settlements proof_id must reference an existing service_proof."""
        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                "INSERT INTO settlements (settlement_id, payer_pid, payee_pid, amount, token_type, proof_id) "
                "VALUES ('s3', 'payer1', 'payee1', 1.0, 'REFI', 'nonexistent')"
            )


# ---------------------------------------------------------------------------
# GAP 6: license_tier Column
# ---------------------------------------------------------------------------
class TestLicenseTierMigration:
    """Test that the license_tier column exists in the schema."""

    def test_license_tier_column_exists(self, memory_db):
        """license_tier column should exist in token_state."""
        cols = {row[1] for row in memory_db.execute(
            "PRAGMA table_info(token_state)"
        ).fetchall()}
        assert "license_tier" in cols
        assert "license_active" in cols
        assert "license_expires" in cols

    def test_license_tier_defaults_to_free(self, memory_db):
        """New token_state rows should default license_tier to 'free'."""
        memory_db.execute(
            "INSERT INTO token_state (pid) VALUES ('test_pid_123')"
        )
        memory_db.commit()
        row = memory_db.execute(
            "SELECT license_tier FROM token_state WHERE pid='test_pid_123'"
        ).fetchone()
        assert row["license_tier"] == "free"
