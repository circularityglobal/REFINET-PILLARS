"""
REFInet Pillar — Unix Domain Socket IPC

Provides local inter-process communication via Unix domain socket
at ~/.refinet/pillar.sock. Same JSON protocol as WebSocket bridge
but lower latency for same-machine communication.

Protocol:
    Request:  {"selector": "/status.json", "session_id": "optional"}\\n
    Response: {"status": "ok", "data": "...", "signature": {...}}\\n

Each message is a single JSON line terminated by \\n.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from core.config import IPC_SOCKET

logger = logging.getLogger("refinet.ipc")


class IPCServer:
    """
    Unix domain socket server for local IPC.

    Provides the same interface as WebSocketBridge but over a Unix socket.
    """

    def __init__(self, gopher_server, socket_path=None):
        self.gopher_server = gopher_server
        self.socket_path = socket_path or str(IPC_SOCKET)

    async def start(self):
        """Start the IPC server."""
        # Clean up stale socket
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        server = await asyncio.start_unix_server(
            self._handle_client, path=self.socket_path
        )

        # Set socket permissions (owner only)
        os.chmod(self.socket_path, 0o600)

        logger.info(f"[IPC] Unix socket server listening on {self.socket_path}")

        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        """Handle a single IPC client connection."""
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=300.0)
                if not line:
                    break

                try:
                    request = json.loads(line.decode("utf-8").strip())
                    response = await self._handle_request(request)
                except json.JSONDecodeError:
                    response = {"status": "error", "error": "Invalid JSON"}
                except Exception as e:
                    response = {"status": "error", "error": str(e)}

                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"[IPC] Client error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_request(self, request: dict) -> dict:
        """Process a single IPC request."""
        selector = request.get("selector", "")
        session_id = request.get("session_id")

        # Session validation
        if session_id:
            try:
                from auth.session import validate_session
                session = validate_session(session_id)
                if not session:
                    return {"status": "error", "error": "Invalid or expired session"}
            except ImportError:
                pass

        # Route through Gopher server
        try:
            response_text = await self.gopher_server._route(selector)
        except Exception as e:
            return {"status": "error", "error": f"Route error: {e}"}

        from crypto.signing import hash_content, sign_content

        content_hash = hash_content(response_text.encode("utf-8"))
        signature_hex = sign_content(
            response_text.encode("utf-8"),
            self.gopher_server.private_key,
        )

        return {
            "status": "ok",
            "selector": selector,
            "data": response_text,
            "signature": {
                "pid": self.gopher_server.pid_data["pid"],
                "pubkey": self.gopher_server.pid_data["public_key"],
                "sig": signature_hex,
                "hash": content_hash,
            },
        }

    async def stop(self):
        """Clean up the socket file."""
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass


async def start_ipc_server(gopher_server, config: dict = None):
    """Start the IPC server."""
    ipc = IPCServer(gopher_server)
    await ipc.start()
