"""
REFInet Pillar — Peer Management CLI

Subcommands for adding, listing, and removing known peers.
Enables WAN peer discovery by allowing manual peer registration.
"""

import hashlib


def add_peer(args):
    """Add a peer manually to the known peers database."""
    from db.live_db import init_live_db, upsert_peer

    init_live_db()

    # Generate a placeholder PID from hostname if not provided
    pid = args.pid or hashlib.sha256(
        f"{args.host}:{args.port}".encode()
    ).hexdigest()

    upsert_peer(
        pid=pid,
        public_key="",
        hostname=args.host,
        port=args.port,
        pillar_name=args.name,
    )
    print(f"  Peer added: {args.host}:{args.port}")
    print(f"  PID: {pid[:16]}...")


def list_peers(args):
    """List all known peers."""
    from db.live_db import init_live_db, get_peers

    init_live_db()
    peers = get_peers()

    if not peers:
        print("  No peers known.")
        return

    print(f"  {'Status':>8}  {'Name':20}  {'Address':30}  {'PID':18}")
    print(f"  {'─' * 8}  {'─' * 20}  {'─' * 30}  {'─' * 18}")

    for p in peers:
        status = p.get("status", "unknown")
        name = (p.get("pillar_name") or "?")[:20]
        addr = f"{p['hostname']}:{p.get('port', 7070)}"
        pid_short = p["pid"][:16] + "..."
        onion = p.get("onion_address")
        print(f"  [{status:>8}] {name:20}  {addr:30}  {pid_short}")
        if onion:
            print(f"             .onion: {onion}")


def remove_peer(args):
    """Remove a peer by PID or PID prefix."""
    from db.live_db import init_live_db, get_peers, _connect

    init_live_db()
    peers = get_peers()
    matches = [p for p in peers if p["pid"].startswith(args.pid)]

    if not matches:
        print(f"  No peer matching '{args.pid}'")
        return

    if len(matches) > 1:
        print(f"  Multiple peers match '{args.pid}'. Be more specific:")
        for p in matches:
            print(f"    {p['pid'][:16]}... ({p.get('pillar_name', '?')})")
        return

    peer = matches[0]
    with _connect() as conn:
        conn.execute("DELETE FROM peers WHERE pid = ?", (peer["pid"],))
    print(f"  Removed: {peer.get('pillar_name', peer['pid'][:16])}")


def register_peer_subcommands(subparsers):
    """Register 'peer' subcommand group on the CLI parser."""
    peer_parser = subparsers.add_parser("peer", help="Manage known peers")
    peer_sub = peer_parser.add_subparsers(dest="peer_command")

    # peer add
    peer_add = peer_sub.add_parser("add", help="Add a peer manually")
    peer_add.add_argument("--host", required=True, help="Peer hostname or IP")
    peer_add.add_argument("--port", type=int, default=7070, help="Peer port (default: 7070)")
    peer_add.add_argument("--pid", default=None, help="Peer PID (auto-generated if omitted)")
    peer_add.add_argument("--name", default=None, help="Human-readable peer name")
    peer_add.set_defaults(func=add_peer)

    # peer list
    peer_list = peer_sub.add_parser("list", help="List known peers")
    peer_list.set_defaults(func=list_peers)

    # peer remove
    peer_remove = peer_sub.add_parser("remove", help="Remove a peer by PID prefix")
    peer_remove.add_argument("--pid", required=True, help="PID or PID prefix to match")
    peer_remove.set_defaults(func=remove_peer)
