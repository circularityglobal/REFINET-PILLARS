"""
REFInet Pillar — Archive Database Manager

Stores compressed yearly data for long-term historical records.
Data flows: Live DB → (after 13 months) → Archive DB

Archive is append-only and lightweight.
"""

from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path

from core.config import DB_DIR, ensure_dirs
from db.schema import ARCHIVE_SCHEMA


ARCHIVE_DB_PATH = DB_DIR / "archive.db"


@contextmanager
def _connect():
    ensure_dirs()
    conn = sqlite3.connect(str(ARCHIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_archive_db():
    """Create the archive database and all tables."""
    with _connect() as conn:
        conn.executescript(ARCHIVE_SCHEMA)
        conn.commit()


def archive_yearly_summary(
    accounting_year: int,
    pid: str,
    total_tx_count: int = 0,
    total_volume: float = 0.0,
    avg_latency_ms: float = 0.0,
    total_content_served: int = 0,
    total_uptime_seconds: int = 0,
    peers_seen: int = 0,
):
    """Write or update a yearly summary record."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO yearly_summary
               (accounting_year, pid, total_tx_count, total_volume,
                avg_latency_ms, total_content_served, total_uptime_seconds, peers_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(accounting_year, pid) DO UPDATE SET
                   total_tx_count=excluded.total_tx_count,
                   total_volume=excluded.total_volume,
                   avg_latency_ms=excluded.avg_latency_ms,
                   total_content_served=excluded.total_content_served,
                   total_uptime_seconds=excluded.total_uptime_seconds,
                   peers_seen=excluded.peers_seen""",
            (accounting_year, pid, total_tx_count, total_volume,
             avg_latency_ms, total_content_served, total_uptime_seconds, peers_seen),
        )
        conn.commit()


def archive_monthly_snapshot(
    accounting_year: int,
    accounting_month: int,
    pid: str,
    tx_count: int,
    volume: float,
    snapshot_data: dict,
    content_hash: str = None,
):
    """Store a compressed monthly snapshot (daily data as JSON blob)."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO monthly_snapshot
               (accounting_year, accounting_month, pid, tx_count, volume,
                snapshot_data, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(accounting_year, accounting_month, pid) DO UPDATE SET
                   tx_count=excluded.tx_count,
                   volume=excluded.volume,
                   snapshot_data=excluded.snapshot_data,
                   content_hash=excluded.content_hash""",
            (accounting_year, accounting_month, pid, tx_count, volume,
             json.dumps(snapshot_data), content_hash),
        )
        conn.commit()


def checkpoint_archive_db():
    """Run a WAL checkpoint to prevent journal file accumulation."""
    with _connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def get_yearly_summaries(pid: str) -> list[dict]:
    """Get all yearly summaries for a Pillar."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM yearly_summary WHERE pid=? ORDER BY accounting_year DESC",
            (pid,),
        ).fetchall()
        return [dict(r) for r in rows]


def migrate_to_archive(pid: str) -> int:
    """
    Migrate data older than 13 months from live DB to archive DB.
    Returns count of months archived.
    """
    from db.live_db import _connect as live_connect, get_accounting_date
    from core.config import LIVE_DB_RETENTION_MONTHS
    from crypto.signing import hash_content

    current_day, current_month, current_year = get_accounting_date()
    current_total = current_year * 13 + current_month
    cutoff_total = current_total - LIVE_DB_RETENTION_MONTHS

    archived_count = 0

    with live_connect() as live_conn:
        rows = live_conn.execute(
            """SELECT DISTINCT accounting_year, accounting_month
               FROM daily_metrics
               WHERE pid=?
               ORDER BY accounting_year, accounting_month""",
            (pid,),
        ).fetchall()

        for row in rows:
            year = row["accounting_year"]
            month = row["accounting_month"]
            row_total = year * 13 + month

            if row_total >= cutoff_total:
                continue

            metrics = live_conn.execute(
                """SELECT
                       SUM(total_tx_count) as tx_count,
                       SUM(total_volume) as volume,
                       AVG(avg_latency_ms) as avg_latency,
                       SUM(content_served) as content_served,
                       SUM(uptime_seconds) as uptime,
                       MAX(peers_connected) as peers
                   FROM daily_metrics
                   WHERE accounting_year=? AND accounting_month=? AND pid=?""",
                (year, month, pid),
            ).fetchone()

            daily_rows = live_conn.execute(
                """SELECT * FROM daily_metrics
                   WHERE accounting_year=? AND accounting_month=? AND pid=?""",
                (year, month, pid),
            ).fetchall()
            snapshot_data = [dict(r) for r in daily_rows]
            snapshot_hash = hash_content(
                json.dumps(snapshot_data, sort_keys=True, default=str).encode()
            )

            archive_monthly_snapshot(
                accounting_year=year,
                accounting_month=month,
                pid=pid,
                tx_count=metrics["tx_count"] or 0,
                volume=metrics["volume"] or 0.0,
                snapshot_data=snapshot_data,
                content_hash=snapshot_hash,
            )

            archive_yearly_summary(
                accounting_year=year,
                pid=pid,
                total_tx_count=metrics["tx_count"] or 0,
                total_volume=metrics["volume"] or 0.0,
                avg_latency_ms=metrics["avg_latency"] or 0.0,
                total_content_served=metrics["content_served"] or 0,
                total_uptime_seconds=metrics["uptime"] or 0,
                peers_seen=metrics["peers"] or 0,
            )

            archived_count += 1

    return archived_count


async def periodic_archival(pid: str, interval_hours: int = 24):
    """Background task: check for archivable data once per day."""
    import asyncio
    import logging

    logger = logging.getLogger("refinet.archive")

    await asyncio.sleep(60)
    logger.info(f"Archive monitor started ({interval_hours}h interval)")

    while True:
        try:
            count = migrate_to_archive(pid)
            if count:
                logger.info(f"Archived {count} month(s) of metrics data")
                # Checkpoint WAL after successful migration to reclaim space
                try:
                    from db.live_db import checkpoint_live_db
                    checkpoint_live_db()
                    checkpoint_archive_db()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Archival error: {e}")
        await asyncio.sleep(interval_hours * 3600)
