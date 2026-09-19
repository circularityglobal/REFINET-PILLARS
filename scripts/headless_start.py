#!/usr/bin/env python3
"""
REFInet Headless Start — Bootstrap Node Entrypoint

Bypasses the onboarding wizard by pre-seeding identity from the
REFINET_PID_JSON environment variable. Then execv's into pillar.py.

This script is the Docker ENTRYPOINT for the bootstrap node.

Environment:
    REFINET_PID_JSON      required — the node's pid.json as a JSON string
    REFINET_PID_PASSWORD  required when the private key is encrypted
    REFINET_HOSTNAME      hostname the node advertises (default gopher.refinet.io)
    REFINET_PORT          REFInet port (default 7070)

The key is written through ``crypto.pid.save_pid``, which gives it mode
0600. No binding is fabricated: a bootstrap node has no wallet, and a
binding nobody signed would fail verification and mislead any peer that
read it. Onboarding is skipped by REFINET_HEADLESS instead.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# --- Step 1: Read and validate the secret ---

pid_json = os.environ.get("REFINET_PID_JSON")
if not pid_json:
    sys.exit("FATAL: REFINET_PID_JSON environment variable is not set.\n"
             "Set it with: flyctl secrets set REFINET_PID_JSON='...'")

pid_data = json.loads(pid_json)
required = {"pid", "public_key", "private_key", "created_at", "protocol", "key_store"}
if not required.issubset(pid_data.keys()):
    sys.exit(f"FATAL: REFINET_PID_JSON is missing keys: {required - set(pid_data.keys())}")

# An encrypted key cannot be unlocked without its password, and there is
# nobody at a terminal here — fail now rather than after the server starts.
if isinstance(pid_data["private_key"], dict) and not os.environ.get("REFINET_PID_PASSWORD"):
    sys.exit("FATAL: REFINET_PID_JSON holds an encrypted key but "
             "REFINET_PID_PASSWORD is not set.\n"
             "Set it with: flyctl secrets set REFINET_PID_PASSWORD='...'")

# --- Step 2: Write directory structure and pid.json ---

from core.config import ensure_dirs, PID_FILE, CONFIG_FILE, PROTOCOL_VERSION
from crypto.pid import save_pid

ensure_dirs()                      # also enforces 0700 on ~/.refinet
save_pid(pid_data, PID_FILE)       # writes 0600

# --- Step 3: Write config.json ---

config = {
    "hostname": os.environ.get("REFINET_HOSTNAME", "gopher.refinet.io"),
    "port": int(os.environ.get("REFINET_PORT", "7070")),
    "pillar_name": "REFInet Bootstrap Pillar",
    "description": "The canonical REFInet bootstrap node. gopher://gopher.refinet.io:7070",
    "protocol_version": PROTOCOL_VERSION,
    "tor_enabled": False,
    "websocket_enabled": False,
}
CONFIG_FILE.write_text(json.dumps(config, indent=2))

# --- Step 4: Init DB ---

from db.live_db import init_live_db

init_live_db()

print(f"Headless start: PID {pid_data['pid'][:16]}... ready, DB seeded.", file=sys.stderr)

# --- Step 5: execv into pillar.py ---

# The wizard exists to guarantee a wallet-bound identity before serving.
# A bootstrap node has no wallet, so it declares itself headless instead of
# carrying a binding it never signed.
os.environ["REFINET_HEADLESS"] = "1"

pillar = str(Path(__file__).parent.parent / "pillar.py")
os.execv(sys.executable, [
    sys.executable, pillar, "run",
    "--host", "0.0.0.0",
    "--port", os.environ.get("REFINET_PORT", "7070"),
    "--no-gopher",   # port 70 requires root; Fly handles external :70 → :7070
    "--no-mesh",     # UDP multicast is LAN-only; WAN peers use peers.json
])
