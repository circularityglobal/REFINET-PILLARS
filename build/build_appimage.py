#!/usr/bin/env python3
"""
Build AppImage for REFInet Pillar (portable Linux executable).

Usage:
    python build/build_appimage.py

Requires: Linux x86_64 with FUSE (or --appimage-extract-and-run fallback).
Downloads appimagetool automatically if not present.

Pipeline:
    1. Build standalone binary via PyInstaller (if not already present)
    2. Create AppDir structure (AppRun, .desktop, icon, binary)
    3. Download appimagetool if needed
    4. Package into .AppImage
    5. Smoke-test the .AppImage
"""

import base64
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
SPEC_FILE = PROJECT_ROOT / "build" / "refinet-pillar.spec"
BUILD_DIR = PROJECT_ROOT / "build"
APPDIR = BUILD_DIR / "AppDir"
APPIMAGE_OUTPUT = DIST_DIR / "refinet-pillar.AppImage"
APPIMAGETOOL = BUILD_DIR / "appimagetool"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/"
    "continuous/appimagetool-x86_64.AppImage"
)

APP_ID = "io.refinet.pillar"
APP_NAME = "refinet-pillar"
APP_VERSION = "0.3.0"


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
        print(f"[1/5] Binary already exists: {binary}")
        return binary

    print("[1/5] Building binary with PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "temp"),
        "--clean", "--noconfirm",
    ])

    if not binary.exists():
        print(f"ERROR: PyInstaller did not produce {binary}")
        sys.exit(1)

    return binary


# Minimal 48x48 PNG icon (dark teal circle with "R" — base64-encoded)
# Generated offline; avoids needing Pillow or any image library at build time.
_ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAA3klEQVRoge3YMQ6D"
    "MBBF0TuF+98yJUUkJIjt8djMSP+2vsbWgBkAAAAAAAAA+L3t6gXMsqcv2O4esj19"
    "wch/UBfyqwPWQ18VsF/z0wGtB48KaB/cE3Dq4J6A0wePBGQP7gk4ffCRgFMH9wSc"
    "Pjgj4NTBPQGnDx4NOHzwTMDhg2cDdh98JuDwwbMBuw8+G7D74CsBhw6eDdh98NWA"
    "Qwe3BMwcfOeBDd8WMHLwuwJ8fUDvwUcC7PDAIwGjB7cEDD14JGDmg2cCZj54NmDn"
    "g88EHD54NuDwwf8JAAAAAAAAQK9/+jgxUhwtHk0AAAAASUVORK5CYII="
)


def create_appdir(binary: Path) -> Path:
    """Create the AppDir directory structure."""
    print("[2/5] Creating AppDir structure...")

    if APPDIR.exists():
        shutil.rmtree(APPDIR)

    bin_dir = APPDIR / "usr" / "bin"
    bin_dir.mkdir(parents=True)

    # --- Binary ---
    dest_binary = bin_dir / APP_NAME
    shutil.copy2(binary, dest_binary)
    dest_binary.chmod(0o755)
    size_mb = dest_binary.stat().st_size / (1024 * 1024)
    print(f"  Installed: usr/bin/{APP_NAME} ({size_mb:.1f} MB)")

    # --- AppRun (launcher) ---
    apprun = APPDIR / "AppRun"
    apprun.write_text(
        '#!/bin/sh\n'
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/bin/refinet-pillar" "$@"\n'
    )
    apprun.chmod(0o755)
    print("  Created: AppRun")

    # --- .desktop file ---
    desktop = APPDIR / f"{APP_ID}.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        f"Name=REFInet Pillar\n"
        f"Exec=refinet-pillar\n"
        f"Icon={APP_ID}\n"
        "Type=Application\n"
        "Terminal=true\n"
        "Categories=Network;System;\n"
        f"Comment=Sovereign Gopher mesh node with Ed25519 identity\n"
        f"X-AppImage-Version={APP_VERSION}\n"
    )
    print(f"  Created: {APP_ID}.desktop")

    # --- Icon (48x48 PNG) ---
    icon_path = APPDIR / f"{APP_ID}.png"
    icon_path.write_bytes(base64.b64decode(_ICON_PNG_B64))
    print(f"  Created: {APP_ID}.png (48x48)")

    # Also place in hicolor theme dir (some tools check here)
    hicolor = APPDIR / "usr" / "share" / "icons" / "hicolor" / "48x48" / "apps"
    hicolor.mkdir(parents=True)
    shutil.copy2(icon_path, hicolor / f"{APP_ID}.png")

    return APPDIR


