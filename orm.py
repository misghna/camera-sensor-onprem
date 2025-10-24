import mysql.connector
import json
from configparser import ConfigParser

def get_db_connection():
    config = ConfigParser()
    config.read('credentials.ini')
    
    return mysql.connector.connect(
        host=config.get('database', 'db_host'),
        database=config.get('database', 'db_name'),
        user=config.get('database', 'db_user'),
        password=config.get('database', 'db_password'),
        port=config.getint('database', 'db_port')
    )

def get_camera_data():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT device_id, serial_id, c.site_id, s.name as site_name 
        FROM camera.camera c 
        LEFT JOIN camera.site s ON c.site_id = s.site_id
    """)
    
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return json.dumps(results, default=str)

# Usage
data = get_camera_data()
print(data)
