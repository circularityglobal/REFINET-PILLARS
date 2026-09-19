"""The ledger: rollups instead of per-request rows (F11), receipts (F10),
and amounts as integers (F12)."""

import asyncio
import json
import time

import pytest

from crypto.attestation import sign_witness
from crypto.pid import generate_pid, get_private_key
from core.gopher_server import GopherServer, RateLimiter
from db import live_db
from db.money import (
    ZERO_ADDRESS, asset, fold_by_asset, fold_units, format_units, to_units,
)


@pytest.fixture
async def server(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    srv = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    yield srv, tcp.sockets[0].getsockname()[1]
    tcp.close()
    await tcp.wait_closed()


async def _query(port, selector):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{selector}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=5)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8", errors="replace")


def _count(table):
    with live_db._connect() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]


class TestRequestsAreNotTransactions:
    @pytest.mark.asyncio
    async def test_serving_writes_no_unbounded_rows(self, server):
        srv, port = server
        for _ in range(5):
            await _query(port, "/about")
        assert _count("daily_tx") == 0
        assert _count("service_proofs") == 0

    @pytest.mark.asyncio
    async def test_tx_count_today_still_counts_requests(self, server):
        """status.json and the root menu must keep reporting the same number."""
        srv, port = server
        assert live_db.get_tx_count_today(srv.pid_data["pid"]) == 0
        for _ in range(3):
            await _query(port, "/about")
        assert live_db.get_tx_count_today(srv.pid_data["pid"]) == 3

    @pytest.mark.asyncio
    async def test_status_json_reports_the_count(self, server):
        srv, port = server
        await _query(port, "/about")
        body = await _query(port, "/status.json")
        status = json.loads(body.split("\r\n.")[0])
        assert status["tx_count_today"] >= 1

    def test_real_transactions_still_count(self, server):
        srv, _ = server
        pid = srv.pid_data["pid"]
        live_db.record_transaction(dapp_id="swap.dapp", pid=pid,
                                   amount_units=10**18, asset=asset(43113))
        assert live_db.get_tx_count_today(pid) == 1
        assert _count("daily_tx") == 1

    def test_rows_from_older_releases_are_not_double_counted(self, server):
        srv, _ = server
        pid = srv.pid_data["pid"]
        live_db.record_transaction(dapp_id="gopher.core", pid=pid, selector="/x")
        live_db.increment_requests_served(pid)
        assert live_db.get_tx_count_today(pid) == 1

    def test_replication_rejections_are_still_recorded(self, server):
        srv, _ = server
        live_db.record_transaction(dapp_id="mesh.replication",
                                   pid=srv.pid_data["pid"], selector="/holes/x")
        assert live_db.get_replication_rejections_today() == 1


