"""
REFInet Pillar — Mesh Peer Discovery

Pillars discover each other on local networks via UDP multicast.
No DNS, no central registry — just broadcast your existence.

This is the foundation of the REFInet mesh:
  - Each Pillar announces itself periodically
  - Neighbors listen and register new peers
  - Peer lists propagate organically

Think of it like Lightning Network channel discovery, but for Gopher.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import logging
import time
from pathlib import Path

from core.config import (
    MULTICAST_GROUP,
    MULTICAST_PORT,
    DISCOVERY_INTERVAL_SEC,
    PROTOCOL_VERSION,
)
from db.live_db import upsert_peer, update_peer_onion

logger = logging.getLogger("refinet.discovery")


def build_announce_message(pid_data: dict, hostname: str, port: int,
                           pillar_name: str, onion_address: str = None) -> bytes:
    """Build a JSON announcement message for multicast."""
    msg = {
        "type": "pillar_announce",
        "protocol": "REFInet",
        "version": PROTOCOL_VERSION,
        "pid": pid_data["pid"],
        "public_key": pid_data["public_key"],
        "hostname": hostname,
        "port": port,
        "pillar_name": pillar_name,
        "timestamp": int(time.time()),
    }
    if onion_address:
        msg["onion_address"] = onion_address
    return json.dumps(msg).encode("utf-8")


def parse_announce_message(data: bytes) -> dict | None:
    """Parse an incoming announcement. Returns dict or None if invalid."""
    try:
        msg = json.loads(data.decode("utf-8"))
        if msg.get("type") == "pillar_announce" and msg.get("protocol") == "REFInet":
            return msg
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


class PeerAnnouncer:
    """Periodically announces this Pillar on the local network via multicast."""

    def __init__(self, pid_data: dict, hostname: str, port: int,
                 pillar_name: str, onion_address: str = None):
        self.pid_data = pid_data
        self.hostname = hostname
        self.port = port
        self.pillar_name = pillar_name
        self.onion_address = onion_address

    async def run(self):
        """Broadcast presence every DISCOVERY_INTERVAL_SEC seconds."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        msg = build_announce_message(
            self.pid_data, self.hostname, self.port, self.pillar_name,
            onion_address=self.onion_address,
        )

        logger.info(f"Announcer started (multicast {MULTICAST_GROUP}:{MULTICAST_PORT})")

        try:
            while True:
                try:
                    sock.sendto(msg, (MULTICAST_GROUP, MULTICAST_PORT))
                    logger.debug("Sent announce")
                except Exception as e:
                    logger.warning(f"Announce failed: {e}")
                await asyncio.sleep(DISCOVERY_INTERVAL_SEC)
        finally:
            sock.close()


class PeerListener:
    """Listens for announcements from other Pillars on the local network."""

    def __init__(self, own_pid: str):
        self.own_pid = own_pid

    async def run(self):
        """Listen for multicast announcements and register new peers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass  # Not available on all platforms

        sock.bind(("", MULTICAST_PORT))

        # Join multicast group
        group = socket.inet_aton(MULTICAST_GROUP)
        mreq = struct.pack("4sL", group, socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)

        logger.info(f"Listener started on multicast {MULTICAST_GROUP}:{MULTICAST_PORT}")

        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    data, addr = await loop.run_in_executor(None, lambda: sock.recvfrom(4096))
                    msg = parse_announce_message(data)
                    if not msg:
                        continue
                    peer_pid = msg.get("pid")
                    peer_key = msg.get("public_key")
                    if not peer_pid or not peer_key or peer_pid == self.own_pid:
                        continue

                    # Use the actual sender IP if hostname is "localhost"
                    hostname = msg.get("hostname", addr[0])
                    if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
                        hostname = addr[0]

                    # Check if this is a genuinely new peer
                    from db.live_db import get_peers as _get_all_peers
                    known_pids = {p["pid"] for p in _get_all_peers()}
                    is_new = peer_pid not in known_pids

                    upsert_peer(
                        pid=peer_pid,
                        public_key=peer_key,
                        hostname=hostname,
                        port=msg.get("port", 7070),
                        pillar_name=msg.get("pillar_name"),
                        protocol_version=msg.get("version"),
                    )

                    # Store .onion address if announced
                    peer_onion = msg.get("onion_address")
                    if peer_onion:
                        update_peer_onion(peer_pid, peer_onion)

                    logger.info(f"Discovered peer: {msg.get('pillar_name', '?')} [{peer_pid[:16]}...] @ {hostname}")

                    # Trigger registry sync for new peers
                    if is_new:
                        asyncio.ensure_future(
                            self._on_new_peer_discovered(hostname, msg.get("port", 7070), peer_pid)
                        )
                except BlockingIOError:
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Listener error: {e}")
                    await asyncio.sleep(1)
        finally:
            sock.close()

    async def _on_new_peer_discovered(self, peer_host, peer_port, peer_pid):
        """Trigger registry sync when a new peer is discovered."""
        try:
            from mesh.replication import sync_peer_registry
            imported = await sync_peer_registry(peer_host, peer_port, peer_pid)
            if imported:
                logger.info(f"Imported {imported} gopherhole(s) from new peer {peer_pid[:8]}")
        except Exception as e:
            logger.warning(f"Replication from new peer {peer_pid[:8]} failed: {e}")


# ---------------------------------------------------------------------------
# Bootstrap / WAN Peer Loading
# ---------------------------------------------------------------------------


def load_bootstrap_peers(peers_file: Path) -> int:
    """
    Load peers from a JSON file into the database.

    The file should contain a JSON array of peer objects:
    [{"hostname": "10.0.0.5", "port": 7070, "pid": "abc...", "pillar_name": "Remote"}]

    Returns count of peers loaded.
    """
    if not peers_file.exists():
        return 0
    try:
        with open(peers_file) as f:
            peers = json.load(f)
        if not isinstance(peers, list):
            logger.warning(f"Bootstrap peers file is not a JSON array: {peers_file}")
            return 0
        count = 0
        for peer in peers:
            hostname = peer.get("hostname")
            pid = peer.get("pid")
            if not hostname or not pid:
                continue
            upsert_peer(
                pid=pid,
                public_key=peer.get("public_key", ""),
                hostname=hostname,
                port=peer.get("port", 7070),
                pillar_name=peer.get("pillar_name"),
                protocol_version=peer.get("version"),
            )
            onion = peer.get("onion_address")
            if onion:
                update_peer_onion(pid, onion)
            count += 1
        return count
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load bootstrap peers: {e}")
        return 0


# ---------------------------------------------------------------------------
# Peer Health Monitoring
# ---------------------------------------------------------------------------
HEALTH_CHECK_INTERVAL_SEC = 60

# Peer health state machine:
# unknown → online (first successful ping)
# online → degraded (1–4 consecutive failures)
# degraded → offline (5+ consecutive failures)
# offline → online (next successful ping resets consecutive_failures to 0)
OFFLINE_THRESHOLD = 5


async def periodic_health_check():
    """Background task: ping all known peers every 60 seconds and update health status."""
    from core.gopher_client import ping
    from db.live_db import get_peers, update_peer_health

    # Initial delay — let discovery populate peers first
    await asyncio.sleep(15)

    logger.info("Health monitor started (60s interval)")

    while True:
        try:
            peers = get_peers()
            for peer in peers:
                hostname = peer.get("hostname")
                port = peer.get("port", 7070)
                if not hostname:
                    continue
                latency = await ping(hostname, port, timeout=5)
                update_peer_health(peer["pid"], latency)
        except Exception as e:
            logger.warning(f"Health check error: {e}")
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SEC)
