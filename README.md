# Image Server Systemd Service Setup

This guide will help you set up the image server to run automatically as a systemd service, ensuring it starts on boot and restarts automatically if it crashes.

## Files Included

1. **image-server.service** - Systemd service configuration file
2. **install-service.sh** - Automated installation script
3. **uninstall-service.sh** - Automated uninstallation script
4. **README.md** - This file

## Quick Installation

### Step 1: Stop your currently running server
```bash
# If you're running the server manually, press Ctrl+C to stop it
# Or if it's running in the background, find and kill the process
ps aux | grep server.py
sudo kill <PID>
```

### Step 2: Make the installation script executable
```bash
cd /home/ubuntu/camera-sensor-media
chmod +x install-service.sh
```

### Step 3: Run the installation script
```bash
sudo ./install-service.sh
```

That's it! The service is now installed and running.

## Manual Installation (Alternative Method)

If you prefer to install manually:

```bash
# 1. Copy the service file to systemd directory
sudo cp image-server.service /etc/systemd/system/

# 2. Set correct permissions
sudo chmod 644 /etc/systemd/system/image-server.service

# 3. Reload systemd daemon
sudo systemctl daemon-reload

# 4. Enable service to start on boot
sudo systemctl enable image-server

# 5. Start the service
sudo systemctl start image-server

# 6. Check status
sudo systemctl status image-server
```

## Service Management Commands

### Check Service Status
```bash
sudo systemctl status image-server
```

### Start the Service
```bash
sudo systemctl start image-server
```

### Stop the Service
```bash
sudo systemctl stop image-server
```

### Restart the Service
```bash
sudo systemctl restart image-server
```

### Enable Service (start on boot)
```bash
sudo systemctl enable image-server
```

### Disable Service (don't start on boot)
```bash
sudo systemctl disable image-server
```

## Viewing Logs

### View Real-time Service Logs (systemd journal)
```bash
sudo journalctl -u image-server -f
```

### View Last 100 Lines of Logs
```bash
sudo journalctl -u image-server -n 100
```

### View Application Output Logs
```bash
sudo tail -f /var/log/image-server.log
```

### View Application Error Logs
```bash
sudo tail -f /var/log/image-server-error.log
```

### View Logs Since Today
```bash
sudo journalctl -u image-server --since today
```

### View Logs for Specific Time Period
```bash
sudo journalctl -u image-server --since "2025-10-24 10:00:00" --until "2025-10-24 12:00:00"
```

---

# Image Processor Systemd Timer Setup

In addition to the image server service, you can set up the image processor to run automatically every 30 minutes.

## Quick Installation - Image Processor Timer

### Option 1: Using the All-in-One Installation Script

```bash
cd /home/ubuntu/camera-sensor-media
chmod +x img_processor_installer.sh
./img_processor_installer.sh
```

### Option 2: Direct Command Installation

Copy and paste this entire block into your terminal:

```bash
# Create service file
sudo tee /etc/systemd/system/image-processor.service > /dev/null << 'EOF'
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

# Create timer file
sudo tee /etc/systemd/system/image-processor.timer > /dev/null << 'EOF'
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

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable image-processor.timer
sudo systemctl start image-processor.timer

# Check status
sudo systemctl status image-processor.timer
```

## Image Processor Timer Configuration

The image processor timer is configured to:
- **First run**: 5 minutes after system boot
- **Recurring**: Every 30 minutes after each execution
- **Persistent**: If a run is missed (system was off), it will run immediately when system starts
- **Logs**: Output saved to `/var/log/image_processor.log` and errors to `/var/log/image_processor_error.log`

## Image Processor Management Commands

### Check Timer Status
```bash
sudo systemctl status image-processor.timer
```

### Check Service Status
```bash
sudo systemctl status image-processor.service
```

### List All Timers (see next scheduled run)
```bash
sudo systemctl list-timers
# Or specifically for image processor:
sudo systemctl list-timers image-processor.timer
```

