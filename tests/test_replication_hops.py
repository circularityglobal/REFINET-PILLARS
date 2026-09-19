"""A registry record must survive more than one replication hop (F6, F7).

The signature covers registered_at, so an importer that re-dates a record
breaks it for the next peer. These tests replicate A -> B -> C and verify
the record at C, which is exactly where the old bug showed up.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from core.gopherhole import verify_gopherhole_signature, namespaced_selector
from crypto.pid import generate_pid, get_private_key
from crypto.signing import sign_content
from db import live_db


def _signed_record(pid_data, selector="/holes/hop", name="Hop Site",
                   registered_at="2026-01-05"):
    payload = f"{pid_data['pid']}:{selector}:{name}:{registered_at}"
    return {
        "pid": pid_data["pid"],
        "selector": selector,
        "name": name,
        "description": "travelled the mesh",
        "owner_address": "",
        "pubkey_hex": pid_data["public_key"],
        "signature": sign_content(payload.encode(), get_private_key(pid_data)),
        "registered_at": registered_at,
        "tx_hash": "hop",
        "source": "local",
    }


@pytest.fixture
def three_dbs(tmp_path, monkeypatch):
    """Three isolated live DBs standing in for three Pillars."""
    paths = {}
    for name in ("a", "b", "c"):
        d = tmp_path / name
        d.mkdir()
        paths[name] = d / "live.db"

    def use(name):
        monkeypatch.setattr(live_db, "LIVE_DB_PATH", paths[name])
        live_db.init_live_db()

    return use


async def _replicate_into(hole_rows, source_pid):
    """Run sync_peer_registry against a peer serving *hole_rows*."""
    from mesh import replication
    payload = json.dumps({"schema_version": 1, "gopherholes": hole_rows}) + "\r\n."
    with patch.object(replication, "fetch",
                      AsyncMock(return_value=SimpleNamespace(text=payload))):
        return await replication.sync_peer_registry("peer.example", 7070, source_pid)


def _directory_rows():
    """What /directory.json would publish from the current DB."""
    return [
        {k: h[k] for k in (
            "pid", "selector", "name", "description", "owner_address",
            "pubkey_hex", "signature", "registered_at", "tx_hash", "source")}
        for h in live_db.list_gopherholes()
    ]


@pytest.mark.asyncio
async def test_record_survives_three_hops(three_dbs):
    author = generate_pid()
    record = _signed_record(author)

    # Pillar A: the author registers it
    three_dbs("a")
    live_db.register_gopherhole(
        pid=record["pid"], selector=record["selector"], name=record["name"],
        description=record["description"], owner_address="",
        pubkey_hex=record["pubkey_hex"], signature=record["signature"],
        source="local", registered_at=record["registered_at"])
    rows_a = _directory_rows()

    # Pillar B imports from A
    three_dbs("b")
    assert await _replicate_into(rows_a, "a" * 64) == 1
    rows_b = _directory_rows()
    assert rows_b[0]["registered_at"] == record["registered_at"]
    assert verify_gopherhole_signature(rows_b[0])

    # Pillar C imports from B — the hop that used to fail
    three_dbs("c")
    assert await _replicate_into(rows_b, "b" * 64) == 1
    rows_c = _directory_rows()
    assert rows_c[0]["registered_at"] == record["registered_at"]
    assert verify_gopherhole_signature(rows_c[0]), (
        "record was re-dated in transit and no longer verifies"
    )


@pytest.mark.asyncio
async def test_record_claiming_a_foreign_pid_is_not_imported(three_dbs):
    """Signing with your own key while claiming someone else's PID (F7)."""
    impostor = generate_pid()
    victim_pid = generate_pid()["pid"]
    payload = f"{victim_pid}:/holes/steal:Stolen:2026-01-05"
    forged = {
        "pid": victim_pid,
        "selector": "/holes/steal",
        "name": "Stolen",
        "description": "",
        "owner_address": "",
        "pubkey_hex": impostor["public_key"],
        "signature": sign_content(payload.encode(), get_private_key(impostor)),
        "registered_at": "2026-01-05",
        "tx_hash": "x",
        "source": "local",
    }
    assert not verify_gopherhole_signature(forged)

    three_dbs("b")
    assert await _replicate_into([forged], "a" * 64) == 0
    assert live_db.list_gopherholes() == []


def test_namespaced_selector_must_match_the_records_pid():
    author = generate_pid()
    other = generate_pid()
    good = _signed_record(author, selector=namespaced_selector(author["pid"], "site"))
    assert verify_gopherhole_signature(good)

    # Same author, but a namespace belonging to another Pillar
    bad = _signed_record(author, selector=namespaced_selector(other["pid"], "site"))
    assert not verify_gopherhole_signature(bad)
