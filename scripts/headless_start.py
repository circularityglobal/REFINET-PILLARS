#!/usr/bin/env python3
"""
REFInet Headless Start — Bootstrap Node Entrypoint

Bypasses the onboarding wizard by pre-seeding identity from the
REFINET_PID_JSON environment variable. Then execv's into pillar.py.

This script is the Docker ENTRYPOINT for the bootstrap node.

Two modes:

  Bootstrap (unchanged): REFINET_PID_JSON carries the key, injected from a
  secret on every start.

  Operator (0.6.0): no REFINET_PID_JSON. The key lives on the persistent
  volume; on first start REFINET_GENERATE_PID=1 creates it there. This is
  how a founder's VPS or a company's cloud runs a Pillar: the key is born
  on the machine and never passes through anyone's secret store.

Environment:
    REFINET_PID_JSON      bootstrap mode — the node's pid.json as a JSON string
    REFINET_GENERATE_PID  operator mode — "1" creates a key if the volume has none
    REFINET_PID_PASSWORD  required when the private key is (or should be) encrypted
    REFINET_HOSTNAME      hostname the node advertises (default: REFINET_PUBLIC_DOMAIN,
                          else gopher.refinet.io in bootstrap mode)
    REFINET_PORT          REFInet port (default 7070)
    REFINET_PILLAR_NAME   display name
    REFINET_*             every other setting — see core/config.py _ENV_OVERRIDES

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


def _drop_privileges():
    """Give the data directory to REFINET_RUN_AS, then become that user.

    Volumes arrive owned by root (Fly volumes, host bind mounts, Docker's
    mount point for a directory the image did not create), and a Pillar
    running unprivileged could not write its own key or database into one.
    The image starts as root with REFINET_RUN_AS=refinet, so this fixes
    ownership and drops root before any Pillar code runs. Nothing happens
    outside the image (the variable is unset) or when the platform already
    started us unprivileged (Kubernetes runAsUser).
    """
    user = os.environ.get("REFINET_RUN_AS")
    if not user or os.name != "posix" or os.geteuid() != 0:
        return
    import pwd
    pw = pwd.getpwnam(user)
    data = Path(pw.pw_dir) / ".refinet"
    data.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(data):
        for name in [root] + [os.path.join(root, n) for n in dirs + files]:
            os.lchown(name, pw.pw_uid, pw.pw_gid)
    os.setgroups([])
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.environ["HOME"] = pw.pw_dir   # core.config derives ~/.refinet from it


_drop_privileges()

# --- Step 1: Read and validate the secret ---

from core.config import ensure_dirs, PID_FILE, CONFIG_FILE, PROTOCOL_VERSION
from crypto.pid import generate_pid, load_pid, save_pid

pid_json = os.environ.get("REFINET_PID_JSON")
bootstrap_mode = bool(pid_json)
generated = False
if pid_json:
    pid_data = json.loads(pid_json)
else:
    pid_data = load_pid(PID_FILE)
    if pid_data is None:
        if os.environ.get("REFINET_GENERATE_PID", "").lower() not in ("1", "true", "yes"):
            sys.exit("FATAL: REFINET_PID_JSON environment variable is not set.\n"
                     "Set it with: flyctl secrets set REFINET_PID_JSON='...'\n"
                     "Or, to create this Pillar's key on its own volume, set "
                     "REFINET_GENERATE_PID=1.")
        pid_data = generate_pid(password=os.environ.get("REFINET_PID_PASSWORD") or None)
        generated = True

required = {"pid", "public_key", "private_key", "created_at", "protocol", "key_store"}
if not required.issubset(pid_data.keys()):
    source = "REFINET_PID_JSON" if pid_json else str(PID_FILE)
    sys.exit(f"FATAL: {source} is missing keys: {required - set(pid_data.keys())}")

# An encrypted key cannot be unlocked without its password, and there is
# nobody at a terminal here — fail now rather than after the server starts.
if isinstance(pid_data["private_key"], dict) and not os.environ.get("REFINET_PID_PASSWORD"):
    sys.exit("FATAL: REFINET_PID_JSON holds an encrypted key but "
             "REFINET_PID_PASSWORD is not set.\n"
             "Set it with: flyctl secrets set REFINET_PID_PASSWORD='...'")

# --- Step 2: Write directory structure and pid.json ---

ensure_dirs()                      # also enforces 0700 on ~/.refinet
if pid_json or generated:
    save_pid(pid_data, PID_FILE)   # writes 0600

# --- Step 3: Write config.json ---

if bootstrap_mode:
    default_host = "gopher.refinet.io"
    default_name = "REFInet Bootstrap Pillar"
    default_description = "The canonical REFInet bootstrap node. gopher://gopher.refinet.io:7070"
else:
    default_host = os.environ.get("REFINET_PUBLIC_DOMAIN") or "localhost"
    default_name = "REFInet Pillar"
    default_description = "A sovereign node in Gopherspace"

# Keys an operator added to config.json by hand survive a restart; the
# ones below are (re)asserted from the environment every start.
try:
    config = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
except (json.JSONDecodeError, OSError):
    config = {}
config.update({
    "hostname": os.environ.get("REFINET_HOSTNAME", default_host),
    "port": int(os.environ.get("REFINET_PORT", "7070")),
    "pillar_name": os.environ.get("REFINET_PILLAR_NAME", default_name),
    "description": default_description,
    "protocol_version": PROTOCOL_VERSION,
    "tor_enabled": False,
    "websocket_enabled": False,
})
CONFIG_FILE.write_text(json.dumps(config, indent=2))

# --- Step 4: Init DB ---

from db.live_db import init_live_db

init_live_db()

mode = "bootstrap" if bootstrap_mode else ("operator, new key" if generated else "operator")
print(f"Headless start ({mode}): PID {pid_data['pid'][:16]}... ready, DB seeded.", file=sys.stderr)
if generated:
    print(f"PILLAR_ID={pid_data['pid']}", file=sys.stderr)

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
