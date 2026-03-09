"""Tests for dual-port architecture: port 70 (standard Gopher) vs port 7070 (REFInet)."""

import asyncio
import pytest
from core.gopher_server import GopherServer, REFINET_ROUTES


@pytest.fixture
async def standard_gopher_server(tmp_path, monkeypatch):
    """Start a GopherServer with is_refinet=False (standard Gopher mode)."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
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


@pytest.fixture
async def refinet_server(tmp_path, monkeypatch):
    """Start a GopherServer with is_refinet=True (REFInet mode)."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    (tmp_path / "gopherroot" / "news").mkdir()

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost",
                          is_refinet=True)
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


class TestStandardGopherRouteGating:
    """REFInet-specific routes should be blocked on port 70 (is_refinet=False)."""

    @pytest.mark.asyncio
    async def test_auth_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/auth")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_rpc_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/rpc")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_pid_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/pid")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_transactions_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/transactions")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_peers_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/peers")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_ledger_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/ledger")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_network_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/network")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_directory_json_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/directory.json")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_auth_subpath_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/auth/challenge")
        assert "Connect on port 7070" in resp

    @pytest.mark.asyncio
    async def test_rpc_subpath_blocked(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/rpc/balance")
        assert "Connect on port 7070" in resp


class TestStandardGopherAllowed:
    """Standard Gopher content should still be served on port 70."""

    @pytest.mark.asyncio
    async def test_root_menu(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "")
        assert "REFINET Headquarters" in resp
        assert ".\r\n" in resp

    @pytest.mark.asyncio
    async def test_root_no_auth_link(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "")
        assert "Authentication" not in resp
        assert "RPC Gateway" not in resp

    @pytest.mark.asyncio
    async def test_root_has_refinet_notice(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "")
        assert "port 7070" in resp

    @pytest.mark.asyncio
    async def test_about_allowed(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/about")
        assert "ABOUT" in resp

    @pytest.mark.asyncio
    async def test_dapps_allowed(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/dapps")
        assert "DAPP" in resp.upper()

    @pytest.mark.asyncio
    async def test_directory_allowed(self, standard_gopher_server):
        _, port = standard_gopher_server
        resp = await _query(port, "/directory")
        assert "GOPHERHOLE" in resp.upper()


class TestREFInetServerUnchanged:
    """REFInet server (is_refinet=True) should still serve everything."""

    @pytest.mark.asyncio
    async def test_root_full_menu(self, refinet_server):
        _, port = refinet_server
        resp = await _query(port, "")
        assert "R E F I n e t" in resp
        assert "Authentication" in resp

    @pytest.mark.asyncio
    async def test_auth_works(self, refinet_server):
        _, port = refinet_server
        resp = await _query(port, "/auth")
        assert "SIWE" in resp or "AUTHENTICATION" in resp

    @pytest.mark.asyncio
    async def test_pid_works(self, refinet_server):
        _, port = refinet_server
        resp = await _query(port, "/pid")
        assert "pid:" in resp and "public_key:" in resp

    @pytest.mark.asyncio
    async def test_peers_works(self, refinet_server):
        _, port = refinet_server
        resp = await _query(port, "/peers")
        assert "peer" in resp.lower()


class TestIsRefinetFlag:
    """Test the is_refinet flag on GopherServer instances."""

    def test_default_is_refinet(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
        monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
        monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
        monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
        monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
        server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
        assert server.is_refinet is True

    def test_explicit_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
        monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
        monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
        monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
        monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
        server = GopherServer(host="127.0.0.1", port=0, hostname="localhost",
                              is_refinet=False)
        assert server.is_refinet is False

    def test_refinet_routes_tuple_complete(self):
        """Ensure all REFInet-exclusive routes are listed."""
        assert "/auth" in REFINET_ROUTES
        assert "/rpc" in REFINET_ROUTES
        assert "/pid" in REFINET_ROUTES
        assert "/transactions" in REFINET_ROUTES
        assert "/peers" in REFINET_ROUTES
        assert "/ledger" in REFINET_ROUTES
        assert "/network" in REFINET_ROUTES
        assert "/directory.json" in REFINET_ROUTES
