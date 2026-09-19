"""
REFInet Pillar — Gopherhole Business Logic

Handles gopherhole creation, validation, and signature verification.
A gopherhole is a registered content site on the REFInet Gopher mesh.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.config import GOPHER_ROOT, load_config
from crypto.pid import get_or_create_pid
from crypto.unlock import get_unlocked_key
from crypto.signing import sign_content, verify_signature, pid_matches_key
from db.live_db import (
    register_gopherhole,
    get_accounting_date,
    gopherhole_exists,
)


# /holes/<slug> (original form) or /holes/<first 16 hex of PID>/<slug>
# (namespaced form, opt-in). A slug is global only if nobody else picks it;
# the namespaced form makes the owner part of the name.
SELECTOR_PATTERN = re.compile(
    r"^/holes/(?:(?P<ns>[0-9a-f]{16})/)?[a-zA-Z0-9_-]{1,64}$"
)


def namespaced_selector(pid: str, slug: str) -> str:
    """Return the namespaced selector /holes/<pid[:16]>/<slug>."""
    return f"/holes/{pid[:16]}/{slug}"


STARTER_GOPHERMAP = """\
i{name}\tfake\t(NULL)\t0\r
i{description}\tfake\t(NULL)\t0\r
i\tfake\t(NULL)\t0\r
iPublished on REFInet Pillar\tfake\t(NULL)\t0\r
iPillar ID: {pid}\tfake\t(NULL)\t0\r
iRegistered: {registered_at}\tfake\t(NULL)\t0\r
i\tfake\t(NULL)\t0\r
0README\t{selector}/README.txt\t{host}\t{port}\r
.\r
"""

STARTER_README = """\
# {name}

{description}

## About This Gopherhole

This gopherhole is served by a REFInet Pillar node.
Pillar ID: {pid}
Registered: {registered_at}

## Navigation

Browse this gopherhole at:
  gopher://{host}:{port}{selector}
"""


def validate_selector(selector: str, pid: str | None = None):
    """Selector must be /holes/<slug> or /holes/<pid16>/<slug>.

    When *pid* is given and the selector is namespaced, the namespace must be
    that PID's first 16 hex characters.
    """
    m = SELECTOR_PATTERN.match(selector)
    if not m:
        raise ValueError(
            f"Invalid selector '{selector}'. "
            f"Must match /holes/<slug> or /holes/<pid16>/<slug> where slug is "
            f"1-64 alphanumeric, dash, or underscore chars."
        )
    if pid is not None and m.group("ns") and m.group("ns") != pid[:16]:
        raise ValueError(
            f"Namespaced selector '{selector}' does not belong to PID {pid[:16]}"
        )


def create_gopherhole(name: str, selector: str, description: str = "",
                      owner_address: str = "") -> dict:
    """
    Full gopherhole creation flow:
    1. Validate selector
    2. Scaffold gopherroot directory
    3. Sign registration record
    4. Write to registry
    5. Return registration record
    """
    pid_data = get_or_create_pid()
    pid = pid_data["pid"]
    validate_selector(selector, pid=pid)

    pubkey_hex = pid_data["public_key"]
    private_key = get_unlocked_key(pid_data)

    config = load_config()
    host = config.get("hostname", "localhost")
    port = config.get("port", 7070)

    gopherroot = Path(GOPHER_ROOT)
    hole_dir = gopherroot / selector.lstrip("/")

    if hole_dir.exists():
        raise FileExistsError(
            f"Directory {hole_dir} already exists. "
            f"Gopherhole '{selector}' may already be registered."
        )

    # Check DB too
    if gopherhole_exists(pid, selector):
        raise FileExistsError(
            f"Gopherhole '{selector}' is already registered for this PID."
        )

    # Get accounting date
    day, month, year = get_accounting_date()
    registered_at = f"{year}-{month:02d}-{day:02d}"

    # Scaffold directory structure
    hole_dir.mkdir(parents=True, exist_ok=False)

    desc = description or "A gopherhole on the REFInet mesh."

    # Write starter gophermap
    gophermap_content = STARTER_GOPHERMAP.format(
        name=name,
        description=desc,
        pid=pid,
        selector=selector,
        host=host,
        port=port,
        registered_at=registered_at,
    )
    (hole_dir / "gophermap").write_text(gophermap_content)

    # Write starter README
    readme_content = STARTER_README.format(
        name=name,
        description=desc,
        pid=pid,
        selector=selector,
        host=host,
        port=port,
        registered_at=registered_at,
    )
    (hole_dir / "README.txt").write_text(readme_content)

    # Sign the registration payload
    signing_payload = f"{pid}:{selector}:{name}:{registered_at}"
    signature = sign_content(signing_payload.encode(), private_key)

    # Write to registry — pass registered_at to ensure signature and DB use same date
    tx_hash = register_gopherhole(
        pid=pid,
        selector=selector,
        name=name,
        description=description,
        owner_address=owner_address,
        pubkey_hex=pubkey_hex,
        signature=signature,
        source="local",
        registered_at=registered_at,
    )

    return {
        "pid": pid,
        "selector": selector,
        "name": name,
        "description": description,
        "registered_at": registered_at,
        "tx_hash": tx_hash,
        "path": str(hole_dir),
        "url": f"gopher://{host}:{port}{selector}",
    }


def verify_gopherhole_signature(hole_record: dict) -> bool:
    """
    Verify a gopherhole record. The single verifier every importer calls.

    All checks must pass:
      1. The signed payload is rebuilt from the record's own fields
         (pid:selector:name:registered_at) — never recomputed or re-dated.
      2. The Ed25519 signature verifies against ``pubkey_hex``.
      3. ``pid == SHA-256(pubkey_hex)`` — the key is the PID's key, so
         nobody can register a record claiming someone else's PID.
      4. A namespaced selector's namespace is the record's own PID.

    Returns True/False.
    """
    pid = hole_record["pid"]
    pubkey_hex = hole_record["pubkey_hex"]
    if not pid_matches_key(pid, pubkey_hex):
        return False
    m = SELECTOR_PATTERN.match(hole_record["selector"])
    if m and m.group("ns") and m.group("ns") != pid[:16]:
        return False
    payload = (
        f"{pid}:{hole_record['selector']}:"
        f"{hole_record['name']}:{hole_record['registered_at']}"
    )
    return verify_signature(
        payload.encode(),
        hole_record["signature"],
        pubkey_hex,
    )