class TestRateLimiterIsBounded:
    def test_idle_addresses_are_swept(self):
        limiter = RateLimiter(max_requests=5, window_seconds=1, sweep_every=10)
        for i in range(9):
            limiter.is_allowed(f"10.0.0.{i}")
        time.sleep(1.1)
        limiter.is_allowed("10.0.1.1")          # 10th call triggers the sweep
        assert len(limiter._requests) == 1

    def test_table_never_exceeds_its_cap(self):
        limiter = RateLimiter(max_requests=5, window_seconds=300,
                              max_tracked_ips=50, sweep_every=10_000)
        for i in range(500):
            limiter.is_allowed(f"10.1.{i // 256}.{i % 256}")
        assert len(limiter._requests) <= 50

    def test_limiting_still_works(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert [limiter.is_allowed("1.2.3.4") for _ in range(4)] == \
            [True, True, True, False]


class TestReceipts:
    def _receipt(self, requester, server_pid, selector="/about", status="match"):
        return sign_witness(
            get_private_key(requester), requester["pid"],
            f"refinet://pillar/{server_pid}{selector}",
            int(time.time()), "a" * 64, status)

    @pytest.mark.asyncio
    async def test_counter_signed_receipt_is_recorded(self, server):
        srv, port = server
        requester = generate_pid()
        payload = json.dumps({
            "receipt": self._receipt(requester, srv.pid_data["pid"]),
            "public_key": requester["public_key"],
        })
        body = await _query(port, f"/proof/receipt\t{payload}")
        assert "RECEIPT ACCEPTED" in body
        assert _count("service_proofs") == 1
        with live_db._connect() as conn:
            row = conn.execute("SELECT * FROM service_proofs").fetchone()
        assert row["requester_pid"] == requester["pid"]
        assert row["pid"] == srv.pid_data["pid"]

    @pytest.mark.asyncio
    async def test_forged_receipt_is_refused(self, server):
        srv, port = server
        requester, impostor = generate_pid(), generate_pid()
        receipt = self._receipt(requester, srv.pid_data["pid"])
        payload = json.dumps({"receipt": receipt,
                              "public_key": impostor["public_key"]})
        body = await _query(port, f"/proof/receipt\t{payload}")
        assert "Receipt rejected" in body
        assert _count("service_proofs") == 0

    @pytest.mark.asyncio
    async def test_pillar_cannot_counter_sign_its_own_service(self, server):
        """The point of F10: no minting proofs against your own requests."""
        srv, port = server
        receipt = sign_witness(
            srv.private_key, srv.pid_data["pid"],
            f"refinet://pillar/{srv.pid_data['pid']}/about",
            int(time.time()), "a" * 64, "match")
        payload = json.dumps({"receipt": receipt,
                              "public_key": srv.pid_data["public_key"]})
        body = await _query(port, f"/proof/receipt\t{payload}")
        assert "cannot counter-sign its own service" in body
        assert _count("service_proofs") == 0

    @pytest.mark.asyncio
    async def test_receipt_for_another_pillar_is_refused(self, server):
        srv, port = server
        requester = generate_pid()
        payload = json.dumps({
            "receipt": self._receipt(requester, generate_pid()["pid"]),
            "public_key": requester["public_key"],
        })
        body = await _query(port, f"/proof/receipt\t{payload}")
        assert "does not name this Pillar" in body

    @pytest.mark.asyncio
    async def test_receipt_route_is_blocked_on_the_standard_port(self, server):
        srv, _ = server
        srv.is_refinet = False
        assert "REFInet feature" in await srv._route("/proof/receipt\t{}")


class TestMoneyIsAnInteger:
    def test_one_token_survives_a_round_trip(self, server):
        """1e18 cannot be held exactly by a float."""
        srv, _ = server
        live_db.record_transaction(
            dapp_id="swap.dapp", pid=srv.pid_data["pid"],
            amount_units=10**18 + 1, asset=asset(43113, ZERO_ADDRESS, 18))
        with live_db._connect() as conn:
            row = conn.execute("SELECT * FROM daily_tx").fetchone()
        assert to_units(row["amount_units"]) == 10**18 + 1
        assert row["asset_chain_id"] == 43113
        assert row["asset_decimals"] == 18

    def test_amounts_above_the_sqlite_integer_range(self, server):
        srv, _ = server
        huge = 10**30
        live_db.record_transaction(dapp_id="swap.dapp", pid=srv.pid_data["pid"],
                                   amount_units=huge, asset=asset(43113))
        with live_db._connect() as conn:
            row = conn.execute("SELECT * FROM daily_tx").fetchone()
        assert to_units(row["amount_units"]) == huge

    def test_fold_is_exact(self):
        rows = [{"amount_units": str(10**18 + 1)} for _ in range(1000)]
        assert fold_units(rows) == 1000 * (10**18 + 1)

    def test_assets_are_never_added_together(self):
        rows = [
            {"amount_units": "5", "asset_chain_id": 43113,
             "asset_address": ZERO_ADDRESS, "asset_decimals": 18},
            {"amount_units": "7", "asset_chain_id": 8453,
             "asset_address": ZERO_ADDRESS, "asset_decimals": 18},
        ]
        assert sorted(fold_by_asset(rows).values()) == [5, 7]

    def test_missing_amounts_read_as_zero(self):
        assert fold_units([{"amount_units": None}, {"amount_units": ""}]) == 0

    def test_display_formatting_does_not_lie(self):
        assert format_units(10**18, 18) == "1"
        assert format_units(1, 18) == "0"          # below display precision
        assert format_units(1_500_000, 6) == "1.5"


class TestLegacySchema:
    def test_float_columns_are_still_there_for_old_readers(self, server):
        with live_db._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_tx)")}
        assert {"amount", "amount_units", "asset_chain_id"} <= cols

    def test_migration_adds_columns_to_an_existing_database(self, tmp_path, monkeypatch):
        """A 0.4.x database must upgrade in place."""
        import sqlite3
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE daily_metrics (
                accounting_day INTEGER NOT NULL, accounting_month INTEGER NOT NULL,
                accounting_year INTEGER NOT NULL, pid TEXT NOT NULL,
                total_tx_count INTEGER DEFAULT 0, total_volume REAL DEFAULT 0.0,
                avg_latency_ms REAL DEFAULT 0.0, peers_connected INTEGER DEFAULT 0,
                content_served INTEGER DEFAULT 0, uptime_seconds INTEGER DEFAULT 0,
                PRIMARY KEY (accounting_day, accounting_month, accounting_year, pid));
            CREATE TABLE service_proofs (
                proof_id TEXT PRIMARY KEY, pid TEXT NOT NULL, service TEXT NOT NULL,
                proof_hash TEXT NOT NULL, signature TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.commit()
        conn.close()

        monkeypatch.setattr(live_db, "LIVE_DB_PATH", db_path)
        live_db.init_live_db()
        with live_db._connect() as conn:
            metrics = {r[1] for r in conn.execute("PRAGMA table_info(daily_metrics)")}
            proofs = {r[1] for r in conn.execute("PRAGMA table_info(service_proofs)")}
        assert "requests_served" in metrics
        assert {"requester_pid", "resource"} <= proofs
        live_db.increment_requests_served("pid-x")
        assert live_db.get_tx_count_today("pid-x") == 1


class TestChallengeRegistryIsBounded:
    """The nonce registry must not become the growth problem F11 fixed."""

    def test_expired_challenges_are_purged(self, server):
        from datetime import datetime, timedelta, timezone
        srv, _ = server
        pid = srv.pid_data["pid"]
        for i in range(5):
            live_db.record_siwe_nonce(f"fresh{i}", "login", pid, ttl_seconds=900)
        with live_db._connect() as conn:
            old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            for i in range(20):
                conn.execute(
                    """INSERT INTO siwe_nonces
                       (nonce, purpose, pid, issued_at, expires_at, spent_at)
                       VALUES (?,?,?,?,?,?)""",
                    (f"stale{i}", "login", pid, old, old, old))
            conn.commit()

        assert live_db.purge_expired_siwe_nonces() == 20
        with live_db._connect() as conn:
            left = conn.execute("SELECT COUNT(*) c FROM siwe_nonces").fetchone()["c"]
        assert left == 5, "fresh challenges must survive the sweep"

    def test_the_purge_is_actually_scheduled(self):
        """A sweep nothing calls is not a sweep (this was a real miss)."""
        import inspect
        import pillar
        assert "purge_expired_siwe_nonces" in inspect.getsource(
            pillar.periodic_wal_checkpoint)


class TestReceiptIntakeIsBounded:
    """service_proofs is undeletable, so intake must be bounded (a real miss
    found while re-checking: the first version of /proof/receipt stored a new
    row for every submission, including duplicates)."""

    def _submit(self, srv, signer, i=0, resource=None, at=None):
        """Submit a receipt. `at` pins the clock.

        A receipt's signature covers its fetched_at, so reading the clock
        per submission makes "the same receipt" mean different things either
        side of a second boundary — which is a real distinction the ledger
        is right to record, and a flaky test if the caller did not mean it.
        """
        from crypto.attestation import sign_witness
        base = int(time.time()) if at is None else at
        r = sign_witness(
            get_private_key(signer), signer["pid"],
            resource or f"refinet://pillar/{srv.pid_data['pid']}/about",
            base - i, f"{i:064d}", "match")
        return srv._handle_receipt(
            "/proof/receipt\t" + json.dumps(
                {"receipt": r, "public_key": signer["public_key"]}),
            "localhost", 7070)

    @pytest.mark.asyncio
    async def test_the_same_receipt_is_stored_once(self, server):
        srv, _ = server
        signer = generate_pid()
        at = int(time.time())
        first = self._submit(srv, signer, at=at)
        assert "RECEIPT ACCEPTED" in first
        for _ in range(20):
            again = self._submit(srv, signer, at=at)
        assert "ALREADY ON FILE" in again
        assert live_db.count_service_proofs() == 1

    @pytest.mark.asyncio
    async def test_one_requester_cannot_flood(self, server, monkeypatch):
        import core.gopher_server as gs
        monkeypatch.setattr(gs, "MAX_RECEIPTS_PER_REQUESTER_PER_DAY", 3)
        srv, _ = server
        signer = generate_pid()
        at = int(time.time())
        outs = [self._submit(srv, signer, i, at=at) for i in range(6)]
        assert live_db.count_service_proofs() == 3
        assert sum("daily limit reached for this requester" in o for o in outs) == 3

    @pytest.mark.asyncio
    async def test_fresh_identities_cannot_flood(self, server, monkeypatch):
        """Identities are free, so a per-requester cap alone is not enough."""
        import core.gopher_server as gs
        monkeypatch.setattr(gs, "MAX_RECEIPTS_PER_DAY", 4)
        srv, _ = server
        at = int(time.time())
        for i in range(10):
            self._submit(srv, generate_pid(), i, at=at)
        assert live_db.count_service_proofs() == 4

    @pytest.mark.asyncio
    async def test_oversize_resource_is_refused(self, server):
        srv, _ = server
        out = self._submit(srv, generate_pid(), resource="x" * 600)
        assert "too long" in out
        assert live_db.count_service_proofs() == 0
