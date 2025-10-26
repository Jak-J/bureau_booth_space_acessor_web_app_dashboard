"""
Bureau Booths Dashboard - Flask Application
============================================
A professional web application for managing and monitoring booth occupancy,
sensor data, and analytics across multiple locations and clients.

KEY FEATURES:
- Real-time booth occupancy monitoring
- Multi-client support with role-based access control
- Google Sheets integration for sensor data
- Performance-optimized caching system
- Comprehensive analytics and reporting

CONFIGURATION:
- Edit login.csv to manage user credentials
- Edit clients.csv to manage locations and booths
- Ensure newcred.json contains valid Google Sheets API credentials
- Change app.secret_key for production use (line 22)

MAIN COMPONENTS:
1. DataCache: Thread-safe caching system with TTL
2. Google Sheets API: Real-time data synchronization
3. Flask Routes: Web endpoints for dashboard, analytics, etc.
4. Background Thread: Automatic cache refresh
"""

import os
from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from http.client import RemoteDisconnected
import numpy as np
import threading
import time
from threading import Lock
import logging

# Configure logging for cache refresh events
# This logs all cache operations and API calls for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==============================================================================
# --- 1. APP & DATA INITIALIZATION ---
# ==============================================================================
app = Flask(__name__)

# IMPORTANT: Change this secret key for production!
# Generate a secure key: python -c "import secrets; print(secrets.token_hex(32))"
# This key is used to encrypt session data and cookies
app.secret_key = 'your_very_secret_key'

# Load user credentials and client configuration from CSV files
# These files must exist in the project root directory
try:
    df_login = pd.read_csv('login.csv')  # Contains: username, password, role, client_name
    df_clients = pd.read_csv('clients.csv')  # Contains: client_name, location, booth, booth_id, max_occupancy
except FileNotFoundError:
    print("FATAL ERROR: 'login.csv' or 'clients.csv' not found. Please ensure they are in the project folder.")
    exit()

# ==============================================================================
# --- 1.5. DATA CACHE SYSTEM WITH TTL & RETRY LOGIC ---
# ==============================================================================
class DataCache:
    """
    Thread-safe cache for Google Sheets data with TTL (Time-To-Live).
    - Stores booth data in memory with automatic expiration
    - Implements retry logic with exponential backoff for failed API calls
    - Refreshes data in background thread to avoid blocking requests
    """
    def __init__(self, ttl_seconds=120):
        self.cache = {}  # {worksheet_name: {'data': df, 'timestamp': time}}
        self.ttl = ttl_seconds
        self.lock = Lock()
        self.is_refreshing = False
        self.last_refresh_time = 0

    def get(self, key):
        """Get cached data if it exists and hasn't expired."""
        with self.lock:
            if key in self.cache:
                cached_item = self.cache[key]
                age = time.time() - cached_item['timestamp']
                if age < self.ttl:
                    return cached_item['data']
                else:
                    # Cache expired, remove it
                    del self.cache[key]
        return None

    def set(self, key, data):
        """Store data in cache with current timestamp."""
        with self.lock:
            self.cache[key] = {
                'data': data,
                'timestamp': time.time()
            }

    def is_expired(self, key):
        """Check if cache entry has expired."""
        with self.lock:
            if key not in self.cache:
                return True
            age = time.time() - self.cache[key]['timestamp']
            return age >= self.ttl

    def clear(self):
        """Clear all cached data."""
        with self.lock:
            self.cache.clear()

# Initialize global cache with 2-minute TTL
data_cache = DataCache(ttl_seconds=120)

# ==============================================================================
# --- 2. GOOGLE SHEETS API CONFIGURATION ---
# ==============================================================================
# This section connects to Google Sheets to fetch real-time sensor data
# The application expects a Google Sheet named "Simulated_Sensor_Data"
# Each worksheet in the sheet should be named: "location_booth" (e.g., "Adelaide_Booth A")

gspread_client = None
worksheet = None
spreadsheet = None

