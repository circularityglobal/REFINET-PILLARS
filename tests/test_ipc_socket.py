"""Tests for integration/ipc_socket.py — Unix Domain Socket IPC."""

import os
import pytest
from integration.ipc_socket import IPCServer
from core.config import IPC_SOCKET


class TestIPCServerInit:
    """Constructor and configuration."""

    def test_default_socket_path(self):
        ipc = IPCServer(gopher_server=None)
        assert ipc.socket_path == str(IPC_SOCKET)

    def test_custom_socket_path(self):
        ipc = IPCServer(gopher_server=None, socket_path="/tmp/test.sock")
        assert ipc.socket_path == "/tmp/test.sock"

    def test_stores_gopher_server_ref(self):
        sentinel = object()
        ipc = IPCServer(gopher_server=sentinel)
        assert ipc.gopher_server is sentinel


class TestIPCStop:
    """Socket cleanup on stop."""

    @pytest.mark.asyncio
    async def test_stop_removes_socket_file(self, tmp_path):
        sock_path = str(tmp_path / "test.sock")
        # Create a dummy socket file
        with open(sock_path, "w") as f:
            f.write("")
        assert os.path.exists(sock_path)

        ipc = IPCServer(gopher_server=None, socket_path=sock_path)
        await ipc.stop()
        assert not os.path.exists(sock_path)

    @pytest.mark.asyncio
    async def test_stop_nonexistent_socket_is_safe(self, tmp_path):
        sock_path = str(tmp_path / "nonexistent.sock")
        ipc = IPCServer(gopher_server=None, socket_path=sock_path)
        await ipc.stop()  # Should not raise


class TestIPCHandleRequest:
    """Request handling (unit-level)."""

    @pytest.mark.asyncio
    async def test_request_without_server_errors(self):
        """Without a gopher_server, routing fails gracefully."""
        ipc = IPCServer(gopher_server=None)
        result = await ipc._handle_request({"selector": "/"})
        assert result["status"] == "error"
