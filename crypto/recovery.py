"""
REFInet Pillar — Multi-Device Key Recovery (Shamir's Secret Sharing)

Split a private key into N shares, any K of which can reconstruct the original.
Uses Shamir's Secret Sharing over GF(256) — no external dependencies.

Usage:
    # Split: creates 5 shares, any 3 reconstruct the key
    shares = split_key(private_key_hex, threshold=3, num_shares=5)

    # Recover: provide any 3 shares
    recovered = recover_key(shares[:3])
    assert recovered == private_key_hex
"""

from __future__ import annotations

import os
import base64
import hashlib
from typing import List


# ---------------------------------------------------------------------------
# Galois Field GF(256) arithmetic
# ---------------------------------------------------------------------------
# Irreducible polynomial: x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
# This polynomial has 2 as a primitive element, ensuring all 255
# non-zero elements of GF(256) are generated.
_EXP = [0] * 512
_LOG = [0] * 256


def _init_gf256():
    """Initialize GF(256) exp/log tables."""
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]

_init_gf256()


def _gf_mul(a: int, b: int) -> int:
    """Multiply two GF(256) elements."""
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _gf_div(a: int, b: int) -> int:
    """Divide two GF(256) elements."""
    if b == 0:
        raise ZeroDivisionError("Division by zero in GF(256)")
    if a == 0:
        return 0
    return _EXP[(_LOG[a] - _LOG[b]) % 255]


# ---------------------------------------------------------------------------
# Shamir's Secret Sharing
# ---------------------------------------------------------------------------
def _eval_polynomial(coeffs: list[int], x: int) -> int:
    """Evaluate a polynomial at x in GF(256). coeffs[0] is the secret."""
    result = 0
    for coeff in reversed(coeffs):
        result = _gf_mul(result, x) ^ coeff
    return result


def _lagrange_interpolate(points: list[tuple[int, int]], x: int = 0) -> int:
    """
    Lagrange interpolation at x in GF(256).
    points: list of (x_i, y_i) tuples.
    """
    result = 0
    for i, (xi, yi) in enumerate(points):
        num = yi
        for j, (xj, _) in enumerate(points):
            if i != j:
                num = _gf_mul(num, _gf_div(x ^ xj, xi ^ xj))
        result ^= num
    return result


def _split_byte(secret_byte: int, threshold: int, num_shares: int) -> list[tuple[int, int]]:
    """Split a single byte into shares using Shamir's scheme."""
    # Generate random polynomial: coeffs[0] = secret, coeffs[1..k-1] = random
    coeffs = [secret_byte] + [int.from_bytes(os.urandom(1), "big") for _ in range(threshold - 1)]
    # Evaluate at x = 1, 2, ..., num_shares (never at x = 0, that's the secret)
    return [(i + 1, _eval_polynomial(coeffs, i + 1)) for i in range(num_shares)]


def split_key(private_key_hex: str, threshold: int = 3, num_shares: int = 5) -> List[str]:
    """
    Split a private key into shares using Shamir's Secret Sharing.

    Args:
        private_key_hex: Hex-encoded private key (32 bytes = 64 hex chars)
        threshold: Minimum shares needed to reconstruct (default: 3)
        num_shares: Total shares to generate (default: 5)

    Returns:
        List of base64-encoded share strings. Each share includes:
        - 1 byte: share index (x coordinate)
        - 1 byte: threshold
        - 4 bytes: PID fingerprint (first 4 bytes of SHA-256 of key)
        - N bytes: share data (y coordinates for each secret byte)

    Raises:
        ValueError: If parameters are invalid
    """
    if threshold < 2:
        raise ValueError("Threshold must be at least 2")
    if num_shares < threshold:
        raise ValueError("num_shares must be >= threshold")
    if num_shares > 255:
        raise ValueError("Maximum 255 shares")

    secret_bytes = bytes.fromhex(private_key_hex)
    if len(secret_bytes) == 0:
        raise ValueError("Private key cannot be empty")

    # PID fingerprint for share identification
    fingerprint = hashlib.sha256(private_key_hex.encode()).digest()[:4]

    # Split each byte independently
    all_shares = [_split_byte(b, threshold, num_shares) for b in secret_bytes]

    # Assemble shares: group by share index
    result = []
    for share_idx in range(num_shares):
        x = all_shares[0][share_idx][0]  # x coordinate (1-based)
        y_values = bytes(all_shares[byte_idx][share_idx][1]
                         for byte_idx in range(len(secret_bytes)))

        # Header: index(1) + threshold(1) + fingerprint(4)
        header = bytes([x, threshold]) + fingerprint
        share_data = header + y_values

        # Encode as base64 with "REFINET-SHARE-" prefix for identification
        encoded = base64.b64encode(share_data).decode("ascii")
        result.append(f"REFINET-SHARE-{encoded}")

    return result


