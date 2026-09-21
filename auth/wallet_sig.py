"""
REFInet Pillar — Wallet signature verification (EOA + contract wallets)

An EOA signature is recovered with ecrecover. A contract wallet (Safe,
any ERC-4337 account) produces no recoverable signature: it answers
EIP-1271 ``isValidSignature(bytes32,bytes)`` on-chain, returning the magic
value ``0x1626ba7e``. That call has to happen on the chain the message
names, which is why the message's ``Chain ID`` matters.

Without ``web3`` installed, or for a chain this Pillar has no endpoint
for, only the EOA path runs — the behaviour of earlier releases.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("refinet.walletsig")

EIP1271_MAGIC_VALUE = bytes.fromhex("1626ba7e")

# isValidSignature(bytes32 _hash, bytes _signature) returns (bytes4)
EIP1271_ABI = [
    {
        "inputs": [
            {"name": "_hash", "type": "bytes32"},
            {"name": "_signature", "type": "bytes"},
        ],
        "name": "isValidSignature",
        "outputs": [{"name": "", "type": "bytes4"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _eip191_hash(message_text: str) -> bytes:
    """The hash a wallet signs for personal_sign / EIP-4361."""
    from eth_account.messages import encode_defunct, _hash_eip191_message
    return _hash_eip191_message(encode_defunct(text=message_text))


def _endpoint_for(chain_id: int) -> str | None:
    """The RPC endpoint this Pillar would use for *chain_id*, if any."""
    try:
        from rpc.config import load_rpc_config
        endpoints = load_rpc_config().get(chain_id) or []
        return endpoints[0] if endpoints else None
    except Exception:
        return None


def verify_eip1271(message_text: str, signature: str, address: str,
                   chain_id: int) -> tuple[bool, str]:
    """Ask the account contract whether it considers the signature valid.

    Returns (ok, reason). Blocking: call it from a thread in async code.
    """
    try:
        from web3 import Web3, HTTPProvider
    except ImportError:
        return (False, "contract-wallet verification requires: pip install web3")

    endpoint = _endpoint_for(chain_id)
    if not endpoint:
        return (False, f"no RPC endpoint configured for chain {chain_id}")

    try:
        w3 = Web3(HTTPProvider(endpoint, request_kwargs={"timeout": 10}))
        checksum = Web3.to_checksum_address(address)
        if w3.eth.get_code(checksum) in (b"", "0x", None):
            return (False, "address has no contract code on this chain")
        contract = w3.eth.contract(address=checksum, abi=EIP1271_ABI)
        sig_bytes = bytes.fromhex(signature[2:] if signature.startswith("0x") else signature)
        result = contract.functions.isValidSignature(
            _eip191_hash(message_text), sig_bytes
        ).call()
        if bytes(result) == EIP1271_MAGIC_VALUE:
            return (True, "valid (EIP-1271)")
        return (False, "contract rejected the signature")
    except Exception as exc:  # network, revert, malformed signature
        logger.debug("EIP-1271 check failed on chain %s: %s", chain_id, exc)
        return (False, f"EIP-1271 check failed: {exc}")


def _accepted_contract_chains() -> set[int]:
    """Chains this Pillar will verify a contract wallet on."""
    from core.config import load_config
    config = load_config()
    configured = config.get("contract_wallet_chain_ids") or []
    if configured:
        return {int(c) for c in configured}
    return {int(config.get("staking_chain_id", 50))}


def verify_wallet_signature(message_text: str, signature: str, address: str,
                            chain_id: int = None,
                            allow_contract: bool = True) -> tuple[bool, str]:
    """Verify a wallet signature: ecrecover first, then EIP-1271.

    Returns (ok, reason). Raises ImportError when eth-account is missing,
    matching ``verify_siwe_signature``.
    """
    from auth.siwe import verify_siwe_signature, parse_chain_id

    try:
        if verify_siwe_signature(message_text, signature, address):
            return (True, "valid (EOA)")
        reason = "signature does not match the address"
    except ValueError as exc:
        # Malformed for ecrecover — a contract wallet's signature often is.
        reason = str(exc)

    if not allow_contract:
        return (False, reason)

    if chain_id is None:
        chain_id = parse_chain_id(message_text)
    # The chain decides which contract answers isValidSignature. Letting the
    # signed message choose it lets a signer deploy a contract at the same
    # address on a chain nobody watches and be believed here, so the Pillar
    # states which chains it accepts a contract wallet on.
    accepted = _accepted_contract_chains()
    if chain_id not in accepted:
        return (False, f"{reason}; contract wallets are not accepted on chain {chain_id}")
    ok, contract_reason = verify_eip1271(message_text, signature, address, chain_id)
    if ok:
        return (True, contract_reason)
    return (False, f"{reason}; {contract_reason}")
