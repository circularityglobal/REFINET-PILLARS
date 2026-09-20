"""
Deterministic cross-repository test vectors (pillar-vectors.json).

Produced by the Pillar's own code from fixed keys, times and nonces, and
consumed by tests on both sides of the TradeSphere bridge. A divergence
fails a test rather than a merchant.

    python3 -m tests.vectors --write     # regenerate tests/fixtures/pillar-vectors.json
    python3 -m tests.vectors             # print to stdout

Every value here is derived from the constants below. The keys are public
test keys and must never hold funds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "pillar-vectors.json"

PILLAR_SEED = hashlib.sha256(b"refinet-pillar-vector-key-v1").digest()
WALLET_KEY = "0x" + hashlib.sha256(b"refinet-wallet-vector-key-v1").hexdigest()
FIXED_TIME = 1789800000                     # 2026-09-19T06:40:00Z
FIXED_ISSUED_AT = "2026-09-19T06:40:00+00:00"
FIXED_NONCE = "00112233445566778899aabbccddeeff"
BINDING_CHAIN_ID = 43113
COMPANY_URL = "https://tradesphere.example/company/42"


def pillar_key() -> tuple[Ed25519PrivateKey, str, str]:
    key = Ed25519PrivateKey.from_private_bytes(PILLAR_SEED)
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return key, hashlib.sha256(bytes.fromhex(pub)).hexdigest(), pub


def registry_vector() -> dict:
    from crypto.signing import sign_content
    key, pid, pub = pillar_key()
    record = {
        "pid": pid,
        "selector": "/holes/vector",
        "name": "Vector Hole",
        "registered_at": "2026-09-19",
        "pubkey_hex": pub,
    }
    payload = f"{pid}:{record['selector']}:{record['name']}:{record['registered_at']}"
    record["signing_payload"] = payload
    record["signature"] = sign_content(payload.encode(), key)
    return record


def response_vector() -> dict:
    from crypto.signing import build_signature_trailer, domain_preimage, DOMAIN_RESPONSE, hash_content
    key, pid, pub = pillar_key()
    body = "iHello from the vector Pillar\tfake\t(NULL)\t0\r\n.\r\n"
    selector = "/holes/vector/README"
    trailer = build_signature_trailer(body.encode(), key, pid, pub, selector, FIXED_TIME)
    body_hash = hash_content(body.encode())
    return {
        "body": body,
        "selector": selector,
        "time": FIXED_TIME,
        "hash": body_hash,
        "envelope_preimage_hex": domain_preimage(
            DOMAIN_RESPONSE, pid, selector, FIXED_TIME, body_hash).hex(),
        "response": body + trailer,
    }


def witness_vector() -> dict:
    from crypto.attestation import sign_witness
    key, pid, pub = pillar_key()
    body = b'{"name":"Receipt #12"}'
    return {
        "public_key": pub,
        "attestation": sign_witness(
            key, pid, "https://api.tradesphere.example/nft/c/43113/f/0xFactory/7/12",
            FIXED_TIME, hashlib.sha256(body).hexdigest(), "match"),
    }


VECTOR_PROTOCOL = "0.5.0"


def binding_vector() -> dict | None:
    """Binding + identity v3 — present once the identity step has landed."""
    try:
        from crypto.binding import build_binding_vector
    except ImportError:
        return None
    key, pid, pub = pillar_key()
    return build_binding_vector(
        private_key=key, pid=pid, public_key=pub, wallet_key=WALLET_KEY,
        chain_id=BINDING_CHAIN_ID, nonce=FIXED_NONCE, issued_at=FIXED_ISSUED_AT,
        company_url=COMPANY_URL, authority=f"{pid}.pillar.refinet",
        created_at=FIXED_ISSUED_AT,
        # Fixed, so a release does not re-sign a vector other teams pin
        protocol=VECTOR_PROTOCOL,
    )


def build() -> dict:
    _, pid, pub = pillar_key()
    vectors = {
        "version": 1,
        "pillar": {"pid": pid, "public_key": pub},
        "registry_record": registry_vector(),
        "response_block": response_vector(),
        "witness_attestation": witness_vector(),
    }
    binding = binding_vector()
    if binding is not None:
        vectors["binding_identity_v3"] = binding
    return vectors


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"write {FIXTURE_PATH}")
    args = parser.parse_args()
    if args.write:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(render())
        print(f"wrote {FIXTURE_PATH}")
    else:
        print(render(), end="")


if __name__ == "__main__":
    main()
