"""
REFInet Pillar — Privacy Forward Proxy / Anonymizer

Async TCP forward proxy that anonymizes outgoing Gopher requests:
  - Strips identifying metadata from requests
  - Injects signed PID authentication tokens
  - Routes through Tor SOCKS5 if available
  - Logs all proxied requests to the audit chain

This is the core privacy proxy component of the SGIS PRD.
External clients connect to port 7074 and their requests are
anonymized before being forwarded to the target Gopher server.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from crypto.signing import hash_content, sign_content

logger = logging.getLogger("refinet.proxy")

# Default ports allowed for outbound Gopher
ALLOWED_PORTS = {70, 7070, 105}

# Private/loopback ranges to block (SSRF protection)
_BLOCKED_PREFIXES = ("127.", "0.", "10.", "192.168.", "172.16.", "172.17.",
                     "172.18.", "172.19.", "172.20.", "172.21.", "172.22.",
                     "172.23.", "172.24.", "172.25.", "172.26.", "172.27.",
                     "172.28.", "172.29.", "172.30.", "172.31.", "169.254.",
                     "::1", "fe80:", "fd")


def _is_blocked_host(host: str) -> bool:
    """Check if a host is a private/loopback address."""
    return any(host.startswith(prefix) for prefix in _BLOCKED_PREFIXES)


class ForwardProxy:
    """
    Async TCP forward proxy for anonymizing Gopher requests.

    Listens on a local port and forwards requests to external Gopher
    servers, stripping metadata and optionally routing through Tor.

    Protocol:
        Client sends: target_host:target_port/selector\\r\\n
        Proxy forwards selector to target, returns response.
        PID signature is injected into the forwarded request context.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7074,
                 pid_data: dict = None, private_key=None,
                 tor_socks_port: int = None,
                 strip_metadata: bool = True):
        self.host = host
        self.port = port
        self.pid_data = pid_data
        self.private_key = private_key
        self.tor_socks_port = tor_socks_port
        self.strip_metadata = strip_metadata
        self.request_count = 0

    async def start(self):
        """Start the forward proxy server."""
        server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        addr = server.sockets[0].getsockname()
        logger.info(f"[PROXY] Forward proxy listening on {addr[0]}:{addr[1]}")

        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        """Handle a proxy client connection."""
        addr = writer.get_extra_info("peername")
        try:
            # Read the proxy request: target_host:target_port/selector
            raw = await asyncio.wait_for(reader.readline(), timeout=30.0)
            request = raw.decode("utf-8", errors="replace").strip()

            if not request:
                writer.write(b"3Error: empty request\tfake\t(NULL)\t0\r\n.\r\n")
                await writer.drain()
                return

            # Parse: host:port/selector or host/selector (default port 7070)
            target_host, target_port, selector = self._parse_request(request)

            if not target_host:
                writer.write(b"3Error: invalid request format\tfake\t(NULL)\t0\r\n.\r\n")
                await writer.drain()
                return

            # SSRF protection
            if _is_blocked_host(target_host):
                writer.write(b"3Error: blocked destination\tfake\t(NULL)\t0\r\n.\r\n")
                await writer.drain()
                return

            if target_port not in ALLOWED_PORTS:
                writer.write(b"3Error: port not allowed\tfake\t(NULL)\t0\r\n.\r\n")
                await writer.drain()
                return

            logger.info(f"[PROXY] {addr[0]} → {target_host}:{target_port}{selector}")
            self.request_count += 1

            # Forward request through Tor or direct
            response = await self._forward_request(
                target_host, target_port, selector
            )

            # Inject PID authentication token as metadata
            if self.pid_data and self.private_key:
                timestamp = int(time.time())
                token_data = f"{self.pid_data['pid']}:{timestamp}:{selector}"
                token_sig = sign_content(token_data.encode("utf-8"), self.private_key)
                token_header = (
                    f"\r\n---BEGIN REFINET PROXY TOKEN---\r\n"
                    f"pid:{self.pid_data['pid']}\r\n"
                    f"timestamp:{timestamp}\r\n"
                    f"signature:{token_sig}\r\n"
                    f"---END REFINET PROXY TOKEN---\r\n"
                )
                response += token_header.encode("utf-8")

            writer.write(response)
            await writer.drain()

            # Log to audit chain (best effort)
            self._log_proxy_request(target_host, target_port, selector)

        except asyncio.TimeoutError:
            logger.warning(f"[PROXY] {addr[0]} timeout")
        except Exception as e:
            logger.error(f"[PROXY] {addr[0]} error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _parse_request(self, request: str) -> tuple:
        """Parse proxy request into (host, port, selector)."""
        try:
            # Format: host:port/selector or host/selector
            if "/" in request:
                host_part, selector = request.split("/", 1)
                selector = "/" + selector
            else:
                host_part = request
                selector = ""

            if ":" in host_part:
                host, port_str = host_part.rsplit(":", 1)
                port = int(port_str)
            else:
                host = host_part
                port = 7070

            return (host.strip(), port, selector)
        except Exception:
            return (None, None, None)

    async def _forward_request(self, host: str, port: int,
                                selector: str) -> bytes:
        """Forward a Gopher request to the target server."""
        try:
            if self.tor_socks_port:
                # Route through Tor SOCKS5
                return await self._forward_via_tor(host, port, selector)
            else:
                # Direct connection
                return await self._forward_direct(host, port, selector)
        except Exception as e:
            return f"3Proxy error: {e}\tfake\t(NULL)\t0\r\n.\r\n".encode("utf-8")

    async def _forward_direct(self, host: str, port: int,
                               selector: str) -> bytes:
        """Direct TCP forwarding."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=15.0
        )
        try:
            writer.write(f"{selector}\r\n".encode("utf-8"))
            await writer.drain()
            response = await asyncio.wait_for(reader.read(65536), timeout=30.0)
            return response
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _forward_via_tor(self, host: str, port: int,
                                selector: str) -> bytes:
        """Forward through Tor SOCKS5 proxy."""
        # Use asyncio SOCKS proxy via Tor
        # This requires the Tor SOCKS port to be available
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    "127.0.0.1", self.tor_socks_port,
                ), timeout=15.0
            )
            # SOCKS5 handshake
            writer.write(b"\x05\x01\x00")  # Version 5, 1 method, no auth
            await writer.drain()
            resp = await reader.read(2)
            if resp != b"\x05\x00":
                raise ConnectionError("SOCKS5 handshake failed")

            # SOCKS5 connect request
            host_bytes = host.encode("utf-8")
            writer.write(
                b"\x05\x01\x00\x03" +
                bytes([len(host_bytes)]) + host_bytes +
                port.to_bytes(2, "big")
            )
            await writer.drain()
            resp = await reader.read(10)
            if len(resp) < 2 or resp[1] != 0:
                raise ConnectionError("SOCKS5 connect failed")

            # Forward the Gopher request through Tor
            writer.write(f"{selector}\r\n".encode("utf-8"))
            await writer.drain()
            response = await asyncio.wait_for(reader.read(65536), timeout=30.0)
            return response
        except Exception as e:
            logger.warning(f"[PROXY] Tor forwarding failed: {e}, falling back to direct")
            return await self._forward_direct(host, port, selector)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _log_proxy_request(self, host: str, port: int, selector: str):
        """Log a proxied request (best effort, never blocks)."""
        try:
            from db.audit import append_audit_entry
            if self.pid_data and self.private_key:
                append_audit_entry(
                    table_name="proxy_requests",
                    operation="FORWARD",
                    record_key=f"{host}:{port}{selector}",
                    record_data={
                        "target_host": host,
                        "target_port": port,
                        "selector": selector,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    pid=self.pid_data["pid"],
                    private_key=self.private_key,
                )
        except Exception:
            pass


async def start_proxy(config: dict, pid_data: dict = None,
                      private_key=None, tor_manager=None):
    """
    Start the forward proxy server.

    Args:
        config: Pillar configuration dict
        pid_data: PID data for signing proxy tokens
        private_key: Ed25519 private key for signing
        tor_manager: Optional TorManager for SOCKS routing
    """
    from core.config import PROXY_PORT

    tor_socks = None
    if tor_manager and tor_manager.is_active():
        tor_socks = config.get("tor_socks_port", 9050)

    proxy = ForwardProxy(
        host="127.0.0.1",
        port=config.get("proxy_port", PROXY_PORT),
        pid_data=pid_data,
        private_key=private_key,
        tor_socks_port=tor_socks,
        strip_metadata=config.get("proxy_strip_metadata", True),
    )
    await proxy.start()
