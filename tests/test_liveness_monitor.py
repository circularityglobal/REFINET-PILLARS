"""Liveness monitor: nobody is charged for the monitor's own downtime."""

import time

import pytest

from mesh.staking import StakeStatus
from monitor import liveness as lv

DAY = 20_000
START = DAY * 86400
A, B, C = "a" * 64, "b" * 64, "c" * 64


@pytest.fixture
def conn(tmp_path):
    return lv.open_db(tmp_path / "monitor.db")


def _rounds(conn, n, results):
    """Record n rounds on DAY; results maps pid -> number of successful rounds."""
    for i in range(n):
        ts = START + i * lv.ROUND_INTERVAL_SEC
        conn.execute("INSERT INTO rounds (ts) VALUES (?)", (ts,))
        for pid, ok_rounds in results.items():
            conn.execute("INSERT INTO probes (pid, ts, ok) VALUES (?, ?, ?)",
                         (pid, ts, int(i < ok_rounds)))
    conn.commit()


def test_full_day_judges_by_threshold(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 96, B: 80, C: 40})
    pids, why = lv.inactive_for_day(conn, DAY)
    assert pids == [C]          # B answered 83% of rounds: a restart, not an outage
    assert "3 Pillar(s) probed" in why


def test_monitor_downtime_charges_nobody(conn):
    _rounds(conn, int(lv.ROUNDS_PER_DAY * 0.5), {A: 0, B: 0})
    pids, why = lv.inactive_for_day(conn, DAY)
    assert pids == [] and "not judging" in why


def test_pillar_never_probed_is_left_alone(conn):
    # A answers every round; B was never probed at all (registered later, or
    # the monitor could not resolve it) and must not be charged for that.
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 96})
    assert lv.inactive_for_day(conn, DAY)[0] == []
    assert conn.execute("SELECT COUNT(*) FROM probes WHERE pid = ?", (B,)).fetchone()[0] == 0


def test_a_day_nothing_answered_is_the_monitors_own_outage(conn):
    # Full coverage, every probe failed: the monitor lost its egress, DNS or
    # clock. Charging the whole network for that is exactly what must not
    # happen.
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 0, B: 0, C: 0})
    pids, why = lv.inactive_for_day(conn, DAY)
    assert pids == []
    assert "monitor's outage" in why


def test_one_answering_pillar_is_enough_to_judge_the_day(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 96, B: 0})
    assert lv.inactive_for_day(conn, DAY)[0] == [B]


def test_other_days_do_not_count(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 0})
    assert lv.inactive_for_day(conn, DAY + 1)[0] == []


def test_finalize_is_idempotent(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 0, B: 0, C: 96})
    sent = []

    def submit(pids, day):
        sent.append((tuple(pids), day))
        return "0xtx"

    assert lv.finalize_day(conn, DAY, submit) == [A, B]
    assert lv.finalize_day(conn, DAY, submit) == []
    assert sent == [((A, B), DAY)]


def test_dry_run_sends_and_marks_nothing(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 0, C: 96})
    assert lv.finalize_day(conn, DAY, None) == [A]
    assert lv.pending_for_day(conn, DAY, [A]) == [A]


def test_failed_submit_is_retried_next_time(conn):
    _rounds(conn, lv.ROUNDS_PER_DAY, {A: 0, C: 96})

    def boom(pids, day):
        raise RuntimeError("rpc down")

    with pytest.raises(RuntimeError):
        lv.finalize_day(conn, DAY, boom)
    assert lv.finalize_day(conn, DAY, lambda p, d: "0xtx") == [A]


def test_batches(conn, monkeypatch):
    monkeypatch.setattr(lv, "SUBMIT_BATCH", 2)
    pids = [format(i, "064x") for i in range(5)]
    _rounds(conn, lv.ROUNDS_PER_DAY, dict({p: 0 for p in pids}, **{C: 96}))
    batches = []
    lv.finalize_day(conn, DAY, lambda p, d: batches.append(list(p)) or "0x")
    assert [len(b) for b in batches] == [2, 2, 1]


class Reader:
    async def directory(self):
        return [A, B, C]

    async def status(self, pid):
        if pid == C:
            return StakeStatus(pid=pid, active=False)                   # withdrawn
        return StakeStatus(pid=pid, active=pid == A, operator="0x" + "11" * 20,
                           endpoint=f"{pid[0]}.example.com")