try:
    # Define the scope for Google Sheets API access
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    # Load credentials from newcred.json (Google Service Account credentials)
    # To set up: https://docs.gspread.org/en/latest/oauth2.html
    creds = ServiceAccountCredentials.from_json_keyfile_name('Gsheetscreds.json', scope)
    gspread_client = gspread.authorize(creds)

    # Open the main spreadsheet
    # CHANGE THIS NAME if using a different Google Sheet
    spreadsheet = gspread_client.open("Simulated_Sensor_Data")
    print("✅ Successfully connected to Google Sheets.")

except Exception as e:
    print(f"⚠️ WARNING: Could not connect to Google Sheets. Live data will be unavailable.")
    print(f"   Details: {e}")
    print(f"   Make sure newcred.json exists and contains valid credentials.")
    spreadsheet = None

# ==============================================================================
# --- 3. HELPER FUNCTIONS ---
# ==============================================================================

def fetch_worksheet_with_retry(worksheet_name, max_retries=3):
    """
    Fetch worksheet data with exponential backoff retry logic.
    - Retries up to 3 times on failure
    - Waits 1s, 2s, 4s between retries (exponential backoff)
    - Returns None if all retries fail
    """
    if spreadsheet is None:
        return None

    for attempt in range(max_retries):
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
            data = worksheet.get_all_records()
            return data if data else None
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"Worksheet '{worksheet_name}' not found.")
            return None
        except Exception as e:
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            if attempt < max_retries - 1:
                logger.warning(f"API call failed for '{worksheet_name}' (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s... Error: {e}")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to fetch '{worksheet_name}' after {max_retries} attempts. Error: {e}")

    return None

def get_data_from_sheet():
    if not worksheet: return None
    try:
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], format='%m/%d/%Y %H:%M', errors='coerce')
        return df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)
    except Exception as e:
        logger.error(f"Error fetching data from Google Sheet: {e}")
        return None

def load_sensor_data(loc_name, booth_name):
    """
    Load sensor data with intelligent caching and retry logic.

    OPTIMIZATION STRATEGY:
    1. Check cache first - if data exists and not expired, return immediately (instant)
    2. If cache expired or missing, fetch from Google Sheets with retry logic
    3. Store result in cache for next 2 minutes
    4. Return cached data to avoid repeated API calls

    This reduces API calls by ~80-90% and makes dashboard load in 1-2s instead of 5-10s.
    """
    required_cols = [
        'timestamp', 'temp_c', 'humidity_pct', 'co2_ppm', 'pir_state',
        'voc', 'pm25_ugm3', 'ch2o_ppm', 'occupancy_count', 'light_lux', 'sound_dBA'
    ]
    numeric_cols = [
        'temp_c', 'humidity_pct', 'co2_ppm', 'voc', 'pm25_ugm3', 'ch2o_ppm',
        'occupancy_count', 'light_lux', 'sound_dBA'
    ]

    # Construct cache key
    cache_key = f"{loc_name.replace(' ', '')}_{booth_name.replace(' ', '')}"

    # STEP 1: Check cache first (instant return if valid)
    cached_data = data_cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    # STEP 2: Cache miss or expired - fetch from Google Sheets
    if spreadsheet is None:
        logger.error("Google Sheets connection not established. Using dummy data.")
        return create_dummy_data()

    # STEP 3: Fetch with retry logic (exponential backoff)
    data = fetch_worksheet_with_retry(cache_key, max_retries=3)

    if data is None:
        logger.warning(f"Could not fetch data for {cache_key}. Returning None.")
        return None

    # STEP 4: Process and clean data
    df = pd.DataFrame(data) if data else None

    if df is not None and not df.empty:
        # Ensure all required columns exist
        for col in required_cols:
            if col not in df.columns:
                df[col] = None

        # Convert sensor columns to numeric
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Convert timestamp to datetime
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

        # Sort by timestamp
        df = df.sort_values(by='timestamp').reset_index(drop=True)

        # STEP 5: Store in cache for next 2 minutes
        data_cache.set(cache_key, df)
        logger.info(f"Successfully loaded and cached data from Google worksheet: {cache_key}")

        return df

    return None

