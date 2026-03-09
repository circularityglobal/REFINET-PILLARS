"""Tests for crypto/zkp.py — Schnorr ZKP and MembershipProof."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from crypto.zkp import SchnorrZKP, MembershipProof


def _pub_hex(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


class TestSchnorrZKP:
    """Schnorr zero-knowledge proof tests."""

    def test_prove_and_verify(self, test_private_key):
        pub = _pub_hex(test_private_key)
        proof = SchnorrZKP.prove(test_private_key, context="test")
        assert SchnorrZKP.verify(proof, pub, context="test")

    def test_wrong_key_fails(self, test_private_key):
        other_key = Ed25519PrivateKey.generate()
        other_pub = _pub_hex(other_key)
        proof = SchnorrZKP.prove(test_private_key, context="test")
        assert not SchnorrZKP.verify(proof, other_pub, context="test")

    def test_context_separation(self, test_private_key):
        pub = _pub_hex(test_private_key)
        proof = SchnorrZKP.prove(test_private_key, context="session-A")
        assert not SchnorrZKP.verify(proof, pub, context="session-B")

    def test_proof_has_required_fields(self, test_private_key):
        proof = SchnorrZKP.prove(test_private_key)
        assert proof["type"] == "schnorr-zkp-v1"
        assert "commitment" in proof
        assert "challenge" in proof
        assert "response" in proof
        assert "public_key" in proof

    def test_empty_context_works(self, test_private_key):
        pub = _pub_hex(test_private_key)
        proof = SchnorrZKP.prove(test_private_key)
        assert SchnorrZKP.verify(proof, pub)

    def test_tampered_challenge_fails(self, test_private_key):
        pub = _pub_hex(test_private_key)
        proof = SchnorrZKP.prove(test_private_key, context="test")
        proof["challenge"] = "a" * 64
        assert not SchnorrZKP.verify(proof, pub, context="test")

    def test_wrong_type_fails(self, test_private_key):
        pub = _pub_hex(test_private_key)
        proof = SchnorrZKP.prove(test_private_key)
        proof["type"] = "wrong-type"
        assert not SchnorrZKP.verify(proof, pub)


class TestMembershipProof:
    """Membership proof (simplified OR-proof) tests."""

    def test_member_proves_membership(self, test_private_key):
        our_pub = _pub_hex(test_private_key)
        other1 = _pub_hex(Ed25519PrivateKey.generate())
        other2 = _pub_hex(Ed25519PrivateKey.generate())
        members = [our_pub, other1, other2]

        proof = MembershipProof.prove(test_private_key, members, context="vote")
        assert MembershipProof.verify(proof, members, context="vote")

    def test_non_member_cant_prove(self):
        outsider = Ed25519PrivateKey.generate()
        member1 = _pub_hex(Ed25519PrivateKey.generate())
        member2 = _pub_hex(Ed25519PrivateKey.generate())
        with pytest.raises(ValueError, match="not in the member set"):
            MembershipProof.prove(outsider, [member1, member2])

    def test_wrong_context_fails(self, test_private_key):
        our_pub = _pub_hex(test_private_key)
        members = [our_pub, _pub_hex(Ed25519PrivateKey.generate())]
        proof = MembershipProof.prove(test_private_key, members, context="A")
        assert not MembershipProof.verify(proof, members, context="B")

    def test_proof_has_required_fields(self, test_private_key):
        our_pub = _pub_hex(test_private_key)
        members = [our_pub]
        proof = MembershipProof.prove(test_private_key, members)
        assert proof["type"] == "membership-proof-v1"
        assert proof["member_count"] == 1
        assert "ring_commitments" in proof
        assert "ring_challenge" in proof
        assert "proof" in proof

    def test_wrong_member_count_fails(self, test_private_key):
        our_pub = _pub_hex(test_private_key)
        members = [our_pub, _pub_hex(Ed25519PrivateKey.generate())]
        proof = MembershipProof.prove(test_private_key, members)
        # Verify against wrong member list
        assert not MembershipProof.verify(proof, [our_pub])
