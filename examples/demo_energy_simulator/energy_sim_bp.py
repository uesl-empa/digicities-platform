# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Energy Simulation Blueprint
Independent module for building energy simulation with weather data integration
"""

from flask import Blueprint, request, jsonify
import pandas as pd
import numpy as np
from pathlib import Path
import requests
import base64
from datetime import datetime
import json
from werkzeug.utils import secure_filename
import os
import tempfile
from dotenv import load_dotenv
import pickle
import threading

# Cross-platform file locking
try:
    import fcntl  # Unix/Linux
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False  # Windows

# Load environment variables
load_dotenv()

# Import authentication (local module; auth is disabled by default for the demo).
from auth import require_api_key

# Create blueprint
energy_sim_bp = Blueprint('energy_sim', __name__)

# Configuration
ALLOWED_EXTENSIONS = {'epw', 'csv', 'txt'}
TEMP_UPLOAD_FOLDER = tempfile.gettempdir()

# Weather files bundled with the service. A scenario's weather_data filename is
# resolved here first (offline, no NextCloud needed); demo_weather.epw ships with
# the demo workspace's Location.
WEATHER_DIR = Path(__file__).resolve().parent / 'assets' / 'weather'


def load_local_weather(filename: str):
    """Parse a bundled EPW by filename, or None if it isn't present."""
    if not filename:
        return None
    path = WEATHER_DIR / secure_filename(filename)
    if path.exists():
        wd = parse_weather_file(str(path))
        if wd:
            wd['source'] = 'file'
        return wd
    return None

# Persistent on-disk result store. RESULTS_DIR (a mounted docker volume in the
# compose stack) keeps results across container restarts; otherwise a temp dir.
STORAGE_DIR = Path(os.environ.get('RESULTS_DIR') or (Path(tempfile.gettempdir()) / 'energy_sim_results'))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Thread lock for Windows (fallback when fcntl not available)
_file_lock = threading.Lock()

