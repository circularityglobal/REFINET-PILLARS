#!/usr/bin/env python3
"""
Build .deb package for REFInet Pillar (Debian/Ubuntu).

Usage:
    python build/build_deb.py

Requires: Linux with dpkg-deb (ships with every Debian/Ubuntu).
Expects PyInstaller binary already built at dist/refinet-pillar-setup,
or builds it automatically.

Pipeline:
    1. Build standalone binary via PyInstaller (if not already present)
    2. Create Debian package tree (DEBIAN/control, usr/local/bin/, etc.)
    3. Package into .deb using dpkg-deb
    4. Verify .deb metadata with dpkg-deb --info
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
SPEC_FILE = PROJECT_ROOT / "build" / "refinet-pillar.spec"
DEB_OUTPUT = DIST_DIR / "refinet-pillar.deb"

# Package metadata (sourced from pyproject.toml values)
PKG_NAME = "refinet-pillar"
PKG_VERSION = "0.3.0"
PKG_ARCH = "amd64"  # overridden at runtime if arm64
PKG_MAINTAINER = "S6 Labs LLC <support@s6labs.com>"
PKG_DESCRIPTION = "Sovereign Gopher mesh node with Ed25519 identity and encrypted mesh networking"
PKG_HOMEPAGE = "https://refinet.io"
PKG_LICENSE = "AGPL-3.0-or-later"


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a command, abort on failure."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"ERROR: command failed (exit {result.returncode})")
        if hasattr(result, "stderr") and result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        sys.exit(1)
    return result


def detect_arch() -> str:
    """Map platform.machine() to Debian architecture names."""
    machine = platform.machine().lower()
    mapping = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armhf",
    }
    arch = mapping.get(machine, "amd64")
    print(f"  Detected arch: {machine} -> deb arch: {arch}")
    return arch


def ensure_binary() -> Path:
    """Build the PyInstaller binary if it doesn't already exist."""
    binary = DIST_DIR / "refinet-pillar-setup"
    if binary.exists():
        print(f"[1/5] Binary already exists: {binary}")
        return binary

    print("[1/5] Building binary with PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--distpath", str(DIST_DIR),
        "--workpath", str(PROJECT_ROOT / "build" / "temp"),
        "--clean", "--noconfirm",
    ])

    if not binary.exists():
        print(f"ERROR: PyInstaller did not produce {binary}")
        sys.exit(1)

    return binary


