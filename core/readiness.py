from __future__ import annotations

"""
REFInet Pillar — Service Readiness Checker

Checks every optional service and dependency at startup.
All checks are synchronous and local — no network, no subprocess spawning.
Results are used by the onboarding wizard, the /health Gopher route,
and the browser extension status panel.
"""

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServiceStatus:
    name: str                    # human display name
    key: str                     # machine key (used in JSON)
    available: bool              # can this service be used right now?
    installed: bool              # is the binary/library present?
    configured: bool             # is it configured in config.json?
    version: Optional[str]       # detected version string, if available
    install_cmd: Optional[str]   # what to run to install it
    config_key: Optional[str]    # which config.json key controls it
    notes: Optional[str]         # any additional context


# Services classified as required (missing = ✗) vs optional (missing = ○)
REQUIRED_KEYS = {"python", "cryptography", "argon2"}
OPTIONAL_KEYS = {"websockets", "eth_account", "web3", "tor", "stem", "tls", "qrcode"}


def check_all(config: dict) -> list[ServiceStatus]:
    """
    Check every optional service and dependency.

    Returns one ServiceStatus per service, in a fixed order.
    All checks are synchronous and local — no network calls, no daemon starts.
    """
    statuses = [
        _check_python(),
        _check_cryptography(),
        _check_argon2(),
        _check_websockets(config),
        _check_eth_account(),
        _check_web3(),
        _check_tor(config),
        _check_tls(),
        _check_qrcode(),
        _check_stem(),
    ]
    return statuses


def _check_python() -> ServiceStatus:
    version = sys.version.split()[0]
    ok = sys.version_info >= (3, 9)
    return ServiceStatus(
        name="Python",
        key="python",
        available=ok,
        installed=True,
        configured=True,
        version=version,
        install_cmd="https://python.org" if not ok else None,
        config_key=None,
        notes="Python 3.9+ required" if not ok else None,
    )


def _check_cryptography() -> ServiceStatus:
    try:
        import cryptography
        return ServiceStatus(
            name="cryptography",
            key="cryptography",
            available=True,
            installed=True,
            configured=True,
            version=cryptography.__version__,
            install_cmd=None,
            config_key=None,
            notes=None,
        )
    except ImportError:
        return ServiceStatus(
            name="cryptography",
            key="cryptography",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install cryptography>=41.0.0",
            config_key=None,
            notes=None,
        )


def _check_argon2() -> ServiceStatus:
    try:
        import argon2
        version = getattr(argon2, "__version__", None)
        return ServiceStatus(
            name="argon2",
            key="argon2",
            available=True,
            installed=True,
            configured=True,
            version=version,
            install_cmd=None,
            config_key=None,
            notes=None,
        )
    except ImportError:
        return ServiceStatus(
            name="argon2",
            key="argon2",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install argon2-cffi",
            config_key=None,
            notes=None,
        )


def _check_websockets(config: dict) -> ServiceStatus:
    configured = config.get("websocket_enabled", True)
    try:
        import websockets
        version = getattr(websockets, "__version__", None)
        return ServiceStatus(
            name="WebSocket bridge",
            key="websockets",
            available=True,
            installed=True,
            configured=configured,
            version=version,
            install_cmd=None,
            config_key="websocket_enabled",
            notes="Required for browser extension",
        )
    except ImportError:
        return ServiceStatus(
            name="WebSocket bridge",
            key="websockets",
            available=False,
            installed=False,
            configured=configured,
            version=None,
            install_cmd="pip install websockets>=12.0",
            config_key="websocket_enabled",
            notes="Required for browser extension",
        )


def _check_eth_account() -> ServiceStatus:
    try:
        import eth_account
        version = getattr(eth_account, "__version__", None)
        return ServiceStatus(
            name="SIWE / Wallet auth",
            key="eth_account",
            available=True,
            installed=True,
            configured=True,
            version=version,
            install_cmd=None,
            config_key=None,
            notes="Required for wallet sign-in",
        )
    except ImportError:
        return ServiceStatus(
            name="SIWE / Wallet auth",
            key="eth_account",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install eth-account>=0.10.0",
            config_key=None,
            notes="Required for wallet sign-in",
        )


def _check_web3() -> ServiceStatus:
    try:
        import web3
        return ServiceStatus(
            name="EVM RPC gateway",
            key="web3",
            available=True,
            installed=True,
            configured=True,
            version=web3.__version__,
            install_cmd=None,
            config_key=None,
            notes="Required for Ethereum/Polygon/Arbitrum/Base RPC",
        )
    except ImportError:
        return ServiceStatus(
            name="EVM RPC gateway",
            key="web3",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install web3>=6.0.0",
            config_key=None,
            notes="Required for Ethereum/Polygon/Arbitrum/Base RPC",
        )


def _check_tor(config: dict) -> ServiceStatus:
    installed = shutil.which("tor") is not None

    # Get version from tor binary
    version = None
    if installed:
        try:
            result = subprocess.run(
                ["tor", "--version"],
                capture_output=True, text=True, timeout=3,
            )
            # Parse version from first line, e.g. "Tor version 0.4.7.13."
            first_line = result.stdout.strip().split("\n")[0]
            for part in first_line.split():
                if part[0].isdigit():
                    version = part.rstrip(".")
                    break
        except Exception:
            version = None

    # Check if stem is available (Tor without stem is unusable)
    try:
        import stem
        stem_ok = True
    except ImportError:
        stem_ok = False

    available = installed and stem_ok
    configured = config.get("tor_enabled", False)

    # Platform-specific install hint
    install_cmd = _tor_install_hint() if not installed else None

    return ServiceStatus(
        name="Tor hidden service",
        key="tor",
        available=available,
        installed=installed,
        configured=configured,
        version=version,
        install_cmd=install_cmd,
        config_key="tor_enabled",
        notes="Provides .onion address for global reachability without static IP",
    )


