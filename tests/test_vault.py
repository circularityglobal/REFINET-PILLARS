"""Tests for vault/storage.py — Encrypted Personal Vault."""

import sqlite3
import pytest
from pathlib import Path
from db.schema import LIVE_SCHEMA


def _patch_vault(tmp_path, monkeypatch):
    """Redirect vault to tmp_path with in-file SQLite."""
    import vault.storage as mod

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "live.db"

    # Initialize DB with schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript(LIVE_SCHEMA)
    conn.close()

    monkeypatch.setattr(mod, "VAULT_DIR", vault_dir)
    monkeypatch.setattr(mod, "LIVE_DB_PATH", db_path)


class TestVaultStorage:
    """Vault store, retrieve, list, delete operations."""

    def test_store_and_retrieve(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, retrieve_item

        data = b"secret document content"
        result = store_item("doc1", data, "password123", "pid-aaa")
        assert result["name"] == "doc1"
        assert result["size_bytes"] == len(data)
        assert result["file_hash"]

        retrieved = retrieve_item("doc1", "password123")
        assert retrieved == data

    def test_list_items(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, list_items

        store_item("a", b"aaa", "pw", "pid-1")
        store_item("b", b"bbb", "pw", "pid-1")
        items = list_items("pid-1")
        assert len(items) == 2

    def test_delete_item(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, delete_item, list_items

        store_item("todelete", b"data", "pw", "pid-1")
        delete_item("todelete", "pid-1")
        assert len(list_items("pid-1")) == 0

    def test_vault_stats(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, get_vault_stats

        store_item("x", b"12345", "pw", "pid-1")
        store_item("y", b"67890", "pw", "pid-1")
        stats = get_vault_stats("pid-1")
        assert stats["item_count"] == 2
        assert stats["total_bytes"] == 10

    def test_wrong_pid_cant_delete(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, delete_item

        store_item("owned", b"data", "pw", "pid-owner")
        with pytest.raises(FileNotFoundError):
            delete_item("owned", "pid-attacker")

    def test_retrieve_nonexistent_raises(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import retrieve_item

        with pytest.raises(FileNotFoundError):
            retrieve_item("ghost", "pw")

    def test_empty_vault_stats(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import get_vault_stats

        stats = get_vault_stats("pid-empty")
        assert stats["item_count"] == 0
        assert stats["total_bytes"] == 0

    def test_store_returns_item_id(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item

        result = store_item("myitem", b"content", "pw", "pid-1")
        assert result["item_id"].startswith("vault_")
        assert len(result["item_id"]) > 6

    def test_list_items_filtered_by_pid(self, tmp_path, monkeypatch):
        _patch_vault(tmp_path, monkeypatch)
        from vault.storage import store_item, list_items

        store_item("alice-doc", b"a", "pw", "pid-alice")
        store_item("bob-doc", b"b", "pw", "pid-bob")
        alice_items = list_items("pid-alice")
        bob_items = list_items("pid-bob")
        assert len(alice_items) == 1
        assert len(bob_items) == 1
        assert alice_items[0]["name"] == "alice-doc"
