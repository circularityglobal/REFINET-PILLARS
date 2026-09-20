"""
REFInet Pillar — /.well-known/refinet.json (domain proof)

A Pillar on a live domain serves a signed document at
``https://<domain>/.well-known/refinet.json`` naming its PID, its key and
where it answers. Serving it proves control of the domain; the signature
proves the PID's key vouches for the domain. Together with the staking
contract's ``endpointOf(pid)`` it closes the loop:

    domain  --serves-->  PID  --bound to-->  wallet  --staked-->  100,000 REFI

An app on the same domain family (the founder's apex, say) can serve the
same document — by proxying or rewriting to the Pillar — and appear in
``linked_domains``: that is how an app claims its Pillar.

The signature is Ed25519 under REFINET-WELL-KNOWN-v1 over
SHA-256(canonical JSON of the document without "signature").
"""

from __future__ import annotations

import re
import time

from crypto.signing import (
    DOMAIN_WELL_KNOWN, canonical_json, hash_content, pid_matches_key,
    sign_domain, verify_domain,
)

SCHEMA = "refinet-pillar/1"
WELL_KNOWN_PATH = "/.well-known/refinet.json"

# RFC 1123 host name, lower case, no port, no trailing dot.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def normalize_domain(value: str) -> str:
    """Lower-case a domain and strip a scheme, path or trailing dot."""
    value = (value or "").strip().lower()
    value = re.sub(r"^[a-z]+://", "", value)
    value = value.split("/", 1)[0].rstrip(".")
    return value


def is_valid_domain(value: str) -> bool:
    """A dotted host name (no IP literal, no port)."""
    return bool(_DOMAIN_RE.match(value or "")) and not re.fullmatch(r"[0-9.]+", value)


def build_well_known(pid_data: dict, private_key, config: dict,
                     issued_at: int | None = None) -> dict:
    """Build and sign this Pillar's well-known document from its config."""
    from core.version import __version__

    domain = normalize_domain(config.get("public_domain", ""))
    host = domain or config.get("hostname", "localhost")
    port = int(config.get("port", 7070))
    endpoints = {"gopher": f"gopher://{host}:{port}"}
    if config.get("tls_port"):
        endpoints["gophers"] = f"gophers://{host}:{int(config['tls_port'])}"
    if config.get("http_gateway_enabled") and domain:
        endpoints["http"] = f"https://{domain}"

    doc = {
        "schema": SCHEMA,
        "protocol": __version__,
        "pid": pid_data["pid"],
        "public_key": pid_data["public_key"],
        "domain": domain,
        "linked_domains": sorted({normalize_domain(d) for d in config.get("linked_domains") or []
                                  if normalize_domain(d)}),
        "endpoints": endpoints,
        "staking": {
            "chain_id": int(config.get("staking_chain_id", 50)),
            "contracts": list(config.get("staking_contracts") or []),
        },
        "issued_at": int(time.time()) if issued_at is None else int(issued_at),
    }
    doc["signature"] = sign_domain(DOMAIN_WELL_KNOWN, private_key,
                                   hash_content(canonical_json(doc)))
    return doc


def verify_well_known(doc: dict, expected_pid: str | None = None,
                      expected_domain: str | None = None,
                      max_age_sec: int | None = None) -> tuple[bool, str]:
    """Check a fetched document: schema, key-to-PID, signature, and claims.

    ``expected_domain`` is the domain it was fetched from; it must be the
    document's ``domain`` or one of its ``linked_domains``.

    ``max_age_sec`` refuses a document older than that, so a proof captured
    before a Pillar moved domains cannot be replayed for ever. A Pillar
    builds this document per request; only a stored copy goes stale.
    """
    try:
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            return (False, "not a refinet-pillar/1 document")
        if not pid_matches_key(doc["pid"], doc["public_key"]):
            return (False, "public key does not hash to pid")
        body = {k: v for k, v in doc.items() if k != "signature"}
        if not verify_domain(DOMAIN_WELL_KNOWN, doc["signature"], doc["public_key"],
                             hash_content(canonical_json(body))):
            return (False, "signature does not verify")
        if expected_pid and doc["pid"] != expected_pid.lower():
            return (False, "document names a different PID")
        if max_age_sec is not None:
            age = time.time() - int(doc.get("issued_at", 0))
            if age > max_age_sec:
                return (False, f"document is {int(age // 86400)} days old")
        if expected_domain:
            want = normalize_domain(expected_domain)
            claimed = {doc.get("domain")} | set(doc.get("linked_domains") or [])
            if want not in claimed:
                return (False, f"document does not claim {want}")
        return (True, "valid")
    except (KeyError, TypeError, AttributeError) as exc:
        return (False, f"malformed document: {exc}")


def gopher_endpoint(doc: dict) -> tuple[str, int] | None:
    """(host, port) from a verified document's gopher endpoint."""
    m = re.match(r"^gopher://([^/:]+):(\d+)", (doc.get("endpoints") or {}).get("gopher", ""))
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))
