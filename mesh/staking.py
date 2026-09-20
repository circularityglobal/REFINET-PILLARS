"""
REFInet Pillar — PillarStaking reader (XDC)

Reads the PillarStaking contract (contracts/src/PillarStaking.sol) with
plain JSON-RPC ``eth_call``: no web3 dependency, so a minimal install can
still check whether a peer is staked.

    isActive(pid)    — admitted and earning (>= 100,000 REFI, not unstaking)
    operatorOf(pid)  — the wallet that staked; must be bound to the PID
    endpointOf(pid)  — the domain the Pillar serves /.well-known/refinet.json on
    pidsPage(o, n)   — the directory, for chain discovery

A Pillar ID is SHA-256 of the Ed25519 public key, so the 64-hex PID is the
contract's bytes32 key as-is.

Several contracts may be configured: a Pillar active in any of them counts.
Answers are cached; when the RPC is unreachable a cached answer is used
for up to STALE_GRACE_SEC, after which the Pillar counts as not active.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("refinet.staking")

# keccak256 selectors (cast sig "isActive(bytes32)" etc.). Hard-coded so no
# keccak implementation is needed; tests/test_staking.py pins them.
SEL_IS_ACTIVE = "5c36901c"
SEL_OPERATOR_OF = "63ea4ab2"
SEL_ENDPOINT_OF = "ab091871"
SEL_STAKE_OF = "07177c9c"
SEL_PILLAR_COUNT = "ce90dc30"
SEL_PIDS_PAGE = "6878efd3"

CACHE_TTL_SEC = 600
STALE_GRACE_SEC = 6 * 3600
RPC_TIMEOUT_SEC = 10
MAX_RPC_RESPONSE = 1024 * 1024
DIRECTORY_PAGE = 200
DIRECTORY_MAX = 5000

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_PID_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_SLOT = "0" * 64


# ---------------------------------------------------------------------------
# Minimal ABI encoding for the calls above
# ---------------------------------------------------------------------------
def encode_call(selector: str, *args) -> str:
    """Encode a call whose arguments are bytes32 (64-hex str) or uint256 (int)."""
    out = "0x" + selector
    for arg in args:
        if isinstance(arg, int):
            out += format(arg, "064x")
        else:
            value = str(arg).lower().removeprefix("0x")
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"not a bytes32: {arg!r}")
            out += value
    return out


def _words(result: str) -> bytes:
    data = bytes.fromhex(result.removeprefix("0x"))
    if len(data) % 32:
        raise ValueError("ABI result is not word-aligned")
    return data


def decode_uint(result: str) -> int:
    return int.from_bytes(_words(result)[:32], "big")


def decode_bool(result: str) -> bool:
    return decode_uint(result) != 0


def decode_address(result: str) -> str:
    return "0x" + _words(result)[12:32].hex()


def decode_string(result: str) -> str:
    data = _words(result)
    offset = int.from_bytes(data[:32], "big")
    length = int.from_bytes(data[offset:offset + 32], "big")
    raw = data[offset + 32:offset + 32 + length]
    if len(raw) != length:
        raise ValueError("ABI string runs past the result")
    return raw.decode("utf-8")


def decode_bytes32_array(result: str) -> list[str]:
    data = _words(result)
    offset = int.from_bytes(data[:32], "big")
    count = int.from_bytes(data[offset:offset + 32], "big")
    start = offset + 32
    if start + 32 * count > len(data):
        raise ValueError("ABI array runs past the result")
    return [data[start + 32 * i:start + 32 * (i + 1)].hex() for i in range(count)]


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def http_json_rpc(url: str, payload: dict, timeout: float = RPC_TIMEOUT_SEC) -> dict:
    """POST one JSON-RPC request. Synchronous; run it in an executor."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "refinet-pillar"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-configured URL
        body = resp.read(MAX_RPC_RESPONSE + 1)
    if len(body) > MAX_RPC_RESPONSE:
        raise ValueError("RPC response too large")
    return json.loads(body)


@dataclass
class StakeStatus:
    pid: str
    active: bool
    operator: str | None = None
    endpoint: str = ""
    stake_units: int = 0
    contract: str | None = None
    checked_at: float = 0.0
    error: str | None = None
    stale: bool = False


