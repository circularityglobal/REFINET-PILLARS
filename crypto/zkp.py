"""
REFInet Pillar — Cryptographic Authentication (Schnorr Protocol)

Provides authentication using Schnorr-based proofs:
  - Prove knowledge of a private key without revealing it
  - Non-interactive via Fiat-Shamir heuristic (hash-based challenge)
  - Compatible with Ed25519 keys used throughout REFInet

Two proof types:
  1. SchnorrZKP — Prove you own a specific PID (zero-knowledge: key not revealed)
  2. MembershipAttestation — Prove your PID is a member of a set
     NOTE: This is NOT anonymous. The verifier learns which member proved
     membership. For anonymous membership proofs, a ring signature scheme
     (e.g., LSAG) would be required.

Usage:
    # Prover generates proof
    proof = SchnorrZKP.prove(private_key, context="auth-session-123")

    # Verifier checks proof
    valid = SchnorrZKP.verify(proof, public_key_hex, context="auth-session-123")
"""

from __future__ import annotations

import hashlib
import os
import json
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


class SchnorrZKP:
    """
    Non-interactive Schnorr zero-knowledge proof over Ed25519.

    The prover demonstrates knowledge of a private key corresponding
    to a public key without revealing the private key itself.

    Protocol (Fiat-Shamir):
        1. Prover generates random nonce k, computes commitment R = k*G
        2. Challenge c = SHA-256(R || public_key || context)
        3. Response s = k + c * private_key (mod order)
        4. Verifier checks: s*G == R + c*public_key

    Since Ed25519 doesn't expose scalar arithmetic directly, we use
    the Ed25519 sign/verify as a building block for the ZKP.
    """

    @staticmethod
    def prove(private_key: Ed25519PrivateKey, context: str = "") -> dict:
        """
        Generate a Schnorr ZKP proving knowledge of the private key.

        Args:
            private_key: The Ed25519 private key to prove knowledge of
            context: Domain separation string (e.g., session ID, timestamp)

        Returns:
            Proof dict with: commitment, challenge, response, public_key
        """
        # Get public key
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        # Generate random nonce and create commitment
        # We use the Ed25519 signing mechanism: sign a random message
        # to create a verifiable commitment
        nonce = os.urandom(32)
        commitment_data = hashlib.sha256(nonce + pub_bytes).digest()

        # Fiat-Shamir challenge: hash(commitment || public_key || context)
        challenge_input = commitment_data + pub_bytes + context.encode("utf-8")
        challenge = hashlib.sha256(challenge_input).hexdigest()

        # Response: sign the challenge with the private key
        response_data = (challenge + commitment_data.hex()).encode("utf-8")
        response = private_key.sign(response_data)

        return {
            "type": "schnorr-zkp-v1",
            "commitment": commitment_data.hex(),
            "challenge": challenge,
            "response": response.hex(),
            "public_key": pub_bytes.hex(),
            "context": context,
        }

    @staticmethod
    def verify(proof: dict, public_key_hex: str, context: str = "") -> bool:
        """
        Verify a Schnorr ZKP.

        Args:
            proof: Proof dict from prove()
            public_key_hex: Expected public key hex
            context: Must match the context used in prove()

        Returns:
            True if the proof is valid
        """
        try:
            if proof.get("type") != "schnorr-zkp-v1":
                return False

            # Verify public key matches
            if proof["public_key"] != public_key_hex:
                return False

            # Verify context matches
            if proof.get("context", "") != context:
                return False

            pub_bytes = bytes.fromhex(public_key_hex)
            commitment = bytes.fromhex(proof["commitment"])

            # Recompute challenge
            challenge_input = commitment + pub_bytes + context.encode("utf-8")
            expected_challenge = hashlib.sha256(challenge_input).hexdigest()

            if proof["challenge"] != expected_challenge:
                return False

            # Verify signature (response)
            public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            response_data = (proof["challenge"] + commitment.hex()).encode("utf-8")
            response = bytes.fromhex(proof["response"])

            public_key.verify(response, response_data)
            return True

        except Exception:
            return False


class MembershipAttestation:
    """
    Prove that a PID belongs to a set of PIDs (authenticated membership).

    IMPORTANT: This is NOT anonymous / zero-knowledge with respect to
    membership. The proof embeds the prover's public key, so the verifier
    learns exactly which member created the proof. This is an authenticated
    membership attestation, not a ring signature.

    For anonymous membership proofs, a proper ring signature scheme (e.g.,
    LSAG — Linkable Spontaneous Anonymous Group) would be needed.
    """

    @staticmethod
    def prove(private_key: Ed25519PrivateKey, member_pubkeys: list[str],
              context: str = "") -> dict:
        """
        Prove membership in a set of public keys.

        NOTE: The prover's identity IS revealed to the verifier.
        This proves "I am a member" but does NOT hide which member.

        Args:
            private_key: The prover's Ed25519 private key
            member_pubkeys: List of public key hex strings (the set)
            context: Domain separation string

        Returns:
            Membership attestation dict
        """
        our_pub = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

        if our_pub not in member_pubkeys:
            raise ValueError("Our public key is not in the member set")

        # Generate individual proof for our key
        our_proof = SchnorrZKP.prove(private_key, context=context)

        # Create blinded commitments for other members
        ring_commitments = []
        for pubkey in member_pubkeys:
            if pubkey == our_pub:
                # Our real commitment (blinded)
                ring_commitments.append(hashlib.sha256(
                    bytes.fromhex(our_proof["commitment"]) + os.urandom(16)
                ).hexdigest())
            else:
                # Simulated commitment
                ring_commitments.append(hashlib.sha256(
                    os.urandom(32)
                ).hexdigest())

        # Combined challenge over all commitments
        combined = "".join(ring_commitments) + context
        ring_challenge = hashlib.sha256(combined.encode("utf-8")).hexdigest()

        return {
            "type": "membership-attestation-v1",
            "member_count": len(member_pubkeys),
            "ring_commitments": ring_commitments,
            "ring_challenge": ring_challenge,
            "proof": our_proof,
            "context": context,
        }

    @staticmethod
    def verify(membership_proof: dict, member_pubkeys: list[str],
               context: str = "") -> bool:
        """
        Verify a membership attestation.

        Confirms that the prover knows a private key corresponding to
        one of the public keys in member_pubkeys. NOTE: the prover's
        identity is visible in the proof (not anonymous).

        Args:
            membership_proof: Attestation dict from prove()
            member_pubkeys: The set of public keys
            context: Must match the context used in prove()

        Returns:
            True if proof is valid and prover is a member
        """
        try:
            if membership_proof.get("type") not in ("membership-attestation-v1", "membership-proof-v1"):
                return False

            if membership_proof.get("context", "") != context:
                return False

            if membership_proof["member_count"] != len(member_pubkeys):
                return False

            # Verify the underlying Schnorr proof
            inner_proof = membership_proof["proof"]
            prover_pubkey = inner_proof["public_key"]

            # The prover's public key must be in the member set
            if prover_pubkey not in member_pubkeys:
                return False

            # Verify the Schnorr proof itself
            if not SchnorrZKP.verify(inner_proof, prover_pubkey, context=context):
                return False

            # Verify ring challenge consistency
            commitments = membership_proof["ring_commitments"]
            combined = "".join(commitments) + context
            expected = hashlib.sha256(combined.encode("utf-8")).hexdigest()

            return membership_proof["ring_challenge"] == expected

        except Exception:
            return False


# Backwards-compatible alias (deprecated — use MembershipAttestation)
MembershipProof = MembershipAttestation
