"""Shared pytest fixtures for REFInet Pillar tests."""

import sqlite3
import pytest
from pathlib import Path
from crypto.pid import generate_pid, get_private_key
from db.schema import LIVE_SCHEMA


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
