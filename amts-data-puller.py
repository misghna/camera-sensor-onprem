import requests
import mysql.connector
import time
from datetime import datetime, timedelta, timezone
from configparser import ConfigParser
import pickle
import os
import json
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
SESSION_FILE = "analysis.pkl"
BASE_URL = "http://144.202.94.227/T4DWeb"
CREDENTIALS_FILE = "credentials.ini"

# Window Settings
PAST_DAYS = 5
FUTURE_DAYS = 5
MIN_DAYS_REMAINING = 1  # Update if ToDate is closer than this

# --- LOAD DATABASE CREDENTIALS ---
config = ConfigParser()
if not os.path.exists(CREDENTIALS_FILE):
    print(f"[!] Error: {CREDENTIALS_FILE} not found.")
    exit(1)

config.read(CREDENTIALS_FILE)

try:
    DB_CONFIG = {
        'user': config.get('database', 'db_user'),
        'password': config.get('database', 'db_password'),
        'host': config.get('database', 'db_host'),
        'database': config.get('database', 'db_name'),
        'port': config.getint('database', 'db_port', fallback=3306)
    }
except Exception as e:
    print(f"[!] Error reading database credentials: {e}")
    exit(1)

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "http://144.202.94.227",
    "Referer": f"{BASE_URL}/Analysis/List"
}

