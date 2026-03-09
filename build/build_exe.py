#!/usr/bin/env python3
"""
Cross-platform build script for REFInet Pillar standalone executable.

Usage:
    python build/build_exe.py

Produces platform-specific binary in dist/:
    Windows: dist/refinet-pillar-setup.exe
    macOS:   dist/refinet-pillar.dmg   (future)
    Linux:   dist/refinet-pillar.AppImage (future)
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = PROJECT_ROOT / "build" / "refinet-pillar.spec"
DIST_DIR = PROJECT_ROOT / "dist"
WORK_DIR = PROJECT_ROOT / "build" / "temp"


def run(cmd: list, **kwargs) -> None:
    """Run a command, abort on failure."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"ERROR: command failed with exit code {result.returncode}")
        sys.exit(1)


def install_deps() -> None:
    """Install PyInstaller and project dependencies."""
    print("\n[1/4] Installing dependencies...")
    run([sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"])
    run([sys.executable, "-m", "pip", "install", "-r",
         str(PROJECT_ROOT / "requirements.txt"), "--quiet"])

    # Optional extras — best-effort
    print("[2/4] Installing optional extras (best-effort)...")
    for pkg in ["eth-account", "websockets", "qrcode[pil]", "stem"]:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
            capture_output=True,
        )


def build() -> Path:
    """Run PyInstaller and return the output path."""
    print("[3/4] Running PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--distpath", str(DIST_DIR),
        "--workpath", str(WORK_DIR),
        "--clean",
        "--noconfirm",
    ])

    # Determine expected output name
    system = platform.system()
    if system == "Windows":
        exe = DIST_DIR / "refinet-pillar-setup.exe"
    else:
        exe = DIST_DIR / "refinet-pillar-setup"

    if not exe.exists():
        print(f"ERROR: Expected output not found at {exe}")
        sys.exit(1)

    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"  Output: {exe} ({size_mb:.1f} MB)")
    return exe


def smoke_test(exe: Path) -> None:
    """Verify the binary starts and responds to --help."""
    print("[4/4] Smoke test...")
    result = subprocess.run(
        [str(exe), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        print("  Smoke test PASSED")
    else:
        print(f"  Smoke test FAILED (exit {result.returncode})")
        print(f"  stdout: {result.stdout[:500]}")
        print(f"  stderr: {result.stderr[:500]}")
        sys.exit(1)


def main() -> None:
    system = platform.system()
    print(f"=== REFInet Pillar Build — {system} {platform.machine()} ===")
    print(f"Python: {sys.version}")
    print(f"Project: {PROJECT_ROOT}")

    install_deps()
    exe = build()
    smoke_test(exe)

    print(f"\nBuild successful: {exe}")


if __name__ == "__main__":
    main()
