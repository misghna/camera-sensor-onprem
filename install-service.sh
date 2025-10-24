#!/bin/bash

# Image Server Service Installation Script
# This script sets up the image server to run as a systemd service

set -e

echo "================================================"
echo "Image Server Service Installation"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Define paths
SERVICE_FILE="image-server.service"
SYSTEMD_PATH="/etc/systemd/system/image-server.service"
SERVER_PATH="/home/ubuntu/camera-sensor-media/server.py"
VENV_PATH="/home/ubuntu/camera-sensor-media/myenv"

# Verify files exist
echo "Checking prerequisites..."
if [ ! -f "$SERVER_PATH" ]; then
    echo "ERROR: server.py not found at $SERVER_PATH"
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtual environment not found at $VENV_PATH"
    exit 1
fi

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: Service file not found: $SERVICE_FILE"
    echo "Please make sure image-server.service is in the current directory"
    exit 1
fi

echo "✓ All prerequisites found"
echo ""

# Stop the service if it's already running
if systemctl is-active --quiet image-server; then
    echo "Stopping existing service..."
    systemctl stop image-server
    echo "✓ Service stopped"
fi

# Copy service file to systemd directory
echo "Installing service file..."
cp "$SERVICE_FILE" "$SYSTEMD_PATH"
chmod 644 "$SYSTEMD_PATH"
echo "✓ Service file installed to $SYSTEMD_PATH"
echo ""

# Reload systemd daemon
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Daemon reloaded"
echo ""

# Enable service to start on boot
echo "Enabling service to start on boot..."
systemctl enable image-server
echo "✓ Service enabled"
echo ""

# Start the service
echo "Starting image-server service..."
systemctl start image-server
echo "✓ Service started"
echo ""

# Wait a moment for service to initialize
sleep 2

# Check service status
echo "================================================"
echo "Service Status:"
echo "================================================"
systemctl status image-server --no-pager
echo ""

# Show useful commands
echo "================================================"
echo "Installation Complete!"
echo "================================================"
echo ""
echo "Useful commands:"
echo "  View status:        sudo systemctl status image-server"
echo "  Stop service:       sudo systemctl stop image-server"
echo "  Start service:      sudo systemctl start image-server"
echo "  Restart service:    sudo systemctl restart image-server"
echo "  View logs:          sudo journalctl -u image-server -f"
echo "  View output logs:   sudo tail -f /var/log/image-server.log"
echo "  View error logs:    sudo tail -f /var/log/image-server-error.log"
echo "  Disable service:    sudo systemctl disable image-server"
echo ""
echo "The service will now automatically start on system boot."
echo "================================================"