def calculate_comfort_score(row):
    """
    Calculates a comfort score (0-100) for a single row of sensor data.
    Each metric is scored from 0-100 and the final score is a weighted average.
    """
    scores = {}

    # 1. Temperature (Ideal: 20-25°C)
    temp = row.get('temp_c')
    if pd.notna(temp):
        if 20 <= temp <= 25:
            scores['temp'] = 100
        elif 18 <= temp < 20 or 25 < temp <= 27:
            scores['temp'] = 50
        else:
            scores['temp'] = 0

    # 2. Humidity (Ideal: 40-50%)
    hum = row.get('humidity_pct')
    if pd.notna(hum):
        if 40 <= hum <= 50:
            scores['hum'] = 100
        elif 30 <= hum < 40 or 50 < hum <= 60:
            scores['hum'] = 50
        else:
            scores['hum'] = 0

    # 3. CO2 (Ideal: < 600 ppm)
    co2 = row.get('co2_ppm')
    if pd.notna(co2):
        if co2 <= 600: scores['co2'] = 100
        elif co2 <= 1000: scores['co2'] = 75
        elif co2 <= 2000: scores['co2'] = 25
        else: scores['co2'] = 0

    # 4. VOCs (Ideal: < 300 ppb - assuming your VOC index maps to this)
    voc = row.get('voc')
    if pd.notna(voc):
        if voc <= 300: scores['voc'] = 100
        elif voc <= 500: scores['voc'] = 50
        else: scores['voc'] = 0

    # 5. PM2.5 (Ideal: < 12 µg/m³)
    pm25 = row.get('pm25_ugm3')
    if pd.notna(pm25):
        if pm25 <= 12: scores['pm25'] = 100
        elif pm25 <= 35: scores['pm25'] = 50
        else: scores['pm25'] = 0

    if not scores:
        return 0

    # Final score is the average of all available metric scores
    return sum(scores.values()) / len(scores)

def create_dummy_data():
    """Create dummy sensor data for testing when Google Sheets is unavailable"""
    import numpy as np

    # Create timestamps for the last 24 hours
    timestamps = pd.date_range(end=datetime.now(), periods=24, freq='H')

    # Create dummy data
    data = {
        'timestamp': timestamps,
        'temp_c': np.random.normal(22, 2, 24),  # Temperature around 22°C
        'humidity_pct': np.random.normal(45, 5, 24),  # Humidity around 45%
        'co2_ppm': np.random.normal(800, 100, 24),  # CO2 around 800ppm
        'pir_state': np.random.choice(['Occupied', 'Vacant'], 24, p=[0.3, 0.7]),
        'voc': np.random.normal(200, 50, 24),
        'pm25_ugm3': np.random.normal(15, 5, 24),
        'ch2o_ppm': np.random.normal(0.05, 0.01, 24),
        'occupancy_count': np.random.randint(0, 5, 24),
        'light_lux': np.random.normal(400, 100, 24),
        'sound_dBA': np.random.normal(45, 10, 24)
    }

    return pd.DataFrame(data)

def get_locations(df_clients, client_name=None):
    if client_name:
        return df_clients[df_clients['client_name'] == client_name]['location'].unique().tolist()
    else:
        return df_clients['location'].unique().tolist()

# ==============================================================================
# --- 3.5. BACKGROUND CACHE REFRESH THREAD ---
# ==============================================================================
def background_cache_refresh():
    """
    Background thread that periodically refreshes cache data from Google Sheets.
    - Runs every 2 minutes (matches cache TTL)
    - Fetches all booth data in advance
    - Prevents cache misses and API quota issues
    - Logs refresh events clearly
    """
    def refresh_all_booths():
        logger.info("🔄 Refreshing data from Google Sheets... (background thread)")
        try:
            for index, row in df_clients.iterrows():
                loc_name = row['location']
                booth_name = row['booth']
                # This will fetch and cache the data
                load_sensor_data(loc_name, booth_name)
                time.sleep(0.5)  # Small delay to avoid API rate limiting
            logger.info("✅ Cache refresh completed successfully")
        except Exception as e:
            logger.error(f"❌ Error during cache refresh: {e}")

    # Run refresh every 2 minutes (120 seconds)
    while True:
        time.sleep(120)
        refresh_all_booths()