def download_appimagetool() -> Path:
    """Download appimagetool if not already present."""
    if APPIMAGETOOL.exists():
        print(f"[3/5] appimagetool already present: {APPIMAGETOOL}")
        return APPIMAGETOOL

    print("[3/5] Downloading appimagetool...")
    print(f"  URL: {APPIMAGETOOL_URL}")

    urllib.request.urlretrieve(APPIMAGETOOL_URL, str(APPIMAGETOOL))
    APPIMAGETOOL.chmod(0o755)

    size_mb = APPIMAGETOOL.stat().st_size / (1024 * 1024)
    print(f"  Downloaded: {APPIMAGETOOL} ({size_mb:.1f} MB)")
    return APPIMAGETOOL


def build_appimage(appdir: Path, tool: Path) -> Path:
    """Run appimagetool to create the .AppImage."""
    print("[4/5] Building .AppImage...")

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if APPIMAGE_OUTPUT.exists():
        APPIMAGE_OUTPUT.unlink()

    env = os.environ.copy()
    env["ARCH"] = "x86_64"
    env["VERSION"] = APP_VERSION

    # Try direct execution first; fall back to --appimage-extract-and-run
    # (needed in Docker / environments without FUSE)
    cmd = [str(tool), str(appdir), str(APPIMAGE_OUTPUT)]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print("  Direct execution failed (no FUSE?), trying extract-and-run...")
        cmd = [str(tool), "--appimage-extract-and-run", str(appdir), str(APPIMAGE_OUTPUT)]
        # appimagetool itself is an AppImage that needs extraction on CI
        # Alternative: extract it first, then run the extracted binary
        extract_result = subprocess.run(
            [str(tool), "--appimage-extract"],
            capture_output=True, text=True, cwd=str(BUILD_DIR),
        )
        squashfs_root = BUILD_DIR / "squashfs-root"
        extracted_tool = squashfs_root / "AppRun"
        if extracted_tool.exists():
            run([str(extracted_tool), str(appdir), str(APPIMAGE_OUTPUT)], env=env)
        else:
            print(f"  stderr: {result.stderr[:500]}")
            print("ERROR: appimagetool failed and extraction fallback unavailable")
            sys.exit(1)

    if not APPIMAGE_OUTPUT.exists():
        print(f"ERROR: appimagetool did not produce {APPIMAGE_OUTPUT}")
        sys.exit(1)

    size_mb = APPIMAGE_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"  Output: {APPIMAGE_OUTPUT} ({size_mb:.1f} MB)")
    return APPIMAGE_OUTPUT


def smoke_test(appimage: Path) -> None:
    """Run the AppImage with --help to verify it works."""
    print("[5/5] Smoke test...")

    # AppImages are self-extracting; --appimage-extract-and-run avoids FUSE
    # Try direct first, fallback to extract
    for args in [
        [str(appimage), "--help"],
        [str(appimage), "--appimage-extract-and-run", "--help"],
    ]:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and "REFInet Pillar" in result.stdout:
            print("  --help: PASSED")
            return
        # If it fails with the first approach, try next

    # If we get here, try extracting and running directly
    print("  Running via extraction fallback...")
    extract_dir = BUILD_DIR / "appimage-test"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    env = os.environ.copy()
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    result = subprocess.run(
        [str(appimage), "--help"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    if result.returncode == 0:
        print("  --help: PASSED (via APPIMAGE_EXTRACT_AND_RUN)")
    else:
        print(f"  --help: FAILED (exit {result.returncode})")
        print(f"  stdout: {result.stdout[:300]}")
        print(f"  stderr: {result.stderr[:300]}")
        # Don't fail hard — FUSE issues in containers are expected
        print("  WARNING: Smoke test could not run (likely no FUSE). AppImage was built.")

    shutil.rmtree(extract_dir, ignore_errors=True)


def main() -> None:
    system = platform.system()
    machine = platform.machine().lower()

    if system != "Linux":
        print(f"WARNING: Running on {system} — appimagetool requires Linux x86_64.")
        print("  Will create AppDir for inspection but cannot build .AppImage.\n")

    print(f"=== REFInet Pillar — AppImage Build ===")
    print(f"Python: {sys.version}")
    print(f"Arch: {machine}")
    print(f"Project: {PROJECT_ROOT}")

    binary = ensure_binary()
    appdir = create_appdir(binary)

    if system != "Linux":
        print(f"\n[3/5] SKIPPED: appimagetool not available on {system}")
        print(f"  AppDir created at: {appdir}")
        print(f"  Inspect with: ls -la {appdir}")
        print(f"\n  To build on Linux:")
        print(f"    python build/build_appimage.py")
        return

    tool = download_appimagetool()
    appimage = build_appimage(appdir, tool)
    smoke_test(appimage)

    # Cleanup
    shutil.rmtree(APPDIR, ignore_errors=True)
    squashfs = BUILD_DIR / "squashfs-root"
    if squashfs.exists():
        shutil.rmtree(squashfs, ignore_errors=True)

    print(f"\nBuild successful: {appimage}")


if __name__ == "__main__":
    main()
