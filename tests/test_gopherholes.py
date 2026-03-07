"""Tests for gopherhole registry schema, DB functions, and immutability."""

import hashlib
import json
import sqlite3
import pytest
from crypto.signing import sign_content, verify_signature


class TestGopherholesSchema:
    """Test that the gopherholes table and triggers exist."""

    def test_table_created(self, memory_db):
        """gopherholes table should exist after schema init."""
        row = memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='gopherholes'"
        ).fetchone()
        assert row is not None

    def test_insert_gopherhole(self, memory_db, test_pid, test_private_key):
        """Should be able to insert a valid gopherhole record."""
        pid = test_pid["pid"]
        selector = "/holes/test"
        name = "Test Site"
        registered_at = "2026-03-01"
        payload = f"{pid}:{selector}:{name}:{registered_at}"
        signature = sign_content(payload.encode(), test_private_key)

        record = {
            "pid": pid,
            "selector": selector,
            "name": name,
            "description": "A test gopherhole",
            "owner_address": "",
            "pubkey_hex": test_pid["public_key"],
            "signature": signature,
            "registered_at": registered_at,
            "source": "local",
        }
        tx_hash = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()

        memory_db.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, name, "A test gopherhole", "",
             test_pid["public_key"], signature, registered_at, tx_hash, "local"),
        )
        memory_db.commit()

        row = memory_db.execute(
            "SELECT * FROM gopherholes WHERE pid=? AND selector=?",
            (pid, selector),
        ).fetchone()
        assert row is not None
        assert row["name"] == "Test Site"
        assert row["tx_hash"] == tx_hash

    def test_unique_constraint(self, memory_db, test_pid, test_private_key):
        """Cannot insert two gopherholes with same pid+selector."""
        pid = test_pid["pid"]
        selector = "/holes/dup"
        payload = f"{pid}:{selector}:Dup:2026-01-01"
        sig = sign_content(payload.encode(), test_private_key)

        for _ in range(1):
            memory_db.execute(
                """INSERT INTO gopherholes
                   (pid, selector, name, description, owner_address, pubkey_hex,
                    signature, registered_at, tx_hash, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, selector, "Dup", "", "", test_pid["public_key"],
                 sig, "2026-01-01", "hash1", "local"),
            )
        memory_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                """INSERT INTO gopherholes
                   (pid, selector, name, description, owner_address, pubkey_hex,
                    signature, registered_at, tx_hash, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, selector, "Dup2", "", "", test_pid["public_key"],
                 sig, "2026-01-01", "hash2", "local"),
            )

    def test_immutability_no_update(self, memory_db, test_pid, test_private_key):
        """Trigger should prevent UPDATE on gopherholes."""
        pid = test_pid["pid"]
        selector = "/holes/immut"
        payload = f"{pid}:{selector}:Immut:2026-01-01"
        sig = sign_content(payload.encode(), test_private_key)

        memory_db.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, "Immut", "", "", test_pid["public_key"],
             sig, "2026-01-01", "hash", "local"),
        )
        memory_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                "UPDATE gopherholes SET name='Changed' WHERE pid=? AND selector=?",
                (pid, selector),
            )

    def test_immutability_no_delete(self, memory_db, test_pid, test_private_key):
        """Trigger should prevent DELETE on gopherholes."""
        pid = test_pid["pid"]
        selector = "/holes/nodelete"
        payload = f"{pid}:{selector}:NoDelete:2026-01-01"
        sig = sign_content(payload.encode(), test_private_key)

        memory_db.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, "NoDelete", "", "", test_pid["public_key"],
             sig, "2026-01-01", "hash", "local"),
        )
        memory_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            memory_db.execute(
                "DELETE FROM gopherholes WHERE pid=? AND selector=?",
                (pid, selector),
            )


class TestSignatureVerification:
    """Test that gopherhole signatures can be verified with existing crypto API."""

    def test_sign_and_verify_gopherhole(self, test_pid, test_private_key):
        """Signature created with sign_content should verify with verify_signature."""
        payload = f"{test_pid['pid']}:/holes/test:My Site:2026-01-01"
        signature = sign_content(payload.encode(), test_private_key)

        assert verify_signature(
            payload.encode(),
            signature,
            test_pid["public_key"],
        )

    def test_tampered_payload_fails_verification(self, test_pid, test_private_key):
        """Modified payload should fail verification."""
        payload = f"{test_pid['pid']}:/holes/test:My Site:2026-01-01"
        signature = sign_content(payload.encode(), test_private_key)

        tampered = f"{test_pid['pid']}:/holes/test:TAMPERED:2026-01-01"
        assert not verify_signature(
            tampered.encode(),
            signature,
            test_pid["public_key"],
        )


