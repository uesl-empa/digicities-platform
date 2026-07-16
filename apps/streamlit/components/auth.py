# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# auth.py

import streamlit as st
import requests
import base64
import json
import os
import urllib.parse
import socket
from dotenv import load_dotenv

load_dotenv()

KEYCLOAK_BASE_URL = os.getenv("KEYCLOAK_BASE_URL")
REALM = os.getenv("KEYCLOAK_REALM")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")
CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")
REDIRECT_URI = os.getenv("KEYCLOAK_REDIRECT_URI")

AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"
LOCAL_WORKSPACE = os.getenv("LOCAL_WORKSPACE", "workspace_local")


def setup_local_auth():
    """Populate session state as if a user logged in. Used when AUTH_DISABLED=true.

    Workspace discovery priority:
    1. Workspaces declared in the workspace registry (data/workspaces.yaml + auto-discovery
       under $USECASES_DIR). All of them become "groups" the user can pick from.
    2. If the registry is empty or fails to load, fall back to a single workspace
       named by $LOCAL_WORKSPACE.
    """
    st.session_state["authenticated"] = True
    st.session_state["access_token"] = "local"
    st.session_state["nextcloud_token"] = "local"

    group_ids = []
    try:
        # Late import so this module stays importable even if backend.workspace
        # isn't reachable (e.g. during static analysis or tests).
        from backend.workspace import load_registry
        registry = load_registry()
        group_ids = [ctx.id for ctx in registry]
    except Exception as exc:
        print(f"[setup_local_auth] workspace registry load failed: {exc}")

    if not group_ids:
        group_ids = [LOCAL_WORKSPACE]

    st.session_state["access_payload"] = {
        "preferred_username": "local_user",
        "email": "local@localhost",
        "groups": group_ids,
    }
    st.session_state["token_timestamp"] = float("inf")
    st.session_state["token_expires_in"] = float("inf")


def is_running_locally():
    """
    Detect if the app is running locally vs in production
    """
    # Method 1: Check for explicit environment override
    env_setting = os.getenv('ENVIRONMENT', '').lower()
    if env_setting == 'production':
        return False
    if env_setting == 'local' or env_setting == 'development':
        return True

    # Method 2: Check STREAMLIT_ENV
    streamlit_env = os.getenv('STREAMLIT_ENV', '').lower()
    if streamlit_env == 'production':
        return False
    if streamlit_env == 'development':
        return True

    # Method 3: Check if we're running on known production domains
    try:
        # Check if the current working directory suggests production deployment
        cwd = os.getcwd().lower()
        production_indicators = [
            '/opt/',
            '/var/',
            '/home/ubuntu',
            '/app',
            'docker',
            'container'
        ]
        if any(indicator in cwd for indicator in production_indicators):
            return False
    except:
        pass

    # Method 4: Check hostname for production indicators
    try:
        hostname = socket.gethostname().lower()
        production_hostnames = [
            'prod',
            'production',
            'server',
            'digicities',
            'platform'
        ]
        if any(indicator in hostname for indicator in production_hostnames):
            return False
    except:
        pass

    # Method 5: Check if we're running on localhost/127.0.0.1 (only for clear local indicators)
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        # Only consider it local if it's clearly localhost
        clear_local_indicators = [
            hostname.lower() == 'localhost',
            local_ip == '127.0.0.1',
            hostname.lower().startswith('desktop-'),
            hostname.lower().startswith('laptop-')
        ]

        if any(clear_local_indicators):
            return True
    except:
        pass

    # Method 6: Check for development ports (only if other indicators suggest local)
    try:
        import sys
        for arg in sys.argv:
            if '--server.port' in arg and ('8501' in arg or '8502' in arg or '8503' in arg):
                # Only consider this local if hostname also suggests it
                try:
                    hostname = socket.gethostname().lower()
                    if 'localhost' in hostname or hostname.startswith('desktop-') or hostname.startswith('laptop-'):
                        return True
                except:
                    pass
    except:
        pass

    # Default to production (safer assumption)
    return False


def get_redirect_uri():
    """
    Get the appropriate redirect URI based on environment
    """
    # Check for manual override first
    if hasattr(st.session_state, 'auth_redirect_override') and st.session_state.auth_redirect_override:
        return st.session_state.auth_redirect_override

    # Check for local development environment variable
    local_redirect = os.getenv('KEYCLOAK_LOCAL_REDIRECT_URI')
    if is_running_locally() and local_redirect:
        print(f"DEBUG: Using local redirect URI from env: {local_redirect}")
        return local_redirect

    # Auto-detect local development
    if is_running_locally():
        # Try to determine the local port
        port = os.getenv('STREAMLIT_SERVER_PORT', '8501')

        # Check if port is specified in command line args
        try:
            import sys
            for i, arg in enumerate(sys.argv):
                if arg == '--server.port' and i + 1 < len(sys.argv):
                    port = sys.argv[i + 1]
                    break
                elif arg.startswith('--server.port='):
                    port = arg.split('=')[1]
                    break
        except:
            pass

        local_uri = f"http://localhost:{port}"
        print(f"DEBUG: Auto-detected local redirect URI: {local_uri}")
        return local_uri

    # Use production URI
    print(f"DEBUG: Using production redirect URI: {REDIRECT_URI}")
    return REDIRECT_URI


def build_login_url():
    """
    Build login URL with environment-appropriate redirect URI
    """
    redirect_uri = get_redirect_uri()

    login_url = (
        f"{KEYCLOAK_BASE_URL}/realms/{REALM}/protocol/openid-connect/auth?"
        f"response_type=code&"
        f"client_id={urllib.parse.quote(CLIENT_ID)}&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"scope=openid email profile"
    )

    print(f"DEBUG: Built login URL with redirect: {redirect_uri}")
    return login_url


