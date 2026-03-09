#!/usr/bin/env bash
# REFInet Pillar — One-line installer
# Usage: curl -fsSL https://get.refinet.network/install.sh | bash
set -euo pipefail

REFINET_VERSION="0.2.0"
INSTALL_DIR="${REFINET_INSTALL_DIR:-$HOME/.refinet/pillar}"
REPO="https://github.com/refinet/pillar"

echo ""
echo "REFInet Pillar Installer v${REFINET_VERSION}"
echo "=========================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3.9+ is required but python3 was not found."
    echo "Install Python: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
    echo "ERROR: Python 3.9+ required, found ${PYTHON_VERSION}"
    exit 1
fi
echo "Python: ${PYTHON_VERSION} OK"

# Check pip
if ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip3 is required but was not found."
    echo "Install pip: python3 -m ensurepip --upgrade"
    exit 1
fi
echo "pip3: OK"

# Show what will happen
echo ""
echo "This will:"
echo "  1. Download REFInet Pillar v${REFINET_VERSION} from GitHub"
echo "  2. Verify SHA-256 checksum"
echo "  3. Install to ${INSTALL_DIR}"
echo "  4. Install Python dependencies"
echo ""

# Download
TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

echo "Downloading REFInet Pillar v${REFINET_VERSION}..."
if ! curl -fsSL "${REPO}/archive/refs/tags/v${REFINET_VERSION}.tar.gz" \
    -o "${TMPDIR}/refinet-pillar.tar.gz"; then
    echo "ERROR: Download failed. Check your internet connection."
    exit 1
fi
echo "Download complete."

# Verify checksum (if available)
CHECKSUM_URL="${REPO}/releases/download/v${REFINET_VERSION}/CHECKSUMS.txt"
if curl -fsSL "${CHECKSUM_URL}" -o "${TMPDIR}/CHECKSUMS.txt" 2>/dev/null; then
    EXPECTED_SHA=$(grep "refinet-pillar-v${REFINET_VERSION}.tar.gz" "${TMPDIR}/CHECKSUMS.txt" | awk '{print $1}' || true)
    if [ -n "${EXPECTED_SHA}" ]; then
        if command -v sha256sum &>/dev/null; then
            ACTUAL_SHA=$(sha256sum "${TMPDIR}/refinet-pillar.tar.gz" | cut -d' ' -f1)
        elif command -v shasum &>/dev/null; then
            ACTUAL_SHA=$(shasum -a 256 "${TMPDIR}/refinet-pillar.tar.gz" | cut -d' ' -f1)
        else
            echo "Warning: No sha256sum or shasum found, skipping verification."
            ACTUAL_SHA="${EXPECTED_SHA}"
        fi
        if [ "${EXPECTED_SHA}" != "${ACTUAL_SHA}" ]; then
            echo "ERROR: Checksum mismatch! Download may be corrupted or tampered with."
            echo "  Expected: ${EXPECTED_SHA}"
            echo "  Actual:   ${ACTUAL_SHA}"
            exit 1
        fi
        echo "Checksum verified OK"
    fi
else
    echo "Note: Checksum file not available, skipping verification."
fi

# Install
echo "Installing to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
tar -xzf "${TMPDIR}/refinet-pillar.tar.gz" -C "${INSTALL_DIR}" --strip-components=1
chmod +x "${INSTALL_DIR}/pillar.py"

# Install Python dependencies
echo "Installing Python dependencies..."
cd "${INSTALL_DIR}"
pip3 install --user -r requirements.txt

# Ensure ~/.local/bin is on PATH
LOCAL_BIN="${HOME}/.local/bin"
if [ -d "${LOCAL_BIN}" ] && ! echo "${PATH}" | grep -q "${LOCAL_BIN}"; then
    echo ""
    echo "Note: ${LOCAL_BIN} is not in your PATH."
    echo "Add it by running:"
    echo "  export PATH=\"${LOCAL_BIN}:\${PATH}\""
    echo "Or add this line to your ~/.bashrc or ~/.zshrc for persistence."
fi

echo ""
echo "=========================================="
echo "REFInet Pillar installed to ${INSTALL_DIR}"
echo "=========================================="
echo ""
echo "Start your Pillar:"
echo "  cd ${INSTALL_DIR} && python3 pillar.py"
echo ""
echo "Check status:"
echo "  cd ${INSTALL_DIR} && python3 pillar.py --status"
echo ""
echo "Or install as a system service (Linux):"
echo "  sudo bash ${INSTALL_DIR}/deploy/install.sh"
echo ""
echo "Documentation: https://docs.refinet.network"
echo "Gopherspace:   gopher://pillar.refinet.network:7070"
echo ""