def recover_key(shares: List[str]) -> str:
    """
    Reconstruct a private key from Shamir shares.

    Args:
        shares: List of share strings (at least threshold shares required)

    Returns:
        Hex-encoded private key

    Raises:
        ValueError: If shares are invalid, insufficient, or mismatched
    """
    if not shares:
        raise ValueError("No shares provided")

    # Parse shares
    parsed = []
    for share_str in shares:
        if not share_str.startswith("REFINET-SHARE-"):
            raise ValueError("Invalid share format — missing REFINET-SHARE- prefix")
        encoded = share_str[len("REFINET-SHARE-"):]
        try:
            raw = base64.b64decode(encoded)
        except Exception:
            raise ValueError("Invalid share — base64 decode failed")

        if len(raw) < 7:  # 1 + 1 + 4 + at least 1 byte
            raise ValueError("Share too short")

        x = raw[0]
        threshold = raw[1]
        fingerprint = raw[2:6]
        y_values = raw[6:]

        parsed.append({
            "x": x,
            "threshold": threshold,
            "fingerprint": fingerprint,
            "y_values": y_values,
        })

    # Validate consistency
    threshold = parsed[0]["threshold"]
    fingerprint = parsed[0]["fingerprint"]
    key_len = len(parsed[0]["y_values"])

    if len(parsed) < threshold:
        raise ValueError(f"Need at least {threshold} shares, got {len(parsed)}")

    for s in parsed:
        if s["threshold"] != threshold:
            raise ValueError("Shares have mismatched thresholds")
        if s["fingerprint"] != fingerprint:
            raise ValueError("Shares are from different keys (fingerprint mismatch)")
        if len(s["y_values"]) != key_len:
            raise ValueError("Shares have mismatched lengths")

    # Check for duplicate x coordinates
    x_values = [s["x"] for s in parsed]
    if len(set(x_values)) != len(x_values):
        raise ValueError("Duplicate shares provided")

    # Reconstruct each byte via Lagrange interpolation
    recovered_bytes = []
    for byte_idx in range(key_len):
        points = [(s["x"], s["y_values"][byte_idx]) for s in parsed[:threshold]]
        recovered_byte = _lagrange_interpolate(points, 0)
        recovered_bytes.append(recovered_byte)

    return bytes(recovered_bytes).hex()


def generate_recovery_shares(pid_data: dict, password: str = None,
                             threshold: int = 3, num_shares: int = 5) -> List[str]:
    """
    Generate recovery shares from a PID.

    If the PID is encrypted, a password is required to decrypt first.
    The shares encode the raw private key, not the encrypted form.

    Args:
        pid_data: PID data dict (from load_pid)
        password: Password if PID is encrypted
        threshold: Minimum shares to reconstruct
        num_shares: Total shares to generate

    Returns:
        List of share strings
    """
    from crypto.pid import is_encrypted, decrypt_private_key

    priv_field = pid_data["private_key"]
    if isinstance(priv_field, dict):
        if not password:
            raise ValueError("PID is encrypted — password required")
        priv_hex = decrypt_private_key(priv_field, password)
    else:
        priv_hex = priv_field

    return split_key(priv_hex, threshold=threshold, num_shares=num_shares)
