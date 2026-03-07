"""Tests for first-run initialization: PID generation, DB creation, gopherhole scaffolding."""

import sqlite3
import pytest
from pathlib import Path
from crypto.pid import generate_pid, save_pid, load_pid, get_private_key, get_or_create_pid
from db.schema import LIVE_SCHEMA, ARCHIVE_SCHEMA


class TestPIDGeneration:
    """Test PID generation on first run."""

    def test_has_required_fields(self):
        pid_data = generate_pid()
        assert "pid" in pid_data
        assert "public_key" in pid_data
        assert "private_key" in pid_data
        assert "created_at" in pid_data

    def test_pid_is_64_char_hex(self):
        pid_data = generate_pid()
        assert len(pid_data["pid"]) == 64
        int(pid_data["pid"], 16)  # Should not raise

    def test_public_key_is_64_char_hex(self):
        pid_data = generate_pid()
        assert len(pid_data["public_key"]) == 64
        int(pid_data["public_key"], 16)

    def test_private_key_is_64_char_hex(self):
        pid_data = generate_pid()
        assert len(pid_data["private_key"]) == 64
        int(pid_data["private_key"], 16)

    def test_two_pids_are_unique(self):
        p1 = generate_pid()
        p2 = generate_pid()
        assert p1["pid"] != p2["pid"]

    def test_save_and_load_pid(self, tmp_path):
        pid_data = generate_pid()
        pid_file = tmp_path / "pid.json"
        save_pid(pid_data, path=pid_file)

        loaded = load_pid(path=pid_file)
        assert loaded is not None
        assert loaded["pid"] == pid_data["pid"]
        assert loaded["public_key"] == pid_data["public_key"]
        assert loaded["private_key"] == pid_data["private_key"]

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = load_pid(path=tmp_path / "nonexistent.json")
        assert result is None

    def test_get_private_key_reconstructs(self):
        pid_data = generate_pid()
        key = get_private_key(pid_data)
        sig = key.sign(b"test data")
        assert len(sig) == 64  # Ed25519 signature length

    def test_get_or_create_pid_creates_on_first_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / "pid.json")
        pid_data = get_or_create_pid()
        assert pid_data["pid"]
        # Second call returns same PID
        pid_data2 = get_or_create_pid()
        assert pid_data2["pid"] == pid_data["pid"]


class TestLiveDBInit:
    """Test live database initialization creates all required tables."""

    def test_creates_all_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LIVE_SCHEMA)
        conn.commit()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "daily_tx" in tables
        assert "daily_metrics" in tables
        assert "peers" in tables
        assert "content_index" in tables
        assert "token_state" in tables
        assert "gopherholes" in tables
        assert "siwe_sessions" in tables
        conn.close()

    def test_daily_tx_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LIVE_SCHEMA)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(daily_tx)").fetchall()
        }
        assert "tx_id" in columns
        assert "dapp_id" in columns
        assert "pid" in columns
        assert "content_hash" in columns
        assert "accounting_day" in columns
        assert "accounting_month" in columns
        assert "accounting_year" in columns
        conn.close()

    def test_triggers_exist(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LIVE_SCHEMA)
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert "gopherholes_no_update" in triggers
        assert "gopherholes_no_delete" in triggers
        assert "siwe_sessions_no_delete" in triggers
        conn.close()

    def test_peers_health_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LIVE_SCHEMA)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(peers)").fetchall()
        }
        assert "status" in columns
        assert "latency_ms" in columns
        assert "consecutive_failures" in columns
        assert "last_checked" in columns
        conn.close()


class TestArchiveDBInit:
    """Test archive database initialization creates all required tables."""

    def test_creates_all_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(ARCHIVE_SCHEMA)
        conn.commit()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "yearly_summary" in tables
        assert "monthly_snapshot" in tables
        assert "peer_history" in tables
        conn.close()

    def test_yearly_summary_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(ARCHIVE_SCHEMA)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(yearly_summary)").fetchall()
        }
        assert "accounting_year" in columns
        assert "pid" in columns
        assert "total_tx_count" in columns
        assert "total_volume" in columns
        conn.close()


class TestFirstRunGopherhole:
    """Test gopherhole creation works with fresh state."""

    def test_create_gopherhole_with_fresh_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
        monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
        monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
        monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
        monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
        monkeypatch.setattr("core.gopherhole.GOPHER_ROOT", tmp_path / "gopherroot")
        # Monkeypatch cached module-level DB paths and PID_FILE
        monkeypatch.setattr("db.live_db.DB_DIR", tmp_path / ".refinet" / "db")
        monkeypatch.setattr("db.live_db.LIVE_DB_PATH", tmp_path / ".refinet" / "db" / "live.db")
        monkeypatch.setattr("db.archive_db.DB_DIR", tmp_path / ".refinet" / "db")
        monkeypatch.setattr("db.archive_db.ARCHIVE_DB_PATH", tmp_path / ".refinet" / "db" / "archive.db")
        monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
        (tmp_path / "gopherroot").mkdir()

        from db.live_db import init_live_db
        from db.archive_db import init_archive_db
        init_live_db()
        init_archive_db()

        from core.gopherhole import create_gopherhole
        result = create_gopherhole(
            name="Test Site",
            selector="/holes/test",
            description="A test gopherhole",
        )

        assert result["name"] == "Test Site"
        assert result["selector"] == "/holes/test"
        assert result["tx_hash"]
        assert (tmp_path / "gopherroot" / "holes" / "test" / "gophermap").exists()
        assert (tmp_path / "gopherroot" / "holes" / "test" / "README.txt").exists()