def create_deb_tree(binary: Path, arch: str) -> Path:
    """Create the Debian package directory structure."""
    print("[2/5] Creating Debian package tree...")

    deb_root = PROJECT_ROOT / "build" / "deb-staging"
    if deb_root.exists():
        shutil.rmtree(deb_root)

    # Directory layout:
    #   DEBIAN/control
    #   DEBIAN/postinst
    #   usr/local/bin/refinet-pillar
    #   usr/share/doc/refinet-pillar/copyright
    #   usr/lib/systemd/system/refinet-pillar.service

    debian_dir = deb_root / "DEBIAN"
    bin_dir = deb_root / "usr" / "local" / "bin"
    doc_dir = deb_root / "usr" / "share" / "doc" / PKG_NAME
    systemd_dir = deb_root / "usr" / "lib" / "systemd" / "system"

    for d in [debian_dir, bin_dir, doc_dir, systemd_dir]:
        d.mkdir(parents=True)

    # --- DEBIAN/control ---
    installed_size_kb = binary.stat().st_size // 1024
    control = debian_dir / "control"
    control.write_text(
        f"Package: {PKG_NAME}\n"
        f"Version: {PKG_VERSION}\n"
        f"Architecture: {arch}\n"
        f"Maintainer: {PKG_MAINTAINER}\n"
        f"Installed-Size: {installed_size_kb}\n"
        f"Depends: libc6 (>= 2.31), libssl1.1 | libssl3\n"
        f"Section: net\n"
        f"Priority: optional\n"
        f"Homepage: {PKG_HOMEPAGE}\n"
        f"Description: {PKG_DESCRIPTION}\n"
        f" REFInet Pillar is a sovereign Gopher protocol node with Ed25519\n"
        f" identity, encrypted storage, mesh networking, and blockchain\n"
        f" integration. Run your own node in Gopherspace.\n"
    )
    print(f"  Created: DEBIAN/control")

    # --- DEBIAN/postinst ---
    postinst = debian_dir / "postinst"
    postinst.write_text(
        "#!/bin/sh\n"
        "set -e\n"
        "\n"
        "# Create refinet data directory for the installing user\n"
        "if [ -n \"$SUDO_USER\" ]; then\n"
        "    REAL_HOME=$(getent passwd \"$SUDO_USER\" | cut -d: -f6)\n"
        "    if [ -n \"$REAL_HOME\" ] && [ ! -d \"$REAL_HOME/.refinet\" ]; then\n"
        "        mkdir -p \"$REAL_HOME/.refinet\"\n"
        "        chown \"$SUDO_USER:$SUDO_USER\" \"$REAL_HOME/.refinet\"\n"
        "    fi\n"
        "fi\n"
        "\n"
        "echo ''\n"
        "echo '  REFInet Pillar installed successfully.'\n"
        "echo '  Run: refinet-pillar run'\n"
        "echo '  Or enable the systemd service: systemctl enable --now refinet-pillar'\n"
        "echo ''\n"
    )
    postinst.chmod(0o755)
    print(f"  Created: DEBIAN/postinst")

    # --- DEBIAN/prerm ---
    prerm = debian_dir / "prerm"
    prerm.write_text(
        "#!/bin/sh\n"
        "set -e\n"
        "\n"
        "# Stop systemd service if running\n"
        "if systemctl is-active --quiet refinet-pillar 2>/dev/null; then\n"
        "    systemctl stop refinet-pillar\n"
        "fi\n"
        "if systemctl is-enabled --quiet refinet-pillar 2>/dev/null; then\n"
        "    systemctl disable refinet-pillar\n"
        "fi\n"
    )
    prerm.chmod(0o755)
    print(f"  Created: DEBIAN/prerm")

    # --- Binary ---
    dest_binary = bin_dir / "refinet-pillar"
    shutil.copy2(binary, dest_binary)
    dest_binary.chmod(0o755)
    size_mb = dest_binary.stat().st_size / (1024 * 1024)
    print(f"  Installed: usr/local/bin/refinet-pillar ({size_mb:.1f} MB)")

    # --- Copyright ---
    copyright_file = doc_dir / "copyright"
    copyright_file.write_text(
        f"Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        f"Upstream-Name: {PKG_NAME}\n"
        f"Upstream-Contact: {PKG_MAINTAINER}\n"
        f"Source: https://github.com/circularityglobal/REFINET-PILLARS\n"
        f"\n"
        f"Files: *\n"
        f"Copyright: 2025-2026 S6 Labs LLC\n"
        f"License: {PKG_LICENSE}\n"
        f" This program is free software: you can redistribute it and/or modify\n"
        f" it under the terms of the GNU Affero General Public License as\n"
        f" published by the Free Software Foundation, either version 3 of the\n"
        f" License, or (at your option) any later version.\n"
        f" .\n"
        f" On Debian systems, the complete text of the GNU Affero General Public\n"
        f" License version 3 can be found in /usr/share/common-licenses/AGPL-3.\n"
    )
    print(f"  Created: usr/share/doc/{PKG_NAME}/copyright")

    # --- Systemd service ---
    service_file = systemd_dir / "refinet-pillar.service"
    service_file.write_text(
        "[Unit]\n"
        "Description=REFInet Pillar — Sovereign Gopher Mesh Node\n"
        "Documentation=https://docs.refinet.io\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart=/usr/local/bin/refinet-pillar run\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "# Security hardening\n"
        "NoNewPrivileges=yes\n"
        "ProtectSystem=strict\n"
        "ProtectHome=read-only\n"
        "ReadWritePaths=/home\n"
        "PrivateTmp=yes\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    print(f"  Created: usr/lib/systemd/system/refinet-pillar.service")

    return deb_root


def build_deb(deb_root: Path) -> Path:
    """Build the .deb package using dpkg-deb."""
    print("[3/5] Building .deb package...")

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if DEB_OUTPUT.exists():
        DEB_OUTPUT.unlink()

    run(["dpkg-deb", "--build", "--root-owner-group", str(deb_root), str(DEB_OUTPUT)])

    if not DEB_OUTPUT.exists():
        print(f"ERROR: dpkg-deb did not produce {DEB_OUTPUT}")
        sys.exit(1)

    size_mb = DEB_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"  Output: {DEB_OUTPUT} ({size_mb:.1f} MB)")
    return DEB_OUTPUT


