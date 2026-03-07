#!/usr/bin/env python3
"""
REFInet Pillar — Main Entry Point

Launch your sovereign node in Gopherspace.

Usage:
    python3 pillar.py                    # Start with defaults (port 7070 + 70)
    python3 pillar.py --port 7070        # Specify REFInet port
    python3 pillar.py --gopher-port 70   # Specify standard Gopher port
    python3 pillar.py --no-gopher        # Disable standard Gopher server
    python3 pillar.py --host 0.0.0.0     # Specify bind address
    python3 pillar.py --no-mesh          # Disable peer discovery

    python3 pillar.py hole create --name "My Site" --selector /holes/mysite
    python3 pillar.py hole list [--peers] [--json]
    python3 pillar.py hole verify --pid <pid> --selector /holes/mysite

What happens on launch:
    1. Pillar ID (PID) is generated or loaded from ~/.refinet/pid.json
    2. SQLite databases initialized (live + archive)
    3. REFInet server starts on TCP port 7070 (full features)
    4. Standard Gopher server starts on TCP port 70 (public content)
    5. Peer discovery begins via UDP multicast
    6. You are now part of Gopherspace and the REFInet mesh

Connect with any Gopher client:
    curl gopher://localhost:7070/       # REFInet (full features)
    curl gopher://localhost:70/         # Standard Gopherspace
    lynx gopher://localhost:7070
"""

import argparse
import asyncio
import logging
import sys

from core.config import GOPHER_HOST, GOPHER_PORT, load_config
from core.gopher_server import GopherServer
from core.tor_manager import TorManager
from crypto.pid import get_or_create_pid, get_short_pid
from mesh.discovery import PeerAnnouncer, PeerListener, periodic_health_check
from mesh.replication import periodic_replication
from db.archive_db import periodic_archival
from db.live_db import init_live_db, reset_peer_statuses_to_unknown, checkpoint_live_db
from db.archive_db import checkpoint_archive_db


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def main(host: str, port: int, gopher_port: int, enable_mesh: bool,
               enable_gopher: bool = True):
    """Launch all Pillar services."""
    config = load_config()
    pid_data = get_or_create_pid()
    short_pid = get_short_pid(pid_data)

    # Ensure DB is initialized and peer statuses are reset to unknown
    # so the first health check cycle starts from a clean state.
    init_live_db()
    reset_peer_statuses_to_unknown()

    # Update config with CLI overrides
    config["hostname"] = host if host != "0.0.0.0" else config.get("hostname", "localhost")
    config["port"] = port

    # Tor startup — before TCP servers so bind address can be determined
    tor = TorManager(config)
    tor_active = await tor.start()
    if tor_active:
        onion = await tor.create_hidden_services()
        if onion:
            config["onion_address"] = onion
            _print_tor_banner(onion, port, gopher_port)
        else:
            logging.getLogger("refinet.tor").warning(
                "[TOR] Hidden service creation failed — continuing without Tor"
            )
            tor_active = False

    # Determine bind addresses based on Tor mode
    if tor_active:
        # Port 7070: loopback only (Tor forwards inbound)
        host_7070 = "127.0.0.1"
        # Port 70: loopback if exposed via Tor, otherwise all interfaces
        host_70 = "127.0.0.1" if config.get("tor_expose_port_70") else host
    else:
        host_7070 = host
        host_70 = host

    # REFInet server — full features on port 7070
    refinet_server = GopherServer(host=host_7070, port=port,
                                  hostname=config["hostname"],
                                  is_refinet=True,
                                  tor_manager=tor)

    tasks = [refinet_server.start()]

    # Standard Gopher server — public content on port 70
    if enable_gopher and gopher_port != port:
        gopher_server = GopherServer(host=host_70, port=gopher_port,
                                     hostname=config["hostname"],
                                     is_refinet=False,
                                     tor_manager=tor)
        tasks.append(gopher_server.start())

    # Start archive migration background task
    tasks.append(periodic_archival(pid_data["pid"]))

    # Periodic WAL checkpoint to prevent journal accumulation
    tasks.append(periodic_wal_checkpoint())

    # Tor health monitoring
    if tor_active:
        tasks.append(tor.check_tor_health())

    # Start mesh discovery (unless disabled)
    if enable_mesh:
        # Mesh announces the REFInet port (7070), not the standard Gopher port
        announcer = PeerAnnouncer(
            pid_data=pid_data,
            hostname=config["hostname"],
            port=port,
            pillar_name=config.get("pillar_name", "REFInet Pillar"),
            onion_address=config.get("onion_address"),
        )
        listener = PeerListener(own_pid=pid_data["pid"])
        tasks.append(announcer.run())
        tasks.append(listener.run())
        tasks.append(periodic_replication())
        tasks.append(periodic_health_check())

    try:
        await asyncio.gather(*tasks)
    finally:
        await tor.stop()


