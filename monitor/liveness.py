"""
REFInet liveness monitor — the PillarStaking oracle (v1)

Every ROUND_INTERVAL_SEC it reads the staking directory and asks each
registered Pillar for a signed answer (``/g/status.json`` over its HTTP
gateway). A probe counts only when the envelope signature verifies against
that Pillar's own key and is freshly dated — so nothing but the Pillar
itself, holding its key, can satisfy it. Once a UTC day is over it decides
which Pillars were inactive that day and calls
``recordInactive(pids, day)`` from the ORACLE_ROLE key.

The monitor must never charge anyone for its own downtime:

  * a day is judged only if the monitor completed at least
    MIN_COVERAGE of that day's expected rounds; otherwise nobody is charged;
  * and only if some Pillar answered that day: a day on which nothing
    answered anywhere is the monitor's own outage, not everyone else's;
  * a Pillar is inactive when fewer than ACTIVE_THRESHOLD of the rounds
    that probed it succeeded — short restarts and deploys pass;
  * a Pillar no round probed that day is left alone.

The contract adds the rest: at most 1 REFI per Pillar per day, never below
99,999 REFI, idempotent per (pid, day), nothing while unstaking, nothing on
the registration day, and nothing older than 7 days.

    python3 -m monitor.liveness --contract 0x... [--rpc URL] [--db PATH]
    ORACLE_PRIVATE_KEY=0x... python3 -m monitor.liveness --contract 0x... --submit

Without --submit it only prints what it would record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger("refinet.monitor")

ROUND_INTERVAL_SEC = 900                     # 96 rounds per day
ROUNDS_PER_DAY = 86400 // ROUND_INTERVAL_SEC
MIN_COVERAGE = 0.8                           # monitor must have run 80% of the day
ACTIVE_THRESHOLD = 0.8                       # a Pillar must answer 80% of its probes
SUBMIT_BATCH = 100
FINALIZE_DELAY_SEC = 3600                    # judge a day one hour after it ends
PROBE_TIMEOUT_SEC = 10
CONCURRENCY = 16

PROBE_SELECTOR = "/g/status.json"
PROBE_MAX_SKEW_SEC = 600
# Mirrors PillarStaking.MAX_BACKFILL_DAYS: older days are refused on-chain,
# so there is no point retrying them.
MAX_BACKFILL_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (ts INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK (id = 1), last_day INTEGER);
CREATE TABLE IF NOT EXISTS probes (
    pid TEXT NOT NULL, ts INTEGER NOT NULL, ok INTEGER NOT NULL,
    PRIMARY KEY (pid, ts)
);
CREATE TABLE IF NOT EXISTS submitted (
    day INTEGER NOT NULL, pid TEXT NOT NULL, tx TEXT,
    PRIMARY KEY (day, pid)
);
"""


