#!/bin/bash

# Image Server Service Uninstallation Script

set -e

echo "================================================"
echo "Image Server Service Uninstallation"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

SYSTEMD_PATH="/etc/systemd/system/image-server.service"

# Check if service exists
if [ ! -f "$SYSTEMD_PATH" ]; then
    echo "Service file not found. Nothing to uninstall."
    exit 0
fi

# Stop the service if it's running
if systemctl is-active --quiet image-server; then
    echo "Stopping service..."
    systemctl stop image-server
    echo "✓ Service stopped"
fi

# Disable the service
if systemctl is-enabled --quiet image-server 2>/dev/null; then
    echo "Disabling service..."
    systemctl disable image-server
    echo "✓ Service disabled"
fi

# Remove service file
echo "Removing service file..."
rm -f "$SYSTEMD_PATH"
echo "✓ Service file removed"
echo ""

# Reload systemd daemon
echo "Reloading systemd daemon..."
systemctl daemon-reload
systemctl reset-failed
echo "✓ Daemon reloaded"
echo ""

echo "================================================"
echo "Uninstallation Complete!"
echo "================================================"
echo ""
echo "Note: Log files were not removed:"
echo "  - /var/log/image-server.log"
echo "  - /var/log/image-server-error.log"
echo ""
echo "You can remove them manually if needed:"
echo "  sudo rm -f /var/log/image-server*.log"
echo "================================================"