class T4DScraper:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(COMMON_HEADERS)
        self._load_session()

    def _load_session(self):
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "rb") as f:
                    self.session.cookies.update(pickle.load(f))
            except Exception: pass

    def _save_session(self):
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(self.session.cookies.get_dict(), f)

    def login(self):
        print(f"[*] Logging in as {self.username}...")
        payload = {"UserName": self.username, "Password": self.password}
        try:
            r = self.session.post(f"{BASE_URL}/Account/DoLogOn", data=payload)
            if r.status_code == 200 and "LogOn" not in r.url:
                print("[+] Login successful.")
                self._save_session()
                return True
            print("[-] Login failed.")
        except Exception as e:
            print(f"[!] Login exception: {e}")
        return False

    def ensure_auth(self):
        try:
            r = self.session.get(f"{BASE_URL}/")
            if "Account/LogOn" in r.url or "LogOn" in r.text:
                return self.login()
            return True
        except: return self.login()

    def get_projects(self):
        self.ensure_auth()
        r = self.session.post(f"{BASE_URL}/Project/Select/")
        projects = []
        if r.status_code == 200:
            try:
                data = r.json()
                soup = BeautifulSoup(data.get("html", ""), "html.parser")
                for opt in soup.find_all("option"):
                    projects.append({"id": int(opt.get("value")), "name": opt.text.strip()})
            except: pass
        return projects

    def switch_project(self, project_id):
        self.ensure_auth()
        r = self.session.post(f"{BASE_URL}/Project/Change", data={"id": project_id})
        return r.status_code == 200

    def get_auto_analyses(self):
        """Returns ONLY analyses containing '-Auto'."""
        self.ensure_auth()
        r = self.session.post(f"{BASE_URL}/Analysis/List")
        analyses = []
        if r.status_code == 200:
            try:
                data = r.json()
                soup = BeautifulSoup(data.get("html", ""), "html.parser")
                for block in soup.select("div.analysis-list-item"):
                    block_id = block.get("id")
                    if not block_id: continue
                    a_id = int(block_id.split("-")[-1])
                    name = block.find("a").text.strip()
                    if "-Auto" in name:
                        analyses.append({"id": a_id, "name": name})
            except: pass
        return analyses

    def ensure_date_window(self, analysis_id):
        """
        Checks current config. 
        Only updates if the 'ToDate' is expiring soon (< 1 day left).
        New Window: [Now - 5 days] to [Now + 5 days].
        """
        self.ensure_auth()
        
        # 1. Fetch Current Config
        r = self.session.post(f"{BASE_URL}/Analysis/Edit/{analysis_id}/")
        if r.status_code != 200: return False
        
        try:
            html_content = r.json().get("html", "")
            soup = BeautifulSoup(html_content, "html.parser")
            form = soup.find("form", id="edit-analysis-form")
            if not form: return False
        except: return False

        # 2. Parse Existing Values
        payload = {}
        current_to_date_str = ""
        
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                val = inp.get("value", "")
                if inp.get("type") == "checkbox":
                    if inp.get("checked"): payload[name] = "true" 
                else:
                    payload[name] = val
                    
                # Capture the current End Date (Local)
                if name == "ToDateLocal":
                    current_to_date_str = val

        for sel in form.find_all("select"):
            name = sel.get("name")
            if name:
                selected = sel.find("option", selected=True)
                payload[name] = selected.get("value") if selected else ""

        # 3. Check if Update is Needed
        needs_update = True
        now = datetime.now()
        
        if current_to_date_str:
            try:
                # T4D format is usually MM/DD/YYYY HH:MM:SS
                current_to_date = datetime.strptime(current_to_date_str, "%m/%d/%Y %H:%M:%S")
                
                # Calculate time remaining
                remaining = current_to_date - now
                
                if remaining > timedelta(days=MIN_DAYS_REMAINING):
                    print(f"    [i] Config is fresh (expires in {remaining.days} days). Skipping update.")
                    needs_update = False
                else:
                    print(f"    [!] Config expiring soon ({remaining}). Updating...")
            except ValueError:
                # If date parse fails, force update to be safe
                print("    [!] Could not parse current date. Forcing update.")
                needs_update = True
        
        if not needs_update:
            return True  # Proceed to pull data

        # 4. Calculate New Window (-5 to +5)
        start_date = now - timedelta(days=PAST_DAYS)
        end_date = now + timedelta(days=FUTURE_DAYS)
        
        # Handle UTC Offsets
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        offset = utc_now - now
        
        start_utc = start_date + offset
        end_utc = end_date + offset

        fmt_local = "%m/%d/%Y %H:%M:%S"
        fmt_utc = "%m/%d/%Y %I:%M:%S %p"

        updates = {
            "FromDateLocal": start_date.strftime(fmt_local),
            "ToDateLocal": end_date.strftime(fmt_local),
            "EffectiveFromDateLocal": start_date.strftime(fmt_local),
            "EffectiveToDateLocal": end_date.strftime(fmt_local),
            "HeatMapDateLocal": end_date.strftime(fmt_local),
            
            "FromDateUTC": start_utc.strftime(fmt_utc),
            "ToDateUTC": end_utc.strftime(fmt_utc),
            "EffectiveFromDateUTC": start_utc.strftime(fmt_utc),
            "EffectiveToDateUTC": end_utc.strftime(fmt_utc),
            "HeatMapDateUTC": end_utc.strftime(fmt_utc),
            "UpdatedUTC": utc_now.strftime(fmt_utc)
        }
        payload.update(updates)

        # 5. Save
        save_r = self.session.post(f"{BASE_URL}/Analysis/Save", data=payload)
        if save_r.status_code == 200:
            print(f"    [+] Updated window: -{PAST_DAYS}d to +{FUTURE_DAYS}d")
            return True
            
        return False

    def get_analysis_data(self, analysis_id):
        self.ensure_auth()
        r = self.session.post(f"{BASE_URL}/Analysis/LoadData", data={"id": analysis_id})
        if r.status_code == 200:
            try: return r.json()
            except: return None
        return None

