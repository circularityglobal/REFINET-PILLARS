"""
REFInet Pillar — Identity CLI Commands

Subcommands:
    pillar identity show
    pillar identity rebind --address 0x... [--chain 43113] [--type deployer|operator]

``rebind`` is how a Pillar whose binding predates 0.5.0 gets a proper one.
Before 0.5.0 a binding was made from an ordinary sign-in signature; those
rows still verify, and stay canonical, until the operator re-signs the
statement that actually says what it means:

    I bind this wallet to REFINET Pillar <pid> as its deployer

It needs the wallet, so it can never happen silently. Bindings are
append-only: the old row stays, and the new one becomes canonical.
"""

import os
import sys

from auth.siwe import PURPOSE_BINDING
from crypto.binding import (
    create_binding,
    get_all_bindings,
    get_deployer_binding,
    is_legacy_binding,
    verify_binding,
)
from crypto.pid import is_encrypted, load_pid
from crypto.unlock import get_unlocked_key, is_unlocked, unlock
from db.live_db import init_live_db

_EVM_LEN = 42


def _load_pid_or_exit() -> dict:
    pid_data = load_pid()
    if pid_data is None:
        print("No pid.json found. Run the Pillar once to create an identity.",
              file=sys.stderr)
        sys.exit(1)
    return pid_data


def _unlock_or_exit(pid_data: dict):
    """Unlock the Pillar key, from the environment or an interactive prompt."""
    if not is_encrypted(pid_data) or is_unlocked(pid_data):
        return get_unlocked_key(pid_data)
    password = os.environ.get("REFINET_PID_PASSWORD")
    if password is None and sys.stdin.isatty():
        import getpass
        password = getpass.getpass("Enter PID password: ")
    if not password:
        print("Private key is encrypted. Set REFINET_PID_PASSWORD or run from "
              "a terminal.", file=sys.stderr)
        sys.exit(1)
    try:
        return unlock(pid_data, password)
    except ValueError as exc:
        print(f"Cannot unlock private key: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_identity_show(args):
    """Print this Pillar's identity and its wallet bindings."""
    init_live_db()
    pid_data = _load_pid_or_exit()
    pid = pid_data["pid"]

    print()
    print(f"  PID:         {pid}")
    print(f"  Public key:  {pid_data['public_key']}")
    print(f"  Key store:   {pid_data.get('key_store', 'software')}")
    print(f"  Encrypted:   {'yes' if is_encrypted(pid_data) else 'no'}")

    bindings = get_all_bindings(pid)
    if not bindings:
        print("\n  No wallet bindings. Run the onboarding wizard, or "
              "'pillar identity rebind'.\n")
        return

    canonical = get_deployer_binding(pid)
    print(f"\n  {len(bindings)} binding(s), oldest first:\n")
    for b in bindings:
        ok, reason = verify_binding(b)
        marks = []
        if canonical and b["binding_id"] == canonical["binding_id"]:
            marks.append("canonical")
        if is_legacy_binding(b):
            marks.append("pre-0.5.0")
        suffix = f"  [{', '.join(marks)}]" if marks else ""
        print(f"    {b['binding_id'][:16]}...  {b['binding_type']:<9} "
              f"chain {b['chain_id']:<9} {b['evm_address']}{suffix}")
        print(f"      created {b['created_at']}   verification: "
              f"{'PASS' if ok else 'FAIL'} ({reason})")

    if canonical is not None and is_legacy_binding(canonical):
        print("\n  This Pillar's canonical binding predates 0.5.0: it was made")
        print("  from a sign-in signature, so it is not published in the v3")
        print("  identity document. Re-sign it with:")
        print(f"    pillar identity rebind --address {canonical['evm_address']}")
    print()


def _pending_path():
    from core.config import HOME_DIR
    return HOME_DIR / "pending_binding.json"


def _save_pending(challenge: dict, address: str, binding_type: str) -> None:
    """Remember an issued challenge so a signature can arrive in a later run."""
    import json
    from core.config import ensure_dirs
    ensure_dirs()
    path = _pending_path()
    payload = {"address": address, "type": binding_type,
               "message": challenge["message"], "nonce": challenge["nonce"]}
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, indent=2)


def _load_pending(address: str, binding_type: str):
    import json
    path = _pending_path()
    if not path.exists():
        return None
    try:
        pending = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if (pending.get("address", "").lower() != address.lower()
            or pending.get("type") != binding_type):
        return None
    return pending


def _clear_pending() -> None:
    try:
        _pending_path().unlink(missing_ok=True)
    except OSError:
        pass


def cmd_identity_challenge(args):
    """Issue a binding challenge and remember it for a later `rebind`."""
    from auth.session import create_challenge

    address = (args.address or "").strip()
    if not address.startswith("0x") or len(address) != _EVM_LEN:
        print("Invalid EVM address. Format: 0x followed by 40 hex chars",
              file=sys.stderr)
        sys.exit(1)

    init_live_db()
    _load_pid_or_exit()
    try:
        challenge = create_challenge(
            address, chain_id=args.chain, purpose=PURPOSE_BINDING,
            binding_type=args.type, company_url=args.company_url,
        )
    except ImportError:
        print("Binding requires eth-account: pip install eth-account",
              file=sys.stderr)
        sys.exit(1)

    _save_pending(challenge, address, args.type)
    if args.quiet:
        print(challenge["message"])
        return
    print()
    print(f"  Sign this message with the wallet at {address}:")
    print("  " + "-" * 62)
    for line in challenge["message"].splitlines():
        print(f"  {line}")
    print("  " + "-" * 62)
    print("  Valid for 10 minutes, once. Then run:")
    print(f"    pillar identity rebind --address {address} "
          f"--type {args.type} --signature 0x...")
    print()
    print("  Sign the message exactly as it was issued — a shell pipeline that")
    print("  adds or trims a newline produces a signature that will not match.")
    print(f"  Scripts should read the exact bytes from {_pending_path()}")
    print()


