"""
REFInet Pillar — Unified System Watchdog

Aggregates health signals from all subsystems into a single monitoring loop.
Reports status via the /health Gopher route and optionally sends sd_notify
heartbeats for systemd WatchdogSec integration.

Monitors:
  1. Gopher server — TCP self-connect
  2. SQLite DB — PRAGMA integrity_check
  3. Disk space — warn < 100 MB free
  4. Tor hidden service status
  5. VPN tunnel status
  6. Mesh peer connectivity
  7. Audit chain integrity
  8. Memory usage
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.config import DB_DIR, HOME_DIR, ensure_dirs

logger = logging.getLogger("refinet.watchdog")

CHECK_INTERVAL = 60  # seconds between health checks


@dataclass
class HealthStatus:
    """Snapshot of system health."""
    timestamp: float = 0.0
    gopher_ok: bool = False
    db_ok: bool = False
    disk_ok: bool = False
    disk_free_mb: float = 0.0
    tor_ok: Optional[bool] = None  # None = not configured
    vpn_ok: Optional[bool] = None  # None = not configured
    peers_online: int = 0
    peers_total: int = 0
    audit_chain_ok: bool = False
    audit_chain_length: int = 0
    memory_mb: float = 0.0
    errors: list = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Overall health: core systems must be OK."""
        return self.gopher_ok and self.db_ok and self.disk_ok

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "timestamp": int(self.timestamp),
            "gopher_ok": self.gopher_ok,
            "db_ok": self.db_ok,
            "disk_ok": self.disk_ok,
            "disk_free_mb": round(self.disk_free_mb, 1),
            "tor_ok": self.tor_ok,
            "vpn_ok": self.vpn_ok,
            "peers_online": self.peers_online,
            "peers_total": self.peers_total,
            "audit_chain_ok": self.audit_chain_ok,
            "audit_chain_length": self.audit_chain_length,
            "memory_mb": round(self.memory_mb, 1),
            "errors": self.errors,
        }


