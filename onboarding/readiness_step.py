"""
REFInet Pillar — Onboarding: Launch Readiness Step

Serves a structured readiness checklist as a Gopher menu.
Can be used standalone before full onboarding is built.
Accessible at /onboarding/readiness
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.readiness import ServiceStatus


# Required services — Pillar cannot run without these
_REQUIRED_KEYS = {"python", "cryptography", "argon2"}

# Recommended services — features are disabled without these
_RECOMMENDED_KEYS = {"websockets", "eth_account", "web3", "tls"}

# Optional services — nice to have
_OPTIONAL_KEYS = {"tor", "stem", "qrcode"}


def build_readiness_menu(hostname: str, port: int, config: dict) -> str:
    """
    Return a complete Gopher menu string showing launch readiness.

    Uses info_line(), menu_link(), search_link(), separator() from
    core/menu_builder.py for all output.
    """
    from core.readiness import check_all, get_install_commands
    from core.menu_builder import info_line, menu_link, search_link, separator

    statuses = check_all(config)
    ready, missing_required = is_launch_ready(statuses)

    lines = []
    lines.append(info_line("  REFInet Pillar — Launch Readiness Check"))
    lines.append(separator())
    lines.append(info_line(""))

    # --- REQUIRED ---
    lines.append(info_line("  REQUIRED (must be green to run the Pillar)"))
    for s in statuses:
        if s.key in _REQUIRED_KEYS:
            icon = "✓" if s.available else "✗"
            version_str = f" {s.version}" if s.version else ""
            lines.append(info_line(f"  {icon}  {s.name}{version_str}"))
            if not s.available and s.install_cmd:
                lines.append(info_line(f"      → {s.install_cmd}"))
    lines.append(info_line(""))

    # --- RECOMMENDED ---
    lines.append(info_line("  RECOMMENDED (features disabled without these)"))
    for s in statuses:
        if s.key in _RECOMMENDED_KEYS:
            icon = "✓" if s.available else "○"
            version_str = f" ({s.key} {s.version})" if s.version else ""
            detail = ""
            if s.available and s.notes:
                detail = f"     — {s.notes}"
            elif not s.available and s.install_cmd:
                detail = f"     — {s.install_cmd}"
            lines.append(info_line(f"  {icon}  {s.name}{version_str}{detail}"))
    lines.append(info_line(""))

    # --- OPTIONAL ---
    lines.append(info_line("  OPTIONAL"))
    for s in statuses:
        if s.key in _OPTIONAL_KEYS:
            icon = "✓" if s.available else "○"
            version_str = f" {s.version}" if s.version else ""
            detail = ""
            if not s.available and s.install_cmd:
                detail = f"     — {s.install_cmd}"
            lines.append(info_line(f"  {icon}  {s.name}{version_str}{detail}"))
    lines.append(info_line(""))

    lines.append(separator())

    # Navigation links
    cmds = get_install_commands(statuses)
    if cmds:
        lines.append(search_link(
            "  Copy install command for all missing packages",
            "/onboarding/readiness/install",
            hostname, port,
        ))
    lines.append(menu_link("  Re-run this check", "/onboarding/readiness", hostname, port))
    lines.append(menu_link("  Continue to Pillar setup →", "/pillar-setup", hostname, port))
    lines.append(".\r\n")

    return "".join(lines)


def is_launch_ready(statuses: list) -> tuple[bool, list[str]]:
    """
    Check if all required services are available.

    Returns:
        (True, []) if all required services are available.
        (False, [list of missing required service names]) otherwise.

    Required services are: python, cryptography, argon2.
    Everything else is optional/recommended.
    """
    missing = []
    for s in statuses:
        if s.key in _REQUIRED_KEYS and not s.available:
            missing.append(s.name)
    return (len(missing) == 0, missing)