### Run Image Processor Manually (Right Now)
```bash
sudo systemctl start image-processor.service
```

### Stop the Timer
```bash
sudo systemctl stop image-processor.timer
```

### Restart the Timer
```bash
sudo systemctl restart image-processor.timer
```

### Disable Timer (won't start on boot)
```bash
sudo systemctl disable image-processor.timer
```

### Enable Timer (will start on boot)
```bash
sudo systemctl enable image-processor.timer
```

## Image Processor Logs

### View Real-time Logs (systemd journal)
```bash
sudo journalctl -u image-processor.service -f
```

### View Last 50 Lines of Service Logs
```bash
sudo journalctl -u image-processor.service -n 50
```

### View Application Output Log File
```bash
sudo tail -f /var/log/image_processor.log
```

### View Application Error Log File
```bash
sudo tail -f /var/log/image_processor_error.log
```

### View Last 100 Lines of Log File
```bash
sudo tail -100 /var/log/image_processor.log
```

## Changing Image Processor Schedule

To run at different intervals, edit the timer file:

```bash
sudo nano /etc/systemd/system/image-processor.timer
```

Change `OnUnitActiveSec=30min` to:
- `15min` - Run every 15 minutes
- `1h` - Run every hour
- `2h` - Run every 2 hours
- `6h` - Run every 6 hours

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart image-processor.timer
```

## Verifying Image Processor After Installation

```bash
# Check if timer is active and enabled
sudo systemctl is-active image-processor.timer
sudo systemctl is-enabled image-processor.timer

# See when it will run next
sudo systemctl list-timers image-processor.timer

# Test it manually right now
sudo systemctl start image-processor.service

# Check if it ran successfully
sudo systemctl status image-processor.service

# View the output
sudo tail -20 /var/log/image_processor.log
```

## Uninstalling Image Processor Timer

```bash
# Stop and disable timer
sudo systemctl stop image-processor.timer
sudo systemctl disable image-processor.timer

# Remove service and timer files
sudo rm /etc/systemd/system/image-processor.service
sudo rm /etc/systemd/system/image-processor.timer

# Reload systemd
sudo systemctl daemon-reload
```

---

## Troubleshooting

### Image Server Issues

#### Service Won't Start

1. **Check the service status for error messages:**
   ```bash
   sudo systemctl status image-server
   ```

2. **View detailed logs:**
   ```bash
   sudo journalctl -u image-server -n 50 --no-pager
   ```

3. **Verify file paths in the service file:**
   ```bash
   cat /etc/systemd/system/image-server.service
   ```

4. **Test the server manually:**
   ```bash
   cd /home/ubuntu/camera-sensor-media
   sudo /home/ubuntu/camera-sensor-media/myenv/bin/python server.py
   ```

#### Service Keeps Restarting

Check the error logs:
```bash
sudo tail -100 /var/log/image-server-error.log
```

#### Permission Issues

Ensure the service has access to required directories:
```bash
ls -la /home/ubuntu/camera-sensor-media/
ls -la /mnt/disk*/media
```

#### Database Connection Issues

Verify the credentials.ini file exists and has correct permissions:
```bash
ls -la /home/ubuntu/camera-sensor-media/credentials.ini
```

### Image Processor Issues

#### Timer Not Running

```bash
# Check if timer is active
sudo systemctl is-active image-processor.timer

# Check timer status
sudo systemctl status image-processor.timer

# View timer logs
sudo journalctl -u image-processor.timer -n 20
```

#### Service Failing

```bash
# Check service logs
sudo journalctl -u image-processor.service -n 50

# View error log
sudo tail -50 /var/log/image_processor_error.log

