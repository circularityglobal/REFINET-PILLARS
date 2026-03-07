"""
REFInet Pillar — SIWE (Sign-In With Ethereum) Core

EIP-4361 challenge generation and verification.
Uses eth-account's ecrecover for signature verification.
"""

import secrets
from datetime import datetime, timedelta, timezone

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:
    raise ImportError(
        "SIWE auth requires eth-account. Install with: pip install eth-account"
    )

SESSION_DURATION_HOURS = 24
DOMAIN = "refinet://pillar"


def generate_challenge(address: str, pid: str,
                       chain_id: int = 1) -> tuple[str, str]:
    """
    Generate an EIP-4361 SIWE message for wallet signing.
    Returns (message_text, nonce).

    Args:
        address: EVM address (0x-prefixed, 42 chars)
        pid: Pillar ID hex string
        chain_id: EVM chain ID (default 1 = Ethereum mainnet).
                  Browser sends this via /auth/challenge address:chainId format.
    """
    nonce = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=SESSION_DURATION_HOURS)

    message = (
        f"{DOMAIN} wants you to sign in with your Ethereum account:\n"
        f"{address}\n\n"
        f"Sign in to REFInet Pillar {pid[:16]}...\n\n"
        f"URI: {DOMAIN}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {now.isoformat()}\n"
        f"Expiration Time: {expiry.isoformat()}"
    )

    return message, nonce


def verify_siwe_signature(message_text: str, signature: str,
                          expected_address: str) -> bool:
    """
    Verify a SIWE signature via ecrecover.
    Returns True if recovered address matches expected_address (case-insensitive).
    Raises ValueError on malformed input.
    """
    try:
        encoded = encode_defunct(text=message_text)
        recovered = Account.recover_message(encoded, signature=signature)
        return recovered.lower() == expected_address.lower()
    except Exception as e:
        raise ValueError(f"Signature verification failed: {e}")


def parse_expiry(message_text: str) -> datetime:
    """Extract and parse the Expiration Time from a SIWE message."""
    for line in message_text.splitlines():
        if line.startswith("Expiration Time: "):
            exp_str = line.replace("Expiration Time: ", "").strip()
            return datetime.fromisoformat(exp_str)
    raise ValueError("No Expiration Time found in SIWE message")


def parse_nonce(message_text: str) -> str:
    """Extract the nonce from a SIWE message."""
    for line in message_text.splitlines():
        if line.startswith("Nonce: "):
            return line.replace("Nonce: ", "").strip()
    return ""
