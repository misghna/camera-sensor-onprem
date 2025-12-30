import requests
import pickle
import os
import json
import re
import math
import mysql.connector
import time
from datetime import datetime, timedelta, timezone
from configparser import ConfigParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pyproj import Transformer

# ==========================================
#              CONFIGURATION
# ==========================================

# Map Project IDs to EPSG Codes
# 32148 = NAD83 / Washington North (Meters)
PROJECT_SETTINGS = {
    1: 32148, 
    2: 32148,
    3: 32148,
    # Add other IDs here if they are in different states
}

DEFAULT_EPSG = None 

def get_transformer(project_id):
    epsg = PROJECT_SETTINGS.get(project_id, DEFAULT_EPSG)
    if not epsg: return None
    try:
        return Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    except: return None

def load_db_config(filename='credentials.ini', section='database'):
    parser = ConfigParser()
    parser.read(filename)
    db = {}
    if parser.has_section(section):
        for param in parser.items(section):
            db[param[0]] = param[1]
    return db

# ==========================================
#              T4D CLIENT
# ==========================================

class T4DClient:
    def __init__(self, base_url="http://144.202.94.227", session_file="t4d_session.pkl"):
        self.base_web = f"{base_url}/T4DWeb"
        self.base_admin = f"{base_url}/T4DWeb.Admin/T4D.ProjectManager/api"
        self.session_file = session_file
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
        self.load_session()

    def load_session(self):
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "rb") as f:
                    self.session.cookies.update(pickle.load(f))
            except: pass

    def save_session(self):
        with open(self.session_file, "wb") as f:
            pickle.dump(self.session.cookies.get_dict(), f)

    def login(self, username, password):
        print("Logging in...")
        self.session.post(f"{self.base_web}/Account/DoLogOn", data={"UserName": username, "Password": password})
        self.save_session()
        return bool(self.get_api_token())

    def get_api_token(self):
        try:
            r = self.session.get(f"{self.base_web}/ApiToken/Retrieve")
            return r.json().get("access_token") if r.status_code == 200 else None
        except: return None

    def get_projects(self):
        token = self.get_api_token()
        try:
            r = self.session.get(f"{self.base_admin}/Projects", headers={"Authorization": f"Bearer {token}"})
            return r.json() if r.status_code == 200 else []
        except: return []

    def get_total_stations_for_project(self, project_id):
        token = self.get_api_token()
        try:
            r = self.session.get(f"{self.base_admin}/Projects/{project_id}/TotalStationSensors/", headers={"Authorization": f"Bearer {token}"})
            return r.json() if r.status_code == 200 else []
        except: return []

    def get_locations_list(self, project_id):
        token = self.get_api_token()
        try:
            r = self.session.get(f"{self.base_admin}/Projects/{project_id}/Locations/", headers={"Authorization": f"Bearer {token}"})
            return r.json() if r.status_code == 200 else []
        except: return []

    def get_sensors_list(self, project_id):
        token = self.get_api_token()
        try:
            r = self.session.get(f"{self.base_admin}/Projects/{project_id}/Sensors/", headers={"Authorization": f"Bearer {token}"})
            return r.json() if r.status_code == 200 else []
        except: return []

    def get_sensor_detail(self, project_id, sensor_id):
        token = self.get_api_token()
        try:
            r = self.session.get(f"{self.base_admin}/Projects/{project_id}/Sensors/{sensor_id}", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200: return r.json()
        except: pass
        return None

# ==========================================
#      CORE LOGIC (PARSING & MATCHING)
# ==========================================

def normalize(name):
    if not name: return ""
    return re.sub(r'[\W_]+', '', name).lower()

def extract_primary_number(text):
    if not text: return None
    nums = re.findall(r'\d+', text)
    return int(nums[0]) if nums else None

def parse_coordinates(obj, transformer=None):
    """
    The robust parser verified by the debug script.
    """
    try:
        # 1. Identify container
        source = None
        if obj.get('CurrentCoordinate'): source = obj['CurrentCoordinate']
        elif obj.get('OriginalCoordinate'): source = obj['OriginalCoordinate']
        elif obj.get('ReferenceCoordinate'): source = obj['ReferenceCoordinate']
        elif 'Location' in obj:
            loc = obj['Location']
            if loc.get('GridCoordinate'): source = loc['GridCoordinate']
            elif 'Northing' in loc: source = loc
        elif 'Northing' in obj: source = obj

        if not source: return None

        # 2. Extract Raw Values
        def get_val(data, key):
            val = data.get(key)
            if isinstance(val, dict): return val.get('Value', 0.0)
            return float(val) if val is not None else 0.0

        n_val = get_val(source, 'Northing')
        e_val = get_val(source, 'Easting')
        h_val = get_val(source, 'Elevation')
        if h_val == 0.0 and 'Height' in source: h_val = get_val(source, 'Height')

        # 3. Determine Unit
        def get_unit(data, key):
            val = data.get(key)
            if isinstance(val, dict): return val.get('Unit', 'Meter')
            return 'Meter'

        n_unit = get_unit(source, 'Northing')
        e_unit = get_unit(source, 'Easting')
        h_unit = 'Meter'
        if 'Elevation' in source: h_unit = get_unit(source, 'Elevation')
        elif 'Height' in source: h_unit = get_unit(source, 'Height')

        # 4. Convert to Meters
        factors = { 'Meter': 1.0, 'USSurveyFoot': 1200.0/3937.0, 'InternationalFoot': 0.3048, 'Foot': 0.3048 }

        n_meters = n_val * factors.get(n_unit, 1.0)
        e_meters = e_val * factors.get(e_unit, 1.0)
        h_meters = h_val * factors.get(h_unit, 1.0)

        if abs(n_meters) < 0.001 and abs(e_meters) < 0.001: return None

        # 5. GENERATE GLOBAL COORDINATES
        lat_val, lon_val = None, None
        if transformer:
            try:
                lon_val, lat_val = transformer.transform(e_meters, n_meters)
            except: pass

        return (n_meters, e_meters, h_meters, lat_val, lon_val)

    except Exception: return None

def calculate_distance(coord1, coord2):
    if not coord1 or not coord2: return None
    dn = coord1[0] - coord2[0]
    de = coord1[1] - coord2[1]
    return math.sqrt(dn*dn + de*de)

def find_station_match(candidate_str, station_map, sensor_coords):
    if not candidate_str: return None
    cand_norm = normalize(candidate_str)
    
    for s_name in station_map.keys():
        if normalize(s_name) == cand_norm: return s_name
        
    cand_num = extract_primary_number(candidate_str)
    if cand_num is not None:
        matches = [s for s in station_map.keys() if extract_primary_number(s) == cand_num]
        if len(matches) == 1: return matches[0]
        if len(matches) > 1 and sensor_coords:
            best_match = None
            min_dist = float('inf')
            for m in matches:
                st_coords = station_map[m]['coords']
                dist = calculate_distance(sensor_coords, st_coords)
                if dist is not None and dist < min_dist:
                    min_dist = dist
                    best_match = m
            if best_match and min_dist < 2000: return best_match 
    return None

# ==========================================
#            ORCHESTRATION
# ==========================================

def build_hierarchy(client, limit=None):
    if not client.get_api_token():
        client.login("admin", "Barrite8861##")

    print("Fetching Projects...")
    projects = client.get_projects()
    full_hierarchy = {}

    for p in projects:
        pid = p['ID']
        pname = p['ProjectTitle']
        print(f"\nProcessing Project: {pname} (ID: {pid})")

        transformer = get_transformer(pid)

        # 1. Candidate Pool
        candidate_pool = {}
        ts_list = client.get_total_stations_for_project(pid)
        for s in ts_list:
            candidate_pool[s['StationName']] = {
                'info': s, 'type': 'TotalStation', 'coords': parse_coordinates(s, transformer)
            }
        loc_list = client.get_locations_list(pid)
        for loc in loc_list:
            lname = loc.get('Name', '')
            if lname and lname not in candidate_pool:
                candidate_pool[lname] = {
                    'info': loc, 'type': 'Location', 'coords': parse_coordinates(loc, transformer)
                }
            
        print(f"   > Pool: {len(candidate_pool)} candidates.")

        # 2. Sensor Verification
        confirmed_stations = {}
        confirmed_stations['Unmatched'] = {'info': None, 'type': 'System', 'sensors': [], 'coords': None}

        raw_sensors = client.get_sensors_list(pid)
        if limit and len(raw_sensors) > limit:
            sensors_to_process = raw_sensors[:limit]
            print(f"   > [SAFE MODE] Processing {limit} of {len(raw_sensors)} sensors...")
        else:
            sensors_to_process = raw_sensors
            print(f"   > Processing ALL {len(raw_sensors)} sensors...")

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_sensor = {
                executor.submit(client.get_sensor_detail, pid, s['ID']): s 
                for s in sensors_to_process
            }

            for future in as_completed(future_to_sensor):
                try:
                    detail = future.result()
                    if not detail: continue

                    # PARSE SENSOR COORDS
                    sensor_coords = parse_coordinates(detail, transformer)
                    linked_station_name = None
                    
                    ds_list = detail.get('DataSources', [])
                    if ds_list:
                        data_source_str = ds_list[0].get('DataSourceString', '')
                        parts = data_source_str.split('_')
                        if parts:
                            linked_station_name = find_station_match(parts[-1], candidate_pool, sensor_coords)
                        if not linked_station_name:
                             linked_station_name = find_station_match(data_source_str, candidate_pool, sensor_coords)

                    # Store full sensor object AND the parsed coords
                    sensor_entry = {
                        'data': detail,
                        'parsed_coords': sensor_coords
                    }

                    if linked_station_name:
                        if linked_station_name not in confirmed_stations:
                            confirmed_stations[linked_station_name] = {
                                'info': candidate_pool[linked_station_name]['info'],
                                'type': candidate_pool[linked_station_name]['type'],
                                'coords': candidate_pool[linked_station_name]['coords'],
                                'sensors': []
                            }
                        confirmed_stations[linked_station_name]['sensors'].append(sensor_entry)
                    else:
                        confirmed_stations['Unmatched']['sensors'].append(sensor_entry)
                except Exception: pass
        
        full_hierarchy[pid] = {'name': pname, 'stations': confirmed_stations}

    return full_hierarchy

def prepare_db_records(hierarchy):
    projects_rows, stations_rows, sensors_rows = [], [], []

    for p_id, p_data in hierarchy.items():
        p_name = p_data['name']
        stations_dict = p_data['stations']
        projects_rows.append((p_id, p_name))

        for s_name, s_data in stations_dict.items():
            station_db_id = None
            if s_name != "Unmatched":
                info = s_data['info']
                station_db_id = info['ID']
                coords = s_data['coords'] or (None, None, None, None, None)
                s_type = s_data['type']
                
                if s_type == 'TotalStation':
                    stations_rows.append((
                        station_db_id, p_id, s_name, s_type, 
                        coords[0], coords[1], coords[2], coords[3], coords[4]
                    ))

            for sensor_entry in s_data['sensors']:
                s = sensor_entry['data']
                # Use the pre-parsed coords from the hierarchy
                s_coords = sensor_entry.get('parsed_coords') or (None, None, None, None, None)
                final_fk_id = station_db_id if s_name != "Unmatched" and s_data['type'] == 'TotalStation' else None
                
                sensors_rows.append((
                    s['ID'], p_id, final_fk_id, s['Name'], 
                    s_coords[0], s_coords[1], s_coords[2], s_coords[3], s_coords[4]
                ))
                
    return projects_rows, stations_rows, sensors_rows

# ==========================================
#          DB SAVE (TRANSACTIONAL)
# ==========================================

def save_to_database(cnx, projects, stations, sensors):
    cursor = cnx.cursor()
    try:
        print("Upserting Projects...")
        sql_proj = "INSERT INTO amts_projects (id, name) VALUES (%s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name)"
        cursor.executemany(sql_proj, projects)
        cnx.commit()
        print(f"   > {cursor.rowcount} saved.")

        if stations:
            print(f"Upserting {len(stations)} Stations...")
            sql_stat = """
            INSERT INTO amts_stations (id, project_id, name, type, northing, easting, elevation, latitude, longitude) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                name=VALUES(name), northing=VALUES(northing), easting=VALUES(easting), 
                elevation=VALUES(elevation), latitude=VALUES(latitude), longitude=VALUES(longitude)
            """
            cursor.executemany(sql_stat, stations)
            cnx.commit()
            print(f"   > {cursor.rowcount} saved.")

        if sensors:
            print(f"Upserting {len(sensors)} Sensors...")
            sql_sens = """
            INSERT INTO amts_sensors (id, project_id, station_id, name, northing, easting, elevation, latitude, longitude) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                station_id=VALUES(station_id), name=VALUES(name), 
                northing=VALUES(northing), easting=VALUES(easting), 
                elevation=VALUES(elevation), latitude=VALUES(latitude), longitude=VALUES(longitude)
            """
            cursor.executemany(sql_sens, sensors)
            cnx.commit()
            print(f"   > {cursor.rowcount} saved.")

    except mysql.connector.Error as err:
        print(f"\n[SQL ERROR]: {err}")
    finally:
        cursor.close()

if __name__ == "__main__":
    try:
        db_config = load_db_config('credentials.ini', 'database')
    except Exception as e:
        print(f"Config Error: {e}")
        exit()

    client = T4DClient()
    print(">>> Starting Extraction...")
    
    # 1. EXTRACT
    hierarchy = build_hierarchy(client, limit=None) 
    
    # 2. TRANSFORM
    p_rows, st_rows, se_rows = prepare_db_records(hierarchy)
    
    print("\n" + "="*40)
    print("      DATA STAGING COMPLETE      ")
    print(f"Projects: {len(p_rows)}")
    print(f"Stations: {len(st_rows)}")
    print(f"Sensors:  {len(se_rows)}")
    
    # Check for valid lat/lon
    valid_geo = sum(1 for s in se_rows if s[7] is not None)
    print(f"Sensors with Valid Lat/Lon: {valid_geo} / {len(se_rows)}")

    if not p_rows: exit()

    # 3. LOAD
    try:
        print("\n>>> Connecting to MySQL...")
        cnx = mysql.connector.connect(
            host=db_config['db_host'],
            database=db_config['db_name'],
            user=db_config['db_user'],
            password=db_config['db_password']
        )
        save_to_database(cnx, p_rows, st_rows, se_rows)
        print("\n[SUCCESS] Sync complete.")
        cnx.close()
    except mysql.connector.Error as err:
        print(f"\n[SQL ERROR]: {err}")