def _print_tor_banner(onion_address: str, refinet_port: int, gopher_port: int):
    """Print prominent .onion address banner for operator visibility."""
    print("\n" + "=" * 65)
    print("  REFInet Pillar Tor Address:")
    print(f"  {onion_address}")
    print(f"  (Port {refinet_port} — REFInet full features)")
    print(f"  (Port {gopher_port}   — Standard Gopher, public content)")
    print("=" * 65 + "\n")


def show_status():
    """Display Pillar status from persisted state (offline query)."""
    from core.config import HOME_DIR
    pid_data = get_or_create_pid()
    short_pid = get_short_pid(pid_data)

    print(f"  Pillar ID:  {pid_data['pid']}")
    print(f"  Short PID:  {short_pid}...")
    print(f"  Public Key: {pid_data['public_key'][:32]}...")

    # Tor status
    hs_privkey = HOME_DIR / "tor_data" / "hs_privkey"
    if hs_privkey.exists():
        print("  Tor:        Private key found (address generated at runtime)")
    else:
        print("  Tor:        No hidden service key found")

    # Peer count
    try:
        from db.live_db import get_peers
        peers = get_peers()
        print(f"  Peers:      {len(peers)} known")
    except Exception:
        print("  Peers:      (database not initialized)")


async def periodic_wal_checkpoint(interval_hours: int = 6):
    """Background task: checkpoint WAL files periodically."""
    logger = logging.getLogger("refinet.checkpoint")
    await asyncio.sleep(interval_hours * 3600)
    while True:
        try:
            checkpoint_live_db()
            checkpoint_archive_db()
            logger.debug("WAL checkpoint completed")
        except Exception as e:
            logger.warning(f"WAL checkpoint error: {e}")
        await asyncio.sleep(interval_hours * 3600)


def _add_server_args(parser):
    """Add server-related arguments to a parser."""
    parser.add_argument("--host", default=GOPHER_HOST, help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=GOPHER_PORT, help="REFInet port (default: 7070)")
    parser.add_argument("--gopher-port", type=int, default=70, help="Standard Gopher port (default: 70)")
    parser.add_argument("--no-gopher", action="store_true", help="Disable standard Gopher server on port 70")
    parser.add_argument("--no-mesh", action="store_true", help="Disable peer discovery")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--status", action="store_true", help="Show Pillar status and exit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="REFInet Pillar — Sovereign Gopher Mesh Node",
        epilog="Run your own Pillar. Join Gopherspace.",
    )

    # Server args on the top-level parser (backward compat: `pillar.py --port 7070`)
    _add_server_args(parser)

    subparsers = parser.add_subparsers(dest="command")

    # 'run' subcommand — explicit server start
    run_parser = subparsers.add_parser("run", help="Start the Pillar server")
    _add_server_args(run_parser)

    # 'hole' subcommand group
    from cli.hole import register_hole_subcommands
    register_hole_subcommands(subparsers)

    args = parser.parse_args()
    setup_logging(getattr(args, "verbose", False))

    # Dispatch subcommands
    if args.command == "hole":
        if hasattr(args, "func"):
            args.func(args)
        else:
            parser.parse_args(["hole", "--help"])
    elif args.command == "run" or args.command is None:
        # --status: show status and exit
        if getattr(args, "status", False):
            show_status()
            sys.exit(0)

        # Default: start the server
        host = getattr(args, "host", GOPHER_HOST)
        port = getattr(args, "port", GOPHER_PORT)
        gopher_port = getattr(args, "gopher_port", 70)
        no_mesh = getattr(args, "no_mesh", False)
        no_gopher = getattr(args, "no_gopher", False)
        try:
            asyncio.run(main(host, port, gopher_port,
                             enable_mesh=not no_mesh,
                             enable_gopher=not no_gopher))
        except KeyboardInterrupt:
            print("\n  Pillar shutting down. See you in Gopherspace.\n")
            sys.exit(0)