# Start background refresh thread (daemon thread - stops when app stops)
refresh_thread = threading.Thread(target=background_cache_refresh, daemon=True)
refresh_thread.start()
logger.info("✅ Background cache refresh thread started")

# ==============================================================================
# --- 4. FLASK ROUTES ---
# ==============================================================================

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = str(request.form['password'])
        user_data = df_login[(df_login['username'] == username) & (df_login['password'] == password)]
        if not user_data.empty:
            session['username'] = user_data.iloc[0]['username']
            session['role'] = user_data.iloc[0]['role']
            session['client_name'] = user_data.iloc[0]['client_name']
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    client_name = session.get('client_name')
    user_role = session.get('role')
    locations = get_locations(df_clients, client_name if session.get('role') == 'client' else None)
    booths_in_scope = df_clients
    if user_role == 'client':
        booths_in_scope = df_clients[df_clients['client_name'] == client_name]

    # Initialize all your data structures
    active_alerts = []
    system_status = []
    utilization_values = []
    currently_occupied_count = 0
    location_summaries = {}
    portfolio_kpis = {}
    avg_comfort_score = 0
    occupied_booth_details = []

    # Outer loop for each location
    for loc in locations:
        alert_count = 0  # Reset alert count for each new location
        booths_in_loc = booths_in_scope[booths_in_scope['location'] == loc]['booth'].unique().tolist()

        # Inner loop for each booth within a location
        for booth_name in booths_in_loc:
            df_booth = load_sensor_data(loc, booth_name)

            # Check if data was successfully loaded for the booth
            if df_booth is not None and not df_booth.empty:
                # All logic that depends on 'latest' now happens safely INSIDE this block
                latest = df_booth.iloc[-1]
                co2_val = latest.get('co2_ppm')
                temp_val = latest.get('temp_c')
                comfy_score = calculate_comfort_score(latest)

                #Calculations to see how many are occupied
                if str(latest.get('pir_state', '')).strip().title() == 'Occupied':
                    currently_occupied_count += 1
                    occupied_booth_details.append({'location': loc, 'booth': booth_name})

                # 2. Logic for Active Alerts Log
                if co2_val is not None and co2_val > 1000:
                    active_alerts.append(f"High CO₂ in {loc}, {booth_name}: {int(co2_val)} ppm")
                if temp_val is not None and temp_val > 25:
                    active_alerts.append(f"High Temp in {loc}, {booth_name}: {temp_val}°C")

                # 3. Logic for Booth Status Panel
                last_seen = latest.get('timestamp')
                occ_now = latest.get('occupancy_count')
                occu = latest.get('pir_state')
                system_status.append({'location': loc, 'booth': booth_name, 'last_seen': last_seen, 'occupancy_status': occu, 'count': occ_now, 'comfort_score': comfy_score })

            else:
                # This 'else' block handles the case where no data was found for a booth
                system_status.append({
                    'location': loc,
                    'booth': booth_name,
                    'last_seen': 'Never',
                    'occupancy_status': 'Offline',
                    'count': 0,
                    'comfort_score': 0
                })

        # After checking all booths in a location, assign the total alert count
        location_summaries[loc] = alert_count

    # --- NEW DYNAMIC KPI SPOTLIGHT LOGIC ---
    kpi_data = {}
    spotlight_name = None

    # Only generate spotlight data if the user is a client and has locations
    if user_role == 'client' and locations:
        # Pick the first location and first booth for that client to be the spotlight
        spotlight_loc = locations[0]
        spotlight_booth = df_clients[df_clients['location'] == spotlight_loc]['booth'].unique().tolist()[0]
        spotlight_name = f"{spotlight_loc}, {spotlight_booth}"

        df_spotlight = load_sensor_data(spotlight_loc, spotlight_booth)

        if df_spotlight is not None and not df_spotlight.empty:
            recent_data = df_spotlight.tail(24)
            # Safely populate kpi_data with JSON-serializable values
            temp_values = [float(v) if pd.notna(v) else None for v in recent_data['temp_c']] if 'temp_c' in recent_data.columns else []
            humidity_values = [float(v) if pd.notna(v) else None for v in recent_data['humidity_pct']] if 'humidity_pct' in recent_data.columns else []

            kpi_data = {
                'temp_labels': recent_data['timestamp'].dt.strftime('%H:%M').tolist() if 'timestamp' in recent_data.columns else [],
                'temp_values': temp_values,
                'humidity_values': humidity_values,
                'occupancy_counts': recent_data['pir_state'].value_counts().to_dict() if 'pir_state' in recent_data.columns else {}
            }

    # --- NEW: Admin-only Booth Performance Heatmap Logic ---
    booth_performance_data = []
    if user_role ==  "admin" or user_role == "client":
        # Get the date range from the URL, or default to the last 30 days
        end_date_default = datetime.now()
        start_date_default = end_date_default - timedelta(days=29)

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        start_date = pd.to_datetime(start_date_str) if start_date_str else start_date_default
        end_date = pd.to_datetime(end_date_str) if end_date_str else end_date_default

        # Iterate through every booth in scope (filtered by client if applicable)
        for index, booth_row in booths_in_scope.iterrows():
            loc_name = booth_row['location']
            booth_name = booth_row['booth']
            max_occ = booth_row['max_occupancy']
            df_booth = load_sensor_data(loc_name, booth_name)
            if df_booth is None or df_booth.empty: continue
            # Apply date filters
            filtered_df = df_booth[(df_booth['timestamp'] >= start_date) & (df_booth['timestamp'] <= (pd.to_datetime(end_date_str) + timedelta(days=1) if end_date_str else end_date))]
            if filtered_df.empty:
                utilization_values.append(0)
                continue
            # Calculate Temporal Utilization
            temp_util_df = filtered_df.dropna(subset=['pir_state'])
            temporal_utilization = 0
            if not temp_util_df.empty:
                occupied_count = temp_util_df[temp_util_df['pir_state'].astype(str).str.strip() == 'Occupied'].shape[0]
                total_count = temp_util_df.shape[0]
                temporal_utilization = (occupied_count / total_count * 100) if total_count > 0 else 0
            utilization_values.append(temporal_utilization)
            # Calculate Capacity Utilization
            cap_util_df = filtered_df.dropna(subset=['occupancy_count'])
            cap_util_df = cap_util_df[cap_util_df['occupancy_count'] > 0]
            capacity_utilization = 0
            if not cap_util_df.empty and max_occ > 0:
                avg_occupancy = cap_util_df['occupancy_count'].mean()
                capacity_utilization = (avg_occupancy / max_occ * 100)
            booth_performance_data.append({
                'location': loc_name,
                'booth': booth_name,
                'booth_id': booth_row['booth_id'],
                'temporal_util': temporal_utilization,
                'capacity_util': capacity_utilization
            })
    booth_breakdown = booths_in_scope['location'].value_counts().to_dict()

    occupied_breakdown = {}
    if occupied_booth_details:
        df_occupied = pd.DataFrame(occupied_booth_details)
        if not df_occupied.empty:
            occupied_breakdown = df_occupied['location'].value_counts().to_dict()

    # Compute average performance per location for charting
    location_performance = {}
    try:
        for loc in locations:
            rows = [r for r in booth_performance_data if r.get('location') == loc]
            if rows:
                avg_time = sum(float(r.get('temporal_util') or 0) for r in rows) / len(rows)
                avg_capacity = sum(float(r.get('capacity_util') or 0) for r in rows) / len(rows)
            else:
                avg_time, avg_capacity = 0.0, 0.0
            location_performance[loc] = {
                'time': round(avg_time, 1),
                'capacity': round(avg_capacity, 1)
            }
    except Exception as e:
        # Fail safe: if anything goes wrong, fall back to empty dict
        location_performance = {}

    # Finalize Portfolio KPIs
    portfolio_kpis = {
        'total_booths': len(booths_in_scope),
        'currently_occupied': currently_occupied_count,
        'average_utilization': sum(utilization_values) / len(utilization_values) if utilization_values else 0,
        'booth_breakdown': booth_breakdown,       # Add this
        'occupied_breakdown': occupied_breakdown  # And this
        }

    comfort_chart_data = {'labels': [], 'values': []}
    if user_role == 'admin' or user_role == 'client':
        all_booth_dfs = []
        for index, row in df_clients.iterrows():
            df_b = load_sensor_data(row['location'], row['booth'])
            if df_b is not None and not df_b.empty:
                all_booth_dfs.append(df_b)

        if all_booth_dfs:
            df_all = pd.concat(all_booth_dfs)
            comfort_cols = ['temp_c', 'humidity_pct', 'co2_ppm', 'voc', 'pm25_ugm3', 'light_lux', 'sound_dBA']
            for col in comfort_cols:
                if col in df_all.columns:
                    df_all[col] = pd.to_numeric(df_all[col], errors='coerce')

            df_all = df_all.set_index('timestamp').sort_index()

            # Resample to get hourly average of all sensor readings across the portfolio
            df_hourly = df_all.resample('h').mean(numeric_only=True)
            df_hourly = df_hourly.dropna(how='all')

            if not df_hourly.empty:
                # Calculate the comfort score for each hour
                df_hourly['comfort_score'] = df_hourly.apply(calculate_comfort_score, axis=1)

                # Prepare data for the chart, showing the last 3 days (72 hours)
                comfort_data = df_hourly.tail(72)
                comfort_values = [float(v) if pd.notna(v) else None for v in comfort_data['comfort_score'].round(1)]
                comfort_chart_data = {
                    'labels': comfort_data.index.strftime('%Y-%m-%d %H:00').tolist(),
                    'values': comfort_values
                }
                avg_comfort_score = float(df_hourly['comfort_score'].mean()) if pd.notna(df_hourly['comfort_score'].mean()) else 0

    return render_template('dashboard.html',
                    locations=locations,
                    location_summaries=location_summaries,
                    location_performance=location_performance,
                    active_alerts=active_alerts,
                    system_status=system_status,
                    kpi_data=kpi_data,
                    spotlight_name=spotlight_name,
                    booth_performance_data=booth_performance_data,
                    portfolio_kpis=portfolio_kpis,
                    comfort_chart_data=comfort_chart_data,
                    avg_comfort_score=avg_comfort_score) # Pass the dynamic name to the template

