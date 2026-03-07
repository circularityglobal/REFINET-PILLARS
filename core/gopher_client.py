"""
REFInet Pillar — Async Gopher Client

Enables a Pillar to fetch content from other Gopher servers.
Used for: peer registry sync, hole browsing, self-testing.

SSRF policy: Block loopback only (127.x, ::1). LAN IPs are allowed
since REFInet is a LAN-first sovereign mesh.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass

GOPHER_TIMEOUT = 10  # seconds
MAX_RESPONSE_SIZE = 2 * 1024 * 1024  # 2MB

# Allowed port whitelist
ALLOWED_PORTS = {70, 7070, 105}

# Blocked prefixes — loopback only (LAN IPs allowed for mesh operation)
BLOCKED_HOST_PREFIXES = [
    "127.",
    "0.",
    "::1",
]


@dataclass
class GopherResponse:
    host: str
    port: int
    selector: str
    raw_bytes: bytes
    content_hash: str  # SHA-256 of raw_bytes
    item_type: str     # '1' menu, '0' text, 'I' image, etc.
    size_bytes: int

    @property
    def text(self):
        return self.raw_bytes.decode("utf-8", errors="replace")

    @property
    def is_menu(self):
        return self.item_type == "1"


def _validate_target(host: str, port: int):
    """Raise ValueError if host/port is blocked."""
    if port not in ALLOWED_PORTS:
        raise ValueError(f"Port {port} not in allowed list {ALLOWED_PORTS}")
    for prefix in BLOCKED_HOST_PREFIXES:
        if host.startswith(prefix):
            raise ValueError(f"Host {host} is in blocked range (loopback)")


async def fetch(host: str, port: int, selector: str, item_type: str = "1") -> GopherResponse:
    """
    Fetch a Gopher resource. Returns GopherResponse.
    Raises ValueError on SSRF violation, asyncio.TimeoutError on timeout,
    ConnectionRefusedError if server not reachable.
    """
    _validate_target(host, port)

    # Strip Gopher+ metadata suffixes
    selector = re.sub(r"\t[\+\$].*$", "", selector)

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=GOPHER_TIMEOUT,
    )

    try:
        request = f"{selector}\r\n".encode()
        writer.write(request)
        await writer.drain()

        chunks = []
        total = 0
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=GOPHER_TIMEOUT)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_SIZE:
                raise ValueError(f"Response exceeds {MAX_RESPONSE_SIZE} byte limit")
            chunks.append(chunk)

        raw = b"".join(chunks)
        content_hash = hashlib.sha256(raw).hexdigest()

        return GopherResponse(
            host=host,
            port=port,
            selector=selector,
            raw_bytes=raw,
            content_hash=content_hash,
            item_type=item_type,
            size_bytes=len(raw),
        )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def ping(host: str, port: int, timeout: float = 3) -> float | None:
    """
    TCP ping — sends empty Gopher request, returns latency in ms or None on failure.
    """
    import time
    writer = None
    try:
        _validate_target(host, port)
        start = time.monotonic()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.write(b"\r\n")
        await writer.drain()
        await asyncio.wait_for(reader.read(1024), timeout=timeout)
        elapsed_ms = (time.monotonic() - start) * 1000
        return round(elapsed_ms, 2)
    except Exception:
        return None
    finally:
        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
