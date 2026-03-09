"""
REFInet Pillar — First-Run Onboarding Wizard

State machine that guarantees every Pillar has a wallet-bound identity
before it serves any content.  The wizard runs as a Gopher menu flow on
port 7070 and produces a cryptographically verifiable binding between
the operator's EVM wallet and the Pillar's Ed25519 PID.

State is persisted to ``~/.refinet/onboarding_state.json`` so the wizard
survives restarts.  Once a binding is written the wizard marks itself
``COMPLETE`` and never runs again.

Steps:
    STEP_WELCOME        — explain what the wizard does
    STEP_GENERATE_PID   — generate Ed25519 keypair, save encrypted pid.json
    STEP_CONNECT_WALLET — prompt for EVM address via browser extension
    STEP_SIWE_CHALLENGE — generate + display SIWE challenge
    STEP_SIWE_VERIFY    — verify wallet signature, create binding
    STEP_CONFIRM        — show completed binding, offer proof export
    COMPLETE            — done, normal startup proceeds
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.config import HOME_DIR, PID_FILE, ensure_dirs
from core.menu_builder import info_line, menu_link, search_link, separator
from crypto.pid import generate_pid, save_pid, load_pid, get_private_key
from crypto.binding import (
    create_binding,
    binding_exists,
    export_binding_proof,
    get_deployer_binding,
)
from auth.session import create_challenge

logger = logging.getLogger("refinet.onboarding")

ONBOARDING_STATE_FILE = HOME_DIR / "onboarding_state.json"

# Valid EVM address pattern: 0x followed by exactly 40 hex chars
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ------------------------------------------------------------------
# Gate — checked by pillar.py on every startup
# ------------------------------------------------------------------
def is_onboarding_complete() -> bool:
    """
    Return ``True`` only when **both** conditions hold:
      1. ``pid.json`` exists and is loadable.
      2. At least one ``pid_bindings`` row exists for that PID.
    """
    pid_data = load_pid()
    if pid_data is None:
        return False
    return binding_exists(pid_data["pid"])


# ------------------------------------------------------------------
# State persistence
# ------------------------------------------------------------------
_DEFAULT_STATE: dict = {
    "step": "STEP_WELCOME",
    "pid": None,
    "evm_address": None,
    "challenge_nonce": None,
}


def get_onboarding_state() -> dict:
    """Load wizard state from disk, or return the default initial state."""
    ensure_dirs()
    if ONBOARDING_STATE_FILE.exists():
        try:
            with open(ONBOARDING_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_STATE)


def save_onboarding_state(state: dict) -> None:
    """Persist wizard state to ``~/.refinet/onboarding_state.json``."""
    ensure_dirs()
    with open(ONBOARDING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def reset_onboarding() -> None:
    """
    Delete state + pid files so the wizard starts from scratch.

    Does **not** touch the database — bindings are permanent once written.
    Only safe to call before ``STEP_SIWE_VERIFY`` completes.
    """
    for path in (ONBOARDING_STATE_FILE, PID_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------
# Gopher menu helpers (thin wrappers for readability)
# ------------------------------------------------------------------
def _banner(lines: list[str]) -> None:
    """Append the standard onboarding banner."""
    lines.append(info_line(""))
    lines.append(info_line("  ╔══════════════════════════════════════════╗"))
    lines.append(info_line("  ║     R E F I n e t   O N B O A R D I N G ║"))
    lines.append(info_line("  ║        First-Run Identity Wizard        ║"))
    lines.append(info_line("  ╚══════════════════════════════════════════╝"))
    lines.append(info_line(""))


def _footer(lines: list[str], hostname: str, port: int) -> None:
    """Append reset / abort link at the bottom of every wizard page."""
    lines.append(separator())
    lines.append(menu_link("Abort & Reset Wizard",
                           "/onboarding/reset", hostname, port))
    lines.append(info_line(""))


# ------------------------------------------------------------------
# Step renderers
# ------------------------------------------------------------------
def _step_welcome(hostname: str, port: int) -> str:
    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  This Pillar has no identity yet."))
    lines.append(info_line(""))
    lines.append(info_line("  The setup wizard will:"))
    lines.append(info_line(""))
    lines.append(info_line("    1. Generate a cryptographic Pillar ID (Ed25519 keypair)"))
    lines.append(info_line("    2. Encrypt the private key with a password you choose"))
    lines.append(info_line("    3. Permanently bind your Ethereum wallet to this Pillar"))
    lines.append(info_line(""))
    lines.append(info_line("  The wallet binding proves deployer identity and enables"))
    lines.append(info_line("  mesh trust.  It cannot be forged or reversed."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("Start Setup", "/onboarding/generate-pid",
                           hostname, port))
    lines.append(menu_link("Learn More", "/onboarding/about",
                           hostname, port))
    lines.append(info_line(""))
    return "".join(lines)


def _step_about(hostname: str, port: int) -> str:
    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  WHY WALLET BINDING?"))
    lines.append(info_line(""))
    lines.append(info_line("  Every Pillar in the REFInet mesh is identified by an"))
    lines.append(info_line("  Ed25519 keypair.  The PID (Pillar ID) is the SHA-256"))
    lines.append(info_line("  hash of the public key."))
    lines.append(info_line(""))
    lines.append(info_line("  Binding an EVM wallet to the PID creates a permanent,"))
    lines.append(info_line("  two-sided cryptographic proof:"))
    lines.append(info_line(""))
    lines.append(info_line("    - The wallet signs a SIWE message (EIP-4361)"))
    lines.append(info_line("      proving the wallet owner authorised the binding."))
    lines.append(info_line(""))
    lines.append(info_line("    - The Pillar Ed25519 key signs the binding record"))
    lines.append(info_line("      proving the PID keypair acknowledges the binding."))
    lines.append(info_line(""))
    lines.append(info_line("  Together, these signatures let any peer independently"))
    lines.append(info_line("  verify who deployed a Pillar without trusting a central"))
    lines.append(info_line("  authority."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("Back to Setup", "/onboarding/generate-pid",
                           hostname, port))
    lines.append(info_line(""))
    return "".join(lines)


def _step_generate_pid_prompt(hostname: str, port: int) -> str:
    """Show the password input prompt (no query received yet)."""
    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  STEP 1 — Generate Pillar Identity"))
    lines.append(info_line(""))
    lines.append(info_line("  Choose an encryption password for your private key."))
    lines.append(info_line("  This password protects your Ed25519 key at rest"))
    lines.append(info_line("  (AES-256-GCM + Argon2id)."))
    lines.append(info_line(""))
    lines.append(info_line("  Leave blank for no encryption (not recommended)."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(search_link("Enter encryption password",
                             "/onboarding/generate-pid", hostname, port))
    _footer(lines, hostname, port)
    return "".join(lines)


def _step_generate_pid_execute(query: str, state: dict,
                               hostname: str, port: int) -> str:
    """Generate the PID with the supplied password and save it."""
    password = query.strip() if query.strip() else None
    pid_data = generate_pid(password=password)
    save_pid(pid_data)

    state["step"] = "STEP_CONNECT_WALLET"
    state["pid"] = pid_data["pid"]
    state["password"] = password  # kept in state for SIWE verify step
    save_onboarding_state(state)

    logger.info("Onboarding: PID generated — %s", pid_data["pid"][:16])

    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  Pillar Identity Generated"))
    lines.append(info_line(""))
    lines.append(info_line(f"  PID: {pid_data['pid']}"))
    lines.append(info_line(f"  Public Key: {pid_data['public_key']}"))
    enc_label = "ENCRYPTED (AES-256-GCM)" if password else "UNENCRYPTED"
    lines.append(info_line(f"  Key Storage: {enc_label}"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("Continue to Wallet Setup",
                           "/onboarding/connect-wallet", hostname, port))
    _footer(lines, hostname, port)
    return "".join(lines)


def _step_connect_wallet_prompt(state: dict,
                                hostname: str, port: int) -> str:
    """Show wallet connection instructions + address input."""
    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  STEP 2 — Connect Ethereum Wallet"))
    lines.append(info_line(""))
    lines.append(info_line("  Open the REFInet browser extension and connect"))
    lines.append(info_line("  your wallet.  The extension will display your"))
    lines.append(info_line("  checksummed EVM address (0x...)."))
    lines.append(info_line(""))
    lines.append(info_line("  Paste your EVM address below to continue."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(search_link("Enter your EVM address (0x...)",
                             "/onboarding/connect-wallet", hostname, port))
    _footer(lines, hostname, port)
    return "".join(lines)


def _step_connect_wallet_execute(query: str, state: dict,
                                 hostname: str, port: int) -> str:
    """Validate and store the EVM address."""
    address = query.strip()
    if not _EVM_RE.match(address):
        lines: list[str] = []
        _banner(lines)
        lines.append(info_line("  Invalid EVM address."))
        lines.append(info_line(""))
        lines.append(info_line("  Expected format: 0x followed by 40 hex characters"))
        lines.append(info_line(f"  You entered: {address}"))
        lines.append(info_line(""))
        lines.append(separator())
        lines.append(search_link("Try again — enter your EVM address",
                                 "/onboarding/connect-wallet", hostname, port))
        _footer(lines, hostname, port)
        return "".join(lines)

    state["step"] = "STEP_SIWE_CHALLENGE"
    state["evm_address"] = address
    save_onboarding_state(state)

    logger.info("Onboarding: wallet address stored — %s", address)

    # Fall through to challenge generation
    return _step_siwe_challenge(state, hostname, port)


def _step_siwe_challenge(state: dict, hostname: str, port: int) -> str:
    """Generate and display the SIWE challenge."""
    address = state["evm_address"]
    challenge = create_challenge(address, chain_id=1)

    # Persist the nonce so we can match it on verify
    state["challenge_nonce"] = challenge["nonce"]
    state["siwe_message"] = challenge["message"]
    save_onboarding_state(state)

    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  STEP 3 — Sign SIWE Challenge"))
    lines.append(info_line(""))
    lines.append(info_line("  Sign the following message with your wallet"))
    lines.append(info_line("  (via the REFInet browser extension):"))
    lines.append(info_line(""))
    lines.append(separator())

    # Render each line of the SIWE message as an info_line
    for msg_line in challenge["message"].splitlines():
        lines.append(info_line(f"  {msg_line}"))

    lines.append(separator())

    if challenge.get("qr_base64"):
        lines.append(info_line(""))
        lines.append(info_line("  (QR code available in browser extension)"))

    lines.append(info_line(""))
    lines.append(info_line("  After signing, paste the signature below:"))
    lines.append(info_line(""))
    lines.append(search_link("Enter wallet signature (0x...)",
                             "/onboarding/siwe-verify", hostname, port))
    _footer(lines, hostname, port)
    return "".join(lines)


def _step_siwe_verify(query: str, state: dict,
                      hostname: str, port: int) -> str:
    """Verify the wallet signature and create the binding."""
    signature = query.strip()

    pid_data = load_pid()
    if pid_data is None:
        return _error_menu("pid.json not found — please restart the wizard.",
                           "/onboarding", hostname, port)

    password = state.get("password")
    try:
        priv_key = get_private_key(pid_data, password=password)
    except ValueError as exc:
        return _error_menu(f"Cannot unlock private key: {exc}",
                           "/onboarding/siwe-challenge", hostname, port)

    siwe_message = state.get("siwe_message", "")
    evm_address = state.get("evm_address", "")

    try:
        binding = create_binding(
            pid_data=pid_data,
            evm_address=evm_address,
            siwe_message=siwe_message,
            siwe_signature=signature,
            chain_id=1,
            private_key=priv_key,
            binding_type="deployer",
        )
    except (ValueError, Exception) as exc:
        logger.warning("Onboarding: SIWE verify failed — %s", exc)
        lines: list[str] = []
        _banner(lines)
        lines.append(info_line("  Signature Verification Failed"))
        lines.append(info_line(""))
        lines.append(info_line(f"  Error: {exc}"))
        lines.append(info_line(""))
        lines.append(info_line("  Please try signing again with your wallet."))
        lines.append(info_line(""))
        lines.append(separator())
        lines.append(menu_link("Retry — Back to Challenge",
                               "/onboarding/siwe-challenge", hostname, port))
        _footer(lines, hostname, port)
        return "".join(lines)

    # Success — advance to confirmation
    state["step"] = "STEP_CONFIRM"
    state["binding_id"] = binding["binding_id"]
    save_onboarding_state(state)

    logger.info("Onboarding: binding created — %s", binding["binding_id"][:16])

    return _step_confirm(binding, hostname, port)


def _step_confirm(binding: dict | None, hostname: str, port: int) -> str:
    """Show the completed binding and proof export."""
    if binding is None:
        # Reload from DB when revisiting the confirm page
        state = get_onboarding_state()
        pid = state.get("pid")
        if pid:
            binding = get_deployer_binding(pid)
        if binding is None:
            return _error_menu("Binding not found — please restart.",
                               "/onboarding", hostname, port)

    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  Wallet Binding Complete"))
    lines.append(info_line(""))
    lines.append(info_line(f"  PID:         {binding['pid']}"))
    lines.append(info_line(f"  EVM Address: {binding['evm_address']}"))
    lines.append(info_line(f"  Binding ID:  {binding['binding_id']}"))
    lines.append(info_line(f"  Chain ID:    {binding['chain_id']}"))
    lines.append(info_line(f"  Created:     {binding['created_at']}"))
    lines.append(info_line(f"  Type:        {binding['binding_type']}"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  BINDING PROOF (save this for your records):"))
    lines.append(info_line(""))

    proof_json = export_binding_proof(binding)
    for proof_line in proof_json.splitlines():
        lines.append(info_line(f"  {proof_line}"))

    lines.append(info_line(""))
    lines.append(separator())
    lines.append(info_line("  Your Pillar identity is now cryptographically bound"))
    lines.append(info_line("  to your wallet.  Peers can independently verify this."))
    lines.append(info_line(""))
    lines.append(menu_link("Start Pillar", "/onboarding/complete",
                           hostname, port))
    lines.append(info_line(""))
    return "".join(lines)


def _step_complete(hostname: str, port: int) -> str:
    """Mark onboarding finished and show the final message."""
    state = {"step": "COMPLETE"}
    save_onboarding_state(state)

    logger.info("Onboarding: COMPLETE")

    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  Setup Complete"))
    lines.append(info_line(""))
    lines.append(info_line("  Your Pillar identity is ready."))
    lines.append(info_line("  The server will now enter normal operation."))
    lines.append(info_line(""))
    lines.append(info_line("  Welcome to Gopherspace."))
    lines.append(info_line(""))
    return "".join(lines)


def _step_reset(hostname: str, port: int) -> str:
    """Handle explicit abort/reset request."""
    state = get_onboarding_state()

    # Only allow reset before binding is written
    if state.get("step") in ("STEP_CONFIRM", "COMPLETE"):
        lines: list[str] = []
        _banner(lines)
        lines.append(info_line("  Cannot reset — binding already written."))
        lines.append(info_line("  Bindings are permanent and immutable."))
        lines.append(info_line(""))
        lines.append(separator())
        lines.append(menu_link("Back to Confirmation",
                               "/onboarding/confirm", hostname, port))
        lines.append(info_line(""))
        return "".join(lines)

    reset_onboarding()
    logger.info("Onboarding: wizard reset by operator")

    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  Wizard Reset"))
    lines.append(info_line(""))
    lines.append(info_line("  Onboarding state and PID have been deleted."))
    lines.append(info_line("  You can start fresh."))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("Start Over", "/onboarding", hostname, port))
    lines.append(info_line(""))
    return "".join(lines)


# ------------------------------------------------------------------
# Error helper
# ------------------------------------------------------------------
def _error_menu(message: str, retry_selector: str,
                hostname: str, port: int) -> str:
    lines: list[str] = []
    _banner(lines)
    lines.append(info_line("  Error"))
    lines.append(info_line(""))
    lines.append(info_line(f"  {message}"))
    lines.append(info_line(""))
    lines.append(separator())
    lines.append(menu_link("Retry", retry_selector, hostname, port))
    _footer(lines, hostname, port)
    return "".join(lines)


# ------------------------------------------------------------------
# Main router
# ------------------------------------------------------------------
async def handle_wizard_step(selector: str, query: str,
                             hostname: str, port: int) -> str:
    """
    Route a Gopher request through the onboarding wizard.

    Called by the Gopher server when ``is_onboarding_complete()`` is False.
    *selector* is the Gopher selector path; *query* is the tab-separated
    search input (empty string when absent).

    Returns a Gopher-formatted menu string.
    """
    state = get_onboarding_state()
    step = state.get("step", "STEP_WELCOME")

    # Normalise selector
    sel = selector.rstrip("/") or "/onboarding"

    # ------ explicit route overrides (always honoured) ------
    if sel == "/onboarding/reset":
        return _step_reset(hostname, port)

    if sel == "/onboarding/about":
        return _step_about(hostname, port)

    if sel == "/onboarding/complete":
        return _step_complete(hostname, port)

    # ------ state-driven routing ------

    if step == "STEP_WELCOME" or sel == "/onboarding":
        if sel == "/onboarding/generate-pid" and query:
            return _step_generate_pid_execute(query, state, hostname, port)
        if sel == "/onboarding/generate-pid":
            return _step_generate_pid_prompt(hostname, port)
        return _step_welcome(hostname, port)

    if step == "STEP_GENERATE_PID":
        if query:
            return _step_generate_pid_execute(query, state, hostname, port)
        return _step_generate_pid_prompt(hostname, port)

    if step == "STEP_CONNECT_WALLET":
        if sel == "/onboarding/connect-wallet" and query:
            return _step_connect_wallet_execute(query, state, hostname, port)
        return _step_connect_wallet_prompt(state, hostname, port)

    if step == "STEP_SIWE_CHALLENGE":
        if sel == "/onboarding/siwe-verify" and query:
            return _step_siwe_verify(query, state, hostname, port)
        if sel == "/onboarding/siwe-challenge":
            return _step_siwe_challenge(state, hostname, port)
        # Default: show the challenge
        return _step_siwe_challenge(state, hostname, port)

    if step == "STEP_SIWE_VERIFY":
        if query:
            return _step_siwe_verify(query, state, hostname, port)
        # No signature yet — re-show challenge
        return _step_siwe_challenge(state, hostname, port)

    if step == "STEP_CONFIRM":
        return _step_confirm(None, hostname, port)

    if step == "COMPLETE":
        return _step_complete(hostname, port)

    # Fallback
    return _step_welcome(hostname, port)