def save_simulation_result(scenario_id, results):
    """Save simulation result to disk with file locking."""
    file_path = STORAGE_DIR / f"{scenario_id}.pkl"
    if HAS_FCNTL:
        with open(file_path, 'wb') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            pickle.dump({
                'data': results,
                'created_at': datetime.now(),
                'access_count': 0
            }, f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    else:
        # Windows fallback: use threading lock
        with _file_lock:
            with open(file_path, 'wb') as f:
                pickle.dump({
                    'data': results,
                    'created_at': datetime.now(),
                    'access_count': 0
                }, f)

def load_simulation_result(scenario_id):
    """Load simulation result from disk."""
    file_path = STORAGE_DIR / f"{scenario_id}.pkl"
    if not file_path.exists():
        return None

    try:
        if HAS_FCNTL:
            with open(file_path, 'rb') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                data = pickle.load(f)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return data
        else:
            # Windows fallback: use threading lock
            with _file_lock:
                with open(file_path, 'rb') as f:
                    return pickle.load(f)
    except:
        return None

def update_access_count(scenario_id):
    """Update access count for a result."""
    file_path = STORAGE_DIR / f"{scenario_id}.pkl"
    if not file_path.exists():
        return

    if HAS_FCNTL:
        with open(file_path, 'rb+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            data = pickle.load(f)
            data['access_count'] = data.get('access_count', 0) + 1
            f.seek(0)
            pickle.dump(data, f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    else:
        # Windows fallback: use threading lock with read-then-write
        with _file_lock:
            with open(file_path, 'rb') as f:
                data = pickle.load(f)
            data['access_count'] = data.get('access_count', 0) + 1
            with open(file_path, 'wb') as f:
                pickle.dump(data, f)

def list_all_results():
    """List all stored results."""
    results = []
    for file_path in STORAGE_DIR.glob("*.pkl"):
        try:
            scenario_id = file_path.stem
            data = load_simulation_result(scenario_id)
            if data:
                results.append((scenario_id, data))
        except:
            continue
    return results

def build_result_urls(scenario_id):
    """Build result URLs that are reachable from the user's browser.

    The caller (Streamlit) reaches this service on the internal docker network
    name (demo_energy_simulator:5000), which a browser can't resolve. Set
    PUBLIC_BASE_URL (e.g. http://localhost:5001) so the dashboard link points at
    the published host port instead of the request's host.
    """
    public_base = os.environ.get('PUBLIC_BASE_URL')
    if public_base:
        base_url = public_base.rstrip('/')
    elif 'platform.digicities.ch' in request.host:
        # Production - reverse proxy adds /apps prefix
        base_url = "https://platform.digicities.ch/apps"
    else:
        # Fall back to the request host (correct when the browser hits the
        # service directly on the published port).
        base_url = request.host_url.rstrip('/')

    result_view_url = f"{base_url}/api/energy_simulation/view/{scenario_id}"
    result_api_url = f"{base_url}/api/energy_simulation/results/{scenario_id}"
    return result_view_url, result_api_url

def generate_scenario_id():
    """Generate a unique scenario ID."""
    import uuid
    return str(uuid.uuid4())[:8]  # Short ID for easier sharing

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def download_weather_file(username: str, password: str, workspace: str,
                         filename: str, output_path: str = None,
                         base_url: str = "https://platform.digicities.ch/filestorage") -> str:
    """Download weather file from Nextcloud storage."""
    try:
        if output_path is None:
            output_path = TEMP_UPLOAD_FOLDER

        auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}

        # Updated path to use private_data_products folder
        file_url = f"{base_url}/remote.php/dav/files/{username}/{workspace}/private_data_products/{filename}"

        response = requests.get(file_url, headers=headers, timeout=60)
        response.raise_for_status()

        Path(output_path).mkdir(parents=True, exist_ok=True)
        output_file = Path(output_path) / secure_filename(filename)

        with open(output_file, 'wb') as f:
            f.write(response.content)

        return str(output_file.absolute())

    except Exception as e:
        print(f"Failed to download weather file {filename}: {e}")
        return None

def parse_weather_file(filepath: str) -> dict:
    """Parse EPW weather file to extract temperature data."""
    weather_data = {
        'temperatures': [],
        'location': 'Unknown',
        'has_data': False,
        'humidity': [],
        'wind_speed': []
    }

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Parse location
        if lines and lines[0].startswith('LOCATION'):
            parts = lines[0].split(',')
            if len(parts) > 1:
                weather_data['location'] = parts[1].strip()

        # Find data start
        data_start_idx = 0
        for i, line in enumerate(lines):
            if line.strip() and line[0].isdigit():
                data_start_idx = i
                break

        # Parse hourly data
        for line in lines[data_start_idx:data_start_idx + 8760]:
            parts = line.split(',')
            if len(parts) > 6:
                try:
                    # Column 7: Dry bulb temp
                    temp = float(parts[6])
                    weather_data['temperatures'].append(temp)

                    # Column 9: Relative humidity (if available)
                    if len(parts) > 8:
                        humidity = float(parts[8])
                        weather_data['humidity'].append(humidity)

                    # Column 22: Wind speed (if available)
                    if len(parts) > 21:
                        wind = float(parts[21])
                        weather_data['wind_speed'].append(wind)

                except (ValueError, IndexError):
                    continue

        # Ensure we have 8760 hours
        target_hours = 8760
        if len(weather_data['temperatures']) < target_hours:
            last_temp = weather_data['temperatures'][-1] if weather_data['temperatures'] else 10.0
            weather_data['temperatures'].extend([last_temp] * (target_hours - len(weather_data['temperatures'])))
        elif len(weather_data['temperatures']) > target_hours:
            weather_data['temperatures'] = weather_data['temperatures'][:target_hours]

        weather_data['has_data'] = len(weather_data['temperatures']) > 0

    except Exception as e:
        print(f"Error parsing weather file: {e}")

    return weather_data

def generate_synthetic_weather() -> dict:
    """Generate synthetic weather data when no file is available."""
    hours = np.arange(8760)

    # Annual temperature variation (seasonal)
    annual_temp = 10 + 12 * np.sin(2 * np.pi * (hours - 2160) / 8760)

    # Daily temperature variation
    daily_temp = 6 * np.sin(2 * np.pi * (hours % 24 - 6) / 24)

    # Add some noise
    noise = np.random.normal(0, 1, 8760)

    temperatures = annual_temp + daily_temp + noise

    return {
        'temperatures': temperatures.tolist(),
        'location': 'Synthetic Data',
        'has_data': True,
        'humidity': (50 + 20 * np.sin(2 * np.pi * hours / 8760) + np.random.normal(0, 5, 8760)).tolist(),
        'wind_speed': np.abs(5 + 3 * np.sin(2 * np.pi * hours / 8760) + np.random.normal(0, 2, 8760)).tolist()
    }

def calculate_building_energy(building: dict, weather_data: dict) -> dict:
    """Calculate hourly energy consumption for a building."""

    # Factors and efficiencies
    building_type_factors = {
        'SFH': 1.0,
        'MFH': 0.85,
        'Office': 1.2,
        'Retail': 1.3
    }

    heating_efficiency = {
        'OilHeated': 0.75,
        'GasHeated': 0.85,
        'ElectricallyHeated': 0.95,
        'AirHeated': 2.5,
        'DistrictHeated': 0.90
    }

    dhw_efficiency = {
        'OilHeated': 0.70,
        'GasHeated': 0.80,
        'ElectricallyHeated': 0.90,
        'AirHeated': 2.0,
        'DistrictHeated': 0.85
    }

    # Parse building age
    try:
        age_str = building.get('BuildingAge', '1970')
        if '-' in age_str:
            year = int(age_str.split('-')[0])
        else:
            year = int(age_str)
    except:
        year = 1970

    # Age-based insulation factor
    if year >= 2010:
        age_factor = 0.5
    elif year >= 2000:
        age_factor = 0.6
    elif year >= 1990:
        age_factor = 0.8
    elif year >= 1980:
        age_factor = 1.0
    elif year >= 1970:
        age_factor = 1.2
    elif year >= 1960:
        age_factor = 1.4
    else:
        age_factor = 1.6

    # Building parameters
    floor_area = float(building.get('GroundFloorArea', 200))
    num_floors = float(building.get('NumberOfFloors', 2))
    total_area = floor_area * num_floors

    building_type = building.get('SIA2024BuildingType', 'SFH')
    heating_supply = building.get('HeatingSupply', 'GasHeated')
    dhw_supply = building.get('DHWSupply', 'GasHeated')

    type_factor = building_type_factors.get(building_type, 1.0)
    heat_eff = heating_efficiency.get(heating_supply, 0.85)
    dhw_eff = dhw_efficiency.get(dhw_supply, 0.85)

    # Initialize arrays
    hourly_consumption = np.zeros(8760)
    hourly_heating = np.zeros(8760)
    hourly_dhw = np.zeros(8760)
    hourly_electrical = np.zeros(8760)

    # Base loads
    base_electrical_load = 5.0 * type_factor
    base_dhw_load = 3.0

    # Get weather data
    if weather_data['has_data'] and len(weather_data['temperatures']) == 8760:
        outside_temps = np.array(weather_data['temperatures'])
    else:
        synthetic = generate_synthetic_weather()
        outside_temps = np.array(synthetic['temperatures'])

    # Temperature setpoints
    indoor_setpoint = 20.0
    heating_threshold = 15.0

    # Calculate hourly consumption
    for hour in range(8760):
        hour_of_day = hour % 24
        day_of_year = hour // 24

        # Occupancy patterns
        if 0 <= hour_of_day < 6:
            occupancy_factor = 0.6
        elif 9 <= hour_of_day < 17:
            occupancy_factor = 0.7 if day_of_year % 7 < 5 else 0.8
        else:
            occupancy_factor = 1.0

        # Electrical load
        electrical = base_electrical_load * total_area * occupancy_factor / 1000
        hourly_electrical[hour] = electrical

        # DHW load
        dhw_hour_factor = 1.2 if (6 <= hour_of_day <= 9) or (18 <= hour_of_day <= 22) else 0.8
        dhw = (base_dhw_load * dhw_hour_factor * total_area / dhw_eff) / 1000
        hourly_dhw[hour] = dhw

        # Space heating
        if outside_temps[hour] < heating_threshold:
            u_value = 0.5 * age_factor * type_factor
            temp_diff = indoor_setpoint - outside_temps[hour]
            heating = u_value * temp_diff * total_area * occupancy_factor / heat_eff / 1000
            hourly_heating[hour] = heating

        hourly_consumption[hour] = electrical + dhw + heating

    return {
        'total': hourly_consumption.tolist(),
        'heating': hourly_heating.tolist(),
        'dhw': hourly_dhw.tolist(),
        'electrical': hourly_electrical.tolist(),
        'metadata': {
            'total_area_m2': total_area,
            'building_type': building_type,
            'year_built': year,
            'heating_system': heating_supply,
            'dhw_system': dhw_supply
        }
    }

@energy_sim_bp.route('/energy_simulation', methods=['POST'])
@require_api_key
def energy_simulation():
    """Main energy simulation endpoint. Requires API key authentication."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Extract data. Digicities' converter emits `location` as a list (link
        # results are always arrays), so accept either a dict or a list of
        # locations and gather buildings across them.
        scenario_data = data.get('scenario_data', {})
        location_data = scenario_data.get('location', {})
        if isinstance(location_data, list):
            locations = location_data
        else:
            locations = [location_data] if location_data else []

        buildings = []
        weather_file_name = ''
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            buildings.extend(loc.get('buildings', []) or [])
            weather_file_name = weather_file_name or loc.get('weather_data', '')

        if not buildings:
            return jsonify({"error": "No buildings provided"}), 400

        # Generate unique scenario ID
        scenario_id = generate_scenario_id()

        # Initialize weather data
        weather_data = None

        # Prefer a weather file bundled with the service (offline, no NextCloud).
        if weather_file_name:
            weather_data = load_local_weather(weather_file_name)

        # Try cloud download if credentials provided
        if weather_data is None and 'credentials' in data:
            creds = data['credentials']
            username = creds.get('username') or os.getenv('NEXTCLOUD_BASIC_USERNAME', 'admin')
            password = creds.get('password') or os.getenv('NEXTCLOUD_BASIC_PASSWORD')
            workspace = creds.get('workspace', 'workspace_CHUC2-AIL-Energy-Planning')

            if username and password and weather_file_name:
                filepath = download_weather_file(
                    username,
                    password,
                    workspace,
                    weather_file_name
                )
                if filepath:
                    weather_data = parse_weather_file(filepath)
                    os.remove(filepath)  # Clean up

        # If not loaded yet and no credentials provided, try environment variables
        elif weather_data is None and weather_file_name:
            username = os.getenv('NEXTCLOUD_BASIC_USERNAME', 'admin')
            password = os.getenv('NEXTCLOUD_BASIC_PASSWORD')
            workspace = 'workspace_CHUC2-AIL-Energy-Planning'

            if username and password:
                filepath = download_weather_file(
                    username,
                    password,
                    workspace,
                    weather_file_name
                )
                if filepath:
                    weather_data = parse_weather_file(filepath)
                    os.remove(filepath)  # Clean up

        # Use synthetic data as fallback
        if weather_data is None or not weather_data['has_data']:
            weather_data = generate_synthetic_weather()

        # Process buildings
        results = {
            'scenario_id': scenario_id,
            'service_name': data.get('service_name', 'demo_energy_simulator'),
            'timestamp': datetime.now().isoformat(),
            'location': (locations[0].get('uri', '') if locations else ''),
            'weather_file': weather_file_name,
            'weather_location': weather_data.get('location', 'Unknown'),
            'weather_source': weather_data.get('source') or ('synthetic' if weather_data.get('location') == 'Synthetic Data' else 'cloud'),
            'buildings': [],
            'hourly_totals': np.zeros(8760).tolist(),
            'input_data': data  # Store original input for reference
        }

        # Calculate for each building
        for building in buildings:
            building_result = calculate_building_energy(building, weather_data)

            # Add to results
            results['buildings'].append({
                'uri': building.get('uri', ''),
                'metadata': building_result['metadata'],
                'annual_consumption_kWh': round(sum(building_result['total']), 2),
                'peak_demand_kW': round(max(building_result['total']), 2),
                'annual_heating_kWh': round(sum(building_result['heating']), 2),
                'annual_dhw_kWh': round(sum(building_result['dhw']), 2),
                'annual_electrical_kWh': round(sum(building_result['electrical']), 2),
                'consumption_per_m2': round(sum(building_result['total']) / building_result['metadata']['total_area_m2'], 2)
            })

            # Add to hourly totals
            results['hourly_totals'] = [a + b for a, b in zip(results['hourly_totals'], building_result['total'])]

        # Add aggregated statistics
        total_consumption = results['hourly_totals']
        results['aggregate'] = {
            'total_annual_consumption_kWh': round(sum(total_consumption), 2),
            'peak_demand_kW': round(max(total_consumption), 2),
            'average_hourly_kWh': round(sum(total_consumption) / len(total_consumption), 2),
            'load_factor': round(np.mean(total_consumption) / max(total_consumption), 3) if max(total_consumption) > 0 else 0,
            'number_of_buildings': len(buildings)
        }

        # Include timeseries if requested
        if request.args.get('include_timeseries', 'false').lower() == 'true':
            results['hourly_consumption_kWh'] = total_consumption

        # Store results persistently
        save_simulation_result(scenario_id, results)

        # Generate result URLs with proper prefix
        result_view_url, result_api_url = build_result_urls(scenario_id)

        # Return scenario ID and URLs
        return jsonify({
            'success': True,
            'scenario_id': scenario_id,
            'result_url': result_view_url,
            'api_url': result_api_url,
            'message': 'Simulation completed successfully',
            'summary': {
                'total_annual_consumption_kWh': results['aggregate']['total_annual_consumption_kWh'],
                'number_of_buildings': results['aggregate']['number_of_buildings']
            }
        }), 200

    except Exception as e:
        return jsonify({"error": f"Simulation failed: {str(e)}"}), 500

@energy_sim_bp.route('/energy_simulation/results/<scenario_id>', methods=['GET'])
def get_simulation_results(scenario_id):
    """Get simulation results by scenario ID."""
    result = load_simulation_result(scenario_id)
    if not result:
        return jsonify({'error': 'Scenario not found'}), 404

    # Update access count
    update_access_count(scenario_id)

    # Get results
    results = result['data']
    results['access_metadata'] = {
        'created_at': result['created_at'].isoformat(),
        'access_count': result.get('access_count', 0)
    }

    return jsonify(results), 200

@energy_sim_bp.route('/energy_simulation/results/<scenario_id>/download', methods=['GET'])
def download_simulation_results(scenario_id):
    """Download simulation results as JSON file."""
    result = load_simulation_result(scenario_id)
    if not result:
        return jsonify({'error': 'Scenario not found'}), 404

    # Get results
    results = result['data']

    # Create response with proper headers for download
    from flask import Response
    import json

    response_data = json.dumps(results, indent=2)

    return Response(
        response_data,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename=energy_simulation_{scenario_id}.json',
            'Content-Type': 'application/json'
        }
    )

@energy_sim_bp.route('/energy_simulation/results/<scenario_id>/summary', methods=['GET'])
def get_simulation_summary(scenario_id):
    """Get a summary of simulation results (lightweight endpoint)."""
    result = load_simulation_result(scenario_id)
    if not result:
        return jsonify({'error': 'Scenario not found'}), 404

    results = result['data']
    summary = {
        'scenario_id': scenario_id,
        'timestamp': results['timestamp'],
        'weather_location': results['weather_location'],
        'aggregate': results['aggregate'],
        'buildings_count': len(results['buildings']),
        'created_at': result['created_at'].isoformat()
    }

    return jsonify(summary), 200

@energy_sim_bp.route('/energy_simulation/view/<scenario_id>', methods=['GET'])
def view_simulation_results(scenario_id):
    """Render HTML results page for a scenario."""
    result = load_simulation_result(scenario_id)
    if not result:
        return f"""
        <html>
            <head>
                <title>Results Not Found</title>
                <style>
                    body {{ font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
                    .error {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); text-align: center; }}
                    h1 {{ color: #ef4444; }}
                </style>
            </head>
            <body>
                <div class="error">
                    <h1>⚠️ Results Not Found</h1>
                    <p>The scenario ID '{scenario_id}' does not exist or has expired.</p>
                </div>
            </body>
        </html>
        """, 404

    # Update access count
    update_access_count(scenario_id)
    results = result['data']

    # Generate building cards HTML
    buildings_html = ""
    for idx, building in enumerate(results['buildings']):
        buildings_html += generate_building_html(building, idx)

    # Get proper URLs
    if 'platform.digicities.ch' in request.host:
        # Production - reverse proxy adds /apps prefix
        download_url = f"/apps/api/energy_simulation/results/{scenario_id}/download"
        api_results_url = f"/apps/api/energy_simulation/results/{scenario_id}"
    else:
        # Local development - no /apps prefix
        download_url = f"/api/energy_simulation/results/{scenario_id}/download"
        api_results_url = f"/api/energy_simulation/results/{scenario_id}"

    # Generate HTML page with results
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Energy Simulation Results - {scenario_id}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                background: rgba(255, 255, 255, 0.95);
                border-radius: 12px;
                padding: 30px;
                margin-bottom: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }}
            .title {{
                font-size: 2rem;
                font-weight: bold;
                color: #1a202c;
                margin-bottom: 10px;
            }}
            .subtitle {{
                color: #718096;
                font-size: 14px;
            }}
            .action-buttons {{
                display: flex;
                gap: 10px;
                margin-top: 20px;
                flex-wrap: wrap;
            }}
            .button {{
                padding: 10px 20px;
                border-radius: 6px;
                border: none;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }}
            .button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }}
            .primary-button {{
                background: #667eea;
                color: #fff;
            }}
            .secondary-button {{
                background: #48bb78;
                color: #fff;
            }}
            .metrics-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }}
            .metric-card {{
                background: #fff;
                border-radius: 12px;
                padding: 25px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: center;
            }}
            .metric-value {{
                font-size: 2rem;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .metric-label {{
                font-size: 14px;
                color: #718096;
            }}
            .card {{
                background: #fff;
                border-radius: 12px;
                padding: 25px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }}
            .card-title {{
                font-size: 1.25rem;
                font-weight: 600;
                margin-bottom: 20px;
                color: #2d3748;
            }}
            .building-card {{
                background: #f7fafc;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 15px;
                border: 1px solid #e2e8f0;
            }}
            .building-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }}
            .building-title {{
                font-size: 18px;
                font-weight: 600;
                color: #2d3748;
            }}
            .badge {{
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
                color: #fff;
            }}
            .excellent {{ background: #10b981; }}
            .good {{ background: #3b82f6; }}
            .average {{ background: #f59e0b; }}
            .poor {{ background: #ef4444; }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin-top: 15px;
            }}
            .stat {{
                background: #fff;
                padding: 12px;
                border-radius: 6px;
                border: 1px solid #e2e8f0;
            }}
            .stat-label {{
                font-size: 12px;
                color: #718096;
                margin-bottom: 4px;
            }}
            .stat-value {{
                font-size: 16px;
                font-weight: 600;
                color: #2d3748;
            }}
            .energy-bar {{
                height: 30px;
                background: #e2e8f0;
                border-radius: 6px;
                overflow: hidden;
                margin-top: 15px;
                display: flex;
            }}
            .energy-segment {{
                display: flex;
                align-items: center;
                justify-content: center;
                color: #fff;
                font-size: 11px;
                font-weight: 600;
            }}
            .heating {{ background: #ef4444; }}
            .dhw {{ background: #3b82f6; }}
            .electrical {{ background: #10b981; }}
            .legend {{
                display: flex;
                gap: 20px;
                margin-top: 10px;
                font-size: 13px;
                color: #4a5568;
            }}
            .json-link {{
                color: #667eea;
                text-decoration: none;
                font-weight: 600;
            }}
            .json-link:hover {{
                text-decoration: underline;
            }}
            @media (max-width: 768px) {{
                .metrics-grid {{
                    grid-template-columns: 1fr;
                }}
                .stats-grid {{
                    grid-template-columns: 1fr;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 class="title">🏢 Energy Simulation Results</h1>
                <p class="subtitle">
                    Scenario ID: <strong>{scenario_id}</strong> | 
                    Created: {results['timestamp']} | 
                    Views: {result.get('access_count', 0)}
                </p>
                
                <div class="action-buttons">
                    <button class="button primary-button" onclick="shareResults()">
                        📤 Share Results
                    </button>
                    <a href="{download_url}" class="button secondary-button">
                        💾 Download JSON
                    </a>
                    <button class="button" style="background: #9f7aea; color: #fff;" onclick="copyLink()">
                        📋 Copy Link
                    </button>
                </div>
            </div>

            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value" style="color: #667eea;">
                        {results['aggregate']['total_annual_consumption_kWh']:,.0f}
                    </div>
                    <div class="metric-label">Total Annual Consumption (kWh)</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-value" style="color: #ef4444;">
                        {results['aggregate']['peak_demand_kW']:,.1f}
                    </div>
                    <div class="metric-label">Peak Demand (kW)</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-value" style="color: #10b981;">
                        {results['aggregate']['number_of_buildings']}
                    </div>
                    <div class="metric-label">Buildings Simulated</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-value" style="color: #f59e0b;">
                        {results['aggregate']['load_factor']*100:.1f}%
                    </div>
                    <div class="metric-label">Load Factor</div>
                </div>
            </div>

            <div class="card">
                <h2 class="card-title">Weather Information</h2>
                <div class="stats-grid">
                    <div class="stat">
                        <div class="stat-label">Location</div>
                        <div class="stat-value">{results['weather_location']}</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Data Source</div>
                        <div class="stat-value">{results['weather_source'].title()}</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h2 class="card-title">Building Performance Details</h2>
                {buildings_html}
            </div>

            <div class="card" style="text-align: center; background: #f7fafc;">
                <p style="color: #4a5568; margin-bottom: 10px;">
                    Full data available via API:
                </p>
                <a href="{api_results_url}" class="json-link">
                    📊 View JSON Data
                </a>
            </div>
        </div>

        <script>
            function shareResults() {{
                if (navigator.share) {{
                    navigator.share({{
                        title: 'Energy Simulation Results',
                        text: 'Check out my energy simulation results',
                        url: window.location.href
                    }});
                }} else {{
                    copyLink();
                }}
            }}
            
            function copyLink() {{
                navigator.clipboard.writeText(window.location.href);
                alert('Link copied to clipboard!');
            }}
        </script>
    </body>
    </html>
    """

    return html_content

def generate_building_html(building, index):
    """Generate HTML for a single building."""
    consumption_per_m2 = building.get('consumption_per_m2', 0)

    # Determine efficiency rating
    if consumption_per_m2 < 100:
        rating = 'excellent'
        rating_text = 'Excellent'
    elif consumption_per_m2 < 150:
        rating = 'good'
        rating_text = 'Good'
    elif consumption_per_m2 < 200:
        rating = 'average'
        rating_text = 'Average'
    else:
        rating = 'poor'
        rating_text = 'Poor'

    # Calculate percentages for energy breakdown
    total = building['annual_consumption_kWh']
    heating_pct = (building['annual_heating_kWh'] / total * 100) if total > 0 else 0
    dhw_pct = (building['annual_dhw_kWh'] / total * 100) if total > 0 else 0
    electrical_pct = (building['annual_electrical_kWh'] / total * 100) if total > 0 else 0

    return f"""
    <div class="building-card">
        <div class="building-header">
            <div class="building-title">
                Building {index + 1} - {building['metadata']['building_type']}
            </div>
            <div class="badge {rating}">{rating_text}</div>
        </div>
        
        <div class="stats-grid">
            <div class="stat">
                <div class="stat-label">Total Area</div>
                <div class="stat-value">{building['metadata']['total_area_m2']:,.0f} m²</div>
            </div>
            <div class="stat">
                <div class="stat-label">Year Built</div>
                <div class="stat-value">{building['metadata']['year_built']}</div>
            </div>
            <div class="stat">
                <div class="stat-label">Annual Consumption</div>
                <div class="stat-value">{building['annual_consumption_kWh']:,.0f} kWh</div>
            </div>
            <div class="stat">
                <div class="stat-label">Consumption per m²</div>
                <div class="stat-value">{building['consumption_per_m2']:.1f} kWh/m²</div>
            </div>
        </div>
        
        <div class="energy-bar">
            <div class="energy-segment heating" style="width: {heating_pct:.1f}%">
                {heating_pct:.0f}%
            </div>
            <div class="energy-segment dhw" style="width: {dhw_pct:.1f}%">
                {dhw_pct:.0f}%
            </div>
            <div class="energy-segment electrical" style="width: {electrical_pct:.1f}%">
                {electrical_pct:.0f}%
            </div>
        </div>
        <div class="legend">
            <span>🔥 Heating ({building['annual_heating_kWh']:,.0f} kWh)</span>
            <span>💧 Hot Water ({building['annual_dhw_kWh']:,.0f} kWh)</span>
            <span>⚡ Electrical ({building['annual_electrical_kWh']:,.0f} kWh)</span>
        </div>
    </div>
    """

@energy_sim_bp.route('/energy_simulation/results', methods=['GET'])
def list_simulation_results():
    """List all available simulation results (admin endpoint)."""
    all_results = list_all_results()

    scenarios = []
    for scenario_id, data in all_results:
        scenarios.append({
            'scenario_id': scenario_id,
            'created_at': data['created_at'].isoformat(),
            'access_count': data.get('access_count', 0),
            'buildings_count': len(data['data']['buildings']),
            'total_consumption': data['data']['aggregate']['total_annual_consumption_kWh']
        })

    scenarios.sort(key=lambda x: x['created_at'], reverse=True)

    return jsonify({
        'total_scenarios': len(scenarios),
        'scenarios': scenarios
    }), 200

# API Documentation endpoint
@energy_sim_bp.route('/energy_simulation/api_docs', methods=['GET'])
def api_documentation():
    """Return API documentation for third-party integration."""
    base_url = request.host_url.rstrip('/')

    if 'platform.digicities.ch' in request.host:
        # Production - reverse proxy adds /apps prefix
        api_base = base_url + '/apps/api'
    else:
        # Local development - no /apps prefix
        api_base = base_url + '/api'

    docs = {
        "api_name": "Energy Simulation API",
        "version": "1.0",
        "base_url": api_base,
        "endpoints": {
            "run_simulation": {
                "method": "POST",
                "url": "/energy_simulation",
                "description": "Run an energy simulation and get a unique result URL",
                "request_body": {
                    "service_name": "string (optional)",
                    "scenario_data": {
                        "uri": "string",
                        "name": "string",
                        "location": {
                            "uri": "string",
                            "weather_data": "string (EPW filename or empty for synthetic)",
                            "buildings": [
                                {
                                    "uri": "string",
                                    "SIA2024BuildingType": "string (SFH|MFH|Office|Retail)",
                                    "BuildingAge": "string (year)",
                                    "GroundFloorArea": "number",
                                    "NumberOfFloors": "number",
                                    "HeatingSupply": "string (OilHeated|GasHeated|ElectricallyHeated|AirHeated|DistrictHeated)",
                                    "DHWSupply": "string (OilHeated|GasHeated|ElectricallyHeated|AirHeated|DistrictHeated)"
                                }
                            ]
                        }
                    }
                },
                "response": {
                    "success": "boolean",
                    "scenario_id": "string",
                    "result_url": "string (HTML results page URL)",
                    "api_url": "string (JSON API endpoint)",
                    "summary": {
                        "total_annual_consumption_kWh": "number",
                        "number_of_buildings": "number"
                    }
                },
                "example_curl": f"""curl -X POST {api_base}/energy_simulation \\
  -H "Content-Type: application/json" \\
  -d '{{
    "service_name": "CESARP_Building_Simulation",
    "scenario_data": {{
      "location": {{
        "weather_data": "",
        "buildings": [{{
          "SIA2024BuildingType": "MFH",
          "BuildingAge": "1970",
          "GroundFloorArea": 284,
          "NumberOfFloors": 4,
          "HeatingSupply": "GasHeated",
          "DHWSupply": "GasHeated"
        }}]
      }}
    }}
  }}'"""
            },
            "get_results": {
                "method": "GET",
                "url": "/energy_simulation/results/{scenario_id}",
                "description": "Get full simulation results by scenario ID",
                "response": "Full simulation results JSON"
            },
            "get_summary": {
                "method": "GET",
                "url": "/energy_simulation/results/{scenario_id}/summary",
                "description": "Get lightweight summary of results",
                "response": "Summary JSON with key metrics"
            },
            "download_results": {
                "method": "GET",
                "url": "/energy_simulation/results/{scenario_id}/download",
                "description": "Download results as JSON file",
                "response": "JSON file download"
            }
        },
        "integration_example": {
            "description": "Example JavaScript code for third-party integration",
            "code": f"""// Run simulation from your website
async function runEnergySimulation() {{
    const response = await fetch('{api_base}/energy_simulation', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
            scenario_data: {{
                location: {{
                    weather_data: '',  // Use synthetic weather
                    buildings: [{{
                        SIA2024BuildingType: 'SFH',
                        BuildingAge: '2000',
                        GroundFloorArea: 150,
                        NumberOfFloors: 2,
                        HeatingSupply: 'GasHeated',
                        DHWSupply: 'GasHeated'
                    }}]
                }}
            }}
        }})
    }});
    
    const result = await response.json();
    
    // Display result URL to user
    if (result.success) {{
        console.log('Results available at:', result.result_url);
        // Embed in iframe or redirect
        window.open(result.result_url, '_blank');
    }}
}}"""
        },
        "iframe_integration": {
            "description": "Embed results in an iframe",
            "code": f"""<iframe 
    src="{base_url}/energy_results/{{scenario_id}}" 
    width="100%" 
    height="800px" 
    frameborder="0">
</iframe>"""
        }
    }

    return jsonify(docs), 200

@energy_sim_bp.route('/energy_simulation/validate', methods=['POST'])
@require_api_key
def validate_input():
    """Validate simulation input. Requires API key authentication."""
    try:
        data = request.get_json()

        errors = []
        warnings = []

        # Check structure
        if 'scenario_data' not in data:
            errors.append("Missing 'scenario_data' field")

        buildings = data.get('scenario_data', {}).get('location', {}).get('buildings', [])

        if not buildings:
            errors.append("No buildings provided")

        # Validate each building
        for i, building in enumerate(buildings):
            # Check required fields
            required = ['SIA2024BuildingType', 'GroundFloorArea', 'NumberOfFloors']
            for field in required:
                if field not in building:
                    errors.append(f"Building {i}: Missing required field '{field}'")

            # Validate types
            btype = building.get('SIA2024BuildingType')
            if btype and btype not in ['SFH', 'MFH', 'Office', 'Retail']:
                warnings.append(f"Building {i}: Unknown type '{btype}', will use default factors")

        return jsonify({
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'building_count': len(buildings)
        }), 200 if not errors else 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@energy_sim_bp.route('/energy_simulation/sample', methods=['GET'])
def get_sample_data():
    """Get sample data for testing."""
    return jsonify({
        "service_name": "CESARP_Building_Simulation",
        "scenario_data": {
            "uri": "https://digicities.info/proj/workspace_CHUC2-AIL-Energy-Planning/CESARP-Simulation-Baseline-CH",
            "name": "Sample Simulation",
            "location": {
                "uri": "https://digicities.info/dataproducts/Energy_Plus_Weather_Files/Location/Lugano",
                "weather_data": "CHE_TI_Lugano.067700_TMYx.2009-2023.epw",
                "buildings": [
                    {
                        "uri": "https://digicities.info/dataproducts/GWR/Building/sample1",
                        "SIA2024BuildingType": "MFH",
                        "BuildingAge": "1970",
                        "GroundFloorArea": 284.0,
                        "NumberOfFloors": 4.0,
                        "HeatingSupply": "GasHeated",
                        "DHWSupply": "GasHeated"
                    }
                ]
            }
        }
    })

@energy_sim_bp.route('/energy_simulation/weather_preview', methods=['POST'])
@require_api_key
def preview_weather_data():
    """Preview weather data from EPW file. Requires API key authentication."""
    try:
        data = request.get_json()
        weather_file_name = data.get('weather_file', '')

        # Get credentials from request or environment variables
        credentials = data.get('credentials', {})
        username = credentials.get('username') or os.getenv('NEXTCLOUD_BASIC_USERNAME', 'admin')
        password = credentials.get('password') or os.getenv('NEXTCLOUD_BASIC_PASSWORD')
        workspace = credentials.get('workspace', 'workspace_CHUC2-AIL-Energy-Planning')

        if not weather_file_name:
            # Return synthetic data preview
            synthetic = generate_synthetic_weather()

            # Create hourly dataframe for first week
            hours = list(range(168))  # First week
            temps = synthetic['temperatures'][:168]
            humidity = synthetic['humidity'][:168] if synthetic.get('humidity') else [50] * 168
            wind = synthetic['wind_speed'][:168] if synthetic.get('wind_speed') else [5] * 168

            # Calculate daily statistics
            daily_stats = []
            for day in range(7):
                day_temps = temps[day*24:(day+1)*24]
                daily_stats.append({
                    'day': day + 1,
                    'min_temp': round(min(day_temps), 1),
                    'max_temp': round(max(day_temps), 1),
                    'avg_temp': round(sum(day_temps) / len(day_temps), 1)
                })

            return jsonify({
                'source': 'synthetic',
                'location': 'Synthetic Data',
                'preview_hours': 168,
                'hourly_data': {
                    'hours': hours,
                    'temperature': [round(t, 1) for t in temps],
                    'humidity': [round(h, 1) for h in humidity],
                    'wind_speed': [round(w, 1) for w in wind]
                },
                'daily_stats': daily_stats,
                'annual_stats': {
                    'min_temp': round(min(synthetic['temperatures']), 1),
                    'max_temp': round(max(synthetic['temperatures']), 1),
                    'avg_temp': round(sum(synthetic['temperatures']) / len(synthetic['temperatures']), 1),
                    'heating_degree_days': calculate_hdd(synthetic['temperatures'])
                }
            })

        # Try to download and parse actual weather file
        weather_filepath = None
        if username and password:
            weather_filepath = download_weather_file(
                username,
                password,
                workspace,
                weather_file_name
            )
        else:
            return jsonify({'error': 'No credentials available. Please set NEXTCLOUD_BASIC_USERNAME and NEXTCLOUD_BASIC_PASSWORD in .env file'}), 400

        if not weather_filepath:
            return jsonify({'error': f'Failed to download weather file: {weather_file_name}'}), 400

        # Parse the weather file
        weather_data = parse_weather_file(weather_filepath)

        # Clean up
        if os.path.exists(weather_filepath):
            os.remove(weather_filepath)

        if not weather_data['has_data']:
            return jsonify({'error': 'Failed to parse weather file'}), 400

        # Prepare preview data (first week)
        temps = weather_data['temperatures'][:168]
        humidity = weather_data.get('humidity', [50] * 168)[:168]
        wind = weather_data.get('wind_speed', [5] * 168)[:168]

        # Calculate daily statistics
        daily_stats = []
        for day in range(7):
            day_temps = temps[day*24:(day+1)*24]
            if day_temps:
                daily_stats.append({
                    'day': day + 1,
                    'min_temp': round(min(day_temps), 1),
                    'max_temp': round(max(day_temps), 1),
                    'avg_temp': round(sum(day_temps) / len(day_temps), 1)
                })

        # Calculate annual statistics
        annual_temps = weather_data['temperatures']

        return jsonify({
            'source': 'cloud',
            'location': weather_data.get('location', 'Unknown'),
            'preview_hours': len(temps),
            'hourly_data': {
                'hours': list(range(len(temps))),
                'temperature': [round(t, 1) for t in temps],
                'humidity': [round(h, 1) for h in humidity] if humidity else [],
                'wind_speed': [round(w, 1) for w in wind] if wind else []
            },
            'daily_stats': daily_stats,
            'annual_stats': {
                'min_temp': round(min(annual_temps), 1),
                'max_temp': round(max(annual_temps), 1),
                'avg_temp': round(sum(annual_temps) / len(annual_temps), 1),
                'heating_degree_days': calculate_hdd(annual_temps)
            }
        })

    except Exception as e:
        return jsonify({'error': f'Failed to preview weather data: {str(e)}'}), 500

def calculate_hdd(temperatures, base_temp=18.0):
    """Calculate Heating Degree Days from temperature array."""
    if not temperatures:
        return 0

    daily_temps = []
    for day in range(min(365, len(temperatures) // 24)):
        day_temps = temperatures[day*24:(day+1)*24]
        if day_temps:
            daily_temps.append(sum(day_temps) / len(day_temps))

    hdd = sum(max(0, base_temp - t) for t in daily_temps)
    return round(hdd, 1)