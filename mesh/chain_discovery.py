"""
REFInet Pillar — Chain discovery (the staking contract is the directory)

Multicast finds Pillars on the same LAN. Pillars on the open internet —
pillar.example.com on a VPS, pillars.google.com in someone's cloud — find
each other here instead:

  1. read every registered PID from PillarStaking (``pidsPage``);
  2. keep the ones ``isActive`` with an endpoint;
  3. fetch ``https://<endpoint>/.well-known/refinet.json`` and verify it
     names that PID, claims that domain, and is signed by the PID's key;
  4. record the peer at the Gopher endpoint the document gives.

Replication and health checks then treat it like any other peer. No
bootstrap node is involved, and nothing here runs unless
``staking_contracts`` is configured.

Endpoints come from the chain, so anyone with a stake chooses one. The
fetch resolves the name, refuses private/loopback/link-local addresses,
connects to the address it checked (no second DNS lookup), follows no
redirects and reads at most MAX_DOC_BYTES.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import logging
import socket
import ssl

from crypto.wellknown import (
    WELL_KNOWN_PATH, gopher_endpoint, is_valid_domain, normalize_domain,
    verify_well_known,
)

logger = logging.getLogger("refinet.chain_discovery")

CHAIN_DISCOVERY_INTERVAL_SEC = 900
FETCH_TIMEOUT_SEC = 10
MAX_DOC_BYTES = 64 * 1024
CONCURRENCY = 8
# A Pillar signs its domain proof per request, so a stale one means a stored
# copy — possibly from before the Pillar moved domains.
WELL_KNOWN_MAX_AGE_SEC = 7 * 86400


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a pre-resolved address, with SNI and certificate checks
    against the host name."""

    def __init__(self, host: str, ip: str, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _https_get(domain: str, ip: str, path: str) -> tuple[dict, bytes]:
    """GET one document over TLS from a pre-resolved address.

    Returns (headers, body). The certificate is checked against *domain*,
    not the address, by ssl.create_default_context().
    """
    conn = _PinnedHTTPSConnection(domain, ip, port=443, timeout=FETCH_TIMEOUT_SEC,
                                  context=ssl.create_default_context())
    try:
        conn.request("GET", path, headers={"User-Agent": "refinet-pillar",
                                           "Accept": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        body = resp.read(MAX_DOC_BYTES + 1)
        if len(body) > MAX_DOC_BYTES:
            raise ValueError("document too large")
        return ({k.lower(): v for k, v in resp.getheaders()}, body)
    finally:
        conn.close()


async def fetch_well_known(domain: str) -> dict:
    """Fetch and parse https://<domain>/.well-known/refinet.json safely."""
    from integration.websocket_bridge import resolve_public_address
    domain = normalize_domain(domain)
    if not is_valid_domain(domain):
        raise ValueError(f"not a domain: {domain!r}")
    ip = await resolve_public_address(domain, 443)
    loop = asyncio.get_event_loop()
    _headers, body = await loop.run_in_executor(None, _https_get, domain, ip, WELL_KNOWN_PATH)
    return json.loads(body)


async def discover_peer(pid: str, reader, fetch=fetch_well_known) -> dict | None:
    """Verify one directory entry. Returns the peer record, or None."""
    status = await reader.status(pid)
    if not status.active or not status.endpoint:
        return None
    doc = await fetch(status.endpoint)
    ok, reason = verify_well_known(doc, expected_pid=pid, expected_domain=status.endpoint,
                                   max_age_sec=WELL_KNOWN_MAX_AGE_SEC)
    if not ok:
        logger.info(f"Directory entry {pid[:16]}... @ {status.endpoint} rejected: {reason}")
        return None
    endpoint = gopher_endpoint(doc)
    if not endpoint:
        return None
    host, port = endpoint
    if host != normalize_domain(status.endpoint):
        # The document is verified for this domain only; a Gopher host
        # elsewhere would let a staked entry aim replication at any address.
        logger.info(f"Directory entry {pid[:16]}...: gopher host {host} is not "
                    f"its endpoint {normalize_domain(status.endpoint)}")
        return None
    return {
        "pid": pid,
        "public_key": doc["public_key"],
        "hostname": host,
        "port": port,
        "domain": status.endpoint,
        "pillar_name": status.endpoint,
        "protocol_version": doc.get("protocol"),
    }


async def discover_once(own_pid: str, reader, fetch=fetch_well_known,
                        upsert=None) -> int:
    """One pass over the directory. Returns how many peers were recorded."""
    if upsert is None:
        from db.live_db import upsert_peer as upsert
    pids = [p for p in await reader.directory() if p != own_pid]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _one(pid):
        async with sem:
            try:
                return await discover_peer(pid, reader, fetch)
            except Exception as exc:
                logger.debug(f"Directory entry {pid[:16]}... unreachable: {exc}")
                return None

    found = await asyncio.gather(*[_one(p) for p in pids])
    recorded = 0
    for peer in found:
        if not peer:
            continue
        upsert(pid=peer["pid"], public_key=peer["public_key"], hostname=peer["hostname"],
               port=peer["port"], pillar_name=peer["pillar_name"],
               protocol_version=peer["protocol_version"])
        recorded += 1
    return recorded


async def periodic_chain_discovery(own_pid: str, config: dict):
    """Background task: sync peers from the staking directory."""
    from mesh.staking import get_reader
    reader = get_reader(config)
    if reader is None:
        return
    logger.info(f"Chain discovery started ({len(reader.contracts)} contract(s), "
                f"every {CHAIN_DISCOVERY_INTERVAL_SEC // 60} min)")
    await asyncio.sleep(10)
    while True:
        try:
            n = await discover_once(own_pid, reader)
            if n:
                logger.info(f"Chain discovery: {n} staked peer(s) verified")
        except Exception as exc:
            logger.warning(f"Chain discovery error: {exc}")
        await asyncio.sleep(CHAIN_DISCOVERY_INTERVAL_SEC)
