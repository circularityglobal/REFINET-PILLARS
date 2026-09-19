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
import re
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
from crypto.signing import (
    DOMAIN_ANNOUNCE, pid_matches_key, sign_domain, verify_domain,
)
from db.live_db import upsert_peer, update_peer_onion

logger = logging.getLogger("refinet.discovery")


def verify_peer_identity(pid: str, public_key_hex: str) -> bool:
    """Verify that a public key hashes to the claimed PID.

    PID = SHA-256(public_key_bytes). If the key doesn't hash to the
    claimed PID, the announcement is forged.
    """
    return pid_matches_key(pid, public_key_hex)


ANNOUNCE_MAX_SKEW_SECONDS = 60


def announce_preimage_fields(msg: dict) -> tuple:
    """The fields an announcement signature covers."""
    return (msg["pid"], msg["hostname"], msg["port"], msg["timestamp"])


def build_announce_message(pid_data: dict, hostname: str, port: int,
                           pillar_name: str, onion_address: str = None,
                           private_key=None, timestamp: int = None) -> bytes:
    """Build a JSON announcement message for multicast.

    The announcement is signed over (pid, hostname, port, timestamp) under
    the REFINET-ANNOUNCE-v1 domain. Without a signature anyone on the
    segment could re-announce a real Pillar's PID with their own address
    and receive its traffic, because pid and public_key are public.

    No wallet information is announced: a peer that wants a Pillar's wallet
    fetches /identity.json and verifies the binding itself.
    """
    msg = {
        "type": "pillar_announce",
        "protocol": "REFInet",
        "version": PROTOCOL_VERSION,
        "pid": pid_data["pid"],
        "public_key": pid_data["public_key"],
        "hostname": hostname,
        "port": port,
        "pillar_name": pillar_name,
        "timestamp": int(time.time()) if timestamp is None else int(timestamp),
    }
    if onion_address:
        msg["onion_address"] = onion_address

    if private_key is None:
        try:
            from crypto.unlock import get_unlocked_key
            private_key = get_unlocked_key(pid_data)
        except (ValueError, KeyError, ImportError):
            private_key = None  # Locked key: announce unsigned, as before
    if private_key is not None:
        msg["sig"] = sign_domain(DOMAIN_ANNOUNCE, private_key,
                                 *announce_preimage_fields(msg))

    return json.dumps(msg).encode("utf-8")


def verify_announce_signature(msg: dict, now: int = None) -> tuple[bool, str]:
    """Verify an announcement's signature and freshness.

    Returns (ok, reason). ``(False, "unsigned")`` means the announcement
    carries no signature at all — an older Pillar.
    """
    if "sig" not in msg:
        return (False, "unsigned")
    try:
        timestamp = int(msg["timestamp"])
    except (KeyError, TypeError, ValueError):
        return (False, "no timestamp")
    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > ANNOUNCE_MAX_SKEW_SECONDS:
        return (False, "stale or future-dated announcement")
    if not verify_domain(DOMAIN_ANNOUNCE, msg["sig"], msg.get("public_key", ""),
                         *announce_preimage_fields(msg)):
        return (False, "signature does not verify")
    return (True, "ok")


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

        logger.info(f"Announcer started (multicast {MULTICAST_GROUP}:{MULTICAST_PORT})")

        try:
            while True:
                try:
                    # Rebuilt every round: the signature covers the timestamp,
                    # so one message cannot be reused (or replayed) for long.
                    msg = build_announce_message(
                        self.pid_data, self.hostname, self.port, self.pillar_name,
                        onion_address=self.onion_address,
                    )
                    sock.sendto(msg, (MULTICAST_GROUP, MULTICAST_PORT))
                    logger.debug("Sent announce")
                except Exception as e:
                    logger.warning(f"Announce failed: {e}")
                await asyncio.sleep(DISCOVERY_INTERVAL_SEC)
        finally:
            sock.close()


