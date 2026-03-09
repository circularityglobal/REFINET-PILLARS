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
import os
import signal
import sys

from core.config import GOPHER_HOST, GOPHER_PORT, PID_LOCKFILE, load_config
from core.gopher_server import GopherServer
from core.tor_manager import TorManager
from crypto.pid import get_or_create_pid, get_short_pid
from mesh.discovery import PeerAnnouncer, PeerListener, periodic_health_check
from mesh.replication import periodic_replication
from db.archive_db import periodic_archival
from db.live_db import init_live_db, reset_peer_statuses_to_unknown, checkpoint_live_db
from db.archive_db import checkpoint_archive_db
from core.watchdog import SystemWatchdog


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def check_dependencies():
    """Log status of optional dependencies at startup."""
    dep_logger = logging.getLogger("refinet.deps")
    deps = [
        ("websockets", "WebSocket bridge"),
        ("web3", "EVM RPC gateway"),
        ("eth_account", "SIWE authentication"),
        ("stem", "Tor hidden services"),
        ("pkcs11", "HSM hardware keys"),
        ("qrcode", "QR code generation"),
    ]
    for module_name, feature in deps:
        try:
            __import__(module_name)
            dep_logger.debug(f"  {feature}: available")
        except ImportError:
            dep_logger.info(f"  {feature}: not installed (disabled)")


