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


class BlockedDestination(Exception):
    """Raised when a destination resolves to an address we refuse to visit."""


def address_is_public(ip: str) -> bool:
    """False for loopback, private, link-local, reserved and multicast."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None) is not None:
        addr = addr.ipv4_mapped        # [::ffff:127.0.0.1] is 127.0.0.1
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


async def resolve_public_address(host: str, port: int) -> str:
    """Resolve *host* and return an address that is safe to connect to.

    Raises BlockedDestination when the name resolves to a private,
    loopback, link-local, reserved or multicast address.
    """
    import socket
    loop = asyncio.get_event_loop()
    infos = await loop.getaddrinfo(host.strip("[]"), port,
                                   type=socket.SOCK_STREAM)
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise BlockedDestination(f"{host} did not resolve")
    for ip in addresses:
        if not address_is_public(ip):
            raise BlockedDestination(f"{host} resolves to {ip}")
    return addresses[0]


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
                 allowed_origins: list[str] | None = None,
                 extension_ids: list[str] | None = None,
                 require_origin: bool | None = None):
        """
        Args:
            gopher_server: GopherServer instance for routing
            host: WebSocket bind address
            port: WebSocket port
            allowed_origins: List of allowed origins (prefix or exact match)
            extension_ids: When non-empty, only these extension ids are
                admitted (plus loopback origins)
            require_origin: Refuse connections that send no Origin header
        """
        from core.config import WEBSOCKET_ALLOWED_ORIGINS
        self.gopher_server = gopher_server
        self.host = host
        self.port = port
        self.connection_count = 0
        self.allowed_origins = allowed_origins if allowed_origins is not None else WEBSOCKET_ALLOWED_ORIGINS

        config = {}
        if extension_ids is None or require_origin is None or allowed_origins is None:
            try:
                from core.config import load_config
                config = load_config()
            except Exception:
                config = {}
        self.extension_ids = (extension_ids if extension_ids is not None
                              else config.get("websocket_extension_ids") or [])
        self.require_origin = (require_origin if require_origin is not None
                               else bool(config.get("websocket_require_origin", False)))
        # An app paired with this Pillar (https://app.example.com) is added by
        # exact origin; the defaults above stay as they were.
        if allowed_origins is None:
            extra = [o for o in (config.get("websocket_allowed_origins") or [])
                     if isinstance(o, str) and "://" in o and not o.endswith("://")]
            self.allowed_origins = list(self.allowed_origins) + extra
        if self.extension_ids:
            self.allowed_origins = (
                [f"chrome-extension://{i}" for i in self.extension_ids]
                + [f"moz-extension://{i}" for i in self.extension_ids]
                + [o for o in self.allowed_origins if not o.endswith("://")]
            )
        elif not self.require_origin:
            logger.info(
                "[WS] Any browser extension may connect. Set "
                "websocket_extension_ids in config.json to restrict it."
            )

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

    async def _check_origin(self, connection, request):
        """Reject connections from disallowed origins."""
        origin = request.headers.get("Origin")
        if not origin:
            if self.require_origin:
                logger.warning("[WS] Rejected connection with no Origin header")
                return connection.respond(403, "Forbidden: Origin required\n")
            return None  # Historical behaviour: non-browser local clients
        if not _match_origin(origin, self.allowed_origins):
            logger.warning(f"[WS] Rejected connection from origin: {origin}")
            return connection.respond(403, "Forbidden: origin not allowed\n")
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
        elif msg_type == "onboarding_connect":
            return await self._handle_onboarding_connect(request)
        elif msg_type == "onboarding_signature":
            return await self._handle_onboarding_signature(request)
        elif msg_type == "rebind":
            return await self._handle_rebind(request)

        # Existing selector-based routing (requires gopher_server)
        if self.gopher_server is None:
            return {"status": "error",
                    "error": "Pillar is in onboarding mode. Use onboarding_connect to complete setup."}

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
        """Return Pillar identity as structured JSON.

        During onboarding (gopher_server is None), loads PID directly
        from disk and sets ``onboarding: true`` so the browser extension
        can detect onboarding mode.
        """
        if self.gopher_server is None:
            # Onboarding mode — gopher_server not started yet
            from crypto.pid import load_pid
            pid_data = load_pid()
            resp = {"status": "ok", "type": "identity", "onboarding": True}
            if pid_data:
                resp["pid"] = pid_data["pid"]
                resp["public_key"] = pid_data["public_key"]
                resp["key_store"] = pid_data.get("key_store", "software")
                resp["protocol"] = pid_data.get("protocol", "0.3.0")
            else:
                resp["pid"] = None
            return resp

        return {
            "status": "ok",
            "type": "identity",
            "pid": self.gopher_server.pid_data["pid"],
            "public_key": self.gopher_server.pid_data["public_key"],
            "key_store": self.gopher_server.pid_data.get("key_store", "software"),
            "protocol": self.gopher_server.pid_data.get("protocol", "0.3.0"),
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

    async def _handle_onboarding_connect(self, request: dict) -> dict:
        """Handle wallet address submission during onboarding.

        Ensures a PID exists (generates one if needed), stores the
        address in wizard state, generates a SIWE challenge, and
        returns it so the browser extension can invoke personal_sign.
        """
        address = request.get("address", "").strip()
        if not address.startswith("0x") or len(address) != 42:
            return {"status": "error", "type": "onboarding_connect",
                    "error": "Invalid EVM address. Format: 0x + 40 hex chars"}

        password = request.get("password")  # optional encryption password

        # Ensure PID exists (generate if first-run)
        from crypto.pid import load_pid, generate_pid, save_pid
        from crypto.unlock import unlock
        pid_data = load_pid()
        if pid_data is None:
            pid_data = generate_pid(password=password)
            save_pid(pid_data)
            logger.info("[WS] Onboarding: generated PID %s", pid_data["pid"][:16])
        if password:
            # Unlock in memory for the signature step. The password itself
            # is never written to onboarding_state.json.
            try:
                unlock(pid_data, password)
            except ValueError as e:
                return {"status": "error", "type": "onboarding_connect",
                        "error": f"Cannot unlock private key: {e}"}

        # Advance wizard state
        from onboarding.wizard import get_onboarding_state, save_onboarding_state
        state = get_onboarding_state()
        state["step"] = "STEP_SIWE_CHALLENGE"
        state["pid"] = pid_data["pid"]
        state["evm_address"] = address

        # Generate SIWE challenge
        try:
            from auth.session import create_challenge
            from auth.siwe import PURPOSE_BINDING
            chain_id = int(request.get("chain_id", 1))
            # Onboarding creates a binding, so it issues a binding challenge
            # (§3.1) — not the sign-in message it used before 0.5.0.
            challenge = create_challenge(address, chain_id=chain_id,
                                         purpose=PURPOSE_BINDING,
                                         binding_type="deployer",
                                         company_url=request.get("company_url"))
        except ImportError:
            return {"status": "error", "type": "onboarding_connect",
                    "error": "SIWE requires: pip install eth-account"}
        except Exception as e:
            return {"status": "error", "type": "onboarding_connect",
                    "error": f"Challenge generation failed: {e}"}

        state["challenge_nonce"] = challenge["nonce"]
        state["siwe_message"] = challenge["message"]
        save_onboarding_state(state)

        logger.info("[WS] Onboarding: challenge issued for %s", address)

        return {
            "status": "ok",
            "type": "onboarding_challenge",
            "message": challenge["message"],
            "pid": pid_data["pid"],
        }

    async def _handle_onboarding_signature(self, request: dict) -> dict:
        """Handle wallet signature submission during onboarding.

        Verifies the SIWE signature against the stored challenge,
        creates the deployer binding, and marks onboarding complete.
        """
        signature = request.get("signature", "").strip()
        if not signature:
            return {"status": "error", "type": "onboarding_signature",
                    "error": "Missing signature"}

        from crypto.pid import load_pid
        from crypto.unlock import unlock, get_unlocked_key
        from onboarding.wizard import get_onboarding_state, save_onboarding_state
        from crypto.binding import create_binding

        pid_data = load_pid()
        if pid_data is None:
            return {"status": "error", "type": "onboarding_signature",
                    "error": "No PID found — send onboarding_connect first"}

        state = get_onboarding_state()
        siwe_message = state.get("siwe_message", "")
        evm_address = state.get("evm_address", "")
        if not siwe_message or not evm_address:
            return {"status": "error", "type": "onboarding_signature",
                    "error": "No challenge pending — send onboarding_connect first"}

        try:
            password = request.get("password")
            if password:
                priv_key = unlock(pid_data, password)
            else:
                priv_key = get_unlocked_key(pid_data)
        except ValueError as e:
            # Encrypted key, cold process: resend with "password" to unlock.
            return {"status": "error", "type": "onboarding_signature",
                    "error": f"Cannot unlock private key: {e}",
                    "locked": True, "need": "password"}

        try:
            binding = create_binding(
                pid_data=pid_data,
                evm_address=evm_address,
                siwe_message=siwe_message,
                siwe_signature=signature,
                # chain_id comes from the message the wallet signed
                private_key=priv_key,
                binding_type=state.get("binding_type", "deployer"),
            )
        except (ValueError, Exception) as e:
            logger.warning("[WS] Onboarding: binding failed — %s", e)
            return {"status": "error", "type": "onboarding_signature",
                    "error": f"Binding failed: {e}"}

        # Mark onboarding complete
        state["step"] = "COMPLETE"
        state["binding_id"] = binding["binding_id"]
        save_onboarding_state(state)

        logger.info("[WS] Onboarding: binding created — %s", binding["binding_id"][:16])

        return {
            "status": "ok",
            "type": "onboarding_complete",
            "binding_id": binding["binding_id"],
            "pid": binding["pid"],
            "evm_address": binding["evm_address"],
        }

    async def _handle_rebind(self, request: dict) -> dict:
        """Add a §3.1 binding to a Pillar that is already onboarded.

        Two steps, both ``{"type": "rebind"}``:
          1. ``{"address": "0x..", "binding_type": "deployer"|"operator",
                "chain_id": 43113, "company_url": "https://..."}``
             returns the binding challenge to sign;
          2. ``{"address": "0x..", "message": "<the challenge>",
                "signature": "0x.."}`` writes the binding.

        This is how a Pillar whose only binding was made from a sign-in
        signature (pre-0.5.0) gets a proper one: it needs the wallet, so it
        can never happen silently. Bindings are append-only — the old row
        stays, and the new one becomes canonical.
        """
        address = request.get("address", "").strip()
        if not address.startswith("0x") or len(address) != 42:
            return {"status": "error", "type": "rebind",
                    "error": "Invalid EVM address. Format: 0x + 40 hex chars"}

        binding_type = request.get("binding_type", "deployer")
        if binding_type not in ("deployer", "operator"):
            return {"status": "error", "type": "rebind",
                    "error": "binding_type must be 'deployer' or 'operator'"}

        from crypto.pid import load_pid
        pid_data = (self.gopher_server.pid_data
                    if self.gopher_server is not None else load_pid())
        if pid_data is None:
            return {"status": "error", "type": "rebind", "error": "No PID found"}

        signature = request.get("signature", "").strip()
        message = request.get("message", "")

        # Step 1 — issue the challenge
        if not signature:
            try:
                from auth.session import create_challenge
                from auth.siwe import PURPOSE_BINDING
                chain_id = int(request.get("chain_id", 1))
                challenge = create_challenge(
                    address, chain_id=chain_id, purpose=PURPOSE_BINDING,
                    binding_type=binding_type,
                    company_url=request.get("company_url"))
            except ImportError:
                return {"status": "error", "type": "rebind",
                        "error": "SIWE requires: pip install eth-account"}
            except Exception as e:
                return {"status": "error", "type": "rebind",
                        "error": f"Challenge generation failed: {e}"}
            return {"status": "ok", "type": "rebind_challenge",
                    "message": challenge["message"], "pid": pid_data["pid"],
                    "binding_type": binding_type}

        # Step 2 — write the binding
        if not message:
            return {"status": "error", "type": "rebind",
                    "error": "Missing the signed message"}
        try:
            from crypto.unlock import unlock, get_unlocked_key
            password = request.get("password")
            priv_key = (unlock(pid_data, password) if password
                        else get_unlocked_key(pid_data))
        except ValueError as e:
            return {"status": "error", "type": "rebind",
                    "error": f"Cannot unlock private key: {e}",
                    "locked": True, "need": "password"}

        try:
            from crypto.binding import create_binding
            binding = create_binding(
                pid_data=pid_data,
                evm_address=address,
                siwe_message=message,
                siwe_signature=signature,
                private_key=priv_key,
                binding_type=binding_type,
            )
        except Exception as e:
            logger.warning("[WS] Rebind failed — %s", e)
            return {"status": "error", "type": "rebind", "error": f"Binding failed: {e}"}

        logger.info("[WS] Rebind: %s binding created — %s",
                    binding_type, binding["binding_id"][:16])
        return {"status": "ok", "type": "rebind_complete",
                "binding_id": binding["binding_id"], "pid": binding["pid"],
                "evm_address": binding["evm_address"],
                "binding_type": binding["binding_type"],
                "chain_id": binding["chain_id"]}

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

        # Port restriction: only Gopher ports
        allowed_ports = {70, 7070, 105}
        if port not in allowed_ports:
            return {"status": "error", "error": f"Port {port} not allowed. Use 70, 7070, or 105"}

        # SSRF protection: resolve the name first, then judge the address.
        # A string prefix check passes 0x7f000001, 2130706433, 127.1 and
        # [::ffff:127.0.0.1], and blocks innocent names like fdroid.org.
        try:
            resolved = await resolve_public_address(host, port)
        except BlockedDestination as e:
            return {"status": "error", "error": f"Blocked destination: {e}"}
        except OSError as e:
            return {"status": "error", "error": f"Cannot resolve {host}: {e}"}

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
            # Connect to the address that was checked, so a second DNS
            # answer cannot point somewhere else between check and connect.
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(resolved, port), timeout=15.0
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
            remote_verified = None
            if "---BEGIN REFINET SIGNATURE---" in response_text:
                for line in response_text.split("\n"):
                    if line.startswith("pid:"):
                        remote_pid = line[4:].strip()
                        break
                from crypto.signing import verify_response_block
                remote_verified = verify_response_block(response_text)["valid"]

            return {
                "status": "ok",
                "type": "browse_remote",
                "host": host,
                "port": port,
                "selector": selector,
                "data": response_text,
                "remote_pid": remote_pid,
                "remote_verified": remote_verified,
                "visiting_pid": visiting_pid,
            }
        except asyncio.TimeoutError:
            return {"status": "error", "error": f"Connection to {host}:{port} timed out"}
        except Exception as e:
            return {"status": "error", "error": f"Remote browse error: {e}"}

    def _sign_response(self, selector: str, response_text: str) -> dict:
        """Build a signed response envelope."""
        import time
        from crypto.signing import (
            hash_content, sign_content, response_envelope_signature,
        )

        body = response_text.encode("utf-8")
        content_hash = hash_content(body)
        pid = self.gopher_server.pid_data["pid"]
        # "sig" keeps its original meaning (Ed25519 over the raw data) so
        # existing extension builds keep verifying. "sig1" is the envelope
        # signature binding selector and time, same as the Gopher trailer.
        signature_hex = sign_content(body, self.gopher_server.private_key)
        now = int(time.time())
        envelope_sig = response_envelope_signature(
            self.gopher_server.private_key, pid, selector or "/", now, content_hash,
        )

        return {
            "status": "ok",
            "selector": selector,
            "data": response_text,
            "signature": {
                "pid": pid,
                "pubkey": self.gopher_server.pid_data["public_key"],
                "sig": signature_hex,
                "hash": content_hash,
                "v": 1,
                "selector": selector or "/",
                "time": now,
                "sig1": envelope_sig,
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
        # Loopback unless the operator fronts it with a TLS proxy
        host=config.get("websocket_host") or "127.0.0.1",
        port=config.get("websocket_port", WEBSOCKET_PORT),
    )
    await bridge.start()
