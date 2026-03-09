"""Tests for the built-in REFInet gopherhole content and token replacement."""

import asyncio
import sqlite3
import pytest
from pathlib import Path
from core.gopher_server import GopherServer, render_gophermap
from db.schema import LIVE_SCHEMA

# Resolve the real gopherroot from the project tree (not tmp_path)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOPHERROOT = PROJECT_ROOT / "gopherroot"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def refinet_server(tmp_path, monkeypatch):
    """GopherServer that uses the REAL gopherroot so static files are served."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", GOPHERROOT)
    monkeypatch.setattr("core.gopher_server.GOPHER_ROOT", GOPHERROOT)

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
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
# Static file existence
# ---------------------------------------------------------------------------

GOPHERMAP_PATHS = [
    "gopherroot/holes/refinet/gophermap",
    "gopherroot/holes/refinet/products/gophermap",
    "gopherroot/holes/refinet/products/pillar/gophermap",
    "gopherroot/holes/refinet/products/pillar/download/gophermap",
    "gopherroot/holes/refinet/docs/gophermap",
]

TEXT_FILE_PATHS = [
    "gopherroot/holes/refinet/about.txt",
    "gopherroot/holes/refinet/products/pillar/README.txt",
    "gopherroot/holes/refinet/products/pillar/INSTALL.txt",
    "gopherroot/holes/refinet/products/pillar/CHANGELOG.txt",
    "gopherroot/holes/refinet/products/pillar/download/CHECKSUMS.txt",
    "gopherroot/holes/refinet/docs/getting-started.txt",
    "gopherroot/holes/refinet/docs/faq.txt",
    "gopherroot/holes/refinet/docs/whitepaper.txt",
]


def test_gophermap_files_exist():
    """All required gophermap files must exist."""
    for rel in GOPHERMAP_PATHS:
        path = PROJECT_ROOT / rel
        assert path.is_file(), f"Missing gophermap: {rel}"


def test_text_files_exist():
    """All text content files must exist and have real content (>100 chars)."""
    for rel in TEXT_FILE_PATHS:
        path = PROJECT_ROOT / rel
        assert path.is_file(), f"Missing text file: {rel}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, f"File too short ({len(content)} chars): {rel}"


# ---------------------------------------------------------------------------
# Token replacement
# ---------------------------------------------------------------------------

def test_gophermap_token_replacement():
    """Raw gophermap must contain PILLAR_HOST/PILLAR_PORT tokens.
    After render_gophermap(), tokens must be replaced with real values."""
    raw = (PROJECT_ROOT / "gopherroot/holes/refinet/gophermap").read_text(
        encoding="utf-8"
    )
    assert "PILLAR_HOST" in raw
    assert "PILLAR_PORT" in raw

    rendered = render_gophermap(raw, "localhost", 7070)
    assert "PILLAR_HOST" not in rendered
    assert "PILLAR_PORT" not in rendered
    assert "localhost" in rendered
    assert "7070" in rendered


# ---------------------------------------------------------------------------
# Live serving via GopherServer
# ---------------------------------------------------------------------------

class TestLiveServing:
    """Test that the GopherServer correctly serves refinet gopherhole content."""

    @pytest.mark.asyncio
    async def test_directory_selector_serves_gophermap(self, refinet_server):
        """Requesting /holes/refinet should serve the gophermap with tokens replaced."""
        _, port = refinet_server
        resp = await _query(port, "/holes/refinet")
        assert "REFInet" in resp
        assert "PILLAR_HOST" not in resp

    @pytest.mark.asyncio
    async def test_subdirectory_selector_serves_gophermap(self, refinet_server):
        """Requesting /holes/refinet/products should serve its gophermap."""
        _, port = refinet_server
        resp = await _query(port, "/holes/refinet/products")
        assert "Pillar" in resp

    @pytest.mark.asyncio
    async def test_text_file_selector_serves_content(self, refinet_server):
        """Requesting /holes/refinet/about.txt should serve real text content."""
        _, port = refinet_server
        resp = await _query(port, "/holes/refinet/about.txt")
        assert len(resp) > 100
        assert not resp.startswith("3")  # Gopher error lines start with '3'

    @pytest.mark.asyncio
    async def test_existing_holes_unaffected(self, refinet_server):
        """The /holes/test gopherhole must still serve correctly."""
        _, port = refinet_server
        resp = await _query(port, "/holes/test")
        assert "Test Site" in resp
        assert "PILLAR_HOST" not in resp


# ---------------------------------------------------------------------------
# DB registration
# ---------------------------------------------------------------------------

def test_ensure_refinet_gopherhole_idempotent(tmp_path, monkeypatch, test_pid):
    """Calling ensure_refinet_gopherhole twice should create exactly one record."""
    import db.live_db as live_db

    # The autouse _patch_db_paths fixture already sets up paths and dirs.
    live_db.init_live_db()

    live_db.ensure_refinet_gopherhole(test_pid)
    live_db.ensure_refinet_gopherhole(test_pid)

    db_dir = tmp_path / ".refinet" / "db"
    conn = sqlite3.connect(str(db_dir / "live.db"))
    rows = conn.execute(
        "SELECT COUNT(*) FROM gopherholes WHERE selector=?",
        ("/holes/refinet",),
    ).fetchone()
    conn.close()
    assert rows[0] == 1