class PeerListener:
    """Listens for announcements from other Pillars on the local network.

    Policy:
      * a signed announcement must verify and be fresh, and its timestamp
        must be newer than the last one accepted for that PID;
      * an unsigned announcement (an older Pillar) may introduce a peer we
        have never seen, but may never move a known peer's address;
      * ``discovery_require_signed`` in config.json drops unsigned ones.
    """

    def __init__(self, own_pid: str, require_signed: bool = None):
        self.own_pid = own_pid
        if require_signed is None:
            try:
                from core.config import load_config
                require_signed = bool(load_config().get("discovery_require_signed", False))
            except Exception:
                require_signed = False
        self.require_signed = require_signed
        # Bounded: a stranger can mint keypairs, so this must not grow forever.
        self._last_announce_ts: dict[str, int] = {}
        self.max_tracked_pids = 10000

    def accept_announcement(self, msg: dict, known_pids: set) -> tuple[bool, bool, str]:
        """Decide what to do with an announcement.

        Returns (accept, may_move_address, reason).
        """
        pid = msg.get("pid", "")
        signed_ok, reason = verify_announce_signature(msg)
        if signed_ok:
            last = self._last_announce_ts.get(pid)
            ts = int(msg["timestamp"])
            if last is not None and ts <= last:
                return (False, False, "replayed announcement")
            if (pid not in self._last_announce_ts
                    and len(self._last_announce_ts) >= self.max_tracked_pids):
                # Drop the oldest entry (insertion-ordered dict)
                self._last_announce_ts.pop(next(iter(self._last_announce_ts)))
            self._last_announce_ts[pid] = ts
            return (True, True, "signed")
        if self.require_signed:
            return (False, False, f"unsigned announcement refused ({reason})")
        if pid in known_pids:
            # Known peer, unsigned word: keep serving it at the address we know.
            return (True, False, f"unsigned ({reason}) — address not updated")
        return (True, False, f"unsigned ({reason}) — new peer")

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

                    # Cryptographically verify PID matches public key
                    if not verify_peer_identity(peer_pid, peer_key):
                        logger.warning(
                            f"Rejected peer: PID {peer_pid[:16]}... does not match announced public key"
                        )
                        continue

                    # Check if this is a genuinely new peer
                    from db.live_db import get_peers as _get_all_peers
                    peers_now = {p["pid"]: p for p in _get_all_peers()}
                    is_new = peer_pid not in peers_now

                    accept, may_move, why = self.accept_announcement(
                        msg, set(peers_now))
                    if not accept:
                        logger.warning(
                            f"Rejected announcement from {peer_pid[:16]}...: {why}")
                        continue
                    if not is_new and not may_move:
                        # Refresh last_seen only; never relocate a known peer
                        # on an unsigned announcement.
                        known = peers_now[peer_pid]
                        upsert_peer(
                            pid=peer_pid,
                            public_key=peer_key,
                            hostname=known.get("hostname"),
                            port=known.get("port", 7070),
                            pillar_name=msg.get("pillar_name"),
                            protocol_version=msg.get("version"),
                        )
                        continue

                    # Use the actual sender IP if hostname is "localhost"
                    hostname = msg.get("hostname", addr[0])
                    if hostname in ("localhost", "0.0.0.0", "127.0.0.1"):
                        hostname = addr[0]

                    # evm_address is never taken from an announcement: peers
                    # fetch /identity.json and verify the binding themselves.
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
            # Reject placeholder or invalid PIDs
            if "REPLACE" in pid.upper():
                logger.warning(
                    "Bootstrap peer skipped: PID is a placeholder "
                    "— edit peers.json with real values from your bootstrap node"
                )
                continue
            if not re.fullmatch(r"[0-9a-fA-F]{64}", pid):
                logger.warning(
                    f"Bootstrap peer skipped: PID '{pid[:24]}...' is not a valid 64-character hex string"
                )
                continue
            pub_key = peer.get("public_key", "")
            if pub_key and not verify_peer_identity(pid, pub_key):
                logger.warning(f"Bootstrap peer rejected: PID {pid[:16]}... does not match public key")
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
