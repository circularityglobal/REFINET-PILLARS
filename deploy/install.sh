#!/bin/bash
# REFInet Pillar — Systemd Installation Script
#
# Installs the Pillar as a systemd service for 24/7 operation.
# Run as root: sudo bash deploy/install.sh

set -e

INSTALL_DIR="/opt/refinet"
SERVICE_FILE="/etc/systemd/system/refinet-pillar.service"
USER="refinet"

echo "REFInet Pillar — Service Installation"
echo "======================================"

# Create service user if not exists
if ! id "$USER" &>/dev/null; then
    echo "Creating user: $USER"
    useradd --system --create-home --shell /usr/sbin/nologin "$USER"
fi

# Copy application files
echo "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r . "$INSTALL_DIR/"
chown -R "$USER:$USER" "$INSTALL_DIR"

# Create data directory
echo "Creating data directory"
mkdir -p "/home/$USER/.refinet"
chown -R "$USER:$USER" "/home/$USER/.refinet"

# Install Python dependencies
echo "Installing Python dependencies"
pip3 install -r "$INSTALL_DIR/requirements.txt"

# Install systemd service
echo "Installing systemd service"
cp deploy/refinet-pillar.service "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable refinet-pillar.service

echo ""
echo "Installation complete!"
echo ""
echo "Commands:"
echo "  sudo systemctl start refinet-pillar    # Start the Pillar"
echo "  sudo systemctl stop refinet-pillar     # Stop the Pillar"
echo "  sudo systemctl status refinet-pillar   # Check status"
echo "  sudo journalctl -u refinet-pillar -f   # View logs"
echo ""