class StakingReader:
    """Reads PillarStaking contracts. One instance per process is enough."""

    def __init__(self, contracts: list[str], rpc_url: str,
                 transport=None, cache_ttl: float = CACHE_TTL_SEC,
                 stale_grace: float = STALE_GRACE_SEC, clock=time.time):
        self.contracts = [c for c in contracts if _ADDRESS_RE.match(c or "")]
        for bad in set(contracts) - set(self.contracts):
            logger.warning(f"Ignoring staking contract {bad!r}: not an address")
        self.rpc_url = rpc_url
        self._transport = transport or http_json_rpc
        self.cache_ttl = cache_ttl
        self.stale_grace = stale_grace
        self._clock = clock
        self._cache: dict[str, StakeStatus] = {}
        self._rpc_id = 0

    @classmethod
    def from_config(cls, config: dict) -> "StakingReader | None":
        """A reader for the configured contracts, or None when staking is off."""
        contracts = config.get("staking_contracts") or []
        if not contracts:
            return None
        rpc_url = config.get("staking_rpc") or ""
        if not rpc_url:
            chain_id = int(config.get("staking_chain_id", 50))
            try:
                from rpc.config import load_custom_chains
                load_custom_chains()
            except Exception:
                pass
            from rpc.chains import DEFAULT_CHAINS
            chain = DEFAULT_CHAINS.get(chain_id)
            if not chain:
                logger.warning(f"Staking chain {chain_id} is not in the chain table")
                return None
            rpc_url = chain["rpc"]
        return cls(contracts, rpc_url)

    @property
    def enabled(self) -> bool:
        return bool(self.contracts)

    async def eth_call(self, contract: str, data: str) -> str:
        self._rpc_id += 1
        payload = {"jsonrpc": "2.0", "id": self._rpc_id, "method": "eth_call",
                   "params": [{"to": contract, "data": data}, "latest"]}
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, self._transport, self.rpc_url, payload)
        if not isinstance(reply, dict):
            raise ValueError("malformed RPC reply")
        if reply.get("error"):
            raise ValueError(f"RPC error: {reply['error']}")
        result = reply.get("result")
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ValueError("RPC reply has no result")
        return result

    async def _read_one(self, contract: str, pid: str) -> StakeStatus:
        active = decode_bool(await self.eth_call(contract, encode_call(SEL_IS_ACTIVE, pid)))
        operator = decode_address(await self.eth_call(contract, encode_call(SEL_OPERATOR_OF, pid)))
        if int(operator, 16) == 0:
            return StakeStatus(pid=pid, active=False, contract=contract)
        endpoint = decode_string(await self.eth_call(contract, encode_call(SEL_ENDPOINT_OF, pid)))
        stake = decode_uint(await self.eth_call(contract, encode_call(SEL_STAKE_OF, pid)))
        return StakeStatus(pid=pid, active=active, operator=operator.lower(),
                           endpoint=endpoint.strip().lower(), stake_units=stake,
                           contract=contract)

    async def status(self, pid: str) -> StakeStatus:
        """The Pillar's standing across every configured contract."""
        pid = (pid or "").lower()
        now = self._clock()
        if not _PID_RE.match(pid):
            return StakeStatus(pid=pid, active=False, checked_at=now, error="not a PID")
        cached = self._cache.get(pid)
        if cached and not cached.error and now - cached.checked_at < self.cache_ttl:
            return cached
        try:
            found = None
            for contract in self.contracts:
                st = await self._read_one(contract, pid)
                if st.active:
                    found = st
                    break
                if found is None and st.operator:
                    found = st  # registered but not active: report why
            result = found or StakeStatus(pid=pid, active=False)
            result.checked_at = now
            self._cache[pid] = result
            return result
        except Exception as exc:
            if cached and now - cached.checked_at < self.stale_grace:
                logger.warning(f"Staking RPC failed ({exc}); using cached standing for {pid[:16]}")
                return StakeStatus(**{**cached.__dict__, "stale": True, "error": str(exc)})
            return StakeStatus(pid=pid, active=False, checked_at=now, error=str(exc))

    async def directory(self, max_entries: int = DIRECTORY_MAX) -> list[str]:
        """Every registered PID across the configured contracts (active or not)."""
        pids: list[str] = []
        seen: set[str] = set()
        for contract in self.contracts:
            count = decode_uint(await self.eth_call(contract, "0x" + SEL_PILLAR_COUNT))
            offset = 0
            while offset < count and len(pids) < max_entries:
                page = decode_bytes32_array(await self.eth_call(
                    contract, encode_call(SEL_PIDS_PAGE, offset, DIRECTORY_PAGE)))
                if not page:
                    break
                for pid in page:
                    # A slot a withdrawal emptied reads as zero; indexes never
                    # move, so paging cannot miss a Pillar that stayed.
                    if pid == _EMPTY_SLOT:
                        continue
                    if pid not in seen:
                        seen.add(pid)
                        pids.append(pid)
                offset += len(page)
        return pids[:max_entries]


_reader: StakingReader | None = None
_reader_key: tuple | None = None


def get_reader(config: dict | None = None) -> StakingReader | None:
    """The process-wide reader for the current config (None when staking is off)."""
    global _reader, _reader_key
    if config is None:
        from core.config import load_config
        config = load_config()
    key = (tuple(config.get("staking_contracts") or []),
           config.get("staking_rpc"), config.get("staking_chain_id"))
    if key != _reader_key:
        _reader = StakingReader.from_config(config)
        _reader_key = key
    return _reader
