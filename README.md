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

## Troubleshooting

### Service Won't Start

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

### Service Keeps Restarting

Check the error logs:
```bash
sudo tail -100 /var/log/image-server-error.log
```

### Permission Issues

Ensure the service has access to required directories:
```bash
ls -la /home/ubuntu/camera-sensor-media/
ls -la /mnt/disk*/media
```

### Database Connection Issues

Verify the credentials.ini file exists and has correct permissions:
```bash
ls -la /home/ubuntu/camera-sensor-media/credentials.ini
```

## Uninstallation

### Using the Uninstall Script
```bash
cd /home/ubuntu/camera-sensor-media
chmod +x uninstall-service.sh
sudo ./uninstall-service.sh
```

### Manual Uninstallation
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

The service is configured with the following features:

- **Auto-restart**: If the server crashes, it will automatically restart after 10 seconds
- **Start on boot**: The service starts automatically when the system boots
- **Logging**: Output is logged to `/var/log/image-server.log` and errors to `/var/log/image-server-error.log`
- **Dependencies**: Waits for network and MySQL to be available before starting
- **Working Directory**: Set to `/home/ubuntu/camera-sensor-media`
- **User**: Runs as root (since you were using sudo before)

## Modifying the Service

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

## Log Rotation

To prevent log files from growing too large, you may want to set up log rotation:

```bash
sudo nano /etc/logrotate.d/image-server
```

Add the following content:
```
/var/log/image-server*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

## Verifying the Service After Reboot

After a system reboot, verify the service started automatically:

```bash
# Check if service is running
sudo systemctl status image-server

# Check if it's enabled to start on boot
sudo systemctl is-enabled image-server

# View logs since boot
sudo journalctl -u image-server -b
```

## Port Configuration

The service runs on port 8080 by default. If you need to change this:

1. Set the PORT environment variable in the service file
2. Or modify the port in your server.py file

## Security Notes

- The service runs as root (as you were doing before with sudo)
- Consider running as a non-privileged user if possible for better security
- The service has `NoNewPrivileges=true` to prevent privilege escalation
- Private tmp directory is enabled for additional isolation

## Support

If you encounter issues:
1. Check the service status and logs
2. Verify all file paths are correct
3. Ensure MySQL is running and accessible
4. Test the server manually to isolate the issue

---

**Note**: Make sure to have your `credentials.ini` file in the `/home/ubuntu/camera-sensor-media/` directory before starting the service.
