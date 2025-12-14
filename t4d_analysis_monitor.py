import requests
import pickle
import os
import json
import re
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

SESSION_FILE = "analysis.pkl"

BASE = "http://144.202.94.227/T4DWeb"
URL_LOGIN = f"{BASE}/Account/DoLogOn"
URL_PROJECT_SELECT = f"{BASE}/Project/Select/"
URL_PROJECT_CHANGE = f"{BASE}/Project/Change"
URL_ANALYSIS_LIST = f"{BASE}/Analysis/List"
URL_ANALYSIS_LOAD_DATA = f"{BASE}/Analysis/LoadData"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "http://144.202.94.227",
    "Referer": "http://144.202.94.227/T4DWeb",
    "X-Requested-With": "XMLHttpRequest",
}

# Debug flag - set to True for verbose output
DEBUG = True

# Time window for alarm detection: "hours" or "days"
# Use "hours" for production (12 hours), "days" for testing (5 days)
TIME_WINDOW_MODE = "hours"  # Options: "hours" or "days"
TIME_WINDOW_HOURS = 12     # Hours to check (when mode is "hours")
TIME_WINDOW_DAYS = 5      # Days to check (when mode is "days")


def debug_print(*args, **kwargs):
    """Print only if DEBUG is enabled."""
    if DEBUG:
        print("[DEBUG]", *args, **kwargs)


# -------------------------
#   SESSION MANAGEMENT
# -------------------------

def load_or_create_session():
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)

    debug_print(f"Session file path: {os.path.abspath(SESSION_FILE)}")
    debug_print(f"Session file exists: {os.path.exists(SESSION_FILE)}")

    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "rb") as f:
                cookies = pickle.load(f)
                debug_print(f"Loaded cookies from file: {cookies}")
                session.cookies.update(cookies)
            print("Loaded saved session.")
        except Exception as e:
            debug_print(f"Failed to load session file: {e}")

    debug_print(f"Current session cookies: {session.cookies.get_dict()}")
    return session


def save_session(session):
    cookies = session.cookies.get_dict()
    debug_print(f"Saving session cookies: {cookies}")
    with open(SESSION_FILE, "wb") as f:
        pickle.dump(cookies, f)
    debug_print(f"Session saved to {SESSION_FILE}")


def login(session):
    print("Logging in...")
    payload = {"UserName": "admin", "Password": "Barrite8861##"}
    
    debug_print(f"Login URL: {URL_LOGIN}")
    debug_print(f"Login payload: {payload}")
    debug_print(f"Request headers: {dict(session.headers)}")
    debug_print(f"Cookies before login: {session.cookies.get_dict()}")
    
    try:
        r = session.post(URL_LOGIN, data=payload)
        
        debug_print(f"Login response status code: {r.status_code}")
        debug_print(f"Login response headers: {dict(r.headers)}")
        debug_print(f"Cookies after login: {session.cookies.get_dict()}")
        debug_print(f"Response URL (after redirects): {r.url}")
        debug_print(f"Response history (redirects): {r.history}")
        
        # Check response content
        debug_print(f"Response content length: {len(r.text)}")
        debug_print(f"Response content preview (first 500 chars):\n{r.text[:500]}")
        
        # Try to parse as JSON if possible
        try:
            json_response = r.json()
            debug_print(f"JSON response: {json_response}")
        except:
            debug_print("Response is not JSON")
        
        # Check for common login failure indicators
        login_failed = (
            "LogOn" in r.text or 
            "login" in r.text.lower() or
            "Sign In</a>" in r.text or
            "invalid" in r.text.lower() or
            "incorrect" in r.text.lower()
        )
        
        if login_failed:
            debug_print("WARNING: Response may indicate login failure")
            debug_print(f"Full response:\n{r.text}")
        else:
            debug_print("Login appears successful!")
        
        if r.status_code != 200:
            debug_print(f"WARNING: Non-200 status code: {r.status_code}")
            
    except requests.exceptions.RequestException as e:
        debug_print(f"LOGIN REQUEST FAILED: {e}")
        raise
    
    save_session(session)
    print("Login complete.")
    return session


def is_session_valid(session):
    """Check if current session is still valid."""
    debug_print("Checking session validity...")
    
    # Try a simple request to see if we're logged in
    try:
        r = session.get(f"{BASE}/")
        debug_print(f"Session check status: {r.status_code}")
        debug_print(f"Session check URL: {r.url}")
        
        is_valid = "LogOn" not in r.text and "Account/LogOn" not in r.url
        debug_print(f"Session appears valid: {is_valid}")
        return is_valid
    except Exception as e:
        debug_print(f"Session check failed: {e}")
        return False


# -------------------------
#   PROJECT LIST
# -------------------------