async def main(host: str, port: int, gopher_port: int, enable_mesh: bool,
               enable_gopher: bool = True):
    """Launch all Pillar services."""
    check_dependencies()
    config = load_config()
    pid_data = get_or_create_pid()
    short_pid = get_short_pid(pid_data)

    # Ensure DB is initialized and peer statuses are reset to unknown
    # so the first health check cycle starts from a clean state.
    init_live_db()
    reset_peer_statuses_to_unknown()

    # Load bootstrap/manual peers from peers.json if it exists
    from mesh.discovery import load_bootstrap_peers
    from core.config import PEERS_FILE
    loaded = load_bootstrap_peers(PEERS_FILE)
    if loaded:
        logging.getLogger("refinet").info(
            f"Loaded {loaded} bootstrap peer(s) from peers.json"
        )

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

    # WebSocket bridge — browser extension communication on port 7075
    from integration.websocket_bridge import start_websocket_bridge
    tasks.append(start_websocket_bridge(refinet_server, config))

    # IPC socket — local process communication via Unix socket
    from integration.ipc_socket import start_ipc_server
    tasks.append(start_ipc_server(refinet_server, config))

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

    # System watchdog — unified health monitoring
    watchdog = SystemWatchdog(
        port=port, host="127.0.0.1",
        tor_manager=tor if tor_active else None,
    )
    refinet_server.watchdog = watchdog  # Expose to route handler
    tasks.append(watchdog.run())

    # Write PID lockfile
    try:
        PID_LOCKFILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass

    # Register signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logging.getLogger("refinet").info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    try:
        # Run all tasks until shutdown signal
        task_group = asyncio.gather(*tasks, return_exceptions=True)
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            {task_group, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        await tor.stop()
        # Cleanup lockfile
        try:
            PID_LOCKFILE.unlink(missing_ok=True)
        except OSError:
            pass


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


def _handle_profile_command(args):
    """Handle profile subcommands."""
    from crypto.profiles import (
        list_profiles, create_profile, switch_profile,
        get_active_profile, get_profile_info, delete_profile,
    )
    import getpass

    cmd = getattr(args, "profile_command", None)
    if cmd == "create":
        password = None
        if args.encrypt:
            password = getpass.getpass("Enter password for key encryption: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match.")
                sys.exit(1)
        pid_data = create_profile(args.name, password=password)
        print(f"  Profile '{args.name}' created.")
        print(f"  PID: {pid_data['pid']}")
        if password:
            print("  Private key: ENCRYPTED (AES-256-GCM)")
    elif cmd == "list":
        profiles = list_profiles()
        active = get_active_profile()
        if not profiles:
            print("  No profiles found.")
        else:
            for name in profiles:
                marker = " (active)" if name == active else ""
                info = get_profile_info(name)
                enc = " [encrypted]" if info.get("encrypted") else ""
                print(f"  {name}{marker}{enc} — PID: {info.get('pid', '?')[:16]}...")
    elif cmd == "switch":
        pid_data = switch_profile(args.name)
        print(f"  Switched to profile '{args.name}'")
        print(f"  PID: {pid_data['pid']}")
    elif cmd == "info":
        name = args.name or get_active_profile()
        info = get_profile_info(name)
        print(f"  Profile: {info['name']}")
        print(f"  PID: {info.get('pid', '?')}")
        print(f"  Public Key: {info.get('public_key', '?')[:32]}...")
        print(f"  Encrypted: {'yes' if info.get('encrypted') else 'no'}")
        print(f"  Key Store: {info.get('key_store', 'software')}")
        print(f"  Active: {'yes' if info.get('active') else 'no'}")
    elif cmd == "delete":
        delete_profile(args.name)
        print(f"  Profile '{args.name}' deleted.")
    else:
        print("Usage: pillar.py profile {create|list|switch|info|delete}")


def _handle_recovery_command(args):
    """Handle recovery subcommands."""
    import getpass

    cmd = getattr(args, "recovery_command", None)
    if cmd == "split":
        from crypto.pid import get_or_create_pid, is_encrypted
        from crypto.recovery import generate_recovery_shares

        pid_data = get_or_create_pid()
        password = None
        if is_encrypted(pid_data):
            password = getpass.getpass("Enter PID password: ")

        shares = generate_recovery_shares(
            pid_data, password=password,
            threshold=args.threshold, num_shares=args.shares,
        )
        print(f"\n  Recovery shares generated ({args.threshold}-of-{args.shares}):")
        print(f"  PID: {pid_data['pid'][:16]}...\n")
        for i, share in enumerate(shares, 1):
            print(f"  Share {i}: {share}")
        print(f"\n  Store each share in a SEPARATE secure location.")
        print(f"  Any {args.threshold} shares can reconstruct your private key.\n")

    elif cmd == "restore":
        from crypto.recovery import recover_key
        from crypto.pid import save_pid
        import hashlib

        print("  Enter recovery shares (one per line, empty line to finish):")
        shares = []
        while True:
            line = input("  > ").strip()
            if not line:
                break
            shares.append(line)

        if not shares:
            print("  No shares provided.")
            sys.exit(1)

        try:
            priv_hex = recover_key(shares)
        except ValueError as e:
            print(f"  Recovery failed: {e}")
            sys.exit(1)

        # Reconstruct PID from recovered key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        import time

        priv_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
        pub_bytes = priv_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        pid_hash = hashlib.sha256(pub_bytes).hexdigest()

        pid_data = {
            "pid": pid_hash,
            "public_key": pub_bytes.hex(),
            "private_key": priv_hex,
            "created_at": int(time.time()),
            "protocol": "REFInet-v0.2",
            "key_store": "software",
        }

        password = getpass.getpass("Set password for recovered key (or Enter for none): ")
        if password:
            from crypto.pid import encrypt_private_key
            pid_data["private_key"] = encrypt_private_key(priv_hex, password)

        save_pid(pid_data)
        print(f"\n  Key recovered successfully!")
        print(f"  PID: {pid_hash}")
        print(f"  Saved to: ~/.refinet/pid.json\n")
    else:
        print("Usage: pillar.py recovery {split|restore}")


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

    # 'peer' subcommand group
    from cli.peer import register_peer_subcommands
    register_peer_subcommands(subparsers)

    # 'profile' subcommand group
    profile_parser = subparsers.add_parser("profile", help="Manage identity profiles")
    profile_sub = profile_parser.add_subparsers(dest="profile_command")

    profile_create = profile_sub.add_parser("create", help="Create a new profile")
    profile_create.add_argument("--name", required=True, help="Profile name")
    profile_create.add_argument("--encrypt", action="store_true", help="Encrypt the private key")

    profile_sub.add_parser("list", help="List all profiles")

    profile_switch = profile_sub.add_parser("switch", help="Switch active profile")
    profile_switch.add_argument("--name", required=True, help="Profile to switch to")

    profile_info = profile_sub.add_parser("info", help="Show profile details")
    profile_info.add_argument("--name", help="Profile name (default: active)")

    profile_delete = profile_sub.add_parser("delete", help="Delete a profile")
    profile_delete.add_argument("--name", required=True, help="Profile to delete")

    # 'recovery' subcommand group
    recovery_parser = subparsers.add_parser("recovery", help="Key backup & recovery")
    recovery_sub = recovery_parser.add_subparsers(dest="recovery_command")

    recovery_split = recovery_sub.add_parser("split", help="Split key into recovery shares")
    recovery_split.add_argument("--threshold", type=int, default=3,
                                help="Minimum shares to recover (default: 3)")
    recovery_split.add_argument("--shares", type=int, default=5,
                                help="Total shares to generate (default: 5)")

    recovery_sub.add_parser("restore", help="Restore key from recovery shares")

    args = parser.parse_args()
    setup_logging(getattr(args, "verbose", False))

    # Dispatch subcommands
    if args.command == "profile":
        _handle_profile_command(args)
        sys.exit(0)
    elif args.command == "recovery":
        _handle_recovery_command(args)
        sys.exit(0)
    elif args.command == "hole":
        if hasattr(args, "func"):
            args.func(args)
        else:
            parser.parse_args(["hole", "--help"])
    elif args.command == "peer":
        if hasattr(args, "func"):
            args.func(args)
        else:
            parser.parse_args(["peer", "--help"])
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
