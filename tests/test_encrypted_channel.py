"""Tests for mesh/encrypted_channel.py — E2E Encrypted P2P Communication."""

import struct
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mesh.encrypted_channel import (
    EncryptedChannel,
    get_x25519_public_key,
    derive_shared_secret,
    _ed25519_to_x25519_private,
)


def _make_channel_pair():
    """Create a pair of EncryptedChannels (Alice <-> Bob)."""
    alice_ed = Ed25519PrivateKey.generate()
    bob_ed = Ed25519PrivateKey.generate()

    alice_x25519_pub_bytes = get_x25519_public_key(alice_ed)
    bob_x25519_pub_bytes = get_x25519_public_key(bob_ed)

    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    alice_x_pub = X25519PublicKey.from_public_bytes(alice_x25519_pub_bytes)
    bob_x_pub = X25519PublicKey.from_public_bytes(bob_x25519_pub_bytes)

    ch_alice = EncryptedChannel(alice_ed, bob_x_pub)
    ch_bob = EncryptedChannel(bob_ed, alice_x_pub)
    return ch_alice, ch_bob


class TestEncryptDecryptRoundtrip:
    """Bidirectional encrypt/decrypt."""

    def test_alice_to_bob(self):
        ch_a, ch_b = _make_channel_pair()
        msg = b"hello from alice"
        encrypted = ch_a.encrypt(msg)
        decrypted = ch_b.decrypt(encrypted)
        assert decrypted == msg

    def test_bob_to_alice(self):
        ch_a, ch_b = _make_channel_pair()
        msg = b"hello from bob"
        encrypted = ch_b.encrypt(msg)
        decrypted = ch_a.decrypt(encrypted)
        assert decrypted == msg

    def test_multiple_messages(self):
        ch_a, ch_b = _make_channel_pair()
        for i in range(5):
            msg = f"message-{i}".encode()
            enc = ch_a.encrypt(msg)
            dec = ch_b.decrypt(enc)
            assert dec == msg

    def test_empty_message(self):
        ch_a, ch_b = _make_channel_pair()
        enc = ch_a.encrypt(b"")
        dec = ch_b.decrypt(enc)
        assert dec == b""


class TestNonceCounter:
    """Nonce counter increments."""

    def test_send_counter_increments(self):
        ch_a, _ = _make_channel_pair()
        assert ch_a._send_counter == 0
        ch_a.encrypt(b"a")
        assert ch_a._send_counter == 1
        ch_a.encrypt(b"b")
        assert ch_a._send_counter == 2

    def test_recv_counter_increments(self):
        ch_a, ch_b = _make_channel_pair()
        enc = ch_a.encrypt(b"msg")
        ch_b.decrypt(enc)
        assert ch_b._recv_counter == 1


class TestFraming:
    """Frame size calculation."""

    def test_frame_size(self):
        ch_a, _ = _make_channel_pair()
        encrypted = ch_a.encrypt(b"test data")
        expected_size = EncryptedChannel.frame_size(encrypted)
        assert expected_size == len(encrypted)

    def test_frame_size_too_short(self):
        assert EncryptedChannel.frame_size(b"\x00") is None
        assert EncryptedChannel.frame_size(b"") is None

    def test_frame_header_format(self):
        ch_a, _ = _make_channel_pair()
        encrypted = ch_a.encrypt(b"x")
        length = struct.unpack("!I", encrypted[:4])[0]
        # length should be 12 (nonce) + ciphertext
        assert length == len(encrypted) - 4


class TestX25519Key:
    """X25519 public key derivation."""

    def test_returns_32_bytes(self):
        key = Ed25519PrivateKey.generate()
        pub = get_x25519_public_key(key)
        assert len(pub) == 32

    def test_deterministic(self):
        key = Ed25519PrivateKey.generate()
        assert get_x25519_public_key(key) == get_x25519_public_key(key)


class TestDecryptionFailures:
    """Wrong key / tampered data rejection."""

    def test_wrong_key_fails(self):
        alice = Ed25519PrivateKey.generate()
        bob = Ed25519PrivateKey.generate()
        eve = Ed25519PrivateKey.generate()

        bob_x_pub = get_x25519_public_key(bob)
        eve_x_pub = get_x25519_public_key(eve)

        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        ch_alice_bob = EncryptedChannel(alice, X25519PublicKey.from_public_bytes(bob_x_pub))
        ch_eve_bob = EncryptedChannel(eve, X25519PublicKey.from_public_bytes(bob_x_pub))

        encrypted = ch_alice_bob.encrypt(b"secret")
        with pytest.raises(ValueError, match="Decryption failed"):
            ch_eve_bob.decrypt(encrypted)

    def test_truncated_data_fails(self):
        ch_a, ch_b = _make_channel_pair()
        encrypted = ch_a.encrypt(b"data")
        with pytest.raises(ValueError):
            ch_b.decrypt(encrypted[:10])
