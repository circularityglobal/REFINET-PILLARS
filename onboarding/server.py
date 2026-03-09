"""
REFInet Pillar — Onboarding TCP Server

A minimal async Gopher server that serves only the onboarding wizard.
Runs on the same port (7070) as the main REFInet server — but the main
server has not started yet.  Once the wizard reaches COMPLETE this
server shuts down and control returns to ``pillar.py`` which boots the
full Pillar stack.

The TCP handler follows the exact same pattern as
``GopherServer.handle_client()`` in ``core/gopher_server.py``:
  1. Rate-limit check per source IP.
  2. Read selector + CRLF (with 30-second timeout).
  3. Split tab-separated search query if present.
  4. Route through ``handle_wizard_step()``.
  5. Write response, drain, close.

A WebSocket bridge is also started so the browser extension can drive
the SIWE signing flow during onboarding.
"""

from __future__ import annotations

import asyncio
import logging

from core.config import GOPHER_HOST, WEBSOCKET_PORT, load_config
from core.gopher_server import RateLimiter
from core.menu_builder import info_line
from onboarding.wizard import (
    handle_wizard_step,
    is_onboarding_complete,
    get_onboarding_state,
)

logger = logging.getLogger("refinet.onboarding.server")

# How often (seconds) the completion poller checks wizard state
_POLL_INTERVAL = 2


def _error_response(message: str) -> str:
    """Generate a Gopher error menu (mirrors GopherServer._error_response)."""
    lines = []
    lines.append(info_line(""))
    lines.append(info_line(f"  ERROR: {message}"))
    lines.append(info_line(""))
    return "".join(lines)


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    hostname: str,
    port: int,
    rate_limiter: RateLimiter,
) -> None:
    """
    Handle a single Gopher client connection during onboarding.

    Mirrors the flow of ``GopherServer.handle_client()``:
    rate-limit ➜ read selector+CRLF ➜ route ➜ write ➜ close.
    """
    addr = writer.get_extra_info("peername")
    try:
        # --- Rate-limit check (same pattern as GopherServer) ---
        if not rate_limiter.is_allowed(addr[0]):
            logger.warning("[%s:%s] rate limited during onboarding",
                           addr[0], addr[1])
            writer.write(
                _error_response("Rate limit exceeded. Try again later.")
                .encode("utf-8")
            )
            await writer.drain()
            return

        # --- Read selector (Gopher: client sends selector + CRLF) ---
        raw = await asyncio.wait_for(reader.readline(), timeout=30.0)
        full_line = raw.decode("utf-8", errors="replace").strip()

        # Gopher search queries arrive as: selector<TAB>query
        if "\t" in full_line:
            selector, query = full_line.split("\t", 1)
        else:
            selector = full_line
            query = ""

        # Normalise empty selector to the wizard root
        if not selector or selector == "/":
            selector = "/onboarding"

        logger.info("[%s:%s] onboarding selector='%s'", addr[0], addr[1],
                    selector)

        # --- Route through wizard state machine ---
        response = await handle_wizard_step(selector, query, hostname, port)

        # --- Write response ---
        writer.write(response.encode("utf-8"))
        await writer.drain()

    except asyncio.TimeoutError:
        logger.debug("[%s:%s] read timeout during onboarding",
                     addr[0], addr[1])
    except ConnectionResetError:
        logger.debug("[%s:%s] connection reset during onboarding",
                     addr[0], addr[1])
    except Exception as exc:
        logger.warning("[%s:%s] onboarding error: %s", addr[0], addr[1], exc)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def run_onboarding_server(host: str = GOPHER_HOST,
                                port: int = 7070) -> None:
    """
    Serve the onboarding wizard over Gopher until complete.

    Uses the same ``asyncio.start_server`` TCP pattern as
    ``GopherServer`` in ``core/gopher_server.py``.  All selectors are
    routed through ``handle_wizard_step()``.  A ``RateLimiter``
    (imported from ``core/gopher_server``) protects against abuse.

    The function blocks until ``is_onboarding_complete()`` returns True
    (polled every ``_POLL_INTERVAL`` seconds), then tears down the TCP
    server, the WebSocket bridge, and returns so that ``pillar.py`` can
    proceed with normal startup.
    """
    config = load_config()
    hostname = config.get("hostname", "localhost")

    # Same rate limiter as GopherServer (100 req/min per IP)
    rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

    # TCP handler closure — captures hostname, port, rate_limiter
    async def client_handler(reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        await _handle_client(reader, writer, hostname, port, rate_limiter)

    server = await asyncio.start_server(client_handler, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)

    # --- Banner ---
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     R E F I n e t   O N B O A R D I N G ║")
    print("  ║        First-Run Identity Wizard         ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print(f"  Onboarding server listening on {addrs}")
    print()
    print("  Connect with a Gopher client to complete setup:")
    print(f"    curl gopher://localhost:{port}/")
    print(f"    lynx gopher://localhost:{port}")
    print()
    print("  Or use the REFInet browser extension.")
    print()

    logger.info("Onboarding server started on %s", addrs)

    # --- WebSocket bridge (optional, for browser extension SIWE flow) ---
    ws_task = None
    try:
        from integration.websocket_bridge import start_websocket_bridge
        ws_task = asyncio.create_task(
            start_websocket_bridge(None, config)
        )
        logger.info("WebSocket bridge started for onboarding (port %s)",
                     config.get("websocket_port", WEBSOCKET_PORT))
    except Exception as exc:
        logger.info("WebSocket bridge not available during onboarding: %s",
                     exc)

    # --- Poll for wizard completion ---
    try:
        async with server:
            while True:
                await asyncio.sleep(_POLL_INTERVAL)
                state = get_onboarding_state()
                if state.get("step") == "COMPLETE" and is_onboarding_complete():
                    logger.info(
                        "Onboarding complete — shutting down wizard server"
                    )
                    break
    finally:
        server.close()
        await server.wait_closed()
        if ws_task and not ws_task.done():
            ws_task.cancel()
            try:
                await ws_task
            except (asyncio.CancelledError, Exception):
                pass

    print()
    print("  Onboarding complete. Starting full Pillar services...")
    print()