class SystemWatchdog:
    """
    Periodically checks all subsystem health and exposes the result.

    Usage:
        watchdog = SystemWatchdog(port=7070, tor_manager=tor, vpn_manager=vpn)
        asyncio.create_task(watchdog.run())

        # Later:
        status = watchdog.last_status
    """

    def __init__(self, port: int = 7070, host: str = "127.0.0.1",
                 tor_manager=None, vpn_manager=None):
        self.port = port
        self.host = host
        self.tor_manager = tor_manager
        self.vpn_manager = vpn_manager
        self.last_status: HealthStatus = HealthStatus()
        self._running = False

    async def run(self):
        """Background loop: run health checks every CHECK_INTERVAL seconds."""
        self._running = True
        logger.info("[WATCHDOG] System watchdog started")

        # First check after a short delay to let services start
        await asyncio.sleep(10)

        while self._running:
            try:
                status = await self.check_all()
                self.last_status = status

                if status.healthy:
                    logger.debug("[WATCHDOG] All systems healthy")
                    _sd_notify_watchdog()
                else:
                    logger.warning(
                        f"[WATCHDOG] Unhealthy: {', '.join(status.errors)}"
                    )
            except Exception as e:
                logger.error(f"[WATCHDOG] Check error: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self):
        """Stop the watchdog loop."""
        self._running = False

    async def check_all(self) -> HealthStatus:
        """Run all health checks and return a HealthStatus."""
        status = HealthStatus(timestamp=time.time())
        status.errors = []

        # Run checks concurrently
        results = await asyncio.gather(
            self._check_gopher(status),
            self._check_db(status),
            self._check_disk(status),
            self._check_tor(status),
            self._check_vpn(status),
            self._check_peers(status),
            self._check_audit_chain(status),
            self._check_memory(status),
            return_exceptions=True,
        )

        # Collect any exceptions from checks
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                check_names = [
                    "gopher", "db", "disk", "tor", "vpn",
                    "peers", "audit", "memory",
                ]
                status.errors.append(f"{check_names[i]}: {result}")

        return status

    async def _check_gopher(self, status: HealthStatus):
        """TCP self-connect to verify Gopher server is responding."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=5.0
            )
            writer.write(b"\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            writer.close()
            await writer.wait_closed()
            status.gopher_ok = len(data) > 0
        except Exception:
            status.gopher_ok = False
            status.errors.append("gopher: server not responding")

    async def _check_db(self, status: HealthStatus):
        """PRAGMA integrity_check on the live database."""
        try:
            db_path = DB_DIR / "live.db"
            if not db_path.exists():
                status.db_ok = True  # No DB yet = first run, OK
                return

            def _check():
                conn = sqlite3.connect(str(db_path))
                try:
                    result = conn.execute("PRAGMA integrity_check").fetchone()
                    return result[0] == "ok"
                finally:
                    conn.close()

            loop = asyncio.get_event_loop()
            status.db_ok = await loop.run_in_executor(None, _check)
        except Exception as e:
            status.db_ok = False
            status.errors.append(f"db: {e}")

    async def _check_disk(self, status: HealthStatus):
        """Check available disk space on the data directory."""
        try:
            ensure_dirs()
            usage = shutil.disk_usage(str(HOME_DIR))
            status.disk_free_mb = usage.free / (1024 * 1024)
            status.disk_ok = status.disk_free_mb >= 100
            if not status.disk_ok:
                status.errors.append(
                    f"disk: low space ({status.disk_free_mb:.0f} MB free)"
                )
        except Exception as e:
            status.disk_ok = False
            status.errors.append(f"disk: {e}")

    async def _check_tor(self, status: HealthStatus):
        """Check Tor hidden service status."""
        if self.tor_manager is None:
            status.tor_ok = None
            return
        try:
            status.tor_ok = self.tor_manager.is_active()
        except Exception:
            status.tor_ok = False

    async def _check_vpn(self, status: HealthStatus):
        """Check VPN tunnel status."""
        if self.vpn_manager is None:
            status.vpn_ok = None
            return
        try:
            status.vpn_ok = self.vpn_manager.is_active()
        except Exception:
            status.vpn_ok = False

    async def _check_peers(self, status: HealthStatus):
        """Count online/total peers."""
        try:
            from db.live_db import get_peers
            peers = get_peers()
            status.peers_total = len(peers)
            status.peers_online = sum(
                1 for p in peers if p.get("status") == "online"
            )
        except Exception:
            status.peers_total = 0
            status.peers_online = 0

    async def _check_audit_chain(self, status: HealthStatus):
        """Verify audit chain integrity (last 100 entries for speed)."""
        try:
            from db.audit import verify_chain, get_chain_length
            status.audit_chain_length = get_chain_length()
            if status.audit_chain_length == 0:
                status.audit_chain_ok = True
                return

            valid, _, error = verify_chain(limit=100)
            status.audit_chain_ok = valid
            if not valid:
                status.errors.append(f"audit: {error}")
        except Exception as e:
            status.audit_chain_ok = False
            status.errors.append(f"audit: {e}")

    async def _check_memory(self, status: HealthStatus):
        """Check current process memory usage."""
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in bytes on macOS, KB on Linux
            import sys
            if sys.platform == "darwin":
                status.memory_mb = usage.ru_maxrss / (1024 * 1024)
            else:
                status.memory_mb = usage.ru_maxrss / 1024
        except Exception:
            status.memory_mb = 0.0


def _sd_notify_watchdog():
    """Send systemd watchdog heartbeat (if running under systemd)."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if notify_socket.startswith("@"):
                notify_socket = "\0" + notify_socket[1:]
            sock.sendto(b"WATCHDOG=1", notify_socket)
        finally:
            sock.close()
    except Exception:
        pass
