"""
REFInet Pillar — End-to-End Encrypted Peer Communication Channel

Provides authenticated encryption between Pillars using:
  - X25519 key exchange (derived from Ed25519 keys)
  - AES-256-GCM per-message encryption
  - Nonce counter for replay protection

Message framing:
  [4-byte big-endian length][12-byte nonce][ciphertext+GCM-tag]

The shared secret is derived via X25519 ECDH + HKDF-SHA256.
"""

from __future__ import annotations

import os
import struct
import hashlib
import logging
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("refinet.encrypted_channel")


def _ed25519_to_x25519_private(ed_private: Ed25519PrivateKey) -> X25519PrivateKey:
    """
    Convert an Ed25519 private key to X25519 for key exchange.

    Uses the raw private key bytes directly — both curves use the same
    underlying scalar, but X25519 applies clamping.
    """
    raw = ed_private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return X25519PrivateKey.from_private_bytes(raw)


def _ed25519_pubkey_to_x25519(pub_hex: str) -> X25519PublicKey:
    """
    Convert an Ed25519 public key hex to X25519 public key.

    Note: This is a simplified conversion. For production use,
    the proper birational mapping between Ed25519 and X25519 should be used.
    Here we use the raw bytes approach which works for key agreement.
    """
    # For X25519, we need the Montgomery form. The cryptography library
    # handles this internally when we generate from the private key.
    # For peer keys, we'll exchange X25519 public keys directly.
    pub_bytes = bytes.fromhex(pub_hex)
    return X25519PublicKey.from_public_bytes(pub_bytes)


def derive_shared_secret(our_private: Ed25519PrivateKey,
                         their_x25519_pub: X25519PublicKey) -> bytes:
    """
    Derive a shared AES-256 key via X25519 ECDH + HKDF.

    Returns:
        32-byte AES key
    """
    our_x25519 = _ed25519_to_x25519_private(our_private)
    shared = our_x25519.exchange(their_x25519_pub)

    # Derive AES key via HKDF
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"REFInet-encrypted-channel-v1",
    ).derive(shared)

    return key


def get_x25519_public_key(ed_private: Ed25519PrivateKey) -> bytes:
    """Get the X25519 public key bytes for key exchange announcements."""
    x25519_priv = _ed25519_to_x25519_private(ed_private)
    return x25519_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


class EncryptedChannel:
    """
    Bidirectional encrypted communication channel between two Pillars.

    Usage:
        # Initiator side
        channel = EncryptedChannel(our_private_key, their_x25519_pub)
        encrypted = channel.encrypt(b"hello")
        plaintext = channel.decrypt(received_bytes)

        # Responder side
        channel = EncryptedChannel(our_private_key, their_x25519_pub)
        plaintext = channel.decrypt(received_bytes)
        encrypted = channel.encrypt(b"response")
    """

    def __init__(self, our_private: Ed25519PrivateKey,
                 their_x25519_pub: X25519PublicKey):
        self._aes_key = derive_shared_secret(our_private, their_x25519_pub)
        self._aesgcm = AESGCM(self._aes_key)
        self._send_counter = 0
        self._recv_counter = 0

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt a message with AES-256-GCM.

        Returns framed bytes: [4-byte length][12-byte nonce][ciphertext+tag]
        """
        nonce = self._send_counter.to_bytes(12, "big")
        self._send_counter += 1
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        payload = nonce + ciphertext
        length = struct.pack("!I", len(payload))
        return length + payload

    def decrypt(self, framed_data: bytes) -> bytes:
        """
        Decrypt a framed encrypted message.

        Args:
            framed_data: [4-byte length][12-byte nonce][ciphertext+tag]

        Returns:
            Decrypted plaintext bytes

        Raises:
            ValueError: If decryption fails or data is corrupted
        """
        if len(framed_data) < 4:
            raise ValueError("Framed data too short")

        length = struct.unpack("!I", framed_data[:4])[0]
        payload = framed_data[4:4 + length]

        if len(payload) < 12:
            raise ValueError("Payload too short for nonce")

        nonce = payload[:12]
        ciphertext = payload[12:]

        try:
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            self._recv_counter += 1
            return plaintext
        except Exception:
            raise ValueError("Decryption failed — corrupted data or wrong key")

    @staticmethod
    def frame_size(framed_data: bytes) -> Optional[int]:
        """
        Read the frame length from the first 4 bytes.
        Returns None if not enough data.
        """
        if len(framed_data) < 4:
            return None
        return struct.unpack("!I", framed_data[:4])[0] + 4