async def test_round_probes_registered_pillars_with_endpoints(conn):
    probed = []

    async def probe(pid, endpoint):
        probed.append(endpoint)
        return pid == A

    n = await lv.run_round(conn, Reader(), probe=probe, now=START)
    assert n == 2 and sorted(probed) == ["a.example.com", "b.example.com"]
    rows = dict(conn.execute("SELECT pid, ok FROM probes").fetchall())
    assert rows == {A: 1, B: 0}
    assert conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 1


async def test_probe_refuses_non_domains():
    assert await lv.probe_health(A, "localhost") is False
    assert await lv.probe_health(A, "10.0.0.5") is False


# ---------------------------------------------------------------------------
# A probe must prove the Pillar itself answered, just now
# ---------------------------------------------------------------------------
def _signed_answer(selector="/g/status.json", when=1_000_000, body=b'{"ok":1}'):
    from crypto.pid import generate_pid, get_private_key
    from integration.http_gateway import SIGNATURE_HEADERS, trailer_fields
    from crypto.signing import build_signature_trailer
    pid = generate_pid()
    trailer = build_signature_trailer(body, get_private_key(pid), pid["pid"],
                                      pid["public_key"], selector, when)
    headers = {SIGNATURE_HEADERS[k].lower(): v for k, v in trailer_fields(trailer).items()}
    return pid, headers, body


def test_verify_probe_accepts_a_fresh_signed_answer():
    pid, headers, body = _signed_answer()
    assert lv.verify_probe(pid["pid"], headers, body, now=1_000_010) is True


def test_verify_probe_refuses_a_replayed_answer():
    pid, headers, body = _signed_answer(when=1_000_000)
    assert lv.verify_probe(pid["pid"], headers, body,
                           now=1_000_000 + lv.PROBE_MAX_SKEW_SEC + 1) is False


def test_verify_probe_refuses_a_static_file_server():
    # A page that merely says the right PID, with no signature at all
    pid, _headers, _body = _signed_answer()
    faked = {"x-refinet-pid": pid["pid"]}
    assert lv.verify_probe(pid["pid"], faked, b'{"pid":"%s"}' % pid["pid"].encode(),
                           now=1_000_000) is False


def test_verify_probe_refuses_another_pillars_answer():
    pid, headers, body = _signed_answer()
    assert lv.verify_probe("f" * 64, headers, body, now=1_000_010) is False


def test_verify_probe_refuses_a_tampered_body():
    pid, headers, body = _signed_answer()
    assert lv.verify_probe(pid["pid"], headers, body + b" ", now=1_000_010) is False


# ---------------------------------------------------------------------------
# The day cursor survives a restart, and a failed day is retried
# ---------------------------------------------------------------------------
def test_cursor_is_persisted(conn):
    assert lv.last_finalized_day(conn) is None
    lv.set_last_finalized_day(conn, DAY)
    assert lv.last_finalized_day(conn) == DAY
    lv.set_last_finalized_day(conn, DAY + 1)
    assert lv.last_finalized_day(conn) == DAY + 1


async def test_restart_finalizes_the_day_that_was_in_flight(conn, monkeypatch):
    """A monitor restarted mid-morning must still judge yesterday."""
    finalized = []
    monkeypatch.setattr(lv, "finalize_day",
                        lambda c, day, submit=None: finalized.append(day))

    async def one_round(c, reader, probe=None, now=None):
        return 0

    monkeypatch.setattr(lv, "run_round", one_round)

    class Stop(Exception):
        pass

    async def sleep_once(_):
        raise Stop

    monkeypatch.setattr(lv.asyncio, "sleep", sleep_once)
    today = lv.utc_day(time.time())
    lv.set_last_finalized_day(conn, today - 3)
    with pytest.raises(Stop):
        await lv.run(reader=None, conn=conn)
    # Every day since the stored cursor, including yesterday
    assert finalized == [today - 2, today - 1]
    assert lv.last_finalized_day(conn) == today - 1


async def test_a_day_that_fails_to_submit_is_not_marked_done(conn, monkeypatch):
    today = lv.utc_day(time.time())
    lv.set_last_finalized_day(conn, today - 2)

    def boom(c, day, submit=None):
        raise RuntimeError("rpc down")

    monkeypatch.setattr(lv, "finalize_day", boom)

    async def one_round(c, reader, probe=None, now=None):
        return 0

    monkeypatch.setattr(lv, "run_round", one_round)

    class Stop(Exception):
        pass

    async def sleep_once(_):
        raise Stop

    monkeypatch.setattr(lv.asyncio, "sleep", sleep_once)
    with pytest.raises(Stop):
        await lv.run(reader=None, conn=conn)
    # The cursor did not move, so the next round tries that day again
    assert lv.last_finalized_day(conn) == today - 2
