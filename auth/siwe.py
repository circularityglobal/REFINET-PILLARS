"""
REFInet Pillar — SIWE (Sign-In With Ethereum) Core

EIP-4361 challenge generation and verification.

Two kinds of message exist, and they are never interchangeable:

  * a **login** challenge, whose statement is
    ``Sign in to REFInet Pillar <pid>``. It opens a session.
  * a **binding** challenge, whose statement is
    ``I bind this wallet to REFINET Pillar <pid> as its <role>``. It
    creates a permanent wallet-to-PID binding and is published in the
    Pillar's identity document.

The statement is the discriminator: ``establish_session`` refuses a
binding statement, and ``create_binding`` refuses anything else. A
signature spendable on two purposes is spendable on the one the signer
did not intend.

Every message also carries this Pillar's own authority on the first line
and its full PID in ``URI``/``Resources``, so a message issued by one
Pillar cannot be presented to another.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    _ETH_ACCOUNT_AVAILABLE = True
except ImportError:
    _ETH_ACCOUNT_AVAILABLE = False

SESSION_DURATION_HOURS = 24

# Pre-0.5.0 domain. Kept only so old messages can still be recognised.
DOMAIN = "refinet://pillar"

PURPOSE_LOGIN = "login"
PURPOSE_BINDING = "binding"

LOGIN_STATEMENT_PREFIX = "Sign in to REFInet Pillar "
BINDING_STATEMENT_PREFIX = "I bind this wallet to REFINET Pillar "
BINDING_ROLES = ("deployer", "operator")

# A login challenge must be redeemed inside this window; a binding
# challenge is shorter because it is a permanent record.
LOGIN_NONCE_TTL_SECONDS = 15 * 60
BINDING_NONCE_TTL_SECONDS = 10 * 60

_LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}


def pillar_authority(pid: str, hostname: str = None, port: int = None) -> str:
    """Return the RFC 3986 authority that identifies *this* Pillar.

    EIP-4361's ``domain`` is an authority, and one literal shared by every
    Pillar (the old ``refinet://pillar``) cannot identify anybody. A Pillar
    with a real hostname uses it; otherwise it uses a name derived from its
    own PID, which is unique by construction.
    """
    if hostname is None:
        try:
            from core.config import load_config
            config = load_config()
            hostname = config.get("hostname")
            if port is None:
                port = config.get("port")
        except Exception:
            hostname = None
    if not hostname or hostname in _LOOPBACK_HOSTS:
        return f"{pid}.pillar.refinet"
    return f"{hostname}:{port}" if port else hostname


def pillar_uri(pid: str) -> str:
    """The resource URI naming this Pillar in full."""
    return f"refinet://pillar/{pid}"


def login_statement(pid: str) -> str:
    return f"{LOGIN_STATEMENT_PREFIX}{pid}"


def binding_statement(pid: str, role: str = "deployer") -> str:
    if role not in BINDING_ROLES:
        raise ValueError(f"binding role must be one of {BINDING_ROLES}")
    return f"{BINDING_STATEMENT_PREFIX}{pid} as its {role}"


def _build_message(address: str, pid: str, statement: str, chain_id: int,
                   nonce: str, issued_at: datetime, expires_at: datetime,
                   authority: str, resources: list[str]) -> str:
    lines = [
        f"{authority} wants you to sign in with your Ethereum account:",
        f"{address}",
        "",
        statement,
        "",
        f"URI: {pillar_uri(pid)}",
        "Version: 1",
        f"Chain ID: {chain_id}",
        f"Nonce: {nonce}",
        f"Issued At: {issued_at.isoformat()}",
        f"Expiration Time: {expires_at.isoformat()}",
    ]
    if resources:
        lines.append("Resources:")
        lines.extend(f"- {r}" for r in resources)
    return "\n".join(lines)


def generate_challenge(address: str, pid: str, chain_id: int = 1,
                       purpose: str = PURPOSE_LOGIN,
                       binding_type: str = "deployer",
                       company_url: str = None,
                       authority: str = None,
                       nonce: str = None,
                       issued_at: datetime = None) -> tuple[str, str]:
    """
    Generate an EIP-4361 message for wallet signing.
    Returns (message_text, nonce).

    Args:
        address: EVM address (0x-prefixed, 42 chars)
        pid: Pillar ID hex string (full 64 hex characters)
        chain_id: EVM chain ID (default 1 = Ethereum mainnet).
        purpose: ``"login"`` (a session) or ``"binding"`` (a wallet binding)
        binding_type: ``"deployer"`` or ``"operator"``, for binding messages
        company_url: optional TradeSphere company URL, added to Resources
        authority: override the computed authority (tests, vectors)
        nonce, issued_at: fixed values for reproducible vectors
    """
    if not _ETH_ACCOUNT_AVAILABLE:
        raise ImportError(
            "SIWE auth requires eth-account. Install with: pip install eth-account"
        )
    if purpose not in (PURPOSE_LOGIN, PURPOSE_BINDING):
        raise ValueError(f"unknown challenge purpose: {purpose}")

    nonce = nonce or secrets.token_hex(16)
    now = issued_at or datetime.now(timezone.utc)

    if purpose == PURPOSE_BINDING:
        statement = binding_statement(pid, binding_type)
        expiry = now + timedelta(seconds=BINDING_NONCE_TTL_SECONDS)
    else:
        statement = login_statement(pid)
        # A login message's lifetime is the session it opens.
        expiry = now + timedelta(hours=SESSION_DURATION_HOURS)

    resources = [pillar_uri(pid)]
    if company_url:
        resources.append(company_url)

    message = _build_message(
        address=address, pid=pid, statement=statement, chain_id=chain_id,
        nonce=nonce, issued_at=now, expires_at=expiry,
        authority=authority or pillar_authority(pid),
        resources=resources,
    )
    return message, nonce


def generate_binding_challenge(address: str, pid: str, chain_id: int,
                               binding_type: str = "deployer",
                               company_url: str = None,
                               **kwargs) -> tuple[str, str]:
    """Generate a §3.1 binding challenge. Returns (message_text, nonce)."""
    return generate_challenge(
        address, pid, chain_id=chain_id, purpose=PURPOSE_BINDING,
        binding_type=binding_type, company_url=company_url, **kwargs)


def verify_siwe_signature(message_text: str, signature: str,
                          expected_address: str) -> bool:
    """
    Verify a SIWE signature via ecrecover.
    Returns True if recovered address matches expected_address (case-insensitive).
    Raises ValueError on malformed input.

    This is the EOA path only. Contract wallets (Safe, ERC-4337) answer
    EIP-1271 on-chain — see ``auth.wallet_sig.verify_wallet_signature``.
    """
    if not _ETH_ACCOUNT_AVAILABLE:
        raise ImportError(
            "SIWE auth requires eth-account. Install with: pip install eth-account"
        )
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


def parse_chain_id(message_text: str, default: int = 1) -> int:
    """Extract the Chain ID the wallet signed on."""
    for line in message_text.splitlines():
        if line.startswith("Chain ID: "):
            try:
                return int(line.replace("Chain ID: ", "").strip())
            except ValueError:
                return default
    return default


def parse_uri(message_text: str) -> str:
    """Extract the URI line."""
    for line in message_text.splitlines():
        if line.startswith("URI:"):
            return line.split(":", 1)[1].strip()
    return ""


def parse_statement(message_text: str) -> str:
    """Extract the statement (the line between the address and the fields)."""
    lines = message_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(("URI:", "URI ")):
            # The statement is the last non-empty line before the fields
            for candidate in reversed(lines[:i]):
                if candidate.strip():
                    return candidate.strip()
            return ""
    return ""


def is_binding_message(message_text: str) -> bool:
    """True when this message's statement binds a wallet to a PID."""
    return parse_statement(message_text).startswith(BINDING_STATEMENT_PREFIX)


def parse_binding_statement(message_text: str) -> tuple[str, str] | None:
    """Return (pid, role) for a §3.1 binding message, else None."""
    statement = parse_statement(message_text)
    if not statement.startswith(BINDING_STATEMENT_PREFIX):
        return None
    rest = statement[len(BINDING_STATEMENT_PREFIX):]
    try:
        pid, role = rest.split(" as its ", 1)
    except ValueError:
        return None
    pid, role = pid.strip(), role.strip()
    if role not in BINDING_ROLES:
        return None
    return pid, role


def message_names_pid(message_text: str, pid: str) -> bool:
    """True when the message's URI names *pid* in full.

    Messages issued before 0.5.0 carried the bare ``refinet://pillar``
    domain and named no Pillar; they are not accepted here. Their nonces
    are not in this Pillar's registry either, so they are refused anyway.
    """
    return parse_uri(message_text) == pillar_uri(pid)