# -------------------------
#   DATA PROCESSING
# -------------------------
def parse_and_pivot_t4d_data(json_data):
    if not json_data or "data" not in json_data or not json_data["data"]:
        return []

    grouped_data = {}

    for series in json_data["data"].get("Series", []):
        sensor_id = series.get("SensorID") or series.get("Sensor", {}).get("ID")
        if not sensor_id: continue

        metric_type = series.get("ValueColumn", {}).get("ColumnName", "Unknown") 
        if metric_type not in ["dN", "dE", "dH"]: continue

        obs_container = series.get("SensorValueObservations", {})
        observations = obs_container.get("ValueObservations", [])

        for obs in observations:
            timestamp = obs.get("EndDateUTC")
            if timestamp:
                key = (sensor_id, timestamp)
                if key not in grouped_data:
                    grouped_data[key] = {
                        "sensor_id": sensor_id,
                        "timestamp_utc": timestamp,
                        "val_dN": None, "std_dN": None, "min_dN": None, "max_dN": None,
                        "val_dE": None, "std_dE": None, "min_dE": None, "max_dE": None,
                        "val_dH": None, "std_dH": None, "min_dH": None, "max_dH": None,
                    }
                
                grouped_data[key][f"val_{metric_type}"] = obs.get("ConvertedValue")
                grouped_data[key][f"std_{metric_type}"] = obs.get("ConvertedStdDev")
                grouped_data[key][f"min_{metric_type}"] = obs.get("ConvertedMinValue")
                grouped_data[key][f"max_{metric_type}"] = obs.get("ConvertedMaxValue")

    return list(grouped_data.values())

def push_to_database(data_rows):
    if not data_rows: return

    print(f"      [>] Syncing {len(data_rows)} rows to DB...")
    
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        sql = """
        INSERT INTO amts_sensor_readings (
            sensor_id, timestamp_utc,
            val_dn, std_dn, min_dn, max_dn,
            val_de, std_de, min_de, max_de,
            val_dh, std_dh, min_dh, max_dh
        ) VALUES (
            %(sensor_id)s, %(timestamp_utc)s,
            %(val_dN)s, %(std_dN)s, %(min_dN)s, %(max_dN)s,
            %(val_dE)s, %(std_dE)s, %(min_dE)s, %(max_dE)s,
            %(val_dH)s, %(std_dH)s, %(min_dH)s, %(max_dH)s
        )
        ON DUPLICATE KEY UPDATE
            val_dn = VALUES(val_dn), std_dn = VALUES(std_dn), min_dn = VALUES(min_dn), max_dn = VALUES(max_dn),
            val_de = VALUES(val_de), std_de = VALUES(std_de), min_de = VALUES(min_de), max_de = VALUES(max_de),
            val_dh = VALUES(val_dh), std_dh = VALUES(std_dh), min_dh = VALUES(min_dh), max_dh = VALUES(max_dh);
        """

        batch_size = 1000
        total = len(data_rows)
        for i in range(0, total, batch_size):
            batch = data_rows[i:i + batch_size]
            cursor.executemany(sql, batch)
            conn.commit()
            
        print(f"      [+] Success: {cursor.rowcount} changes.")

    except mysql.connector.Error as err:
        print(f"      [!] Database Error: {err}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

# -------------------------
#   MAIN DAILY LOGIC
# -------------------------
def run_smart_sync():
    bot = T4DScraper("admin", "Barrite8861##")
    projects = bot.get_projects()
    
    print(f"=== T4D SMART SYNC (Window: -{PAST_DAYS} to +{FUTURE_DAYS} days) ===")
    
    for proj in projects:
        print(f"\n--- Project: {proj['name']} ---")
        if not bot.switch_project(proj['id']): 
            print("    [!] Failed to switch project.")
            continue
        
        analyses = bot.get_auto_analyses()
        if not analyses: 
            print("    No '-Auto' analyses found.")
            continue
        
        for analysis in analyses:
            print(f"  Target: {analysis['name']} (ID: {analysis['id']})")
            
            # 1. Check Date & Update if needed
            if bot.ensure_date_window(analysis['id']):
                # 2. Pull Data
                data = bot.get_analysis_data(analysis['id'])
                
                if data:
                    rows = parse_and_pivot_t4d_data(data)
                    if rows:
                        print(f"    Found {len(rows)} rows.")
                        # 3. Push to DB
                        push_to_database(rows)
                    else:
                        print("    0 rows found.")
                else:
                    print("    No response from server.")
            else:
                print("    Config Check Failed.")

if __name__ == "__main__":
    run_smart_sync()