def cmd_identity_rebind(args):
    """Create a §3.1 wallet binding for this Pillar."""
    from auth.session import create_challenge

    address = (args.address or "").strip()
    if not address.startswith("0x") or len(address) != _EVM_LEN:
        print("Invalid EVM address. Format: 0x followed by 40 hex chars",
              file=sys.stderr)
        sys.exit(1)

    init_live_db()
    pid_data = _load_pid_or_exit()
    private_key = _unlock_or_exit(pid_data)

    signature = (args.signature or "").strip()
    pending = _load_pending(address, args.type) if signature else None
    if pending is not None:
        # A challenge issued by an earlier `identity challenge` run. Its
        # nonce is already registered, so this is the message that was signed.
        challenge = {"message": pending["message"], "nonce": pending["nonce"]}
    elif signature:
        print("No pending challenge for that address and type. A signature "
              "only matches the message it was made for — issue one first:\n"
              f"  pillar identity challenge --address {address} "
              f"--type {args.type}", file=sys.stderr)
        sys.exit(1)
    else:
        try:
            challenge = create_challenge(
                address, chain_id=args.chain, purpose=PURPOSE_BINDING,
                binding_type=args.type, company_url=args.company_url,
            )
        except ImportError:
            print("Binding requires eth-account: pip install eth-account",
                  file=sys.stderr)
            sys.exit(1)

    if not signature:
        print()
        print("  Sign this message with the wallet at "
              f"{address}:")
        print("  " + "-" * 62)
        for line in challenge["message"].splitlines():
            print(f"  {line}")
        print("  " + "-" * 62)
        print("  The challenge expires in 10 minutes and can be used once.")
        print()
        try:
            signature = input("  Paste signature (0x...): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.", file=sys.stderr)
            sys.exit(1)

    if not signature:
        print("No signature provided.", file=sys.stderr)
        sys.exit(1)

    try:
        binding = create_binding(
            pid_data=pid_data,
            evm_address=address,
            siwe_message=challenge["message"],
            siwe_signature=signature,
            private_key=private_key,
            binding_type=args.type,
        )
    except ValueError as exc:
        _clear_pending()   # the nonce is spent either way
        print(f"\n  Binding failed: {exc}", file=sys.stderr)
        sys.exit(2)

    _clear_pending()
    ok, reason = verify_binding(binding)
    print()
    print(f"  Binding written: {binding['binding_id']}")
    print(f"  Type:            {binding['binding_type']}")
    print(f"  Chain:           {binding['chain_id']}")
    print(f"  Wallet:          {binding['evm_address']}")
    print(f"  Verification:    {'PASS' if ok else 'FAIL'} ({reason})")
    print()
    print("  It is published at /identity/v3.json. The previous binding is")
    print("  kept — the registry is append-only — but this one is canonical.")
    print()


def register_identity_subcommands(subparsers):
    """Register the 'identity' subcommand group with argparse."""
    identity_parser = subparsers.add_parser(
        "identity", help="Show identity and manage wallet bindings")
    identity_sub = identity_parser.add_subparsers(dest="identity_cmd")

    p_show = identity_sub.add_parser("show", help="Show PID and wallet bindings")
    p_show.set_defaults(func=cmd_identity_show)

    p_challenge = identity_sub.add_parser(
        "challenge", help="Issue a binding challenge to sign (for scripts)")
    p_challenge.add_argument("--address", required=True, help="EVM address (0x...)")
    p_challenge.add_argument("--chain", type=int, default=1,
                             help="Chain ID the wallet signs on (default 1)")
    p_challenge.add_argument("--type", default="deployer",
                             choices=["deployer", "operator"],
                             help="Binding type (default deployer)")
    p_challenge.add_argument("--company-url",
                             help="Optional URL listed in the message's Resources")
    p_challenge.add_argument("--quiet", action="store_true",
                             help="Print only the message, for piping")
    p_challenge.set_defaults(func=cmd_identity_challenge)

    p_rebind = identity_sub.add_parser(
        "rebind", help="Bind a wallet to this Pillar (EIP-4361)")
    p_rebind.add_argument("--address", required=True, help="EVM address (0x...)")
    p_rebind.add_argument("--chain", type=int, default=1,
                          help="Chain ID the wallet signs on (default 1)")
    p_rebind.add_argument("--type", default="deployer",
                          choices=["deployer", "operator"],
                          help="Binding type (default deployer)")
    p_rebind.add_argument("--company-url",
                          help="Optional URL listed in the message's Resources")
    p_rebind.add_argument("--signature",
                          help="Wallet signature; prompted for when omitted")
    p_rebind.set_defaults(func=cmd_identity_rebind)

    return identity_parser
