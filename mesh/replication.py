"""
REFInet Pillar — Gopherhole Registry Replication

Syncs gopherhole registries between peers. When a new peer is discovered
(or on a periodic schedule), fetch their /directory.json and import any
gopherholes we don't already have — after verifying Ed25519 signatures.
"""

import asyncio
import json
import logging

from core.gopher_client import fetch
from core.gopherhole import verify_gopherhole_signature
from db.live_db import (
    get_peers,
    gopherhole_exists,
    register_gopherhole,
    record_transaction,
)

logger = logging.getLogger("refinet.replication")

REPLICATION_INTERVAL_SEC = 300  # 5 minutes


async def sync_peer_registry(peer_host: str, peer_port: int, peer_pid: str) -> int:
    """
    Fetch a peer's /directory.json and import any new gopherholes.
    Only imports records with valid Ed25519 signatures.
    Returns count of newly imported records.
    """
    try:
        response = await fetch(peer_host, peer_port, "/directory.json", item_type="0")
        raw = response.text.strip()
        # Strip Gopher terminator if present
        if raw.endswith("\r\n."):
            raw = raw[:-3]
        elif raw.endswith("."):
            raw = raw[:-1]
        data = json.loads(raw)
        # Handle versioned envelope (schema_version >= 1) or bare array (legacy)
        if isinstance(data, dict) and "gopherholes" in data:
            holes = data["gopherholes"]
        elif isinstance(data, list):
            holes = data
        else:
            logger.warning(f"Unexpected directory.json format from {peer_host}:{peer_port}")
            return 0
    except Exception as e:
        logger.warning(f"Failed to fetch registry from {peer_host}:{peer_port}: {e}")
        return 0

    imported = 0

    for hole in holes:
        pid = hole.get("pid", "")
        selector = hole.get("selector", "")

        # Skip if already in our registry
        if gopherhole_exists(pid, selector):
            continue

        # Verify Ed25519 signature before accepting
        try:
            valid = verify_gopherhole_signature(hole)
        except Exception as e:
            logger.warning(f"Signature verification error for {selector}: {e}")
            continue

        if not valid:
            logger.warning(
                f"Rejected gopherhole {selector} from {peer_pid[:8]} "
                f"— invalid signature"
            )
            # Persist rejection event to daily_tx ledger
            try:
                from crypto.pid import get_or_create_pid
                own_pid = get_or_create_pid()["pid"]
                record_transaction(
                    dapp_id="mesh.replication",
                    pid=own_pid,
                    selector=selector,
                    mesh_peer_pid=peer_pid,
                    content_hash=hole.get("signature", ""),
                )
            except Exception:
                pass  # Never break replication for logging failures
            continue

        try:
            register_gopherhole(
                pid=pid,
                selector=selector,
                name=hole.get("name", ""),
                description=hole.get("description", ""),
                owner_address=hole.get("owner_address", ""),
                pubkey_hex=hole.get("pubkey_hex", ""),
                signature=hole["signature"],
                source=peer_pid,
            )
            imported += 1
            logger.info(f"Imported gopherhole '{hole.get('name')}' from peer {peer_pid[:8]}")
        except Exception as e:
            # UNIQUE constraint = already exists, skip silently
            if "UNIQUE" not in str(e):
                logger.warning(f"Failed to import {selector}: {e}")

    return imported


async def replicate_all_peers():
    """
    Run replication against all known peers.
    Called by the mesh loop periodically.
    """
    peers = get_peers()

    if not peers:
        return

    tasks = [
        sync_peer_registry(p["hostname"], p["port"], p["pid"])
        for p in peers
        if p.get("hostname")
    ]

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total = sum(r for r in results if isinstance(r, int))
        if total:
            logger.info(f"Replicated {total} new gopherhole(s) from {len(peers)} peer(s)")


async def periodic_replication():
    """Background task: replicate registries every REPLICATION_INTERVAL_SEC."""
    while True:
        await asyncio.sleep(REPLICATION_INTERVAL_SEC)
        try:
            await replicate_all_peers()
        except Exception as e:
            logger.warning(f"Periodic replication error: {e}")
