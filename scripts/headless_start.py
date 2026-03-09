#!/usr/bin/env python3
"""
REFInet Headless Start — Bootstrap Node Entrypoint

Bypasses the onboarding wizard by pre-seeding identity and DB from
the REFINET_PID_JSON environment variable. Then execv's into pillar.py.

This script is the Docker ENTRYPOINT for the bootstrap node.
"""
import json
import os
import sys
from pathlib import Path

# --- Step 1: Read and validate the secret ---

pid_json = os.environ.get("REFINET_PID_JSON")
if not pid_json:
    sys.exit("FATAL: REFINET_PID_JSON environment variable is not set.\n"
             "Set it with: flyctl secrets set REFINET_PID_JSON='...'")

pid_data = json.loads(pid_json)
required = {"pid", "public_key", "private_key", "created_at", "protocol", "key_store"}
if not required.issubset(pid_data.keys()):
    sys.exit(f"FATAL: REFINET_PID_JSON is missing keys: {required - set(pid_data.keys())}")

# --- Step 2: Write directory structure and pid.json ---

home = Path.home() / ".refinet"
(home / "db").mkdir(parents=True, exist_ok=True)

pid_file = home / "pid.json"
pid_file.write_text(json.dumps(pid_data, indent=2))

# --- Step 3: Write config.json ---

config = {
    "hostname": os.environ.get("REFINET_HOSTNAME", "gopher.refinet.io"),
    "port": int(os.environ.get("REFINET_PORT", "7070")),
    "pillar_name": "REFInet Bootstrap Pillar",
    "description": "The canonical REFInet bootstrap node. gopher://gopher.refinet.io:7070",
    "protocol_version": "0.3.0",
    "tor_enabled": False,
    "websocket_enabled": False,
}
(home / "config.json").write_text(json.dumps(config, indent=2))

# --- Step 4: Init DB and insert synthetic binding ---

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.live_db import init_live_db, _connect

init_live_db()

pid = pid_data["pid"]
with _connect() as conn:
    conn.execute("""
        INSERT OR IGNORE INTO pid_bindings
            (binding_id, pid, public_key, evm_address, chain_id,
             siwe_message, siwe_signature, pid_signature, binding_type, created_at)
        VALUES
            ('bootstrap-node-binding', ?, ?, '0x0000000000000000000000000000000000000000',
             1, 'bootstrap', 'bootstrap', 'bootstrap', 'deployer', datetime('now'))
    """, (pid, pid_data["public_key"]))
    conn.commit()

print(f"Headless start: PID {pid[:16]}... ready, DB seeded.", file=sys.stderr)

# --- Step 5: execv into pillar.py ---

pillar = str(Path(__file__).parent.parent / "pillar.py")
os.execv(sys.executable, [
    sys.executable, pillar, "run",
    "--host", "0.0.0.0",
    "--port", os.environ.get("REFINET_PORT", "7070"),
    "--no-gopher",   # port 70 requires root; Fly handles external :70 → :7070
    "--no-mesh",     # UDP multicast is LAN-only; WAN peers use peers.json
])
