"""
REFInet Pillar — HTTP Gateway

Browsers cannot open raw TCP, so an app on a live domain cannot speak
Gopher to its Pillar. This gateway answers the same selectors over plain
HTTP, for a TLS reverse proxy (Caddy, nginx, a cloud load balancer) to
publish at https://<public_domain>/:

    GET /.well-known/refinet.json   the signed domain proof (crypto/wellknown.py)
    GET /health                     liveness for load balancers and the monitor
    GET /g/<selector>               any Gopher selector, e.g. /g/status.json

A /g/ answer's body is exactly the bytes the Gopher listener would have
sent before its signature trailer, and the trailer's fields travel as
headers, so the answer verifies the same way whichever transport served it:

    X-Refinet-Pid, X-Refinet-Pubkey, X-Refinet-Sig (Ed25519 over the body),
    X-Refinet-Hash, X-Refinet-V, X-Refinet-Selector, X-Refinet-Time,
    X-Refinet-Sig1 (the §3.3 envelope signature)

GET/HEAD/OPTIONS only. Off unless ``http_gateway_enabled``; binds loopback
unless ``http_gateway_host`` says otherwise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import quote, unquote, urlsplit

logger = logging.getLogger("refinet.http")

REQUEST_TIMEOUT_SEC = 10
MAX_HEAD_BYTES = 16 * 1024
MAX_SELECTOR_CHARS = 2048

SIGNATURE_HEADERS = {
    "pid": "X-Refinet-Pid",
    "pubkey": "X-Refinet-Pubkey",
    "sig": "X-Refinet-Sig",
    "hash": "X-Refinet-Hash",
    "v": "X-Refinet-V",
    "selector": "X-Refinet-Selector",
    "time": "X-Refinet-Time",
    "sig1": "X-Refinet-Sig1",
}

WELL_KNOWN_CACHE_SEC = 60


def _header_safe(value) -> str:
    """A header value the wire can carry: percent-encode anything outside
    Latin-1 (a selector may hold any UTF-8)."""
    text = str(value)
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return quote(text, safe="!#$&'()*+,/:;=?@[]~")


_REASONS = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found",
            405: "Method Not Allowed", 429: "Too Many Requests",
            500: "Internal Server Error"}


def trailer_fields(sig_block: str) -> dict:
    """The key:value lines of a signature trailer."""
    fields = {}
    for line in sig_block.splitlines():
        if ":" in line and not line.startswith("---"):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def selector_from_path(target: str) -> str | None:
    """Map /g/<path>[?query] to a Gopher selector, or None if it is not one."""
    parts = urlsplit(target)
    if parts.path != "/g" and not parts.path.startswith("/g/"):
        return None
    selector = unquote(parts.path[2:])
    if parts.query:
        selector += "?" + unquote(parts.query)
    if selector == "/":
        selector = ""
    if "\r" in selector or "\n" in selector or len(selector) > MAX_SELECTOR_CHARS:
        raise ValueError("bad selector")
    return selector


class HTTPGateway:
    def __init__(self, gopher_server, host: str = "127.0.0.1", port: int = 7080,
                 cors_origins: list[str] | None = None, trust_proxy: bool = False,
                 config_loader=None):
        self.gopher_server = gopher_server
        self.host = host
        self.port = port
        self.cors_origins = list(cors_origins or [])
        self.trust_proxy = trust_proxy
        # The gateway's own limiter: sharing the Gopher server's would let an
        # HTTP client's traffic (or a spoofed address) block Gopher clients.
        from core.gopher_server import RateLimiter
        self.rate_limiter = RateLimiter()
        self._well_known: tuple[float, bytes] | None = None
        if config_loader is None:
            from core.config import load_config
            config_loader = load_config
        self._load_config = config_loader
        self._server = None

    # -- CORS ----------------------------------------------------------
    def _cors(self, origin: str | None, public: bool = False) -> dict:
        exposed = ", ".join(SIGNATURE_HEADERS.values())
        if public or "*" in self.cors_origins:
            allow = "*"
        elif origin and origin in self.cors_origins:
            allow = origin
        else:
            return {}
        headers = {"Access-Control-Allow-Origin": allow,
                   "Access-Control-Expose-Headers": exposed}
        if allow != "*":
            headers["Vary"] = "Origin"
        return headers

    # -- I/O -----------------------------------------------------------
    async def _send(self, writer, status: int, body: bytes, headers: dict,
                    head_only: bool = False):
        lines = [f"HTTP/1.1 {status} {_REASONS.get(status, 'OK')}"]
        headers = {k: _header_safe(v) for k, v in headers.items()}
        headers = {"Content-Length": str(len(body)), "Connection": "close",
                   "X-Content-Type-Options": "nosniff",
                   "Cache-Control": "no-store", **headers}
        lines += [f"{k}: {v}" for k, v in headers.items()]
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        if not head_only:
            writer.write(body)
        await writer.drain()

    async def _text(self, writer, status: int, text: str, cors: dict, head_only=False):
        await self._send(writer, status, text.encode("utf-8"),
                         {"Content-Type": "text/plain; charset=utf-8", **cors}, head_only)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),
                                              timeout=REQUEST_TIMEOUT_SEC)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                    asyncio.TimeoutError):
                return
            if len(head) > MAX_HEAD_BYTES:
                await self._text(writer, 400, "Request too large\n", {})
                return
            lines = head.decode("latin-1").split("\r\n")
            try:
                method, target, _version = lines[0].split(" ", 2)
            except ValueError:
                await self._text(writer, 400, "Bad request line\n", {})
                return
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    # "X-Forwarded-For : 1.2.3.4" is not a header (RFC 9110),
                    # and a proxy that rewrites the well-formed name would
                    # leave this one untouched for us to believe.
                    if k != k.rstrip():
                        continue
                    headers[k.strip().lower()] = v.strip()
            await self._dispatch(method.upper(), target, headers, writer)
        except Exception as e:
            logger.error(f"[HTTP] error: {e}")
            try:
                await self._text(writer, 500, "Internal error\n", {})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _client_ip(self, writer, headers: dict) -> str:
        if self.trust_proxy and headers.get("x-forwarded-for"):
            # The LAST element is the one our own proxy appended; the earlier
            # ones are whatever the client sent. Reading the first would let
            # anyone rotate the header to dodge the limit, or pin a victim's
            # address to it and have that address blocked.
            return headers["x-forwarded-for"].split(",")[-1].strip()
        peer = writer.get_extra_info("peername")
        return peer[0] if peer else "unknown"

    async def _dispatch(self, method: str, target: str, headers: dict, writer):
        origin = headers.get("origin")
        path = urlsplit(target).path
        public = path in ("/.well-known/refinet.json", "/health")
        cors = self._cors(origin, public=public)

        if method == "OPTIONS":
            await self._send(writer, 204, b"", {
                **cors,
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Max-Age": "86400",
            })
            return
        if method not in ("GET", "HEAD"):
            await self._send(writer, 405, b"", {"Allow": "GET, HEAD, OPTIONS", **cors})
            return
        head_only = method == "HEAD"

        server = self.gopher_server
        if not self.rate_limiter.is_allowed(self._client_ip(writer, headers)):
            await self._text(writer, 429, "Rate limit exceeded. Try again later.\n", cors, head_only)
            return

        if path == "/health":
            body = json.dumps({"status": "ok", "pid": server.pid_data["pid"],
                               "protocol": _version()}).encode("utf-8")
            await self._send(writer, 200, body, {"Content-Type": "application/json", **cors},
                             head_only)
            return

        if path == "/.well-known/refinet.json":
            # Cached: this is an unauthenticated public endpoint, and building
            # the document reads config.json off disk and signs it.
            now = time.time()
            if self._well_known is None or now - self._well_known[0] > WELL_KNOWN_CACHE_SEC:
                from crypto.wellknown import build_well_known
                doc = build_well_known(server.pid_data, server.private_key, self._load_config())
                self._well_known = (now, json.dumps(doc, indent=2).encode("utf-8"))
            await self._send(writer, 200, self._well_known[1],
                             {"Content-Type": "application/json", **cors}, head_only)
            return

        try:
            selector = selector_from_path(target)
        except ValueError:
            await self._text(writer, 400, "Bad selector\n", cors, head_only)
            return
        if selector is None:
            await self._text(writer, 404, "Not found. Gopher selectors are served under /g/\n",
                             cors, head_only)
            return
        if selector.startswith("/download/") and not selector.endswith("/"):
            # Binary downloads are not text answers; they stay on Gopher.
            await self._text(writer, 404, "Downloads are served over Gopher\n", cors, head_only)
            return

        server.request_count += 1
        body, sig_block = await server.respond(selector)
        sig_headers = {SIGNATURE_HEADERS[k]: v for k, v in trailer_fields(sig_block).items()
                       if k in SIGNATURE_HEADERS}
        ctype = "application/json" if selector.endswith(".json") else "text/plain"
        await self._send(writer, 200, body.encode("utf-8"),
                         {"Content-Type": f"{ctype}; charset=utf-8", **sig_headers, **cors},
                         head_only)

    async def start(self):
        self._server = await asyncio.start_server(self.handle, self.host, self.port,
                                                  limit=MAX_HEAD_BYTES)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info(f"HTTP gateway listening on {addrs}")
        async with self._server:
            await self._server.serve_forever()


def _version() -> str:
    from core.version import __version__
    return __version__


async def start_http_gateway(gopher_server, config: dict):
    """Start the gateway when ``http_gateway_enabled`` is set."""
    from core.config import HTTP_GATEWAY_PORT
    gateway = HTTPGateway(
        gopher_server,
        host=config.get("http_gateway_host", "127.0.0.1"),
        port=int(config.get("http_gateway_port", HTTP_GATEWAY_PORT)),
        cors_origins=config.get("http_gateway_cors_origins") or [],
        trust_proxy=bool(config.get("http_gateway_trust_proxy", False)),
    )
    await gateway.start()
