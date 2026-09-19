"""
REFInet Pillar — Witness attestations (§3.3 of the TradeSphere bridge spec)

A witness attestation is a Pillar's signed statement about bytes someone
else published: "I fetched <resource> at <fetched_at>, its body hashed to
<hash>, and that matched / did not match / could not be compared with what
the publisher said it published."

The same object is the receipt format for service proofs (F10): when the
signer is the *requester* and the resource names what a Pillar served,
the requester is attesting it received those bytes.

A witness is not a judge: ``mismatch`` is a flag for a human, never an
instruction to reverse anything.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from crypto.signing import DOMAIN_WITNESS, sign_domain, verify_domain, pid_matches_key

STATUSES = ("match", "mismatch", "unreachable")


def sign_witness(private_key: Ed25519PrivateKey, pid: str, resource: str,
                 fetched_at: int, body_hash: str, status: str) -> dict:
    """Build and sign a witness attestation object."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if "\n" in resource:
        raise ValueError("resource must not contain a newline")
    sig = sign_domain(DOMAIN_WITNESS, private_key,
                      pid, resource, int(fetched_at), body_hash, status)
    return {
        "v": 1,
        "pid": pid,
        "resource": resource,
        "fetched_at": int(fetched_at),
        "hash": body_hash,
        "status": status,
        "sig": sig,
    }


def verify_witness(attestation: dict, public_key_hex: str) -> tuple[bool, str]:
    """Verify an attestation against the signer's public key.

    Checks the version, the status vocabulary, that the key is the PID's
    key, and the domain-separated signature. Returns ``(ok, reason)``.
    """
    try:
        if attestation.get("v") != 1:
            return False, "unsupported version"
        if attestation.get("status") not in STATUSES:
            return False, "unknown status"
        pid = attestation["pid"]
        if not pid_matches_key(pid, public_key_hex):
            return False, "public key does not hash to pid"
        ok = verify_domain(
            DOMAIN_WITNESS, attestation["sig"], public_key_hex,
            pid, attestation["resource"], int(attestation["fetched_at"]),
            attestation["hash"], attestation["status"],
        )
        return (True, "valid") if ok else (False, "signature does not verify")
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"malformed attestation: {exc}"