def utc_day(ts: float) -> int:
    return int(ts // 86400)


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------
def verify_probe(pid: str, headers: dict, body: bytes, now: float) -> bool:
    """True when this is a freshly signed answer from *pid* itself."""
    from crypto.signing import (
        DOMAIN_RESPONSE, hash_content, pid_matches_key, verify_domain,
    )
    field = {name.lower(): headers.get(name.lower(), "")
             for name in ("X-Refinet-Pid", "X-Refinet-Pubkey", "X-Refinet-Sig1",
                          "X-Refinet-Selector", "X-Refinet-Time", "X-Refinet-Hash")}
    if field["x-refinet-pid"] != pid:
        return False
    if not pid_matches_key(pid, field["x-refinet-pubkey"]):
        return False
    body_hash = hash_content(body)
    if field["x-refinet-hash"] != body_hash:
        return False
    try:
        signed_at = int(field["x-refinet-time"])
    except ValueError:
        return False
    # A recorded answer replayed later must not pass for liveness
    if abs(now - signed_at) > PROBE_MAX_SKEW_SEC:
        return False
    return verify_domain(DOMAIN_RESPONSE, field["x-refinet-sig1"],
                         field["x-refinet-pubkey"],
                         pid, field["x-refinet-selector"], signed_at, body_hash)


async def probe_health(pid: str, endpoint: str, now: float | None = None) -> bool:
    """True when the Pillar at *endpoint* returns a freshly signed answer.

    A static file server cannot satisfy this: the envelope signature is made
    with the Pillar's own key over the selector, the body and the time.
    """
    from crypto.wellknown import is_valid_domain, normalize_domain
    from integration.websocket_bridge import resolve_public_address
    from mesh.chain_discovery import _https_get

    domain = normalize_domain(endpoint)
    if not is_valid_domain(domain):
        return False
    try:
        ip = await resolve_public_address(domain, 443)
        loop = asyncio.get_event_loop()
        headers, body = await asyncio.wait_for(
            loop.run_in_executor(None, _https_get, domain, ip, PROBE_SELECTOR),
            timeout=PROBE_TIMEOUT_SEC + 2)
        return verify_probe(pid, headers, body, time.time() if now is None else now)
    except Exception:
        return False


async def run_round(conn: sqlite3.Connection, reader, probe=probe_health,
                    now: float | None = None) -> int:
    """Probe every registered Pillar once and record the round. Returns the
    number of Pillars probed."""
    ts = int(time.time() if now is None else now)
    pids = await reader.directory()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(pid):
        async with sem:
            status = await reader.status(pid)
            if not status.operator or not status.endpoint:
                return None
            return pid, await probe(pid, status.endpoint)

    results = [r for r in await asyncio.gather(*[one(p) for p in pids]) if r]
    conn.executemany("INSERT OR REPLACE INTO probes (pid, ts, ok) VALUES (?, ?, ?)",
                     [(pid, ts, int(ok)) for pid, ok in results])
    conn.execute("INSERT OR IGNORE INTO rounds (ts) VALUES (?)", (ts,))
    conn.commit()
    return len(results)


# ---------------------------------------------------------------------------
# Judging a day
# ---------------------------------------------------------------------------
def inactive_for_day(conn: sqlite3.Connection, day: int) -> tuple[list[str], str]:
    """(pids to record inactive, reason). Empty when the day cannot be judged."""
    start, end = day * 86400, (day + 1) * 86400
    rounds = conn.execute("SELECT COUNT(*) FROM rounds WHERE ts >= ? AND ts < ?",
                          (start, end)).fetchone()[0]
    coverage = rounds / ROUNDS_PER_DAY
    if coverage < MIN_COVERAGE:
        return ([], f"monitor covered {coverage:.0%} of day {day}; not judging it")
    rows = conn.execute(
        "SELECT pid, SUM(ok), COUNT(*) FROM probes WHERE ts >= ? AND ts < ? GROUP BY pid",
        (start, end)).fetchall()
    if rows and not any(ok for _pid, ok, _n in rows):
        # Not one Pillar answered all day. A whole network going dark at once
        # is the monitor's own egress, DNS or clock — never everyone else.
        return ([], f"no Pillar answered any probe on day {day}; treating it as "
                    f"this monitor's outage and charging nobody")
    inactive = sorted(pid for pid, ok, n in rows if n and ok / n < ACTIVE_THRESHOLD)
    return (inactive, f"{len(rows)} Pillar(s) probed over {rounds} round(s), {len(inactive)} inactive")


def pending_for_day(conn: sqlite3.Connection, day: int, pids: list[str]) -> list[str]:
    done = {r[0] for r in conn.execute("SELECT pid FROM submitted WHERE day = ?", (day,))}
    return [p for p in pids if p not in done]


def last_finalized_day(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT last_day FROM cursor WHERE id = 1").fetchone()
    return row[0] if row else None


def set_last_finalized_day(conn: sqlite3.Connection, day: int):
    conn.execute("INSERT INTO cursor (id, last_day) VALUES (1, ?) "
                 "ON CONFLICT(id) DO UPDATE SET last_day = excluded.last_day", (day,))
    conn.commit()


def mark_submitted(conn: sqlite3.Connection, day: int, pids: list[str], tx: str | None):
    conn.executemany("INSERT OR IGNORE INTO submitted (day, pid, tx) VALUES (?, ?, ?)",
                     [(day, p, tx) for p in pids])
    conn.commit()


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------
RECORD_INACTIVE_ABI = [{
    "name": "recordInactive", "type": "function", "stateMutability": "nonpayable",
    "inputs": [{"name": "pids", "type": "bytes32[]"}, {"name": "day", "type": "uint32"}],
    "outputs": [],
}]


class Web3Submitter:
    """Sends recordInactive from the ORACLE_ROLE key."""

    def __init__(self, rpc_url: str, contract: str, private_key: str):
        from web3 import Web3
        from eth_account import Account
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        self.account = Account.from_key(private_key)
        self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(contract),
                                             abi=RECORD_INACTIVE_ABI)

    def __call__(self, pids: list[str], day: int) -> str:
        fn = self.contract.functions.recordInactive([bytes.fromhex(p) for p in pids], day)
        tx = fn.build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "chainId": self.w3.eth.chain_id,
            "gasPrice": self.w3.eth.gas_price,   # XDC takes legacy transactions
        })
        signed = self.account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            raise RuntimeError(f"recordInactive reverted: {tx_hash.hex()}")
        return tx_hash.hex()


