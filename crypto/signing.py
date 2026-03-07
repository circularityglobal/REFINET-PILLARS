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
