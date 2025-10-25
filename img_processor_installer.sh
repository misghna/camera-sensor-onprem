#!/bin/bash

# All-in-one Installation script for Image Processor systemd service and timer
# This script creates the service and timer files, then installs them

echo "=========================================="
echo "Image Processor Systemd Setup"
echo "=========================================="

# Get the current directory
CURRENT_DIR=$(pwd)
echo "Working directory: $CURRENT_DIR"
echo ""

# Step 1: Create service file
echo "Step 1: Creating service file..."
cat > /tmp/image-processor.service << 'EOF'
[Unit]
Description=Image Processor Service
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/home/ubuntu/camera-sensor-media
ExecStart=/home/ubuntu/camera-sensor-media/myenv/bin/python /home/ubuntu/camera-sensor-media/image_processor.py
StandardOutput=append:/var/log/image_processor.log
StandardError=append:/var/log/image_processor_error.log

[Install]
WantedBy=multi-user.target
EOF

if [ $? -eq 0 ]; then
    echo "✓ Service file created"
else
    echo "✗ Failed to create service file"
    exit 1
fi

# Step 2: Create timer file
echo "Step 2: Creating timer file..."
cat > /tmp/image-processor.timer << 'EOF'
[Unit]
Description=Run Image Processor every 30 minutes
Requires=image-processor.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

if [ $? -eq 0 ]; then
    echo "✓ Timer file created"
else
    echo "✗ Failed to create timer file"
    exit 1
fi

# Step 3: Copy service file to systemd
echo "Step 3: Installing service file..."
sudo cp /tmp/image-processor.service /etc/systemd/system/
if [ $? -eq 0 ]; then
    echo "✓ Service file installed"
else
    echo "✗ Failed to install service file"
    exit 1
fi

# Step 4: Copy timer file to systemd
echo "Step 4: Installing timer file..."
sudo cp /tmp/image-processor.timer /etc/systemd/system/
if [ $? -eq 0 ]; then
    echo "✓ Timer file installed"
else
    echo "✗ Failed to install timer file"
    exit 1
fi

# Step 5: Reload systemd daemon
echo "Step 5: Reloading systemd daemon..."
sudo systemctl daemon-reload
if [ $? -eq 0 ]; then
    echo "✓ Systemd daemon reloaded"
else
    echo "✗ Failed to reload systemd daemon"
    exit 1
fi

# Step 6: Enable the timer
echo "Step 6: Enabling timer..."
sudo systemctl enable image-processor.timer
if [ $? -eq 0 ]; then
    echo "✓ Timer enabled (will start on boot)"
else
    echo "✗ Failed to enable timer"
    exit 1
fi

# Step 7: Start the timer
echo "Step 7: Starting timer..."
sudo systemctl start image-processor.timer
if [ $? -eq 0 ]; then
    echo "✓ Timer started"
else
    echo "✗ Failed to start timer"
    exit 1
fi

# Clean up temporary files
rm /tmp/image-processor.service /tmp/image-processor.timer

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "The image processor will now run:"
echo "  - 5 minutes after boot"
echo "  - Every 30 minutes thereafter"
echo ""
echo "Current timer status:"
sudo systemctl status image-processor.timer --no-pager -l
echo ""
echo "Next scheduled runs:"
sudo systemctl list-timers image-processor.timer --no-pager
echo ""
echo "=========================================="
echo "Useful commands:"
echo "=========================================="
echo "Check timer status:    sudo systemctl status image-processor.timer"
echo "Check service status:  sudo systemctl status image-processor.service"
echo "View logs (live):      sudo journalctl -u image-processor.service -f"
echo "View log file:         sudo tail -f /var/log/image_processor.log"
echo "List all timers:       sudo systemctl list-timers"
echo "Stop timer:            sudo systemctl stop image-processor.timer"
echo "Disable timer:         sudo systemctl disable image-processor.timer"
echo "Run manually now:      sudo systemctl start image-processor.service"
echo ""
