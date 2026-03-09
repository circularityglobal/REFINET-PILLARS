"""Shared pytest fixtures for REFInet Pillar tests."""

import sqlite3
import pytest
from pathlib import Path
from crypto.pid import generate_pid, get_private_key
from db.schema import LIVE_SCHEMA


@pytest.fixture(autouse=True)
def _patch_db_paths(tmp_path, monkeypatch):
    """Ensure DB module-level paths point to tmp_path so CI works without ~/.refinet."""
    db_dir = tmp_path / ".refinet" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_path / ".refinet"
    monkeypatch.setattr("core.config.HOME_DIR", home_dir)
    monkeypatch.setattr("core.config.DB_DIR", db_dir)
    monkeypatch.setattr("db.live_db.LIVE_DB_PATH", db_dir / "live.db")
    monkeypatch.setattr("db.archive_db.ARCHIVE_DB_PATH", db_dir / "archive.db")
    # Reset the initialization flag so each test re-initializes with patched paths
    import core.gopher_server as _gs
    monkeypatch.setattr(_gs, "_db_initialized", False)


@pytest.fixture
def test_pid():
    """Generate a fresh test PID for each test."""
    return generate_pid()


@pytest.fixture
def test_private_key(test_pid):
    """Get the Ed25519 private key object from a test PID."""
    return get_private_key(test_pid)


@pytest.fixture
def memory_db():
    """
    In-memory SQLite database with the full live schema applied.
    Yields a connection with Row factory enabled.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(LIVE_SCHEMA)
    conn.commit()
    yield conn
    conn.close()
