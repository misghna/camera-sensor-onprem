import requests
import mysql.connector
from datetime import datetime
from configparser import ConfigParser

def get_config():
    config = ConfigParser()
    config.read('credentials.ini')
    return config

def get_db_connection():
    config = get_config()
    return mysql.connector.connect(
        host=config.get('database', 'db_host'),
        database=config.get('database', 'db_name'),
        user=config.get('database', 'db_user'),
        password=config.get('database', 'db_password'),
        port=config.getint('database', 'db_port')
    )

def send_slack_alert(message: str) -> bool:
    config = get_config()
    webhook_url = config.get('slack', 'webhook_url')
    
    try:
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        print(f"Slack response: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Slack error: {e}")
        return False

def check_and_insert_new_alarms():
    """Insert new alarms for overdue devices."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    insert_query = """
    INSERT INTO device_alarms (device_id, alarm_description, alarm_type, issue_start_time, last_alarm_sent_time)
    WITH ranked_snapshots AS (
        SELECT 
            device_id,
            time,
            ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY time DESC) as rn
        FROM snapshot
        WHERE time IS NOT NULL
          AND preset_id = 1
    ),
    device_intervals AS (
        SELECT 
            r1.device_id,
            r1.time as last_snapshot_time,
            r2.time as prev_snapshot_time,
            (r1.time - r2.time) as normal_interval_ms
        FROM ranked_snapshots r1
        JOIN ranked_snapshots r2 ON r1.device_id = r2.device_id AND r2.rn = 2
        WHERE r1.rn = 1
    ),
    overdue_devices AS (
        SELECT 
            device_id,
            last_snapshot_time,
            ROUND(normal_interval_ms / 1000 / 3600, 2) as normal_interval_hours,
            ROUND((UNIX_TIMESTAMP() * 1000 - last_snapshot_time) / 1000 / 3600, 2) as hours_since_last
        FROM device_intervals
        WHERE 
            last_snapshot_time > (UNIX_TIMESTAMP() - 3 * 24 * 3600) * 1000
            AND (UNIX_TIMESTAMP() * 1000 - last_snapshot_time) > (2 * normal_interval_ms)
    )
    SELECT 
        od.device_id,
        CONCAT('Snapshot missing - last seen ', od.hours_since_last, ' hours ago (normal interval: ', od.normal_interval_hours, ' hours)'),
        'snapshot_missing',
        FROM_UNIXTIME(od.last_snapshot_time / 1000),
        NOW()
    FROM overdue_devices od
    LEFT JOIN device_alarms da 
        ON od.device_id = da.device_id 
        AND da.issue_resolved = FALSE
        AND da.alarm_type = 'snapshot_missing'
    WHERE da.id IS NULL
    """
    
    cursor.execute(insert_query)
    new_alarms = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    
    return new_alarms

def check_and_resolve_alarms():
    """Find devices that are back online and resolve their alarms."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
    WITH ranked_snapshots AS (
        SELECT 
            device_id,
            time,
            ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY time DESC) as rn
        FROM snapshot
        WHERE time IS NOT NULL
          AND preset_id = 1
    ),
    device_intervals AS (
        SELECT 
            r1.device_id,
            r1.time as last_snapshot_time,
            r2.time as prev_snapshot_time,
            (r1.time - r2.time) as normal_interval_ms
        FROM ranked_snapshots r1
        JOIN ranked_snapshots r2 ON r1.device_id = r2.device_id AND r2.rn = 2
        WHERE r1.rn = 1
    ),
    healthy_devices AS (
        SELECT device_id
        FROM device_intervals
        WHERE (UNIX_TIMESTAMP() * 1000 - last_snapshot_time) <= (2 * normal_interval_ms)
    )
    SELECT 
        da.id as alarm_id,
        da.device_id,
        c.label as camera_name,
        s.name as site_name,
        da.issue_start_time,
        TIMESTAMPDIFF(HOUR, da.issue_start_time, NOW()) as downtime_hours
    FROM device_alarms da
    JOIN camera c ON da.device_id = c.device_id
    LEFT JOIN site s ON c.site_id = s.site_id
    JOIN healthy_devices hd ON da.device_id = hd.device_id
    WHERE da.issue_resolved = FALSE
      AND da.alarm_type = 'snapshot_missing'
    """
    
    cursor.execute(query)
    resolved_devices = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return resolved_devices

def resolve_alarms(alarm_ids: list):
    """Mark alarms as resolved."""
    if not alarm_ids:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = f"""
    UPDATE device_alarms 
    SET issue_resolved = TRUE,
        issue_resolved_time = NOW()
    WHERE id IN ({','.join(['%s'] * len(alarm_ids))})
    """
    
    cursor.execute(query, alarm_ids)
    conn.commit()
    cursor.close()
    conn.close()

def get_pending_alerts():
    """Get alarms that need notification (new or daily reminder)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
    SELECT 
        da.id as alarm_id,
        da.device_id,
        c.label as camera_name,
        c.serial_id,
        s.name as site_name,
        da.alarm_type,
        da.alarm_description,
        da.issue_start_time,
        da.last_alarm_sent_time,
        da.created_at,
        TIMESTAMPDIFF(HOUR, da.issue_start_time, NOW()) as hours_since_issue
    FROM device_alarms da
    JOIN camera c ON da.device_id = c.device_id
    LEFT JOIN site s ON c.site_id = s.site_id
    WHERE 
        da.issue_resolved = FALSE
        AND c.is_active = 1
        AND (
            TIMESTAMPDIFF(MINUTE, da.created_at, da.last_alarm_sent_time) < 1
            OR da.last_alarm_sent_time < NOW() - INTERVAL 1 DAY
        )
    """
    
    cursor.execute(query)
    alerts = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return alerts

def update_last_sent_time(alarm_ids: list):
    """Update last_alarm_sent_time for processed alarms."""
    if not alarm_ids:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = f"""
    UPDATE device_alarms 
    SET last_alarm_sent_time = NOW() 
    WHERE id IN ({','.join(['%s'] * len(alarm_ids))})
    """
    
    cursor.execute(query, alarm_ids)
    conn.commit()
    cursor.close()
    conn.close()

def format_down_alert(alerts: list) -> str:
    """Format down alerts into a Slack message."""
    if not alerts:
        return None
    
    message = "🚨 *Camera Snapshot Alerts*\n\n"
    
    for alert in alerts:
        site = alert['site_name'] or 'Unknown Site'
        camera = alert['camera_name'] or f"Device {alert['device_id']}"
        hours = alert['hours_since_issue'] or 0
        
        # Check if this is a reminder (created more than 1 hour ago)
        is_reminder = hours > 1
        reminder_tag = " _(reminder)_" if is_reminder else " _(new)_"
        
        message += f"• *{camera}* ({site}){reminder_tag}\n"
        message += f"  └ {alert['alarm_description']}\n"
        message += f"  └ Down for: {hours} hours\n\n"
    
    message += f"_Total: {len(alerts)} camera(s) need attention_"
    
    return message

def format_resolved_alert(resolved: list) -> str:
    """Format resolved alerts into a Slack message."""
    if not resolved:
        return None
    
    message = "✅ *Cameras Back Online*\n\n"
    
    for device in resolved:
        site = device['site_name'] or 'Unknown Site'
        camera = device['camera_name'] or f"Device {device['device_id']}"
        downtime = device['downtime_hours'] or 0
        
        message += f"• *{camera}* ({site})\n"
        message += f"  └ Was down for {downtime} hours\n\n"
    
    message += f"_Total: {len(resolved)} camera(s) recovered_"
    
    return message

def run_alarm_check():
    """Main function to run the alarm check and send notifications."""
    
    print(f"[{datetime.now()}] Starting alarm check...")
    
    # Step 1: Check and resolve devices that are back online
    resolved_devices = check_and_resolve_alarms()
    print(f"Found {len(resolved_devices)} device(s) back online")
    
    if resolved_devices:
        resolved_message = format_resolved_alert(resolved_devices)
        if send_slack_alert(resolved_message):
            print("Sent back-online notification")
            
            resolved_ids = [d['alarm_id'] for d in resolved_devices]
            resolve_alarms(resolved_ids)
            print(f"Resolved {len(resolved_ids)} alarm(s)")
        else:
            print("Failed to send back-online notification")
    
    # Step 2: Insert new alarms for overdue devices
    new_alarms = check_and_insert_new_alarms()
    print(f"Inserted {new_alarms} new alarm(s)")
    
    # Step 3: Get all pending alerts (new + daily reminders)
    alerts = get_pending_alerts()
    print(f"Found {len(alerts)} alert(s) to send")
    
    if alerts:
        down_message = format_down_alert(alerts)
        if send_slack_alert(down_message):
            print("Sent down notification")
            
            alarm_ids = [alert['alarm_id'] for alert in alerts]
            update_last_sent_time(alarm_ids)
            print(f"Updated last_sent_time for {len(alarm_ids)} alarm(s)")
        else:
            print("Failed to send down notification")
    
    print(f"[{datetime.now()}] Alarm check complete.\n")

if __name__ == "__main__":
    run_alarm_check()
