# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# utils/workspace_manager.py - Simplified version
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd

# Mock workspace configurations
MOCK_WORKSPACES = {
    "lugano_hydro": {
        "id": "lugano_hydro",
        "name": "Lugano Hydro Plant",
        "description": "Hydroelectric power plant monitoring and optimization",
        "type": "Energy Generation",
        "location": "Lugano, Switzerland",
        "created_date": "2024-01-15",
        "last_access": "2025-06-10",
        "graphdb_config": {
            "endpoint": "http://localhost:7200/repositories/lugano_hydro",
            "username": "admin",
            "password": "admin"
        },
        "file_storage": {
            "type": "local",
            "path": "data/workspaces/lugano_hydro"
        },
        "permissions": ["read", "write", "query"]
    },
    "vienna_school": {
        "id": "vienna_school",
        "name": "School Building Vienna",
        "description": "Educational facility energy efficiency monitoring",
        "type": "Building Management",
        "location": "Vienna, Austria",
        "created_date": "2024-03-10",
        "last_access": "2025-06-12",
        "graphdb_config": {
            "endpoint": "http://localhost:7200/repositories/vienna_school",
            "username": "admin",
            "password": "admin"
        },
        "file_storage": {
            "type": "local",
            "path": "data/workspaces/vienna_school"
        },
        "permissions": ["read", "query"]
    },
    "alkmaar_windpark": {
        "id": "alkmaar_windpark",
        "name": "WindPark Alkmaar",
        "description": "Wind energy generation and forecasting system",
        "type": "Renewable Energy",
        "location": "Alkmaar, Netherlands",
        "created_date": "2024-04-05",
        "last_access": "2025-06-11",
        "graphdb_config": {
            "endpoint": "http://localhost:7200/repositories/alkmaar_windpark",
            "username": "admin",
            "password": "admin"
        },
        "file_storage": {
            "type": "local",
            "path": "data/workspaces/alkmaar_windpark"
        },
        "permissions": ["read", "write", "query"]
    }
}


def get_user_workspaces(user_id: str) -> List[Dict]:
    """Get list of workspaces available to a user"""
    # Import here to avoid circular imports
    from utils.auth_manager import USER_ACCESS_RIGHTS

    if user_id not in USER_ACCESS_RIGHTS:
        return []

    user_workspace_ids = USER_ACCESS_RIGHTS[user_id]["workspaces"]

    # Return workspace configurations for accessible workspaces
    workspaces = []
    for workspace_id in user_workspace_ids:
        if workspace_id in MOCK_WORKSPACES:
            workspaces.append(MOCK_WORKSPACES[workspace_id])

    return workspaces


def get_workspace_config(workspace_id: str) -> Optional[Dict]:
    """Get configuration for a specific workspace"""
    return MOCK_WORKSPACES.get(workspace_id)


def initialize_workspace_client(workspace_config: Dict):
    """Initialize GraphDB client for a workspace"""
    try:
        # For now, return None to indicate no GraphDB connection
        # In a real implementation, you would use workspace_config['graphdb_config']
        print(f"Initializing client for workspace: {workspace_config['name']}")
        return None
    except Exception as e:
        print(f"Error initializing workspace client: {e}")
        return None


def get_workspace_file_storage_path(workspace_config: Dict) -> Path:
    """Get the file storage path for a workspace"""
    storage_config = workspace_config.get("file_storage", {})
    if storage_config.get("type") == "local":
        return Path(storage_config["path"])
    else:
        # For cloud storage, would return appropriate path/client
        return Path("data/workspaces/default")


def ensure_workspace_directories():
    """Ensure all workspace directories exist with sample data"""
    base_path = Path("data/workspaces")
    base_path.mkdir(parents=True, exist_ok=True)

    # Create sample CSV files for each workspace
    sample_data = {
        "lugano_hydro": {
            "water_flow_data.csv": {
                "timestamp": ["2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05"],
                "flow_rate_m3s": [45.2, 42.8, 48.1, 44.5, 46.9],
                "water_level_m": [125.4, 124.8, 126.2, 125.1, 125.8],
                "power_output_MW": [12.5, 11.8, 13.2, 12.1, 12.9]
            },
            "turbine_efficiency.csv": {
                "turbine_id": ["T001", "T002", "T003", "T004"],
                "efficiency_percent": [89.5, 91.2, 88.8, 90.1],
                "maintenance_hours": [24, 18, 32, 22],
                "last_service": ["2025-05-15", "2025-05-20", "2025-05-10", "2025-05-18"]
            }
        },
        "vienna_school": {
            "building_energy.csv": {
                "timestamp": ["2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05"],
                "heating_kWh": [150, 145, 160, 140, 155],
                "cooling_kWh": [85, 90, 80, 95, 88],
                "lighting_kWh": [65, 62, 68, 60, 66],
                "total_consumption_kWh": [300, 297, 308, 295, 309]
            },
            "room_occupancy.csv": {
                "room_id": ["R101", "R102", "R103", "R104", "R105"],
                "capacity": [30, 35, 25, 40, 32],
                "avg_occupancy": [28, 32, 23, 35, 29],
                "utilization_percent": [93.3, 91.4, 92.0, 87.5, 90.6]
            }
        },
        "alkmaar_windpark": {
            "wind_data.csv": {
                "timestamp": ["2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05"],
                "wind_speed_ms": [12.5, 8.2, 15.8, 11.3, 13.7],
                "wind_direction_deg": [245, 220, 280, 235, 260],
                "power_output_MW": [8.5, 3.2, 12.8, 6.9, 9.8],
                "turbine_availability": [0.98, 0.95, 0.99, 0.97, 0.98]
            },
            "turbine_performance.csv": {
                "turbine_id": ["WT001", "WT002", "WT003", "WT004", "WT005"],
                "rated_power_MW": [2.5, 2.5, 2.5, 2.5, 2.5],
                "capacity_factor": [0.34, 0.31, 0.38, 0.33, 0.36],
                "maintenance_status": ["OK", "SCHEDULED", "OK", "OK", "MINOR_ISSUE"]
            }
        }
    }

    # Create directories and CSV files
    for workspace_id, files in sample_data.items():
        workspace_path = base_path / workspace_id
        workspace_path.mkdir(exist_ok=True)

        for filename, data in files.items():
            csv_path = workspace_path / filename
            if not csv_path.exists():
                df = pd.DataFrame(data)
                df.to_csv(csv_path, index=False)
                print(f"Created sample file: {csv_path}")


# Initialize workspace directories when module is imported
try:
    ensure_workspace_directories()
    print("Workspace directories initialized successfully")
except Exception as e:
    print(f"Error initializing workspace directories: {e}")