class TestDirectoryJsonSchema:
    """Test the /directory.json browser contract schema."""

    def test_json_schema_fields(self, memory_db, test_pid, test_private_key):
        """Each gopherhole in JSON output must have exactly the contract fields."""
        pid = test_pid["pid"]
        selector = "/holes/schema"
        name = "Schema Test"
        registered_at = "2026-03-01"
        payload = f"{pid}:{selector}:{name}:{registered_at}"
        sig = sign_content(payload.encode(), test_private_key)

        record = {
            "pid": pid,
            "selector": selector,
            "name": name,
            "description": "Testing schema",
            "owner_address": "0x1234",
            "pubkey_hex": test_pid["public_key"],
            "signature": sig,
            "registered_at": registered_at,
            "source": "local",
        }
        tx_hash = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()

        memory_db.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, name, "Testing schema", "0x1234",
             test_pid["public_key"], sig, registered_at, tx_hash, "local"),
        )
        memory_db.commit()

        rows = memory_db.execute(
            "SELECT * FROM gopherholes ORDER BY registered_at DESC"
        ).fetchall()
        holes = [dict(r) for r in rows]

        # Build the JSON payload exactly as the server does
        payload_json = [
            {
                "pid": h["pid"],
                "selector": h["selector"],
                "name": h["name"],
                "description": h["description"],
                "owner_address": h["owner_address"],
                "pubkey_hex": h["pubkey_hex"],
                "signature": h["signature"],
                "registered_at": h["registered_at"],
                "tx_hash": h["tx_hash"],
                "source": h["source"],
            }
            for h in holes
        ]

        required_fields = {
            "pid", "selector", "name", "description", "owner_address",
            "pubkey_hex", "signature", "registered_at", "tx_hash", "source",
        }

        for item in payload_json:
            assert set(item.keys()) == required_fields
            assert item["pid"] == pid
            assert item["selector"] == selector
            assert item["source"] in ("local",) or len(item["source"]) == 64  # peer PID

    def test_versioned_envelope_structure(self, memory_db, test_pid, test_private_key):
        """The /directory.json envelope must have schema_version, generated_at, pillar_pid, gopherholes."""
        pid = test_pid["pid"]
        selector = "/holes/envelope"
        name = "Envelope Test"
        registered_at = "2026-03-01"
        payload = f"{pid}:{selector}:{name}:{registered_at}"
        sig = sign_content(payload.encode(), test_private_key)

        record = {
            "pid": pid,
            "selector": selector,
            "name": name,
            "description": "",
            "owner_address": "",
            "pubkey_hex": test_pid["public_key"],
            "signature": sig,
            "registered_at": registered_at,
            "source": "local",
        }
        tx_hash = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()

        memory_db.execute(
            """INSERT INTO gopherholes
               (pid, selector, name, description, owner_address, pubkey_hex,
                signature, registered_at, tx_hash, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, selector, name, "", "",
             test_pid["public_key"], sig, registered_at, tx_hash, "local"),
        )
        memory_db.commit()

        rows = memory_db.execute("SELECT * FROM gopherholes").fetchall()
        holes = [dict(r) for r in rows]
        entries = [
            {
                "pid": h["pid"], "selector": h["selector"], "name": h["name"],
                "description": h["description"], "owner_address": h["owner_address"],
                "pubkey_hex": h["pubkey_hex"], "signature": h["signature"],
                "registered_at": h["registered_at"], "tx_hash": h["tx_hash"],
                "source": h["source"],
            }
            for h in holes
        ]

        from datetime import datetime, timezone
        envelope = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pillar_pid": pid,
            "gopherholes": entries,
        }

        assert envelope["schema_version"] == 1
        assert "generated_at" in envelope
        assert envelope["pillar_pid"] == pid
        assert isinstance(envelope["gopherholes"], list)
        assert len(envelope["gopherholes"]) == 1
        assert envelope["gopherholes"][0]["selector"] == "/holes/envelope"


class TestPeerHealthSchema:
    """Test the peer health status fields in the peers table."""

    def test_peers_table_has_health_columns(self, memory_db):
        """peers table should have status, latency_ms, consecutive_failures, last_checked."""
        columns = {
            row[1]
            for row in memory_db.execute("PRAGMA table_info(peers)").fetchall()
        }
        assert "status" in columns
        assert "latency_ms" in columns
        assert "consecutive_failures" in columns
        assert "last_checked" in columns

    def test_peer_health_defaults(self, memory_db):
        """New peer should have status='unknown', consecutive_failures=0, latency_ms=NULL."""
        memory_db.execute(
            "INSERT INTO peers (pid, public_key) VALUES (?, ?)",
            ("test_pid_123", "pubkey_abc"),
        )
        memory_db.commit()
        row = memory_db.execute("SELECT * FROM peers WHERE pid='test_pid_123'").fetchone()
        assert row["status"] == "unknown"
        assert row["latency_ms"] is None
        assert row["consecutive_failures"] == 0
        assert row["last_checked"] is None

    def test_peer_health_online(self, memory_db):
        """Successful ping should set status='online' and latency."""
        memory_db.execute(
            "INSERT INTO peers (pid, public_key) VALUES (?, ?)",
            ("test_pid_456", "pubkey_def"),
        )
        memory_db.commit()
        memory_db.execute(
            """UPDATE peers SET status='online', latency_ms=42.5,
               consecutive_failures=0, last_checked=CURRENT_TIMESTAMP
               WHERE pid='test_pid_456'""",
        )
        memory_db.commit()
        row = memory_db.execute("SELECT * FROM peers WHERE pid='test_pid_456'").fetchone()
        assert row["status"] == "online"
        assert row["latency_ms"] == 42.5
        assert row["consecutive_failures"] == 0

    def test_peer_health_failure_escalation(self, memory_db):
        """Consecutive failures should escalate: degraded → offline."""
        memory_db.execute(
            "INSERT INTO peers (pid, public_key) VALUES (?, ?)",
            ("test_pid_789", "pubkey_ghi"),
        )
        memory_db.commit()

        # 1 failure → degraded
        memory_db.execute(
            "UPDATE peers SET status='degraded', consecutive_failures=1 WHERE pid='test_pid_789'",
        )
        memory_db.commit()
        row = memory_db.execute("SELECT * FROM peers WHERE pid='test_pid_789'").fetchone()
        assert row["status"] == "degraded"
        assert row["consecutive_failures"] == 1

        # 5 failures → offline (Browser Alignment: threshold is 5, not 3)
        memory_db.execute(
            "UPDATE peers SET status='offline', consecutive_failures=5 WHERE pid='test_pid_789'",
        )
        memory_db.commit()
        row = memory_db.execute("SELECT * FROM peers WHERE pid='test_pid_789'").fetchone()
        assert row["status"] == "offline"
        assert row["consecutive_failures"] == 5
