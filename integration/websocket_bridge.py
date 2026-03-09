"""
REFInet Pillar — WebSocket Bridge for Browser Extensions

Bridges WebSocket connections to internal Gopher route handling.
Browser extensions and client apps connect via ws://localhost:7075
and interact with the Pillar using a JSON protocol.

Protocol:
    Request:  {"selector": "/status.json", "session_id": "optional"}
    Response: {"status": "ok", "data": "...", "signature": {...}}

Origin-restricted for browser extension security. Session validation
for authenticated routes.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger("refinet.websocket")

# Optional dependency
try:
    import websockets
    _WEBSOCKETS_AVAILABLE = True
except ImportError:
    _WEBSOCKETS_AVAILABLE = False


def _match_origin(origin: str, allowed: list[str]) -> bool:
    """
    Check if an origin matches the allowed list.

    Supports prefix matching for browser extension origins
    (e.g., "chrome-extension://" matches "chrome-extension://abcdef123").
    """
    if not origin:
        return False
    for pattern in allowed:
        if pattern.endswith("://"):
            # Prefix match for extension schemes
            if origin.startswith(pattern):
                return True
        else:
            # Exact or port-agnostic match (http://localhost matches http://localhost:3000)
            if origin == pattern or origin.startswith(pattern + ":"):
                return True
    return False


class WebSocketBridge:
    """
    WebSocket server that bridges browser clients to the Gopher server.

    Each WebSocket message is a JSON object with a 'selector' field.
    The bridge routes the selector through the Gopher server's _route()
    method and returns the response as JSON.
    """

    def __init__(self, gopher_server, host: str = "127.0.0.1", port: int = 7075,
                 allowed_origins: list[str] | None = None):
        """
        Args:
            gopher_server: GopherServer instance for routing
            host: WebSocket bind address
            port: WebSocket port
            allowed_origins: List of allowed origins (prefix or exact match)
        """
        from core.config import WEBSOCKET_ALLOWED_ORIGINS
        self.gopher_server = gopher_server
        self.host = host
        self.port = port
        self.connection_count = 0
        self.allowed_origins = allowed_origins if allowed_origins is not None else WEBSOCKET_ALLOWED_ORIGINS

    async def start(self):
        """Start the WebSocket server."""
        if not _WEBSOCKETS_AVAILABLE:
            logger.warning("[WS] websockets not installed. Bridge disabled.")
            return

        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            process_request=self._check_origin,
        ):
            logger.info(f"[WS] WebSocket bridge listening on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever

    async def _check_origin(self, path, request_headers):
        """Reject connections from disallowed origins."""
        origin = request_headers.get("Origin")
        if origin and not _match_origin(origin, self.allowed_origins):
            logger.warning(f"[WS] Rejected connection from origin: {origin}")
            return (403, [("Content-Type", "text/plain")], b"Forbidden: origin not allowed")
        return None  # Allow the connection

    async def _handle_connection(self, websocket):
        """Handle a single WebSocket connection."""
        self.connection_count += 1
        remote = websocket.remote_address
        logger.info(f"[WS] Connection from {remote}")

        try:
            async for message in websocket:
                try:
                    response = await self._handle_message(message)
                    await websocket.send(json.dumps(response))
                except Exception as e:
                    error_response = {
                        "status": "error",
                        "error": str(e),
                    }
                    await websocket.send(json.dumps(error_response))
        except Exception as e:
            logger.debug(f"[WS] Connection closed: {e}")

    async def _handle_message(self, raw_message: str) -> dict:
        """Process a single WebSocket message."""
        try:
            request = json.loads(raw_message)
        except json.JSONDecodeError:
            return {"status": "error", "error": "Invalid JSON"}

        # Typed message routing for clean browser extension communication
        msg_type = request.get("type")

        if msg_type == "identity":
            return self._handle_identity()
        elif msg_type == "auth_challenge":
            return self._handle_auth_challenge(request)
        elif msg_type == "auth_verify":
            return self._handle_auth_verify(request)
        elif msg_type == "browse_remote":
            return await self._handle_browse_remote(request)

        # Existing selector-based routing
        selector = request.get("selector", "")
        session_id = request.get("session_id")

        # Validate session for authenticated routes if provided
        if session_id:
            try:
                from auth.session import validate_session
                session = validate_session(session_id)
                if not session:
                    return {"status": "error", "error": "Invalid or expired session"}
            except ImportError:
                pass  # Auth module not available

        # Route through Gopher server
        try:
            response_text = await self.gopher_server._route(selector)
        except Exception as e:
            return {"status": "error", "error": f"Route error: {e}"}

        return self._sign_response(selector, response_text)

    def _handle_identity(self) -> dict:
        """Return Pillar identity as structured JSON."""
        return {
            "status": "ok",
            "type": "identity",
            "pid": self.gopher_server.pid_data["pid"],
            "public_key": self.gopher_server.pid_data["public_key"],
            "key_store": self.gopher_server.pid_data.get("key_store", "software"),
            "protocol": self.gopher_server.pid_data.get("protocol", "0.2.0"),
        }

    def _handle_auth_challenge(self, request: dict) -> dict:
        """Generate a SIWE challenge for wallet authentication."""
        address = request.get("address", "").strip()
        chain_id = request.get("chain_id", 1)

        if not address.startswith("0x") or len(address) != 42:
            return {"status": "error", "error": "Invalid EVM address. Format: 0x followed by 40 hex chars"}

        try:
            chain_id = int(chain_id)
        except (ValueError, TypeError):
            chain_id = 1

        try:
            from auth.session import create_challenge
            challenge = create_challenge(address, chain_id=chain_id)
            return {
                "status": "ok",
                "type": "auth_challenge",
                "message": challenge["message"],
                "nonce": challenge["nonce"],
                "pid": self.gopher_server.pid_data["pid"],
            }
        except ImportError:
            return {"status": "error", "error": "Authentication requires: pip install eth-account"}
        except Exception as e:
            return {"status": "error", "error": f"Challenge error: {e}"}

    def _handle_auth_verify(self, request: dict) -> dict:
        """Verify a signed SIWE challenge and establish a session."""
        address = request.get("address", "").strip()
        signature = request.get("signature", "").strip()
        message = request.get("message", "").strip()

        if not address.startswith("0x") or len(address) != 42:
            return {"status": "error", "error": "Invalid EVM address"}
        if not signature:
            return {"status": "error", "error": "Missing signature"}
        if not message:
            return {"status": "error", "error": "Missing SIWE message"}

        # Domain validation: reject messages issued for Browser sessions
        if "URI: refinet://browser" in message or "URI:refinet://browser" in message:
            return {"status": "error", "error": "Challenge was issued for Browser session, not Pillar session"}

        try:
            from auth.session import establish_session
            session = establish_session(address, message, signature)
            return {
                "status": "ok",
                "type": "auth_verify",
                "session_id": session["session_id"],
                "expires_at": session["expires_at"],
                "pid": session["pid"],
                "address": session["address"],
            }
        except ImportError:
            return {"status": "error", "error": "Authentication requires: pip install eth-account"}
        except ValueError as e:
            return {"status": "error", "error": f"Verification failed: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Auth error: {e}"}

    async def _handle_browse_remote(self, request: dict) -> dict:
        """Browse a remote Pillar, announcing own PID for peer discovery."""
        host = request.get("host", "").strip()
        port = request.get("port", 7070)
        selector = request.get("selector", "")
        session_id = request.get("session_id")

        if not host:
            return {"status": "error", "error": "Missing remote host"}

        try:
            port = int(port)
        except (ValueError, TypeError):
            port = 7070

        # SSRF protection: block private/loopback addresses
        _blocked_prefixes = (
            "127.", "0.", "10.", "192.168.", "169.254.",
            "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.",
            "172.24.", "172.25.", "172.26.", "172.27.",
            "172.28.", "172.29.", "172.30.", "172.31.",
            "::1", "fe80:", "fd",
        )
        if any(host.startswith(p) for p in _blocked_prefixes) or host == "localhost":
            return {"status": "error", "error": "Blocked destination: private/loopback address"}

        # Port restriction: only Gopher ports
        allowed_ports = {70, 7070, 105}
        if port not in allowed_ports:
            return {"status": "error", "error": f"Port {port} not allowed. Use 70, 7070, or 105"}

        # Validate session if provided
        visiting_pid = None
        if session_id:
            try:
                from auth.session import validate_session
                session = validate_session(session_id)
                if session:
                    visiting_pid = self.gopher_server.pid_data["pid"]
            except ImportError:
                pass

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=15.0
            )
            try:
                # Send selector with optional PID announcement
                gopher_request = selector
                if visiting_pid:
                    # REFInet extension: append PID for peer discovery
                    gopher_request += f"\tPID:{visiting_pid}"
                writer.write(f"{gopher_request}\r\n".encode("utf-8"))
                await writer.drain()
                response = await asyncio.wait_for(reader.read(65536), timeout=30.0)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

            response_text = response.decode("utf-8", errors="replace")

            # Extract remote PID from signature block if present
            remote_pid = None
            if "---BEGIN REFINET SIGNATURE---" in response_text:
                for line in response_text.split("\n"):
                    if line.startswith("pid:"):
                        remote_pid = line[4:].strip()
                        break

            return {
                "status": "ok",
                "type": "browse_remote",
                "host": host,
                "port": port,
                "selector": selector,
                "data": response_text,
                "remote_pid": remote_pid,
                "visiting_pid": visiting_pid,
            }
        except asyncio.TimeoutError:
            return {"status": "error", "error": f"Connection to {host}:{port} timed out"}
        except Exception as e:
            return {"status": "error", "error": f"Remote browse error: {e}"}

    def _sign_response(self, selector: str, response_text: str) -> dict:
        """Build a signed response envelope."""
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


async def start_websocket_bridge(gopher_server, config: dict):
    """
    Start the WebSocket bridge.

    Args:
        gopher_server: GopherServer instance
        config: Pillar configuration dict
    """
    from core.config import WEBSOCKET_PORT

    bridge = WebSocketBridge(
        gopher_server=gopher_server,
        host="127.0.0.1",
        port=config.get("websocket_port", WEBSOCKET_PORT),
    )
    await bridge.start()