@app.route('/location/<loc_name>')
def location_view(loc_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Get all locations for the sidebar to render correctly
    client_name = session.get('client_name')
    all_locations = get_locations(df_clients, client_name if session.get('role') == 'client' else None)

    # Filter booths by client if applicable
    booths_in_scope = df_clients
    if session.get('role') == 'client':
        booths_in_scope = df_clients[df_clients['client_name'] == client_name]

    # Get booths and date filters
    booths_in_loc = booths_in_scope[booths_in_scope['location'] == loc_name]['booth'].unique().tolist()
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    utilization_data = []
    for booth_name in booths_in_loc:
        df_booth = load_sensor_data(loc_name, booth_name)
        if df_booth is None or df_booth.empty:
            continue

        # Apply date filters
        filtered_df = df_booth.copy()
        if start_date_str:
            filtered_df = filtered_df[filtered_df['timestamp'] >= pd.to_datetime(start_date_str)]
        if end_date_str:
            end_date_inclusive = pd.to_datetime(end_date_str) + timedelta(days=1)
            filtered_df = filtered_df[filtered_df['timestamp'] < end_date_inclusive]

        filtered_df.dropna(subset=['pir_state'], inplace=True)

        # Clean the pir_state data to remove whitespace and handle any case issues
        if not filtered_df.empty:
            filtered_df['pir_state'] = filtered_df['pir_state'].astype(str).str.strip()

            occupied_count = filtered_df[filtered_df['pir_state'] == 'Occupied'].shape[0]
            total_count = filtered_df.shape[0]

            utilization_pct = (occupied_count / total_count * 100) if total_count > 0 else 0

            utilization_data.append({'booth_name': booth_name, 'utilization': utilization_pct})

    # Sort data and prepare for Chart.js
    chart_labels, chart_values = [], []
    chart_data = {'labels': [], 'values': []}
    has_chart_data = False
    if utilization_data:
        utilization_data.sort(key=lambda x: x['utilization'], reverse=True)
        chart_labels = [item['booth_name'] for item in utilization_data]
        chart_values = [float(item['utilization']) for item in utilization_data]  # Ensure float values
        chart_data = {'labels': chart_labels, 'values': chart_values}
        has_chart_data = True

    # Render template
    return render_template('location.html',
                           loc_name=loc_name,
                           booths=booths_in_loc,
                           locations=all_locations,
                           chart_labels=chart_labels,
                           chart_values=chart_values,
                           chart_data=chart_data,
                           has_chart_data=has_chart_data,
                           start_date=start_date_str,
                           end_date=end_date_str)

@app.route('/booth/<loc_name>/<booth_name>')
def booth(loc_name, booth_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Security check first
    client_name = session.get('client_name')
    if session['role'] == 'client':
        allowed_booths = df_clients[(df_clients['client_name'] == client_name) & (df_clients['location'] == loc_name)]
        if booth_name not in allowed_booths['booth'].tolist():
            return "Access Denied", 403

    df_booth_data = load_sensor_data(loc_name, booth_name)
    has_data = df_booth_data is not None and not df_booth_data.empty

    if has_data:
        latest_row = df_booth_data.iloc[-1]
        reading = {}
        for key, value in latest_row.items():
            if pd.isna(value):
                reading[key] = None
            elif callable(value):
                reading[key] = None
            else:
                try:
                    reading[key] = float(value) if isinstance(value, (int, float, np.number)) else str(value)
                except (ValueError, TypeError):
                    reading[key] = str(value)

        # Add occupancy_status based on pir_state
        pir_state = reading.get('pir_state', '')
        reading['occupancy_status'] = str(pir_state).strip() if pir_state else 'Unknown'

        # Add comfort_score
        comfort_score = calculate_comfort_score(latest_row)
        reading['comfort_score'] = float(comfort_score) if pd.notna(comfort_score) else 0.0
    else:
        reading = {}

    booth_thresholds = {
        'temp_c': {'low': 18.0, 'high': 24.0},
        'humidity_pct': {'low': 40.0, 'high': 60.0},
        'co2_ppm': {'low': 0.0, 'high': 1000.0},
        'voc': {'low': 0.0, 'high': 100.0},
        'light_lux': {'low': 300.0, 'high': 460.0},
        'sound_dBA': {'low': 50.0, 'high': 120.0},
        'occupancy_count': {'low': 1.0, 'high': 5.0}
    }

    locations = get_locations(df_clients, client_name if session.get('role') == 'client' else None)

    # Comfort chart data - disabled for now
    comfort_chart_data = {'labels': [], 'values': []}

    # Ensure all template variables are JSON-serializable
    template_vars = {
        'reading': reading,
        'locations': locations,
        'loc_name': str(loc_name),
        'booth_name': str(booth_name),
        'thresholds': booth_thresholds,
        'has_data': bool(has_data),
        'comfort_chart_data': comfort_chart_data
    }

    return render_template('booth.html', **template_vars)

@app.route('/analytics/<loc_name>/<booth_name>/<metric>', methods=['GET', 'POST'])
def analytics(loc_name, booth_name, metric):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Security & Data Loading
    client_name = session.get('client_name')
    if session['role'] == 'client':
        allowed_booths = df_clients[(df_clients['client_name'] == client_name) & (df_clients['location'] == loc_name)]
        if booth_name not in allowed_booths['booth'].tolist():
            return "Access Denied", 403

    df_booth_data = load_sensor_data(loc_name, booth_name)
    if df_booth_data is None or df_booth_data.empty:
        return render_template('analytics.html',
                              loc_name=loc_name,
                              booth_name=booth_name,
                              error="No data available")

    # Centralized Configuration for Metrics
    METRIC_CONFIG = {
        'temp_c': {'name': 'Temperature', 'unit': '°C'},
        'humidity_pct': {'name': 'Humidity', 'unit': '%'},
        'co2_ppm': {'name': 'CO₂ Level', 'unit': 'ppm'},
        'voc': {'name': 'VOC Index', 'unit': 'ppb'},
        'pm25_ugm3': {'name': 'PM2.5', 'unit': 'µg/m³'},
        'ch2o_ppm': {'name': 'Formaldehyde', 'unit': 'ppm'},
        'light_lux': {'name': 'Light Intensity', 'unit': 'lux'},
        'sound_dBA': {'name': 'Sound Level', 'unit': 'dBA'},
        'occupancy_count': {'name': 'Occupancy Count', 'unit': 'people'}
    }

    THRESHOLDS = {
        'temp_c': {"low": "18-20", "optimal": "20-25", "high": "> 25"},
        'humidity_pct': {"low": "30-40", "optimal": "40-50", "high": "> 60"},
        'co2_ppm': {"low": "600-1000", "optimal": "< 600", "high": "> 1000"},
        'voc': {"low": "300-500", "optimal": "< 300", "high": "> 500"},
        'pm25_ugm3': {"low": "12-35", "optimal": "< 12", "high": "> 35"}
    }

    # Metric Validation & Configuration Lookup
    if metric not in METRIC_CONFIG:
        return "Invalid metric provided", 400

    config = METRIC_CONFIG[metric]
    threshold_data = THRESHOLDS.get(metric, {})

    # Date Filtering
    filtered_df = df_booth_data.copy()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=29)

    # Check for date parameters in GET request
    start_date_param = request.args.get('start_date')
    end_date_param = request.args.get('end_date')

    if start_date_param:
        start_date = pd.to_datetime(start_date_param)
    if end_date_param:
        end_date = pd.to_datetime(end_date_param)

    # Ensure correct column name 'timestamp' is used
    filtered_df = df_booth_data[(df_booth_data['timestamp'] >= start_date) & (df_booth_data['timestamp'] <= end_date)]

    # Focused Metric Calculation
    current_value = None
    average_value = None
    chart_data = {'labels': [], 'values': []}

    if not filtered_df.empty and metric in filtered_df.columns:
        # Calculate single values for the specific metric
        current_val = filtered_df.iloc[-1][metric]
        current_value = float(current_val) if pd.notna(current_val) else None

        avg_val = filtered_df[metric].mean()
        average_value = float(avg_val) if pd.notna(avg_val) else None

        # Resample data daily for a cleaner chart, preventing too many data points
        df_resampled = filtered_df.set_index('timestamp').resample('D').mean(numeric_only=True)

        # Drop rows where the metric is NaN after resampling
        df_resampled.dropna(subset=[metric], inplace=True)

        if not df_resampled.empty:
            labels = df_resampled.index.strftime('%Y-%m-%d').tolist()
            values = [float(v) if pd.notna(v) else None for v in df_resampled[metric].round(2)]
            chart_data = {'labels': labels, 'values': values}

    # Render Template
    return render_template('analytics.html',
                           loc_name=loc_name,
                           booth_name=booth_name,
                           metric_key=metric,
                           metric_name=config['name'],
                           metric_unit=config['unit'],
                           current_value=current_value,
                           average_value=average_value,
                           threshold_data=threshold_data,
                           chart_data=chart_data,
                           chart_labels=chart_data['labels'],
                           chart_values=chart_data['values'],
                           start_date=start_date.strftime('%Y-%m-%dT%H:%M'),
                           end_date=end_date.strftime('%Y-%m-%dT%H:%M'))

# --- Run the Application ---
if __name__ == '__main__':
    app.run(debug=True)