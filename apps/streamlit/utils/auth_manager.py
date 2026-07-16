# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# utils/auth_manager.py
import hashlib
from typing import Dict, Optional


def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


# Mock user database (demo / local mode; real auth uses Keycloak).
MOCK_USERS = {
    "demo_user": {
        "password_hash": hash_password("demo123"),  # Generate hash dynamically
        "role": "admin",
        "name": "Demo User",
        "email": "demo@digicities.com"
    },
    "energy_analyst": {
        "password_hash": hash_password("analyst123"),  # Generate hash dynamically
        "role": "analyst",
        "name": "Energy Analyst",
        "email": "analyst@digicities.com"
    },
    "municipal_manager": {
        "password_hash": hash_password("manager123"),  # Generate hash dynamically
        "role": "manager",
        "name": "Municipal Manager",
        "email": "manager@digicities.com"
    }
}

# Mock user access rights
USER_ACCESS_RIGHTS = {
    "demo_user": {
        "workspaces": ["lugano_hydro", "vienna_school", "alkmaar_windpark"],
        "role": "admin"
    },
    "energy_analyst": {
        "workspaces": ["lugano_hydro", "alkmaar_windpark"],
        "role": "analyst"
    },
    "municipal_manager": {
        "workspaces": ["vienna_school"],
        "role": "manager"
    }
}


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user with username and password"""
    print(f"Attempting to authenticate user: {username}")

    if username not in MOCK_USERS:
        print(f"User {username} not found in MOCK_USERS")
        print(f"Available users: {list(MOCK_USERS.keys())}")
        return False

    password_hash = hash_password(password)
    stored_hash = MOCK_USERS[username]["password_hash"]

    print(f"Provided password hash: {password_hash}")
    print(f"Stored password hash: {stored_hash}")
    print(f"Hashes match: {password_hash == stored_hash}")

    return stored_hash == password_hash


def get_user_info(username: str) -> Optional[Dict]:
    """Get user information"""
    if username not in MOCK_USERS:
        return None

    user_info = MOCK_USERS[username].copy()
    # Don't return password hash
    user_info.pop("password_hash", None)
    return user_info


def check_workspace_access(user_id: str, workspace_id: str) -> bool:
    """Check if user has access to a specific workspace"""
    if user_id not in USER_ACCESS_RIGHTS:
        return True

    return workspace_id in USER_ACCESS_RIGHTS[user_id]["workspaces"]


def get_user_role(user_id: str) -> Optional[str]:
    """Get user role"""
    if user_id not in USER_ACCESS_RIGHTS:
        return None

    return USER_ACCESS_RIGHTS[user_id]["role"]