def fetch_projects(session):
    """Return list of (project_id, project_name)."""
    debug_print(f"Fetching projects from: {URL_PROJECT_SELECT}")
    
    r = session.post(URL_PROJECT_SELECT)
    
    debug_print(f"Project fetch status: {r.status_code}")
    debug_print(f"Project fetch response preview: {r.text[:300] if r.text else 'Empty'}")

    # Check for various login indicators
    needs_login = (
        r.status_code != 200 or 
        "Account/LogOn" in r.text or 
        "Account__Logon" in r.text or
        "Sign In</a>" in r.text
    )
    
    if needs_login:
        debug_print("Session expired or invalid, re-logging in...")
        session = login(session)
        r = session.post(URL_PROJECT_SELECT)
        debug_print(f"Retry status: {r.status_code}")
        debug_print(f"Retry response preview: {r.text[:300] if r.text else 'Empty'}")

    try:
        json_data = r.json()
        html = json_data.get("html", "")
        debug_print(f"JSON keys in response: {json_data.keys()}")
        debug_print(f"HTML content length: {len(html)}")
    except Exception as e:
        debug_print(f"Failed to parse JSON: {e}")
        debug_print(f"Raw response: {r.text[:500]}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    projects = []
    for opt in soup.find_all("option"):
        pid = int(opt.get("value"))
        name = opt.text.strip()
        projects.append((pid, name))
        debug_print(f"Found project: {pid} - {name}")

    debug_print(f"Total projects found: {len(projects)}")
    return projects


# -------------------------
#   SWITCH PROJECT
# -------------------------

def switch_project(session, project_id):
    """Switch the active project via Project/Change."""
    debug_print(f"Switching to project ID: {project_id}")
    
    payload = {"id": project_id}
    r = session.post(URL_PROJECT_CHANGE, data=payload)

    debug_print(f"Switch response status: {r.status_code}")
    debug_print(f"Switch response preview: {r.text[:200] if r.text else 'Empty'}")

    # Check for various login indicators
    needs_login = (
        r.status_code != 200 or 
        "LogOn" in r.text or
        "Sign In</a>" in r.text
    )
    
    if needs_login:
        debug_print("Session expired during project switch, re-logging in...")
        session = login(session)
        r = session.post(URL_PROJECT_CHANGE, data=payload)
        debug_print(f"Retry switch status: {r.status_code}")

    return session


# -------------------------
#   ANALYSIS LIST FOR CURRENT PROJECT
# -------------------------

def fetch_analysis_list(session):
    """Return ONLY analyses containing '-Auto' in their name."""
    debug_print(f"Fetching analysis list from: {URL_ANALYSIS_LIST}")

    r = session.post(URL_ANALYSIS_LIST)
    
    debug_print(f"Analysis list status: {r.status_code}")
    
    if r.status_code != 200:
        print("Analysis/List failed:", r.status_code)
        debug_print(f"Response content: {r.text[:500]}")
        return []

    try:
        json_data = r.json()
        html = json_data.get("html", "")
        debug_print(f"Analysis HTML length: {len(html)}")
    except Exception as e:
        debug_print(f"Failed to parse analysis JSON: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    results = []
    all_analyses = []

    # Each analysis block is inside <div class="analysis-list-item ...">
    for block in soup.select("div.analysis-list-item"):
        block_id = block.get("id")  # e.g. alarm-list-item-1034
        if not block_id or not block_id.startswith("alarm-list-item-"):
            continue

        analysis_id = int(block_id.split("-")[-1])

        # Extract label text inside <a>
        a = block.find("a")
        if not a:
            continue

        name = a.text.strip()
        all_analyses.append((name, analysis_id))

        # >>> FILTER ONLY "-Auto" ANALYSES <<<
        if "L230 Col on 130th (dH) - Overall Chart" not in name:
            # debug_print(f"Skipping analysis (no -Auto): {analysis_id} - {name}")
            continue

        results.append((name, analysis_id))
        debug_print(f"Found -Auto analysis: {analysis_id} - {name}")

    debug_print(f"Total analyses found: {len(all_analyses)}, filtered -Auto: {len(results)}")
    return results


# -------------------------
#   LOAD ANALYSIS DATA
# -------------------------

def fetch_analysis_data(session, analysis_id):
    """
    Load the actual data for a specific analysis using LoadData API.
    POST: http://144.202.94.227/T4DWeb/Analysis/LoadData
    Payload: id=<analysis_id> (form-encoded)
    Response: JSON
    """
    debug_print(f"="*50)
    debug_print(f"Loading data for analysis ID: {analysis_id}")
    debug_print(f"POST {URL_ANALYSIS_LOAD_DATA}")
    debug_print(f"Payload: id={analysis_id}")
    
    # Form-encoded payload: id=1046
    payload = {"id": analysis_id}
    
    r = session.post(URL_ANALYSIS_LOAD_DATA, data=payload)
    
    debug_print(f"Response status: {r.status_code}")
    debug_print(f"Response Content-Type: {r.headers.get('Content-Type', 'N/A')}")
    debug_print(f"Response length: {len(r.text)} bytes")
    
    if r.status_code != 200:
        print(f"Analysis/LoadData failed for {analysis_id}: {r.status_code}")
        debug_print(f"Response body: {r.text[:500]}")
        return None
    
    # Check if we need to re-login
    if "Sign In</a>" in r.text or "Account__Logon" in r.text:
        debug_print("Session expired during LoadData, re-logging in...")
        session = login(session)
        r = session.post(URL_ANALYSIS_LOAD_DATA, data=payload)
        debug_print(f"Retry LoadData status: {r.status_code}")
    
    try:
        json_data = r.json()
        debug_print(f"JSON parsed successfully!")
        debug_print(f"JSON type: {type(json_data).__name__}")
        
        if isinstance(json_data, dict):
            debug_print(f"JSON keys: {list(json_data.keys())}")
            # Show structure of each key
            for key, value in json_data.items():
                if isinstance(value, list):
                    debug_print(f"  '{key}': list[{len(value)}]")
                    if value and len(value) > 0:
                        debug_print(f"    First item type: {type(value[0]).__name__}")
                        if isinstance(value[0], dict):
                            debug_print(f"    First item keys: {list(value[0].keys())[:10]}")
                elif isinstance(value, dict):
                    debug_print(f"  '{key}': dict with keys {list(value.keys())[:5]}")
                else:
                    debug_print(f"  '{key}': {type(value).__name__} = {str(value)[:80]}")
        elif isinstance(json_data, list):
            debug_print(f"JSON is a list with {len(json_data)} items")
            if json_data:
                debug_print(f"First item: {json_data[0]}")
        
        debug_print(f"Raw JSON preview: {r.text[:1000]}")
        return json_data
        
    except Exception as e:
        debug_print(f"Failed to parse JSON: {e}")
        debug_print(f"Raw response: {r.text[:1000]}")
        return None


# -------------------------
#   THRESHOLD VIOLATION CHECK
# -------------------------

def _create_violation_record(sensor_id, sensor_name, obs, threshold_name, min_value, max_value, 
                             is_symmetrical, violation_type, description):
    """Create a violation alarm record."""
    return {
        "device_id": sensor_id or sensor_name,
        "sensor_name": sensor_name,
        "alarm_description": description,
        "alarm_type": "value_exceeded_threshold",
        "issue_start_time": obs.get("FormattedEndDateLocalString"),  # Use FormattedEndDateLocalString instead of EndDateUTC
        "FormattedEndDateLocalString": obs.get("FormattedEndDateLocalString"),  # For date grouping
        "last_alarm_sent_time": datetime.now(timezone.utc).isoformat(),
        "current_value": obs.get("ConvertedValue"),
        "formatted_value": obs.get("FormattedValue"),
        "threshold_name": threshold_name,
        "threshold_max": max_value,
        "threshold_min": min_value,
        "is_symmetrical": is_symmetrical,
        "violation_type": violation_type
    }


def _is_within_time_window(timestamp_str, hours=None, days=None):
    """
    Check if a timestamp is within the configured time window.
    Uses TIME_WINDOW_MODE to determine if checking hours or days.
    
    Args:
        timestamp_str: Timestamp string in various formats
        hours: Number of hours to check (optional, uses config if not provided)
        days: Number of days to check (optional, uses config if not provided)
    
    Returns:
        True if timestamp is within the time window, False otherwise
    """
    if not timestamp_str:
        return False
    
    # Use provided values or fall back to config
    if hours is None and days is None:
        if TIME_WINDOW_MODE == "hours":
            hours = TIME_WINDOW_HOURS
        else:
            days = TIME_WINDOW_DAYS
    
    try:
        # Parse the timestamp string
        if isinstance(timestamp_str, str):
            # Handle ISO format with timezone
            if "T" in timestamp_str:
                if timestamp_str.endswith("Z"):
                    timestamp_str_parsed = timestamp_str.replace("Z", "+00:00")
                elif "+" in timestamp_str or timestamp_str.count("-") > 2:
                    timestamp_str_parsed = timestamp_str
                else:
                    timestamp_str_parsed = timestamp_str + "+00:00"
                
                try:
                    timestamp = datetime.fromisoformat(timestamp_str_parsed)
                except ValueError:
                    # Try parsing without microseconds
                    timestamp_str_parsed = timestamp_str_parsed.split(".")[0] + "+00:00"
                    timestamp = datetime.fromisoformat(timestamp_str_parsed)
            else:
                # Try different date formats
                # Handle format like "2025-10-29 16:55:15" (YYYY-MM-DD)
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Handle format like "10/25/2025 10:48:45" (MM/DD/YYYY)
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%m/%d/%Y %H:%M:%S")
                    except ValueError:
                        # Try format like "10/25/2025" (MM/DD/YYYY without time)
                        try:
                            timestamp = datetime.strptime(timestamp_str, "%m/%d/%Y")
                        except ValueError:
                            # Try format like "2025-10-29" (YYYY-MM-DD without time)
                            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d")
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            return False
        
        # Ensure timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        # Calculate time difference
        current_time = datetime.now(timezone.utc)
        time_diff = current_time - timestamp
        
        # Check if within time window
        if hours is not None:
            return time_diff <= timedelta(hours=hours)
        else:
            return time_diff <= timedelta(days=days)
    except Exception as e:
        debug_print(f"Error parsing timestamp {timestamp_str}: {e}")
        return False


def _check_if_violates_threshold(value, min_value, max_value, is_symmetrical):
    """
    Check if a value violates the threshold.
    Returns (violation_type, abs_value_if_symmetrical) or None if no violation.
    """
    if value is None:
        return None
    
    if is_symmetrical:
        # Symmetrical: check if absolute value exceeds max
        abs_value = abs(value)
        if abs_value > max_value:
            direction = "above" if value > 0 else "below"
            return (f"exceeds_maximum_{direction}", abs_value)
    else:
        # Non-symmetrical: check if outside min-max range
        if value > max_value:
            return ("above_maximum", None)
        elif value < min_value:
            return ("below_minimum", None)
    
    return None


def _get_all_sensor_observations(data, sensor_id_to_name):
    """
    Extract all observations from all sensors.
    Returns list of (sensor_id, sensor_name, observations) tuples.
    """
    sensors_data = []
    series_list = data.get("Series", [])
    
    for series in series_list:
        sensor_obs = series.get("SensorValueObservations")
        if not sensor_obs:
            continue
        
        sensor_id = sensor_obs.get("SensorID")
        sensor_name = sensor_id_to_name.get(sensor_id, sensor_obs.get("SensorName", f"Sensor-{sensor_id}"))
        observations = sensor_obs.get("ValueObservations", [])
        
        if observations:
            sensors_data.append((sensor_id, sensor_name, observations))
    
    return sensors_data


def check_threshold_violations(analysis_data, device_statuses):
    """
    Check if device values exceed target thresholds (PlotBands or YLimits).
    Checks ALL observations for each device, not just the last one.
    
    Args:
        analysis_data: The analysis data dictionary from LoadData API (full response)
        device_statuses: List of device status dictionaries (used for sensor name mapping)
    
    Returns:
        List of threshold violation alarms (one per violating observation)
    """
    # Validate input
    if not analysis_data or not isinstance(analysis_data, dict):
        return []
    
    data = analysis_data.get("data", {})
    if not data:
        return []
    
    # Build sensor name mapping
    sensor_id_to_name = {
        device.get("sensor_id"): device.get("sensor_name", f"Sensor-{device.get('sensor_id')}")
        for device in device_statuses
        if device.get("sensor_id")
    }
    
    # Get all sensor observations
    sensors_data = _get_all_sensor_observations(data, sensor_id_to_name)
    threshold_violations = []
    
    # Check PlotBands (primary thresholds)
    plot_bands = data.get("PlotBands", [])
    for plot_band in plot_bands:
        min_value = plot_band.get("ConvertedFromValue") or plot_band.get("FromValue")
        max_value = plot_band.get("ConvertedToValue") or plot_band.get("ToValue")
        threshold_name = plot_band.get("Name", "Threshold")
        is_symmetrical = plot_band.get("Symmetrical", False)
        
        if min_value is None or max_value is None:
            continue
        
        # Check each sensor's observations (only from last 5 days to avoid huge counts)
        for sensor_id, sensor_name, observations in sensors_data:
            for obs in observations:
                # Only check observations within configured time window
                obs_timestamp = obs.get("FormattedEndDateLocalString") or obs.get("EndDateUTC")
                if not obs_timestamp or not _is_within_time_window(obs_timestamp):
                    continue
                
                value = obs.get("ConvertedValue")
                result = _check_if_violates_threshold(value, min_value, max_value, is_symmetrical)
                
                if result:
                    violation_type, abs_value = result
                    formatted_value = obs.get("FormattedValue", value)
                    
                    # Build description
                    if is_symmetrical:
                        description = f"Value {formatted_value} exceeds {threshold_name} threshold (max: ±{max_value} ft, current: {abs_value:.4f} ft)"
                    elif violation_type == "above_maximum":
                        description = f"Value {formatted_value} exceeds {threshold_name} threshold (max: {max_value})"
                    else:  # below_minimum
                        description = f"Value {formatted_value} below {threshold_name} threshold (min: {min_value})"
                    
                    violation = _create_violation_record(
                        sensor_id, sensor_name, obs, threshold_name, min_value, max_value,
                        is_symmetrical, violation_type, description
                    )
                    threshold_violations.append(violation)
    
    # Check YLimits (fallback if no PlotBands)
    if not plot_bands:
        y_limits_json = data.get("YLimitsJSON")
        if y_limits_json:
            try:
                y_limits = json.loads(y_limits_json)
                if isinstance(y_limits, list) and y_limits:
                    y_limit = y_limits[0]
                    min_value = y_limit.get("min")
                    max_value = y_limit.get("max")
                    
                    if min_value is not None or max_value is not None:
                        for sensor_id, sensor_name, observations in sensors_data:
                            for obs in observations:
                                # Only check observations within configured time window
                                obs_timestamp = obs.get("FormattedEndDateLocalString") or obs.get("EndDateUTC")
                                if not obs_timestamp or not _is_within_time_window(obs_timestamp):
                                    continue
                                
                                value = obs.get("ConvertedValue")
                                result = _check_if_violates_threshold(value, min_value, max_value, False)
                                
                                if result:
                                    violation_type, _ = result
                                    formatted_value = obs.get("FormattedValue", value)
                                    
                                    # Build description
                                    if violation_type == "above_maximum":
                                        description = f"Value {formatted_value} exceeds Y-axis limit (max: {max_value})"
                                    else:  # below_minimum
                                        description = f"Value {formatted_value} below Y-axis limit (min: {min_value})"
                                    
                                    violation = _create_violation_record(
                                        sensor_id, sensor_name, obs, "Y-Limit", min_value, max_value,
                                        False, violation_type, description
                                    )
                                    threshold_violations.append(violation)
            except Exception as e:
                debug_print(f"Error parsing YLimitsJSON: {e}")
    
    debug_print(f"Found {len(threshold_violations)} threshold violations")
    return threshold_violations


# -------------------------
#   DEVICE STATUS CHECK
# -------------------------

def check_device_status(analysis_data, fallback_hours_threshold=24):
    """
    Check if devices are down or running based on the last 2 observations and current time.
    Uses the actual time interval between the last 2 observations as the threshold.
    If time from last observation to current time > interval between last 2 observations,
    then device is considered down.
    
    Args:
        analysis_data: The analysis data dictionary from LoadData API
        fallback_hours_threshold: Fallback threshold in hours if only 1 observation exists
    
    Returns:
        Dictionary with device status information
    """
    if not analysis_data or not isinstance(analysis_data, dict):
        return None
    
    # Navigate to the actual data
    data = analysis_data.get("data", {})
    if not data:
        return None
    
    series_list = data.get("Series", [])
    if not series_list:
        return None
    
    current_time_utc = datetime.now(timezone.utc)
    device_statuses = []
    
    for series in series_list:
        sensor_obs = series.get("SensorValueObservations")
        if not sensor_obs:
            continue
        
        sensor_id = sensor_obs.get("SensorID")
        sensor_name = sensor_obs.get("SensorName", f"Sensor-{sensor_id}")
        value_observations = sensor_obs.get("ValueObservations", [])
        
        if not value_observations:
            device_statuses.append({
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "status": "down",
                "reason": "No observations found",
                "last_observation": None,
                "last_2_observations": []
            })
            continue
        
        # Get last 2 observations (most recent last in the list)
        if len(value_observations) < 1:
            device_statuses.append({
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "status": "unknown",
                "reason": "No observations available",
                "last_observation": None,
                "last_2_observations": []
            })
            continue
        
        # Get the last observation (most recent)
        last_obs = value_observations[-1]
        # Use EndDateUTC for time calculations, but FormattedEndDateLocalString for display
        last_obs_time_str_utc = last_obs.get("EndDateUTC")  # For time calculations
        last_obs_time_str = last_obs.get("FormattedEndDateLocalString") or last_obs.get("EndDateUTC")  # For display/storage
        
        if not last_obs_time_str_utc:
            device_statuses.append({
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "status": "unknown",
                "reason": "No timestamp in last observation",
                "last_observation": None,
                "last_2_observations": []
            })
            continue
        
        # Parse the last observation timestamp (use UTC for calculations)
        try:
            # Handle both ISO format and other formats (using UTC string for calculations)
            if "T" in last_obs_time_str_utc:
                # Remove Z and add timezone if not present
                if last_obs_time_str_utc.endswith("Z"):
                    last_obs_time_str_parsed = last_obs_time_str_utc.replace("Z", "+00:00")
                elif "+" in last_obs_time_str_utc or last_obs_time_str_utc.count("-") > 2:
                    # Already has timezone info
                    last_obs_time_str_parsed = last_obs_time_str_utc
                else:
                    # No timezone info, assume UTC
                    last_obs_time_str_parsed = last_obs_time_str_utc + "+00:00"
                
                try:
                    last_obs_time = datetime.fromisoformat(last_obs_time_str_parsed)
                except ValueError:
                    # Try parsing without microseconds
                    last_obs_time_str_parsed = last_obs_time_str_parsed.split(".")[0] + "+00:00"
                    last_obs_time = datetime.fromisoformat(last_obs_time_str_parsed)
                
                # Ensure timezone-aware
                if last_obs_time.tzinfo is None:
                    last_obs_time = last_obs_time.replace(tzinfo=timezone.utc)
            else:
                # Try different date formats
                try:
                    last_obs_time = datetime.strptime(last_obs_time_str_utc, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Try MM/DD/YYYY format
                    try:
                        last_obs_time = datetime.strptime(last_obs_time_str_utc, "%m/%d/%Y %H:%M:%S")
                    except ValueError:
                        # Try date only formats
                        try:
                            last_obs_time = datetime.strptime(last_obs_time_str_utc, "%m/%d/%Y")
                        except ValueError:
                            last_obs_time = datetime.strptime(last_obs_time_str_utc, "%Y-%m-%d")
                last_obs_time = last_obs_time.replace(tzinfo=timezone.utc)
            
            # Calculate time from last observation to current time
            time_since_last = current_time_utc - last_obs_time
            hours_since_last = time_since_last.total_seconds() / 3600
            
            # Calculate the interval between last 2 observations
            if len(value_observations) >= 2:
                # Get the second-to-last observation
                second_last_obs = value_observations[-2]
                second_last_obs_time_str_utc = second_last_obs.get("EndDateUTC")  # For calculations
                second_last_obs_time_str = second_last_obs.get("FormattedEndDateLocalString") or second_last_obs.get("EndDateUTC")  # For display
                
                if second_last_obs_time_str_utc:
                    # Parse second-to-last observation timestamp (using UTC for calculations)
                    if "T" in second_last_obs_time_str_utc:
                        # Remove Z and add timezone if not present
                        if second_last_obs_time_str_utc.endswith("Z"):
                            second_last_obs_time_str_parsed = second_last_obs_time_str_utc.replace("Z", "+00:00")
                        elif "+" in second_last_obs_time_str_utc or second_last_obs_time_str_utc.count("-") > 2:
                            # Already has timezone info
                            second_last_obs_time_str_parsed = second_last_obs_time_str_utc
                        else:
                            # No timezone info, assume UTC
                            second_last_obs_time_str_parsed = second_last_obs_time_str_utc + "+00:00"
                        
                        try:
                            second_last_obs_time = datetime.fromisoformat(second_last_obs_time_str_parsed)
                        except ValueError:
                            # Try parsing without microseconds
                            second_last_obs_time_str_parsed = second_last_obs_time_str_parsed.split(".")[0] + "+00:00"
                            second_last_obs_time = datetime.fromisoformat(second_last_obs_time_str_parsed)
                        
                        # Ensure timezone-aware
                        if second_last_obs_time.tzinfo is None:
                            second_last_obs_time = second_last_obs_time.replace(tzinfo=timezone.utc)
                    else:
                        # Try different date formats
                        try:
                            second_last_obs_time = datetime.strptime(second_last_obs_time_str_utc, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            # Try MM/DD/YYYY format
                            try:
                                second_last_obs_time = datetime.strptime(second_last_obs_time_str_utc, "%m/%d/%Y %H:%M:%S")
                            except ValueError:
                                # Try date only formats
                                try:
                                    second_last_obs_time = datetime.strptime(second_last_obs_time_str_utc, "%m/%d/%Y")
                                except ValueError:
                                    second_last_obs_time = datetime.strptime(second_last_obs_time_str_utc, "%Y-%m-%d")
                        second_last_obs_time = second_last_obs_time.replace(tzinfo=timezone.utc)
                    
                    # Calculate interval between last 2 observations
                    interval_between_obs = last_obs_time - second_last_obs_time
                    hours_interval = interval_between_obs.total_seconds() / 3600
                    
                    # Print last two observation times
                    print(f"      Device {sensor_name} (ID: {sensor_id}):")
                    print(f"        Last 2 observations:")
                    print(f"          - 2nd to last: {second_last_obs_time_str} ({second_last_obs_time.isoformat()})")
                    print(f"          - Last: {last_obs_time_str} ({last_obs_time.isoformat()})")
                    print(f"        Interval between last 2: {hours_interval:.2f} hours")
                    print(f"        Time since last observation: {hours_since_last:.2f} hours")
                    
                    # Determine status: if time since last > interval between last 2, device is down
                    if hours_since_last > hours_interval:
                        status = "down"
                        reason = f"Time since last observation ({hours_since_last:.2f} hours) exceeds the interval between last 2 observations ({hours_interval:.2f} hours)"
                    else:
                        status = "running"
                        reason = f"Time since last observation ({hours_since_last:.2f} hours) is within the interval between last 2 observations ({hours_interval:.2f} hours)"
                    
                    print(f"        Status: {status.upper()}")
                    
                    device_statuses.append({
                        "sensor_id": sensor_id,
                        "sensor_name": sensor_name,
                        "status": status,
                        "reason": reason,
                        "last_observation": last_obs_time_str,
                        "last_observation_time": last_obs_time.isoformat(),
                        "hours_since_last": round(hours_since_last, 2),
                        "interval_between_last_2_obs_hours": round(hours_interval, 2),
                        "last_2_observations": [
                            {
                                "timestamp": second_last_obs.get("FormattedEndDateLocalString") or second_last_obs.get("EndDateUTC"),
                                "value": value_observations[-2].get("ConvertedValue"),
                                "formatted_value": value_observations[-2].get("FormattedValue")
                            },
                            {
                                "timestamp": last_obs_time_str,
                                "value": last_obs.get("ConvertedValue"),
                                "formatted_value": last_obs.get("FormattedValue")
                            }
                        ]
                    })
                else:
                    # Second-to-last observation has no timestamp, use fallback
                    print(f"      Device {sensor_name} (ID: {sensor_id}):")
                    print(f"        Last observation: {last_obs_time_str} ({last_obs_time.isoformat()})")
                    print(f"        Time since last observation: {hours_since_last:.2f} hours")
                    print(f"        Note: Could not calculate interval (2nd to last observation has no timestamp)")
                    if hours_since_last > fallback_hours_threshold:
                        status = "down"
                        reason = f"Last observation was {hours_since_last:.2f} hours ago (using fallback threshold: {fallback_hours_threshold} hours - could not calculate interval)"
                    else:
                        status = "running"
                        reason = f"Last observation was {hours_since_last:.2f} hours ago (using fallback threshold: {fallback_hours_threshold} hours - could not calculate interval)"
                    print(f"        Status: {status.upper()}")
                    
                    device_statuses.append({
                        "sensor_id": sensor_id,
                        "sensor_name": sensor_name,
                        "status": status,
                        "reason": reason,
                        "last_observation": last_obs_time_str,
                        "last_observation_time": last_obs_time.isoformat(),
                        "hours_since_last": round(hours_since_last, 2),
                        "interval_between_last_2_obs_hours": None,
                        "last_2_observations": [
                            {
                                "timestamp": last_obs_time_str,
                                "value": last_obs.get("ConvertedValue"),
                                "formatted_value": last_obs.get("FormattedValue")
                            }
                        ]
                    })
            else:
                # Only 1 observation available, use fallback threshold
                print(f"      Device {sensor_name} (ID: {sensor_id}):")
                print(f"        Last observation: {last_obs_time_str} ({last_obs_time.isoformat()})")
                print(f"        Time since last observation: {hours_since_last:.2f} hours")
                print(f"        Note: Only 1 observation available, using fallback threshold: {fallback_hours_threshold} hours")
                if hours_since_last > fallback_hours_threshold:
                    status = "down"
                    reason = f"Last observation was {hours_since_last:.2f} hours ago (using fallback threshold: {fallback_hours_threshold} hours - only 1 observation available)"
                else:
                    status = "running"
                    reason = f"Last observation was {hours_since_last:.2f} hours ago (using fallback threshold: {fallback_hours_threshold} hours - only 1 observation available)"
                print(f"        Status: {status.upper()}")
                
                device_statuses.append({
                    "sensor_id": sensor_id,
                    "sensor_name": sensor_name,
                    "status": status,
                    "reason": reason,
                    "last_observation": last_obs_time_str,
                    "last_observation_time": last_obs_time.isoformat(),
                    "hours_since_last": round(hours_since_last, 2),
                    "interval_between_last_2_obs_hours": None,
                    "last_2_observations": [
                        {
                            "timestamp": last_obs_time_str,
                            "value": last_obs.get("ConvertedValue"),
                            "formatted_value": last_obs.get("FormattedValue")
                        }
                    ]
                })
        except Exception as e:
            # Get last 2 observations for error reporting
            last_2_obs_data = []
            if len(value_observations) >= 2:
                last_2_obs_data = [
                    {
                        "timestamp": value_observations[-2].get("FormattedEndDateLocalString") or value_observations[-2].get("EndDateUTC"),
                        "value": value_observations[-2].get("ConvertedValue"),
                        "formatted_value": value_observations[-2].get("FormattedValue")
                    },
                    {
                        "timestamp": last_obs_time_str,
                        "value": last_obs.get("ConvertedValue"),
                        "formatted_value": last_obs.get("FormattedValue")
                    }
                ]
            elif len(value_observations) >= 1:
                last_2_obs_data = [
                    {
                        "timestamp": last_obs_time_str,
                        "value": last_obs.get("ConvertedValue"),
                        "formatted_value": last_obs.get("FormattedValue")
                    }
                ]
            
            device_statuses.append({
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "status": "error",
                "reason": f"Error parsing timestamp: {str(e)}",
                "last_observation": last_obs_time_str,
                "last_2_observations": last_2_obs_data
            })
    
    return {
        "analysis_id": data.get("ID"),
        "analysis_name": data.get("Name"),
        "check_time_utc": current_time_utc.isoformat(),
        "fallback_hours_threshold": fallback_hours_threshold,
        "devices": device_statuses,
        "total_devices": len(device_statuses),
        "running_count": sum(1 for d in device_statuses if d["status"] == "running"),
        "down_count": sum(1 for d in device_statuses if d["status"] == "down"),
        "unknown_count": sum(1 for d in device_statuses if d["status"] in ["unknown", "error"])
    }


# -------------------------
#   MAIN ORCHESTRATION
# -------------------------

def main():
    """Main function to run T4D analysis monitoring."""
    print("=" * 50)
    print("T4D Web Scraper - Debug Mode")
    print("=" * 50)
    
    session = load_or_create_session()
    
    # Optional: Force fresh login for testing
    # debug_print("Forcing fresh login for testing...")
    # session = login(session)

    # STEP 1 — Get project list
    projects = fetch_projects(session)
    print("\n=== PROJECT LIST ===")
    for pid, name in projects:
        print(f"{pid}: {name}")

    all_data = {}

    # STEP 2 — Loop each project and extract filtered analyses
    for pid, pname in projects:
        print(f"\n---- Switching to Project {pid}: {pname} ----")
        switch_project(session, pid)

        analyses = fetch_analysis_list(session)

        print(f"Found {len(analyses)} -Auto analyses:")
        for a_name, a_id in analyses:
            print(f"  {a_id}: {a_name}")

        # STEP 3 — Load data for each analysis and check device status
        analyses_with_data = []
        for a_name, a_id in analyses:
            print(f"\n  Loading data for: {a_name} (ID: {a_id})")
            data = fetch_analysis_data(session, a_id)
            
            # Check device status based on last 2 observations and current time
            device_status = None
            threshold_violations = []
            if data:
                print(f"    Checking device status...")
                device_status = check_device_status(data, fallback_hours_threshold=24)
                if device_status:
                    print(f"    Devices: {device_status['running_count']} running, {device_status['down_count']} down, {device_status['unknown_count']} unknown")
                    
                    # Check for threshold violations
                    print(f"    Checking threshold violations...")
                    # Pass the full analysis_data (not just data) to check_threshold_violations
                    threshold_violations = check_threshold_violations(data, device_status.get("devices", []))
                    if threshold_violations:
                        print(f"    Found {len(threshold_violations)} threshold violation(s)")
                        for v in threshold_violations:
                            print(f"      - {v.get('sensor_name')}: {v.get('alarm_description')}")
            
            analyses_with_data.append({
                "id": a_id,
                "name": a_name,
                "data": data,
                "device_status": device_status,
                "threshold_violations": threshold_violations
            })

        all_data[pid] = {
            "project_name": pname,
            "analyses": analyses_with_data
        }

    print("\n\n===== FINAL AUTO-ANALYSIS STRUCTURE =====")
    all_device_statuses = []
    for pid, data in all_data.items():
        print(f"\nProject {pid}: {data['project_name']}")
        for analysis in data["analyses"]:
            a_id = analysis["id"]
            a_name = analysis["name"]
            a_data = analysis["data"]
            device_status = analysis.get("device_status")
            has_data = "YES" if a_data else "NO"
            status_summary = ""
            if device_status:
                status_summary = f" [Devices: {device_status['running_count']} running, {device_status['down_count']} down]"
            print(f"   {a_id}: {a_name} [Data: {has_data}]{status_summary}")
            if device_status:
                all_device_statuses.append(device_status)
    
    # Extract chart data: sensors and thresholds
    print(f"\n===== EXTRACTING CHART DATA (SENSORS AND THRESHOLDS) =====")
    sensors_data = []  # Flat table format: one row per observation
    thresholds_data = []  # Flat table format: one row per threshold
    try:
        
        for pid, project_data in all_data.items():
            project_name = project_data.get("project_name")
            
            for analysis in project_data.get("analyses", []):
                analysis_id = analysis.get("id")
                analysis_name = analysis.get("name")
                raw_data = analysis.get("data")
                
                if not raw_data:
                    continue
                
                data = raw_data.get("data", {})
                if not data:
                    continue
                
                # Extract thresholds (PlotBands) - flat table format
                plot_bands = data.get("PlotBands", [])
                for plot_band in plot_bands:
                    min_val = plot_band.get("ConvertedFromValue") or plot_band.get("FromValue")
                    max_val = plot_band.get("ConvertedToValue") or plot_band.get("ToValue")
                    if min_val is not None or max_val is not None:
                        threshold_row = {
                            "project_id": pid,
                            "device_id": analysis_id,
                            "threshold_name": plot_band.get("Name", "Threshold"),
                            "min_value": min_val,
                            "max_value": max_val
                        }
                        thresholds_data.append(threshold_row)
                
                # Extract YLimits if no PlotBands
                if not plot_bands:
                    y_limits_json = data.get("YLimitsJSON")
                    if y_limits_json:
                        try:
                            y_limits = json.loads(y_limits_json)
                            if isinstance(y_limits, list) and y_limits:
                                y_limit = y_limits[0]
                                min_val = y_limit.get("min")
                                max_val = y_limit.get("max")
                                if min_val is not None or max_val is not None:
                                    threshold_row = {
                                        "project_id": pid,
                                        "device_id": analysis_id,
                                        "threshold_name": "Y-Limit",
                                        "min_value": min_val,
                                        "max_value": max_val
                                    }
                                    thresholds_data.append(threshold_row)
                        except Exception as e:
                            debug_print(f"Error parsing YLimitsJSON: {e}")
                
                # Extract sensor time series data - flat table format
                series_list = data.get("Series", [])
                for series in series_list:
                    sensor_obs = series.get("SensorValueObservations")
                    if not sensor_obs:
                        continue
                    
                    sensor_id = sensor_obs.get("SensorID")
                    sensor_name = sensor_obs.get("SensorName", f"Sensor-{sensor_id}")
                    observations = sensor_obs.get("ValueObservations", [])
                    
                    # Create one row per observation
                    for obs in observations:
                        sensor_row = {
                            "project_id": pid,
                            "project_name": project_name,
                            "device_id": analysis_id,
                            "device_name": analysis_name,
                            "sensor_id": sensor_id,
                            "sensor_name": sensor_name,
                            "timestamp": obs.get("FormattedEndDateLocalString") or obs.get("EndDateUTC"),
                            "value": obs.get("ConvertedValue")
                        }
                        sensors_data.append(sensor_row)
        
        print(f"Extracted {len(sensors_data)} sensor observation records and {len(thresholds_data)} threshold records")
    except Exception as e:
        print(f"Error extracting chart data: {e}")
    
    # Collect all down devices and threshold violations, save in alarm format
    # Time window based on TIME_WINDOW_MODE configuration
    time_window_str = f"{TIME_WINDOW_HOURS} hours" if TIME_WINDOW_MODE == "hours" else f"{TIME_WINDOW_DAYS} days"
    print(f"\n===== CHECKING FOR DOWN DEVICES AND THRESHOLD VIOLATIONS (LAST {time_window_str.upper()}) =====")
    down_devices_alarms = []
    current_time = datetime.now(timezone.utc)
    
    # Collect threshold violations from all analyses
    all_threshold_violations = []
    for pid, project_data in all_data.items():
        for analysis in project_data.get("analyses", []):
            violations = analysis.get("threshold_violations", [])
            if violations:
                analysis_id = analysis.get("id")
                analysis_name = analysis.get("name", "").strip()
                # Add analysis context to violations and filter by date
                for violation in violations:
                    violation["analysis_id"] = analysis_id
                    violation["analysis_name"] = analysis_name
                    # Only include violations within configured time window
                    issue_time = violation.get("issue_start_time")
                    if issue_time and _is_within_time_window(issue_time):
                        all_threshold_violations.append(violation)
    
    # Add threshold violations to alarms
    down_devices_alarms.extend(all_threshold_violations)
    
    # Collect down devices (only those that went down within last 5 days)
    # Check if all sensors are down (device down) vs only some sensors down
    for device_status in all_device_statuses:
        analysis_id = device_status.get("analysis_id")
        analysis_name = device_status.get("analysis_name", "").strip()
        all_devices = device_status.get("devices", [])
        
        # Filter devices that are down and within configured time window
        down_sensors = []
        for device in all_devices:
            if device.get("status") == "down":
                issue_start_time = device.get("last_observation_time") or device.get("last_observation")
                
                # Only include if the device went down within configured time window
                if issue_start_time and _is_within_time_window(issue_start_time):
                    down_sensors.append(device)
        
        # Check if all sensors in this analysis are down
        total_sensors = len(all_devices)
        down_sensors_count = len(down_sensors)
        
        if down_sensors_count == 0:
            # No down sensors, skip
            continue
        
        # If all sensors are down, create a device_down alarm
        if down_sensors_count == total_sensors and total_sensors > 0:
            # All sensors are down - device is down
            # Get earliest issue_start_time from all down sensors
            issue_times = []
            sensor_details = []
            for sensor in down_sensors:
                issue_time = sensor.get("last_observation_time") or sensor.get("last_observation")
                if issue_time:
                    issue_times.append(str(issue_time))
                sensor_id = sensor.get("sensor_id") or sensor.get("sensor_name", "unknown")
                sensor_name = sensor.get("sensor_name", f"Sensor-{sensor_id}")
                sensor_details.append(f"  Sensor ID {sensor_id} ({sensor_name}): {sensor.get('reason', 'Device is down')}")
            
            device_issue_start_time = min(issue_times) if issue_times else current_time.isoformat()
            device_description = f"Device is down:\n" + "\n".join(sensor_details)
            
            down_devices_alarms.append({
                "device_id": analysis_id,  # Use analysis_id as device_id when all sensors are down
                "alarm_description": device_description,
                "alarm_type": "device_down",
                "issue_start_time": device_issue_start_time,
                "last_alarm_sent_time": current_time.isoformat(),
                "analysis_id": analysis_id,
                "analysis_name": analysis_name
            })
        else:
            # Only some sensors are down - create sensor_down alarms for individual sensors
            for sensor in down_sensors:
                issue_start_time = sensor.get("last_observation_time") or sensor.get("last_observation")
                sensor_id = sensor.get("sensor_id") or sensor.get("sensor_name", "unknown")
                alarm_description = sensor.get("reason", "Sensor is down")
                
                down_devices_alarms.append({
                    "device_id": sensor_id,  # Use sensor_id for individual sensor alarms
                    "alarm_description": alarm_description,
                    "alarm_type": "sensor_down",
                    "issue_start_time": issue_start_time,
                    "last_alarm_sent_time": current_time.isoformat(),
                    "sensor_name": sensor.get("sensor_name"),
                    "analysis_id": analysis_id,
                    "analysis_name": analysis_name,
                    "hours_since_last": sensor.get("hours_since_last"),
                    "interval_between_last_2_obs_hours": sensor.get("interval_between_last_2_obs_hours")
                })
    
    # Print summary of collected alarms
    if down_devices_alarms:
        device_down_count = sum(1 for a in down_devices_alarms if a.get("alarm_type") == "device_down")
        sensor_down_count = sum(1 for a in down_devices_alarms if a.get("alarm_type") == "sensor_down")
        threshold_count = sum(1 for a in down_devices_alarms if a.get("alarm_type") == "value_exceeded_threshold")
        time_window_str = f"{TIME_WINDOW_HOURS} hours" if TIME_WINDOW_MODE == "hours" else f"{TIME_WINDOW_DAYS} days"
        print(f"\nFound {device_down_count} device(s) down, {sensor_down_count} sensor(s) down, and {threshold_count} threshold violation(s) (from last {time_window_str})")
    else:
        print("No down devices or threshold violations found.")
    
    # Group alarms by analysis_id (used as device_id) and combine all sensor messages in alarm_description
    # Time window based on TIME_WINDOW_MODE configuration
    time_window_str = f"{TIME_WINDOW_HOURS} hours" if TIME_WINDOW_MODE == "hours" else f"{TIME_WINDOW_DAYS} days"
    print(f"\n===== PROCESSING ALL ALARMS (GROUPED BY ANALYSIS_ID, LAST {time_window_str.upper()}) =====")
    try:
        # Group all alarms by: device_id (analysis_id) and alarm_type only
        # Key format: (analysis_id, alarm_type)
        alarms_by_group = {}
        
        for alarm in down_devices_alarms:
            alarm_type = alarm.get("alarm_type")
            analysis_id = alarm.get("analysis_id")
            
            if not analysis_id:
                continue
            
            # Create grouping key: (analysis_id, alarm_type) only
            group_key = (analysis_id, alarm_type)
            
            if group_key not in alarms_by_group:
                alarms_by_group[group_key] = {
                    "device_id": analysis_id,  # Always use analysis_id as device_id
                    "alarm_type": alarm_type,
                    "analysis_name": alarm.get("analysis_name", ""),
                    "alarms": []
                }
            
            # Store the alarm data
            alarms_by_group[group_key]["alarms"].append(alarm)
        
        # Create final alarm records grouped by (analysis_id, alarm_type, date)
        grouped_alarms = []
        
        for (analysis_id, alarm_type), group_data in alarms_by_group.items():
            alarms_in_group = group_data["alarms"]
            analysis_name = group_data.get("analysis_name", "")
            
            if not alarms_in_group:
                continue
            
            # Build description based on alarm type
            description_parts = []
            issue_times = []
            
            if alarm_type == "device_down":
                # Device down: all sensors are down
                # Get sensor details from the first alarm's description
                if alarms_in_group:
                    first_alarm_desc = alarms_in_group[0].get("alarm_description", "")
                    if "Sensor ID" in first_alarm_desc:
                        # Extract sensor information
                        sensor_lines = [line.strip() for line in first_alarm_desc.split("\n") if "Sensor ID" in line]
                        sensor_count = len(sensor_lines)
                        description_parts.append(f"Device is down - All {sensor_count} sensor(s) are down")
                        # Add sensor names
                        for line in sensor_lines[:5]:  # Show first 5 sensors
                            if "Sensor ID" in line:
                                # Extract sensor name from line like "Sensor ID 646 (Col-01B): ..."
                                parts = line.split("(")
                                if len(parts) > 1:
                                    sensor_name = parts[1].split(")")[0]
                                    description_parts.append(f"  - {sensor_name}")
                        if sensor_count > 5:
                            description_parts.append(f"  ... and {sensor_count - 5} more sensor(s)")
                    else:
                        description_parts.append("Device is down - All sensors are down")
                else:
                    description_parts.append("Device is down")
                
                # Collect all issue times
                for alarm_item in alarms_in_group:
                    issue_time = alarm_item.get("issue_start_time")
                    if issue_time:
                        issue_times.append(str(issue_time))
            
            elif alarm_type == "sensor_down":
                # Sensor down: some sensors are down
                sensor_count = len(alarms_in_group)
                description_parts.append(f"{sensor_count} sensor(s) down for this device:")
                
                for alarm_item in alarms_in_group:
                    sensor_id = alarm_item.get("device_id")  # This is sensor_id in the original alarm
                    sensor_name = alarm_item.get("sensor_name", f"Sensor-{sensor_id}")
                    message = alarm_item.get("alarm_description", "")
                    # Extract just the key part of the message (time since last observation)
                    if "Time since last observation" in message:
                        # Extract the hours part
                        hours_match = re.search(r'(\d+\.?\d*)\s+hours', message)
                        if hours_match:
                            hours = hours_match.group(1)
                            description_parts.append(f"  - {sensor_name}: Down for {hours} hours")
                        else:
                            description_parts.append(f"  - {sensor_name}: {message}")
                    else:
                        description_parts.append(f"  - {sensor_name}: {message}")
                    issue_time = alarm_item.get("issue_start_time")
                    if issue_time:
                        issue_times.append(str(issue_time))
            
            elif alarm_type == "value_exceeded_threshold":
                # Threshold violations - clear summary
                violation_count = len(alarms_in_group)
                description_parts.append(f"Threshold violations detected: {violation_count} total violation(s)")
                
                # Group violations by threshold name
                threshold_summary = {}
                for alarm_item in alarms_in_group:
                    threshold_name = alarm_item.get("threshold_name", "Unknown")
                    violation_type = alarm_item.get("violation_type", "")
                    if threshold_name not in threshold_summary:
                        threshold_summary[threshold_name] = {"count": 0, "types": set()}
                    threshold_summary[threshold_name]["count"] += 1
                    threshold_summary[threshold_name]["types"].add(violation_type)
                    issue_time = alarm_item.get("issue_start_time")
                    if issue_time:
                        issue_times.append(str(issue_time))
                
                # Add summary by threshold with violation types
                description_parts.append("Violations by threshold:")
                for threshold_name, summary in sorted(threshold_summary.items()):
                    count = summary["count"]
                    types = ", ".join(sorted(summary["types"]))
                    description_parts.append(f"  - {threshold_name}: {count} violation(s) ({types})")
            
            alarm_description = "\n".join(description_parts)
            issue_start_time = min(issue_times) if issue_times else current_time.isoformat()
            
            alarm_record = {
                "device_id": analysis_id,  # Always use analysis_id as device_id
                "alarm_description": alarm_description,
                "alarm_type": alarm_type,
                "issue_start_time": issue_start_time,
                "last_alarm_sent_time": current_time.isoformat()
            }
            
            grouped_alarms.append(alarm_record)
        
        print(f"Successfully processed {len(grouped_alarms)} alarm record(s)")
        device_down_entries = 0
        threshold_entries = 0
        sensor_down_entries = 0
        total_threshold = 0
        total_sensor_down = 0
        total_device_down = 0
        
        if grouped_alarms:
            device_down_entries = sum(1 for a in grouped_alarms if a.get("alarm_type") == "device_down")
            threshold_entries = sum(1 for a in grouped_alarms if a.get("alarm_type") == "value_exceeded_threshold")
            sensor_down_entries = sum(1 for a in grouped_alarms if a.get("alarm_type") == "sensor_down")
            
            # Count total violations and sensors from original alarms
            for alarm in down_devices_alarms:
                alarm_type = alarm.get("alarm_type")
                if alarm_type == "value_exceeded_threshold":
                    total_threshold += 1
                elif alarm_type == "sensor_down":
                    total_sensor_down += 1
                elif alarm_type == "device_down":
                    total_device_down += 1
            
            print(f"  - {len(grouped_alarms)} alarm record(s) (grouped by device_id, alarm_type, and date)")
            print(f"  - {device_down_entries} device down entry/entries ({total_device_down} total)")
            print(f"  - {threshold_entries} threshold violation entry/entries ({total_threshold} total violations)")
            print(f"  - {sensor_down_entries} sensor down entry/entries ({total_sensor_down} total down sensors)")
            print(f"  - All alarms grouped by: device_id (analysis_id), alarm_type, and EndDateLocalString (date)")
        else:
            print("No alarms found")
        
        # Save final alarms to JSON file
        alarms_file = "alarms_output.json"
        print(f"\n===== SAVING FINAL ALARMS TO {alarms_file} =====")
        try:
            output_data = {
                "generated_at": current_time.isoformat(),
                "total_alarms": len(grouped_alarms),
                "summary": {
                    "device_down_count": device_down_entries,
                    "sensor_down_count": sensor_down_entries,
                    "threshold_violation_count": threshold_entries,
                    "total_sensors_down": total_sensor_down,
                    "total_threshold_violations": total_threshold
                },
                "alarms": grouped_alarms
            }
            
            with open(alarms_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, default=str, ensure_ascii=False)
            
            print(f"Successfully saved {len(grouped_alarms)} alarm record(s) to {alarms_file}")
        except Exception as e:
            print(f"Error saving alarms to JSON file: {e}")
        
        return {
            "alarms": grouped_alarms,
            "sensors_data": sensors_data,
            "thresholds_data": thresholds_data
        }
    except Exception as e:
        print(f"Error processing alarm data: {e}")
        return {
            "alarms": [],
            "sensors_data": sensors_data if 'sensors_data' in locals() else [],
            "thresholds_data": thresholds_data if 'thresholds_data' in locals() else []
        }




if __name__ == "__main__":
    main()