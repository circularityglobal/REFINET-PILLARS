#!/usr/bin/env python3
"""
Build Android .apk for REFInet Pillar.

Usage:
    python build/build_apk.py

Requires: Linux x86_64 with Java 17, Android SDK/NDK (installed by Buildozer).
First build takes ~20 minutes (downloads SDK/NDK). Subsequent builds ~5 min.

Pipeline:
    1. Install Buildozer + dependencies
    2. Prepare build directory (copy pillar source into android build dir)
    3. Run Buildozer to produce .apk
    4. Copy .apk to dist/ with expected filename
    5. Verify .apk exists and report size
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANDROID_DIR = PROJECT_ROOT / "build" / "android"
DIST_DIR = PROJECT_ROOT / "dist"
APK_OUTPUT = DIST_DIR / "refinet-pillar.apk"

# Pillar source packages to copy into the Android build directory
PILLAR_PACKAGES = [
    "core", "crypto", "db", "auth", "mesh", "rpc",
    "cli", "proxy", "integration", "vault", "onboarding",
]


def run(cmd: list, cwd: str = None, **kwargs) -> subprocess.CompletedProcess:
    """Run a command, abort on failure."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, **kwargs)
    if result.returncode != 0:
        print(f"ERROR: command failed (exit {result.returncode})")
        if hasattr(result, "stderr") and result.stderr:
            print(f"  stderr: {result.stderr[:800]}")
        sys.exit(1)
    return result


def install_buildozer() -> None:
    """Install Buildozer and system dependencies."""
    print("[1/5] Installing Buildozer...")
    run([sys.executable, "-m", "pip", "install", "--upgrade",
         "buildozer", "cython"])

    # On Ubuntu, install system deps that Buildozer needs
    if platform.system() == "Linux":
        system_deps = [
            "git", "zip", "unzip", "openjdk-17-jdk",
            "autoconf", "libtool", "pkg-config",
            "zlib1g-dev", "libncurses5-dev", "libncursesw5-dev",
            "libtinfo5", "cmake", "libffi-dev", "libssl-dev",
            "automake",
        ]
        # Check if we can use apt (Ubuntu/Debian)
        if shutil.which("apt-get"):
            print("  Installing system dependencies via apt...")
            subprocess.run(
                ["sudo", "apt-get", "update", "-qq"],
                capture_output=True,
            )
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "-qq"] + system_deps,
                capture_output=True,
            )


def prepare_source() -> None:
    """Copy Pillar source packages into the Android build directory."""
    print("[2/5] Preparing source tree...")

    # Copy pillar.py (main entry point for the daemon)
    src_pillar = PROJECT_ROOT / "pillar.py"
    dst_pillar = ANDROID_DIR / "pillar.py"
    shutil.copy2(src_pillar, dst_pillar)
    print(f"  Copied: pillar.py")

    # Copy each package directory
    for pkg in PILLAR_PACKAGES:
        src = PROJECT_ROOT / pkg
        dst = ANDROID_DIR / pkg
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            py_count = len(list(dst.glob("**/*.py")))
            print(f"  Copied: {pkg}/ ({py_count} files)")
        else:
            print(f"  WARNING: {pkg}/ not found, skipping")

    # Copy gopherroot data directory
    src_gopherroot = PROJECT_ROOT / "gopherroot"
    dst_gopherroot = ANDROID_DIR / "gopherroot"
    if dst_gopherroot.exists():
        shutil.rmtree(dst_gopherroot)
    shutil.copytree(src_gopherroot, dst_gopherroot)
    print(f"  Copied: gopherroot/")


def build_apk() -> Path:
    """Run Buildozer to build the APK."""
    print("[3/5] Building APK with Buildozer (this may take 15-20 minutes)...")

    run(
        ["buildozer", "android", "release"],
        cwd=str(ANDROID_DIR),
    )

    # Find the produced APK
    bin_dir = ANDROID_DIR / "bin"
    apks = list(bin_dir.glob("*.apk")) if bin_dir.exists() else []
    if not apks:
        # Also check for AAB
        apks = list(bin_dir.glob("*.aab")) if bin_dir.exists() else []
    if not apks:
        print("ERROR: Buildozer did not produce an APK")
        print(f"  Checked: {bin_dir}")
        sys.exit(1)

    # Take the first (usually only) APK
    built_apk = apks[0]
    size_mb = built_apk.stat().st_size / (1024 * 1024)
    print(f"  Built: {built_apk.name} ({size_mb:.1f} MB)")
    return built_apk


def copy_output(built_apk: Path) -> Path:
    """Copy APK to dist/ with the expected filename."""
    print("[4/5] Copying to dist/...")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if APK_OUTPUT.exists():
        APK_OUTPUT.unlink()

    shutil.copy2(built_apk, APK_OUTPUT)
    size_mb = APK_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"  Output: {APK_OUTPUT} ({size_mb:.1f} MB)")
    return APK_OUTPUT


def verify(apk: Path) -> None:
    """Basic verification of the APK."""
    print("[5/5] Verifying APK...")

    # Check it's a valid ZIP (APKs are ZIP files)
    import zipfile
    if not zipfile.is_zipfile(str(apk)):
        print("  ERROR: Output is not a valid ZIP/APK file")
        sys.exit(1)
    print("  ZIP structure: valid")

    # List key entries
    with zipfile.ZipFile(str(apk)) as zf:
        names = zf.namelist()
        checks = {
            "AndroidManifest.xml": False,
            "classes.dex": False,
        }
        for name in names:
            for check in checks:
                if check in name:
                    checks[check] = True

        for item, found in checks.items():
            status = "present" if found else "MISSING"
            print(f"  {item}: {status}")

        print(f"  Total entries: {len(names)}")

    print("  Verification: PASSED")


def cleanup() -> None:
    """Remove copied source packages from the Android build directory."""
    print("Cleaning up copied source...")
    for pkg in PILLAR_PACKAGES:
        dst = ANDROID_DIR / pkg
        if dst.exists():
            shutil.rmtree(dst)
    for extra in ["pillar.py", "gopherroot"]:
        p = ANDROID_DIR / extra
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)


def main() -> None:
    system = platform.system()

    if system != "Linux":
        print(f"WARNING: Running on {system} — Buildozer requires Linux x86_64.")
        print("  Will prepare source tree for inspection but cannot build APK.\n")

    print(f"=== REFInet Pillar — Android APK Build ===")
    print(f"Python: {sys.version}")
    print(f"Arch: {platform.machine()}")
    print(f"Project: {PROJECT_ROOT}")

    if system != "Linux":
        prepare_source()
        print(f"\n[3/5] SKIPPED: Buildozer not available on {system}")
        print(f"  Source prepared in: {ANDROID_DIR}")
        print(f"  To build on Linux: python build/build_apk.py")
        # Don't cleanup so user can inspect
        return

    install_buildozer()
    prepare_source()
    built_apk = build_apk()
    apk = copy_output(built_apk)
    verify(apk)
    cleanup()

    print(f"\nBuild successful: {apk}")


if __name__ == "__main__":
    main()