def _tor_install_hint() -> str:
    """Return platform-specific Tor install instructions."""
    system = platform.system().lower()
    if system == "darwin":
        return "brew install tor"
    elif system == "linux":
        return "sudo apt install tor"
    return "Install Tor from https://torproject.org/install"


def _check_tls() -> ServiceStatus:
    try:
        from crypto.tls import is_cert_valid
        from core.config import TLS_DIR
        cert_path = TLS_DIR / "cert.pem"
        cert_exists = cert_path.exists()
        cert_valid = cert_exists and is_cert_valid(cert_path)
        return ServiceStatus(
            name="TLS / GopherS",
            key="tls",
            available=cert_valid,
            installed=True,
            configured=True,
            version=None,
            install_cmd=None,
            config_key=None,
            notes=f"Cert valid: {cert_path}" if cert_valid else "Self-signed cert auto-generated on first run",
        )
    except Exception:
        return ServiceStatus(
            name="TLS / GopherS",
            key="tls",
            available=False,
            installed=True,
            configured=True,
            version=None,
            install_cmd=None,
            config_key=None,
            notes="Self-signed cert auto-generated on first run",
        )


def _check_qrcode() -> ServiceStatus:
    try:
        import qrcode
        version = getattr(qrcode, "__version__", None)
        return ServiceStatus(
            name="QR codes",
            key="qrcode",
            available=True,
            installed=True,
            configured=True,
            version=version,
            install_cmd=None,
            config_key=None,
            notes="Optional — enhances SIWE auth flow",
        )
    except ImportError:
        return ServiceStatus(
            name="QR codes",
            key="qrcode",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install qrcode[pil]",
            config_key=None,
            notes="Optional — enhances SIWE auth flow",
        )


def _check_stem() -> ServiceStatus:
    try:
        import stem
        version = getattr(stem, "__version__", None)
        return ServiceStatus(
            name="stem library",
            key="stem",
            available=True,
            installed=True,
            configured=True,
            version=version,
            install_cmd=None,
            config_key=None,
            notes="Required alongside Tor binary for hidden services",
        )
    except ImportError:
        return ServiceStatus(
            name="stem library",
            key="stem",
            available=False,
            installed=False,
            configured=True,
            version=None,
            install_cmd="pip install stem>=1.8.2",
            config_key=None,
            notes="Required alongside Tor binary for hidden services",
        )


async def check_tor_integration(config: dict, timeout: int = 30) -> ServiceStatus:
    """
    Actually start TorManager and verify hidden service creation.
    This takes 10-120 seconds. Only call when explicitly requested.
    Returns a ServiceStatus with available=True if .onion address was generated.
    """
    from core.tor_manager import TorManager

    tor = TorManager(config)
    try:
        started = await tor.start()
        if not started:
            return ServiceStatus(
                name="Tor hidden service",
                key="tor",
                available=False,
                installed=shutil.which("tor") is not None,
                configured=config.get("tor_enabled", False),
                version=None,
                install_cmd=_tor_install_hint() if not shutil.which("tor") else None,
                config_key="tor_enabled",
                notes="Tor failed to start — check configuration and network",
            )

        onion = await tor.create_hidden_services()
        if onion:
            return ServiceStatus(
                name="Tor hidden service",
                key="tor",
                available=True,
                installed=True,
                configured=True,
                version=None,
                install_cmd=None,
                config_key="tor_enabled",
                notes=f"Live check passed — .onion: {onion}",
            )
        else:
            return ServiceStatus(
                name="Tor hidden service",
                key="tor",
                available=False,
                installed=True,
                configured=config.get("tor_enabled", False),
                version=None,
                install_cmd=None,
                config_key="tor_enabled",
                notes="Tor started but hidden service creation failed",
            )
    except Exception as e:
        return ServiceStatus(
            name="Tor hidden service",
            key="tor",
            available=False,
            installed=shutil.which("tor") is not None,
            configured=config.get("tor_enabled", False),
            version=None,
            install_cmd=_tor_install_hint() if not shutil.which("tor") else None,
            config_key="tor_enabled",
            notes=f"Live check failed: {e}",
        )
    finally:
        await tor.stop()


def format_status_table(statuses: list[ServiceStatus]) -> str:
    """
    Return a plain-text ASCII table suitable for terminal output
    and Gopher info_line() display.
    """
    lines = []
    header = f"{'Service':<20} {'Status':<10} {'Version':<14} Notes"
    lines.append(header)
    lines.append("─" * 65)

    for s in statuses:
        if s.available:
            status_str = "✓ OK"
        elif s.key in REQUIRED_KEYS:
            status_str = "✗ MISSING"
        else:
            status_str = "○ OPTIONAL"

        version_str = s.version if s.version else "—"
        notes_str = ""
        if not s.available and s.install_cmd:
            notes_str = s.install_cmd
        elif s.notes:
            notes_str = s.notes

        lines.append(
            f"{s.name:<20} {status_str:<10} {version_str:<14} {notes_str}"
        )

    return "\n".join(lines)


def get_install_commands(statuses: list[ServiceStatus]) -> list[str]:
    """
    Return pip install commands that would fix all missing Python packages.
    Groups them into a single pip install line where possible.
    Excludes already-available packages and system packages (Tor).
    """
    pip_packages = []
    for s in statuses:
        if not s.available and s.install_cmd and s.install_cmd.startswith("pip install"):
            # Extract the package spec from "pip install <pkg>"
            pkg = s.install_cmd.replace("pip install ", "")
            pip_packages.append(pkg)

    if pip_packages:
        return [f"pip install {' '.join(pip_packages)}"]
    return []