def verify_deb(deb: Path) -> None:
    """Verify the .deb package metadata and contents."""
    print("[4/5] Verifying .deb package...")

    # Show package info
    result = run(["dpkg-deb", "--info", str(deb)], capture_output=True, text=True)
    print(result.stdout)

    # List contents
    result = run(["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    print(f"  Package contains {len(lines)} entries:")
    for line in lines:
        print(f"    {line}")

    # Verify critical files present in contents listing
    contents = result.stdout
    checks = {
        "usr/local/bin/refinet-pillar": "binary",
        "usr/lib/systemd/system/refinet-pillar.service": "systemd unit",
        "usr/share/doc/refinet-pillar/copyright": "copyright",
    }
    all_ok = True
    for path, label in checks.items():
        if path in contents:
            print(f"  {label}: present")
        else:
            print(f"  {label}: MISSING ({path})")
            all_ok = False

    if all_ok:
        print("  Verification: PASSED")
    else:
        print("  Verification: FAILED — missing files")
        sys.exit(1)


def smoke_test(deb: Path) -> None:
    """Extract the .deb and run the binary with --help."""
    print("[5/5] Smoke test (extract + run)...")

    extract_dir = PROJECT_ROOT / "build" / "deb-extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    # Extract without installing
    run(["dpkg-deb", "--extract", str(deb), str(extract_dir)])

    binary = extract_dir / "usr" / "local" / "bin" / "refinet-pillar"
    if not binary.exists():
        print(f"  ERROR: Binary not found at {binary}")
        sys.exit(1)

    # Run --help
    result = subprocess.run(
        [str(binary), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        print("  --help: PASSED")
    else:
        print(f"  --help: FAILED (exit {result.returncode})")
        print(f"  stderr: {result.stderr[:300]}")
        sys.exit(1)

    # Run services
    result = subprocess.run(
        [str(binary), "services"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        print("  services: PASSED")
    else:
        print(f"  services: FAILED (exit {result.returncode})")

    # Verify systemd unit
    service = extract_dir / "usr" / "lib" / "systemd" / "system" / "refinet-pillar.service"
    if service.exists():
        print("  systemd unit: present")
    else:
        print("  WARNING: systemd unit missing")

    # Verify copyright
    copyright_f = extract_dir / "usr" / "share" / "doc" / PKG_NAME / "copyright"
    if copyright_f.exists():
        print("  copyright: present")
    else:
        print("  WARNING: copyright file missing")

    # Cleanup
    shutil.rmtree(extract_dir, ignore_errors=True)


def main() -> None:
    system = platform.system()
    if system != "Linux":
        print(f"WARNING: Running on {system} — dpkg-deb requires Linux.")
        print("  Will create the package tree for inspection but cannot build .deb.\n")

    print(f"=== REFInet Pillar — .deb Package Build ===")
    print(f"Python: {sys.version}")
    print(f"Arch: {platform.machine()}")
    print(f"Project: {PROJECT_ROOT}")

    arch = detect_arch()
    binary = ensure_binary()
    deb_root = create_deb_tree(binary, arch)

    if system != "Linux":
        print(f"\n[3/5] SKIPPED: dpkg-deb not available on {system}")
        print(f"  Package tree created at: {deb_root}")
        print(f"  Inspect with: find {deb_root} -type f")
        print(f"\n  To build on Linux: dpkg-deb --build --root-owner-group {deb_root} {DEB_OUTPUT}")
        # Don't cleanup staging so user can inspect
        return

    deb = build_deb(deb_root)
    verify_deb(deb)
    smoke_test(deb)

    # Cleanup staging
    shutil.rmtree(deb_root, ignore_errors=True)

    print(f"\nBuild successful: {deb}")


if __name__ == "__main__":
    main()
