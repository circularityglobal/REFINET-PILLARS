#!/usr/bin/env python3
"""
Build macOS .dmg disk image for REFInet Pillar.

Usage:
    python build/build_dmg.py

Requires: macOS with hdiutil (ships with every Mac).
Expects PyInstaller binary already built at dist/refinet-pillar-setup.

Pipeline:
    1. Build standalone binary via PyInstaller (if not already present)
    2. Create staging directory with binary + README
    3. Package into .dmg using hdiutil
    4. Smoke-test the binary extracted from the .dmg
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
SPEC_FILE = PROJECT_ROOT / "build" / "refinet-pillar.spec"
DMG_OUTPUT = DIST_DIR / "refinet-pillar.dmg"
VOLUME_NAME = "REFInet Pillar"
BINARY_NAME = "refinet-pillar"


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


def ensure_binary() -> Path:
    """Build the PyInstaller binary if it doesn't already exist."""
    binary = DIST_DIR / "refinet-pillar-setup"
    if binary.exists():
        print(f"[1/4] Binary already exists: {binary}")
        return binary

    print("[1/4] Building binary with PyInstaller...")
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


def create_staging(binary: Path) -> Path:
    """Create a staging directory with the binary and README."""
    print("[2/4] Creating staging directory...")
    staging = PROJECT_ROOT / "build" / "dmg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Copy binary with clean name
    dest_binary = staging / BINARY_NAME
    shutil.copy2(binary, dest_binary)
    os.chmod(dest_binary, 0o755)

    # Create install README
    readme = staging / "INSTALL.txt"
    readme.write_text(
        "REFInet Pillar — macOS Installation\n"
        "====================================\n"
        "\n"
        "Option A — Drag to PATH:\n"
        "  Copy 'refinet-pillar' to /usr/local/bin/\n"
        "\n"
        "  In Terminal:\n"
        "    cp /Volumes/REFInet\\ Pillar/refinet-pillar /usr/local/bin/\n"
        "\n"
        "Option B — Run from anywhere:\n"
        "  Double-click this disk image, then in Terminal:\n"
        "    /Volumes/REFInet\\ Pillar/refinet-pillar run\n"
        "\n"
        "Quick start:\n"
        "  refinet-pillar run          # Start the Pillar server\n"
        "  refinet-pillar --help       # See all commands\n"
        "  refinet-pillar services     # Check dependency status\n"
        "\n"
        "Docs: https://docs.refinet.io\n"
        "Source: https://github.com/circularityglobal/REFINET-PILLARS\n"
    )

    print(f"  Staged: {dest_binary.name} ({dest_binary.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  Staged: {readme.name}")
    return staging


def build_dmg(staging: Path) -> Path:
    """Create .dmg from the staging directory using hdiutil."""
    print("[3/4] Building .dmg...")

    # Remove previous .dmg if it exists
    if DMG_OUTPUT.exists():
        DMG_OUTPUT.unlink()

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    run([
        "hdiutil", "create",
        "-volname", VOLUME_NAME,
        "-srcfolder", str(staging),
        "-ov",                  # overwrite
        "-format", "UDZO",     # zlib-compressed read-only
        str(DMG_OUTPUT),
    ])

    if not DMG_OUTPUT.exists():
        print(f"ERROR: hdiutil did not produce {DMG_OUTPUT}")
        sys.exit(1)

    size_mb = DMG_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"  Output: {DMG_OUTPUT} ({size_mb:.1f} MB)")
    return DMG_OUTPUT


def smoke_test(dmg: Path) -> None:
    """Mount the .dmg, run the binary with --help, then unmount."""
    print("[4/4] Smoke test...")

    mount_point = None
    try:
        # Mount
        result = run(
            ["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly"],
            capture_output=True, text=True,
        )
        # Parse mount point from hdiutil output (last column of last line)
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                mount_point = parts[-1].strip()

        if not mount_point or not Path(mount_point).exists():
            print(f"  WARNING: Could not determine mount point from: {result.stdout}")
            print("  Skipping smoke test — .dmg created successfully")
            return

        print(f"  Mounted at: {mount_point}")

        # Verify binary exists on volume
        binary_on_vol = Path(mount_point) / BINARY_NAME
        if not binary_on_vol.exists():
            print(f"  ERROR: Binary not found at {binary_on_vol}")
            sys.exit(1)

        # Run --help
        test_result = subprocess.run(
            [str(binary_on_vol), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        if test_result.returncode == 0:
            print("  --help: PASSED")
        else:
            print(f"  --help: FAILED (exit {test_result.returncode})")
            print(f"  stderr: {test_result.stderr[:300]}")
            sys.exit(1)

        # Run services
        test_result = subprocess.run(
            [str(binary_on_vol), "services"],
            capture_output=True, text=True, timeout=30,
        )
        if test_result.returncode == 0:
            print("  services: PASSED")
        else:
            print(f"  services: FAILED (exit {test_result.returncode})")

        # Verify INSTALL.txt
        install_txt = Path(mount_point) / "INSTALL.txt"
        if install_txt.exists():
            print("  INSTALL.txt: present")
        else:
            print("  WARNING: INSTALL.txt missing from volume")

    finally:
        # Unmount
        if mount_point and Path(mount_point).exists():
            subprocess.run(
                ["hdiutil", "detach", mount_point, "-quiet"],
                capture_output=True,
            )
            print(f"  Unmounted: {mount_point}")


def main() -> None:
    if platform.system() != "Darwin":
        print("ERROR: .dmg builds require macOS (hdiutil)")
        print("  This script should only run on macOS CI runners or local Macs")
        sys.exit(1)

    print(f"=== REFInet Pillar — macOS .dmg Build ===")
    print(f"Python: {sys.version}")
    print(f"Arch: {platform.machine()}")
    print(f"Project: {PROJECT_ROOT}")

    binary = ensure_binary()
    staging = create_staging(binary)
    dmg = build_dmg(staging)
    smoke_test(dmg)

    # Cleanup staging
    shutil.rmtree(staging, ignore_errors=True)

    print(f"\nBuild successful: {dmg}")


if __name__ == "__main__":
    main()
