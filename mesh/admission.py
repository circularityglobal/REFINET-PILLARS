"""
REFInet Pillar — Stake-gated peer admission

With ``mesh_require_stake`` off (the default) every peer is admitted, as
before 0.6.0. With it on, a peer is admitted only when:

  1. PillarStaking says ``isActive(pid)`` — at least 100,000 REFI staked,
     no unstake pending, and no day recorded inactive against it in the
     last two days; and
  2. the wallet that staked (``operatorOf(pid)``) is bound to the PID by a
     §3.1 binding in the peer's own signed ``/identity/v3.json``, and that
     binding verifies (wallet signature + Pillar counter-signature).

(2) stops anyone from pointing someone else's stake at their own Pillar:
the stake is only as good as the binding the Pillar itself publishes.

Results are cached for ADMISSION_TTL_SEC, so replication rounds do not
re-read the chain for every peer every time.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("refinet.admission")

ADMISSION_TTL_SEC = 600

_cache: dict[tuple[str, str, int], tuple[float, bool, str]] = {}


def parse_signed_json(text: str) -> dict:
    """The JSON body of a Gopher response, without terminator or trailer."""
    from crypto.signing import SIG_BEGIN
    idx = text.find(SIG_BEGIN)
    body = text[:idx] if idx >= 0 else text
    body = body.rstrip()
    if body.endswith("\r\n."):
        body = body[:-3]
    elif body.endswith("\n."):
        body = body[:-2]
    elif body.endswith("."):
        body = body[:-1]
    return json.loads(body)


def operator_is_bound(doc: dict, operator: str) -> tuple[bool, str]:
    """True when *doc* (a verified identity v3 document) carries a valid
    §3.1 binding for *operator*."""
    from crypto.binding import is_legacy_binding, verify_binding
    operator = (operator or "").lower()
    for b in doc.get("bindings") or []:
        if (b.get("evm_address") or "").lower() != operator:
            continue
        record = {
            **b,
            "pid": doc["pid"],
            "public_key": doc["public_key"],
            "binding_type": b.get("type") or "deployer",
        }
        # A §3.1 statement names the PID it binds to, and its Ed25519
        # counter-signature is domain-separated. A "legacy" record is neither,
        # and whether a record counts as legacy is decided by the message the
        # peer supplied — so a peer could present any sign-in message a wallet
        # ever signed anywhere, counter-sign it with its own key, and claim
        # that wallet. A v3 document carries only §3.1 bindings by definition;
        # here that is enforced rather than assumed.
        if is_legacy_binding(record):
            return (False, "binding predates 0.5.0: its statement does not name this Pillar")
        ok, reason = verify_binding(record)
        if ok:
            return (True, "bound")
        return (False, f"binding for operator does not verify: {reason}")
    return (False, "staking wallet is not bound to this Pillar")


async def fetch_identity_v3(host: str, port: int) -> dict:
    from core.gopher_client import fetch
    response = await fetch(host, port, "/identity/v3.json", item_type="0")
    return parse_signed_json(response.text)


async def check_peer(pid: str, host: str, port: int, reader,
                     fetch_identity=fetch_identity_v3) -> tuple[bool, str]:
    """Run both admission checks against one peer. Never raises."""
    from crypto.binding import verify_identity_v3
    try:
        status = await reader.status(pid)
        if not status.active:
            why = status.error or (
                "below 100,000 REFI, unstaking, or recorded inactive in the last 2 days"
                if status.operator else "not registered")
            return (False, f"not active on-chain ({why})")
        doc = await fetch_identity(host, port)
        ok, reason = verify_identity_v3(doc)
        if not ok:
            return (False, f"identity v3: {reason}")
        if doc.get("pid") != pid:
            return (False, "identity document names a different PID")
        return operator_is_bound(doc, status.operator)
    except Exception as exc:
        return (False, f"admission check failed: {exc}")


async def peer_admitted(pid: str, host: str, port: int, config: dict | None = None,
                        reader=None, fetch_identity=fetch_identity_v3,
                        clock=time.time) -> bool:
    """Whether to replicate from / list this peer. True whenever staking
    is not required."""
    if config is None:
        from core.config import load_config
        config = load_config()
    if not config.get("mesh_require_stake"):
        return True
    if reader is None:
        from mesh.staking import get_reader
        reader = get_reader(config)
    if reader is None:
        logger.warning("mesh_require_stake is on but no staking_contracts are "
                       "configured; admitting no peers")
        return False

    now = clock()
    # Keyed by address as well as PID: the identity document is verified at
    # the address it was fetched from, so a verdict for one address says
    # nothing about the same PID announced at another.
    key = (pid, host, port)
    hit = _cache.get(key)
    if hit and now - hit[0] < ADMISSION_TTL_SEC:
        return hit[1]
    ok, reason = await check_peer(pid, host, port, reader, fetch_identity)
    if len(_cache) > 10000:
        _cache.clear()
    _cache[key] = (now, ok, reason)
    if not ok:
        logger.info(f"Peer {pid[:16]}... not admitted: {reason}")
    return ok


def clear_cache():
    _cache.clear()
