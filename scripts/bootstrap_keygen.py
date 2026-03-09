#!/usr/bin/env python3
"""
REFInet Bootstrap Node Key Generator

Run once locally. Never run again. Store output in secrets.

Usage:
    python3 scripts/bootstrap_keygen.py

Output:
    stdout: the full pid.json JSON (pipe to clipboard or a temp file)
    stderr: human-readable summary
"""
import json
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.pid import generate_pid

pid_data = generate_pid(password=None)  # No password — key lives in Fly secrets

# Full JSON to stdout — becomes REFINET_PID_JSON secret
print(json.dumps(pid_data, indent=2))

# Human summary to stderr
print(f"\n{'='*60}", file=sys.stderr)
print(f"  BOOTSTRAP NODE IDENTITY", file=sys.stderr)
print(f"{'='*60}", file=sys.stderr)
print(f"  PID:        {pid_data['pid']}", file=sys.stderr)
print(f"  Public key: {pid_data['public_key']}", file=sys.stderr)
print(f"{'='*60}", file=sys.stderr)
print(f"\n  ⚠  Store the JSON output as REFINET_PID_JSON in:", file=sys.stderr)
print(f"     - GitHub Actions secrets", file=sys.stderr)
print(f"     - Fly.io secrets (flyctl secrets set)", file=sys.stderr)
print(f"  ⚠  Never commit this output to the repo.", file=sys.stderr)
