"""
REFInet Pillar — Content Signing & Verification

Every menu and file served by a Pillar can be signed with its PID.
Other nodes verify signatures to ensure content authenticity.

This is the trust layer that makes REFInet censorship-resistant:
  - Content is self-authenticating (signed by origin PID)
  - No central authority needed to verify
  - Compatible with blockchain anchoring (hash + sig on-chain)
"""

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def hash_content(data: bytes) -> str:
    """SHA-256 hash of content, returned as hex string."""
    return hashlib.sha256(data).hexdigest()


def sign_content(data: bytes, private_key: Ed25519PrivateKey) -> str:
    """Sign content bytes, return hex-encoded signature."""
    signature = private_key.sign(data)
    return signature.hex()


def verify_signature(data: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """
    Verify a content signature against a public key.

    Returns True if valid, False otherwise.
    """
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        sig_bytes = bytes.fromhex(signature_hex)
        public_key.verify(sig_bytes, data)
        return True
    except (InvalidSignature, Exception):
        return False


# ---------------------------------------------------------------------------
# Domain-separated signatures
#
# Every signature a Pillar makes over a structured statement is prefixed with
# a fixed domain string, so a signature made for one purpose (a response, a
# binding, an identity document, a witness attestation, a mesh announcement)
# can never be presented as a signature for another. The preimage is:
#
#     domain || field_1 || "\n" || field_2 || "\n" || ... || field_n
#
# i.e. the domain is followed directly by the newline-joined fields.
# ---------------------------------------------------------------------------
DOMAIN_RESPONSE = "REFINET-RESPONSE-v1"
DOMAIN_BINDING = "REFINET-BINDING-v1"
DOMAIN_IDENTITY = "REFINET-IDENTITY-v3"
DOMAIN_WITNESS = "REFINET-WITNESS-v1"
DOMAIN_ANNOUNCE = "REFINET-ANNOUNCE-v1"


def domain_preimage(domain: str, *fields) -> bytes:
    """Build the exact bytes a domain-separated signature covers."""
    return (domain + "\n".join(str(f) for f in fields)).encode("utf-8")


def sign_domain(domain: str, private_key: Ed25519PrivateKey, *fields) -> str:
    """Sign ``domain || "\\n".join(fields)``; returns hex."""
    return sign_content(domain_preimage(domain, *fields), private_key)


def verify_domain(domain: str, signature_hex: str, public_key_hex: str, *fields) -> bool:
    """Verify a signature made by ``sign_domain``."""
    return verify_signature(domain_preimage(domain, *fields), signature_hex, public_key_hex)


def pid_matches_key(pid: str, public_key_hex: str) -> bool:
    """True when *pid* is SHA-256 of the raw Ed25519 public key.

    A PID is not a name anyone chooses: it is the hash of the key. Every
    record that claims a PID must carry a key that hashes to it.
    """
    try:
        return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest() == pid
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Response signature trailer
#
# Appended after the Gopher "." terminator. The first four lines are the
# original (pre-0.5.0) block and keep their meaning: ``sig`` is Ed25519 over
# the raw body. The remaining lines are additive: ``sig1`` is the
# domain-separated envelope signature that binds the selector and time too.
# ---------------------------------------------------------------------------
SIG_BEGIN = "---BEGIN REFINET SIGNATURE---"
SIG_END = "---END REFINET SIGNATURE---"


def response_envelope_signature(private_key: Ed25519PrivateKey, pid: str,
                                selector: str, unix_time: int,
                                body_hash: str) -> str:
    """The §3.3 envelope signature: binds pid, selector, time and body hash."""
    return sign_domain(DOMAIN_RESPONSE, private_key, pid, selector, unix_time, body_hash)


def build_signature_trailer(body: bytes, private_key: Ed25519PrivateKey,
                            pid: str, public_key_hex: str, selector: str,
                            unix_time: int) -> str:
    """Build the full signature trailer for a served response."""
    body_hash = hash_content(body)
    legacy_sig = sign_content(body, private_key)
    envelope_sig = response_envelope_signature(
        private_key, pid, selector, unix_time, body_hash)
    return (
        f"\r\n{SIG_BEGIN}\r\n"
        f"pid:{pid}\r\n"
        f"pubkey:{public_key_hex}\r\n"
        f"sig:{legacy_sig}\r\n"
        f"hash:{body_hash}\r\n"
        "v:1\r\n"
        f"selector:{selector}\r\n"
        f"time:{unix_time}\r\n"
        f"sig1:{envelope_sig}\r\n"
        f"{SIG_END}\r\n"
    )


def verify_response_block(text: str) -> dict:
    """Split a served response into body + trailer and verify both signatures.

    Returns a dict with ``valid`` (every signature present verifies),
    ``legacy_valid`` (``sig`` over the body), ``envelope_valid`` (``sig1``,
    or None when the trailer predates v1), ``pid_valid`` and the parsed
    ``pid``/``selector``/``time``. A response with no trailer returns
    ``{"valid": False, "reason": "unsigned"}``.
    """
    marker = f"\r\n{SIG_BEGIN}"
    idx = text.find(marker)
    if idx < 0:
        return {"valid": False, "reason": "unsigned"}
    body = text[:idx].encode("utf-8")
    fields = {}
    for line in text[idx + len(marker):].splitlines():
        if line.strip() == SIG_END:
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.rstrip("\r")

    pid = fields.get("pid", "")
    pubkey = fields.get("pubkey", "")
    body_hash = hash_content(body)
    result = {
        "pid": pid,
        "selector": fields.get("selector"),
        "time": fields.get("time"),
        "pid_valid": pid_matches_key(pid, pubkey),
        "hash_valid": fields.get("hash") == body_hash,
        "legacy_valid": verify_signature(body, fields.get("sig", ""), pubkey),
        "envelope_valid": None,
    }
    if fields.get("v") == "1":
        try:
            unix_time = int(fields.get("time", ""))
        except ValueError:
            unix_time = None
        result["envelope_valid"] = unix_time is not None and verify_domain(
            DOMAIN_RESPONSE, fields.get("sig1", ""), pubkey,
            pid, fields.get("selector", ""), unix_time, body_hash)
    result["valid"] = (
        result["pid_valid"] and result["hash_valid"] and result["legacy_valid"]
        and result["envelope_valid"] is not False
    )
    return result


# ---------------------------------------------------------------------------
# Canonical JSON (for signed documents: identity v3, test vectors)
# ---------------------------------------------------------------------------
def canonical_json(obj) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, UTF-8."""
    import json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