def handle_login():
    """
    Handle the login process with environment-aware redirect URI
    """
    query_params = st.query_params
    code = query_params.get("code")

    if code and not st.session_state.get("authenticated"):
        token_url = f"{KEYCLOAK_BASE_URL}/realms/{REALM}/protocol/openid-connect/token"

        # Use the same redirect URI that was used for the login
        redirect_uri = get_redirect_uri()

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,  # Must match the one used in login
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }

        print(f"DEBUG: Token exchange using redirect URI: {redirect_uri}")

        try:
            res = requests.post(token_url, data=data)
            res.raise_for_status()
            token_data = res.json()

            # Store tokens in session (including refresh token!)
            st.session_state["access_token"] = token_data.get("access_token")
            st.session_state["refresh_token"] = token_data.get("refresh_token")  # NEW: Store refresh token
            st.session_state["nextcloud_token"] = token_data["access_token"]
            st.session_state["token_expires_in"] = token_data.get("expires_in", 28800)  # Default 8 hours
            st.session_state["token_timestamp"] = __import__('time').time()  # Track when token was issued

            # Decode payload
            payload_part = token_data.get("access_token").split(".")[1]
            padded = payload_part + '=' * (-len(payload_part) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode()
            payload = json.loads(decoded)
            st.session_state["access_payload"] = payload
            st.session_state["authenticated"] = True

            # Clear code from URL to prevent re-use
            st.query_params.clear()

            print("DEBUG: Authentication successful!")
            print(f"DEBUG: Token expires in {token_data.get('expires_in', 'unknown')} seconds")
            return True

        except Exception as e:
            st.error(f"Token exchange failed: {e}")
            print(f"DEBUG: Token exchange error: {e}")
            if 'res' in locals() and res is not None:
                st.code(res.text)
                print(f"DEBUG: Response text: {res.text}")

    return st.session_state.get("authenticated", False)


def refresh_access_token():
    """
    Refresh the access token using the refresh token
    Returns True if successful, False otherwise
    """
    if not st.session_state.get("refresh_token"):
        print("DEBUG: No refresh token available")
        return False

    token_url = f"{KEYCLOAK_BASE_URL}/realms/{REALM}/protocol/openid-connect/token"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": st.session_state["refresh_token"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    try:
        print("DEBUG: Attempting to refresh access token...")
        res = requests.post(token_url, data=data)
        res.raise_for_status()
        token_data = res.json()

        # Update tokens in session
        st.session_state["access_token"] = token_data.get("access_token")
        st.session_state["refresh_token"] = token_data.get("refresh_token")  # Refresh token can also be rotated
        st.session_state["nextcloud_token"] = token_data["access_token"]
        st.session_state["token_expires_in"] = token_data.get("expires_in", 28800)
        st.session_state["token_timestamp"] = __import__('time').time()

        # Update payload
        payload_part = token_data.get("access_token").split(".")[1]
        padded = payload_part + '=' * (-len(payload_part) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        payload = json.loads(decoded)
        st.session_state["access_payload"] = payload

        # Update GraphDB client if it exists
        if st.session_state.get("workspace_client"):
            client = st.session_state.workspace_client
            client.token = token_data.get("access_token")
            client._create_token_session()
            client._create_session()
            print("DEBUG: Updated GraphDB client with new token")

        print(f"DEBUG: Token refresh successful! New token expires in {token_data.get('expires_in', 'unknown')} seconds")
        return True

    except Exception as e:
        print(f"DEBUG: Token refresh failed: {e}")
        if 'res' in locals() and res is not None:
            print(f"DEBUG: Response text: {res.text}")
        return False


def check_token_expiry():
    """
    Check if the access token is about to expire and refresh if needed
    Returns True if token is valid, False if refresh failed
    """
    if AUTH_DISABLED:
        return True

    if not st.session_state.get("authenticated"):
        return False

    if not st.session_state.get("token_timestamp"):
        # Legacy session without timestamp, assume it's old
        print("DEBUG: No token timestamp, attempting refresh...")
        return refresh_access_token()

    import time
    token_age = time.time() - st.session_state["token_timestamp"]
    token_expires_in = st.session_state.get("token_expires_in", 28800)

    # Refresh token if it's older than 90% of its lifetime
    # e.g., for 8 hour token (28800s), refresh after 7.2 hours (25920s)
    refresh_threshold = token_expires_in * 0.9

    if token_age >= refresh_threshold:
        print(f"DEBUG: Token is {token_age:.0f}s old (threshold: {refresh_threshold:.0f}s), refreshing...")
        if refresh_access_token():
            st.toast("🔄 Session refreshed successfully!", icon="✅")
            return True
        else:
            st.warning("⚠️ Session expired. Please log in again.")
            return False

    return True


def logout():
    """
    Handle logout with environment-aware redirect URI
    """
    redirect_uri = get_redirect_uri()

    st.session_state.clear()
    keycloak_logout_url = (
        f"{KEYCLOAK_BASE_URL}/realms/{REALM}/protocol/openid-connect/logout"
        f"?redirect_uri={urllib.parse.quote(redirect_uri)}"
    )

    print(f"DEBUG: Logout redirect URI: {redirect_uri}")
    st.markdown(f"<meta http-equiv='refresh' content='0;URL={keycloak_logout_url}'>", unsafe_allow_html=True)