def finalize_day(conn: sqlite3.Connection, day: int, submit=None) -> list[str]:
    """Judge *day* and record its inactive Pillars. Returns the PIDs sent
    (or that would be sent, when submit is None)."""
    pids, why = inactive_for_day(conn, day)
    logger.info(f"Day {day}: {why}")
    todo = pending_for_day(conn, day, pids)
    if not todo:
        return []
    if submit is None:
        for pid in todo:
            logger.info(f"  would record inactive: {pid}")
        return todo
    sent = []
    for i in range(0, len(todo), SUBMIT_BATCH):
        batch = todo[i:i + SUBMIT_BATCH]
        tx = submit(batch, day)
        mark_submitted(conn, day, batch, tx)
        logger.info(f"  recorded {len(batch)} inactive Pillar(s) for day {day}: {tx}")
        sent += batch
    return sent


async def run(reader, conn, submit=None):
    """Probe forever; finalize each day FINALIZE_DELAY_SEC after it ends."""
    # The cursor is persisted, so a restart does not skip the day that was
    # in flight, and never starts further back than the chain will accept.
    oldest = utc_day(time.time()) - MAX_BACKFILL_DAYS
    stored = last_finalized_day(conn)
    last_finalized = max(stored, oldest - 1) if stored is not None else utc_day(time.time()) - 2
    while True:
        started = time.time()
        try:
            n = await run_round(conn, reader)
            logger.info(f"Round: {n} Pillar(s) probed")
        except Exception as exc:
            logger.warning(f"Round failed: {exc}")
        yesterday = utc_day(time.time() - FINALIZE_DELAY_SEC) - 1
        while last_finalized < yesterday:
            day = last_finalized + 1
            try:
                finalize_day(conn, day, submit)
            except Exception as exc:
                # Left un-finalised on purpose: the next round retries it
                # while it is still inside the backfill window.
                logger.error(f"Finalizing day {day} failed: {exc}")
                if day > utc_day(time.time()) - MAX_BACKFILL_DAYS:
                    break
            last_finalized = day
            set_last_finalized_day(conn, day)
        await asyncio.sleep(max(1, ROUND_INTERVAL_SEC - (time.time() - started)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="REFInet liveness monitor (PillarStaking oracle)")
    ap.add_argument("--contract", required=True, help="PillarStaking address")
    ap.add_argument("--chain", type=int, default=50, help="50 = XDC, 51 = Apothem")
    ap.add_argument("--rpc", default="", help="RPC URL (default: the chain table's)")
    ap.add_argument("--db", default=str(Path.home() / ".refinet" / "monitor.db"))
    ap.add_argument("--submit", action="store_true",
                    help="send recordInactive (needs ORACLE_PRIVATE_KEY); otherwise dry run")
    ap.add_argument("--finalize-day", type=int, help="judge one UTC day number and exit")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from mesh.staking import StakingReader
    reader = StakingReader.from_config({"staking_contracts": [args.contract],
                                        "staking_chain_id": args.chain,
                                        "staking_rpc": args.rpc})
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(args.db)

    submit = None
    if args.submit:
        key = os.environ.get("ORACLE_PRIVATE_KEY")
        if not key:
            raise SystemExit("--submit needs ORACLE_PRIVATE_KEY")
        submit = Web3Submitter(reader.rpc_url, args.contract, key)

    if args.finalize_day is not None:
        finalize_day(conn, args.finalize_day, submit)
        return
    asyncio.run(run(reader, conn, submit))


if __name__ == "__main__":
    main()