# Test manually
cd /home/ubuntu/camera-sensor-media
sudo /home/ubuntu/camera-sensor-media/myenv/bin/python image_processor.py
```

#### Timer Shows as "n/a" for Next Run

This is normal immediately after starting. Wait a moment and check again:
```bash
sudo systemctl list-timers image-processor.timer
```

## Uninstallation

### Uninstalling Image Server

#### Using the Uninstall Script
```bash
cd /home/ubuntu/camera-sensor-media
chmod +x uninstall-service.sh
sudo ./uninstall-service.sh
```

#### Manual Uninstallation
```bash
# Stop and disable the service
sudo systemctl stop image-server
sudo systemctl disable image-server

# Remove the service file
sudo rm /etc/systemd/system/image-server.service

# Reload systemd
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

## Service Configuration Details

### Image Server Service

The service is configured with the following features:

- **Auto-restart**: If the server crashes, it will automatically restart after 10 seconds
- **Start on boot**: The service starts automatically when the system boots
- **Logging**: Output is logged to `/var/log/image-server.log` and errors to `/var/log/image-server-error.log`
- **Dependencies**: Waits for network and MySQL to be available before starting
- **Working Directory**: Set to `/home/ubuntu/camera-sensor-media`
- **User**: Runs as root (since you were using sudo before)

### Image Processor Timer

The timer is configured with:

- **Type**: oneshot (runs once then exits, doesn't stay running)
- **Schedule**: Every 30 minutes after the last execution completed
- **Boot behavior**: Runs 5 minutes after system boot
- **Persistent**: Catches up on missed runs if system was powered off
- **Logging**: Output logged to `/var/log/image_processor.log` and errors to `/var/log/image_processor_error.log`

## Modifying the Services

### Modifying Image Server Service

If you need to modify the service configuration:

1. Edit the service file:
   ```bash
   sudo nano /etc/systemd/system/image-server.service
   ```

2. Reload the systemd daemon:
   ```bash
   sudo systemctl daemon-reload
   ```

3. Restart the service:
   ```bash
   sudo systemctl restart image-server
   ```

### Modifying Image Processor Timer/Service

1. Edit the timer or service file:
   ```bash
   sudo nano /etc/systemd/system/image-processor.timer
   # or
   sudo nano /etc/systemd/system/image-processor.service
   ```

2. Reload and restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart image-processor.timer
   ```

## Log Rotation

To prevent log files from growing too large, set up log rotation:

```bash
sudo nano /etc/logrotate.d/camera-media-services
```

Add the following content:
```
/var/log/image-server*.log
/var/log/image_processor*.log
{
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

Test the configuration:
```bash
sudo logrotate -d /etc/logrotate.d/camera-media-services
```

## Verifying Services After Reboot

After a system reboot, verify both services:

```bash
# Check image server
sudo systemctl status image-server
sudo systemctl is-enabled image-server

# Check image processor timer
sudo systemctl status image-processor.timer
sudo systemctl is-enabled image-processor.timer

# View all active timers
sudo systemctl list-timers

# View logs since boot
sudo journalctl -u image-server -b
sudo journalctl -u image-processor.service -b
```

## Port Configuration

The image server runs on port 8080 by default. If you need to change this:

1. Set the PORT environment variable in the service file
2. Or modify the port in your server.py file

## Security Notes

- Both services run as root (as you were doing before with sudo)
- Consider running as a non-privileged user if possible for better security
- The image server service has `NoNewPrivileges=true` to prevent privilege escalation
- Private tmp directory is enabled for additional isolation

## Quick Reference

### All Services Status at a Glance
```bash
sudo systemctl status image-server image-processor.timer image-processor.service
```

### View All Logs Together
```bash
sudo journalctl -u image-server -u image-processor.service -f
```

### Restart Everything
```bash
sudo systemctl restart image-server
sudo systemctl restart image-processor.timer
```

## Support

If you encounter issues:
1. Check the service/timer status and logs
2. Verify all file paths are correct
3. Ensure MySQL is running and accessible
4. Test the scripts manually to isolate the issue
5. Check system resources (disk space, memory)

---

**Note**: Make sure to have your `credentials.ini` file in the `/home/ubuntu/camera-sensor-media/` directory before starting the services.
