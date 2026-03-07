"""
REFInet Pillar — Gopherhole CLI Commands

Subcommands:
    pillar hole create --name "My Site" --selector /holes/mysite [--desc "..."] [--owner 0x...]
    pillar hole list [--peers] [--json]
    pillar hole verify --pid <pid> --selector /holes/mysite
"""

import json
import sys

from core.gopherhole import create_gopherhole, verify_gopherhole_signature
from db.live_db import list_gopherholes, get_gopherhole


def cmd_hole_create(args):
    """Register a new gopherhole on this pillar."""
    try:
        result = create_gopherhole(
            name=args.name,
            selector=args.selector,
            description=args.desc or "",
            owner_address=args.owner or "",
        )
        print(f"\nGopherhole registered successfully\n")
        print(f"  Name:        {result['name']}")
        print(f"  Selector:    {result['selector']}")
        print(f"  URL:         {result['url']}")
        print(f"  TX Hash:     {result['tx_hash']}")
        print(f"  Local path:  {result['path']}")
        print(f"\nEdit your content at: {result['path']}/gophermap")
        print(f"Your gopherhole is immediately live on the mesh.\n")
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_hole_list(args):
    """List registered gopherholes."""
    source_filter = None if args.peers else "local"
    holes = list_gopherholes(source_filter=source_filter)

    if args.json:
        print(json.dumps([dict(h) for h in holes], indent=2))
        return

    if not holes:
        label = "on this pillar" if not args.peers else "on the mesh"
        print(f"No gopherholes registered {label} yet.")
        print(f"Run: pillar hole create --name \"My Site\" --selector /holes/mysite")
        return

    label = "mesh" if args.peers else "local"
    print(f"\n{len(holes)} gopherhole(s) registered ({label}):\n")
    for h in holes:
        print(f"  [{h['registered_at']}] {h['name']}")
        print(f"    Selector:  {h['selector']}")
        print(f"    PID:       {h['pid'][:16]}...")
        print(f"    Source:     {h['source']}")
        if h.get("description"):
            print(f"    Desc:      {h['description']}")
        print()


def cmd_hole_verify(args):
    """Verify a gopherhole's Ed25519 signature."""
    hole = get_gopherhole(args.pid, args.selector)
    if not hole:
        print(f"Gopherhole not found: {args.selector} @ {args.pid}", file=sys.stderr)
        sys.exit(1)

    valid = verify_gopherhole_signature(hole)
    if valid:
        print(f"Signature valid -- gopherhole record is authentic")
        print(f"  PID:       {hole['pid']}")
        print(f"  Selector:  {hole['selector']}")
        print(f"  TX Hash:   {hole['tx_hash']}")
    else:
        print(f"Signature INVALID -- record may be tampered", file=sys.stderr)
        sys.exit(2)


def register_hole_subcommands(subparsers):
    """Register the 'hole' subcommand group with argparse."""
    hole_parser = subparsers.add_parser("hole", help="Manage gopherholes")
    hole_sub = hole_parser.add_subparsers(dest="hole_cmd")

    # create
    p_create = hole_sub.add_parser("create", help="Register a new gopherhole")
    p_create.add_argument("--name", required=True, help="Display name")
    p_create.add_argument("--selector", required=True, help="Path e.g. /holes/mysite")
    p_create.add_argument("--desc", help="Description")
    p_create.add_argument("--owner", help="EVM address (optional)")
    p_create.set_defaults(func=cmd_hole_create)

    # list
    p_list = hole_sub.add_parser("list", help="List gopherholes")
    p_list.add_argument("--peers", action="store_true", help="Include peer-replicated holes")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.set_defaults(func=cmd_hole_list)

    # verify
    p_verify = hole_sub.add_parser("verify", help="Verify a gopherhole signature")
    p_verify.add_argument("--pid", required=True)
    p_verify.add_argument("--selector", required=True)
    p_verify.set_defaults(func=cmd_hole_verify)

    return hole_parser
