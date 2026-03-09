"""Tests for the /download Gopher route and binary file serving."""

import asyncio
import gzip
import tarfile
import io
import pytest
from unittest.mock import MagicMock
from core.gopher_server import GopherServer, REFINET_ROUTES


@pytest.fixture
async def download_server(tmp_path, monkeypatch):
    """Start a GopherServer with a populated download directory."""
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    gopherroot = tmp_path / "gopherroot"
    monkeypatch.setattr("core.config.GOPHER_ROOT", gopherroot)
    monkeypatch.setattr("core.gopher_server.GOPHER_ROOT", gopherroot)

    # Create gopherroot structure
    gopherroot.mkdir()
    (gopherroot / "news").mkdir()

    # Create download directory with test files
    download_dir = gopherroot / "download"
    download_dir.mkdir()

    # Gophermap
    (download_dir / "gophermap").write_text(
        "iREFInet Pillar — Download\tfake\t(NULL)\t0\r\n"
        "0  Install Instructions\t/download/INSTALL.txt\tlocalhost\t7070\r\n"
        ".\r\n"
    )

    # Text files
    (download_dir / "INSTALL.txt").write_text("Install guide for REFInet Pillar v0.2.0")
    (download_dir / "CHECKSUMS.txt").write_text("sha256  test-checksum  refinet-pillar-v0.2.0.tar.gz")

    # Create a small test tarball for binary serving
    tarball_path = download_dir / "refinet-pillar-v0.2.0.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        content = b"# REFInet Pillar test file\nversion = '0.2.0'\n"
        info = tarfile.TarInfo(name="refinet-pillar/test.py")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    tarball_path.write_bytes(buf.getvalue())

    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    tcp_server = await asyncio.start_server(
        server.handle_client, "127.0.0.1", 0
    )
    port = tcp_server.sockets[0].getsockname()[1]
    yield server, port, download_dir
    tcp_server.close()
    await tcp_server.wait_closed()


async def _query_text(port: int, selector: str, timeout: float = 5.0) -> str:
    """Send a Gopher request and return the response as text."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8", errors="replace")


async def _query_binary(port: int, selector: str, timeout: float = 5.0) -> bytes:
    """Send a Gopher request and return the raw response bytes."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1048576), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return data


class TestDownloadRoute:
    """Test the /download Gopher route."""

    @pytest.mark.asyncio
    async def test_download_gophermap(self, download_server):
        """GET /download returns the download gophermap."""
        _, port, _ = download_server
        resp = await _query_text(port, "/download")
        assert "DOWNLOAD" in resp
        assert "INSTALL" in resp

    @pytest.mark.asyncio
    async def test_download_install_txt(self, download_server):
        """GET /download/INSTALL.txt returns text content."""
        _, port, _ = download_server
        resp = await _query_text(port, "/download/INSTALL.txt")
        assert "Install" in resp
        assert "0.2.0" in resp

    @pytest.mark.asyncio
    async def test_download_checksums(self, download_server):
        """GET /download/CHECKSUMS.txt returns checksum content."""
        _, port, _ = download_server
        resp = await _query_text(port, "/download/CHECKSUMS.txt")
        assert "sha256" in resp

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, download_server):
        """GET /download/nonexistent.txt returns error."""
        _, port, _ = download_server
        resp = await _query_text(port, "/download/nonexistent.txt")
        assert "Not found" in resp or "not found" in resp.lower()


class TestBinaryServing:
    """Test binary file serving for .tar.gz downloads."""

    @pytest.mark.asyncio
    async def test_binary_tarball_download(self, download_server):
        """Binary .tar.gz file is served correctly without corruption."""
        _, port, download_dir = download_server
        original = (download_dir / "refinet-pillar-v0.2.0.tar.gz").read_bytes()

        downloaded = await _query_binary(port, "/download/refinet-pillar-v0.2.0.tar.gz")

        # Verify bytes match exactly
        assert downloaded == original
        assert len(downloaded) == len(original)

        # Verify it's a valid gzip/tar
        buf = io.BytesIO(downloaded)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert "refinet-pillar/test.py" in names

    @pytest.mark.asyncio
    async def test_binary_no_signature_block(self, download_server):
        """Binary responses must NOT contain text signature blocks."""
        _, port, _ = download_server
        downloaded = await _query_binary(port, "/download/refinet-pillar-v0.2.0.tar.gz")

        # The signature block should not be appended to binary files
        assert b"---BEGIN REFINET SIGNATURE---" not in downloaded

    @pytest.mark.asyncio
    async def test_binary_nonexistent(self, download_server):
        """Requesting a nonexistent .tar.gz returns error."""
        _, port, _ = download_server
        downloaded = await _query_binary(port, "/download/nonexistent.tar.gz")
        text = downloaded.decode("utf-8", errors="replace")
        assert "not found" in text.lower() or "File not found" in text


class TestPathTraversal:
    """Test path traversal protection on the download route."""

    @pytest.mark.asyncio
    async def test_traversal_dotdot(self, download_server):
        """Path traversal via .. is blocked."""
        _, port, _ = download_server
        resp = await _query_text(port, "/download/../../pillar.py")
        # Should return error, not file contents
        assert "pillar.py" not in resp or "Not found" in resp or "denied" in resp.lower()

    @pytest.mark.asyncio
    async def test_traversal_binary_dotdot(self, download_server):
        """Binary path traversal via .. is blocked."""
        _, port, _ = download_server
        downloaded = await _query_binary(port, "/download/../../requirements.txt.tar.gz")
        text = downloaded.decode("utf-8", errors="replace")
        assert "denied" in text.lower() or "not found" in text.lower()


class TestRouteAccessibility:
    """Test that /download is accessible on all ports (not REFInet-only)."""

    def test_download_not_in_refinet_routes(self):
        """/download must NOT be in REFINET_ROUTES to be accessible on port 70."""
        assert "/download" not in REFINET_ROUTES
        # Also check that no download prefix is in the tuple
        for route in REFINET_ROUTES:
            assert not route.startswith("/download")
