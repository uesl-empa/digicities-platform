# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import streamlit as st
import os
import socket

# "Archived" modules - not part of the guided workflow yet. Hidden by default; a
# "Show archived modules" toggle in the sidebar reveals them (flagged when shown).
# The supported end-to-end pipelines are Replica Builder -> Scenario Builder ->
# API Data Submission (energy simulation and flexibility optimiser).
# Query Manager graduated out of this set: it now carries the workspace's
# recommended queries and is the Instance Inspector's landing module.
ARCHIVED_MODULES = {
    "Data Viewer and Uploader",
    "Data Products",
    "Assumptions Module",
}
import asyncio
import concurrent.futures
from functools import lru_cache
import time
from typing import Dict, Optional, Any
import hashlib

# Import styles from separate file
from styles import apply_platform_styles, render_appearance_toggle


# Performance monitoring decorator
def measure_performance(func):
    """Decorator to measure function performance in development mode"""

    def wrapper(*args, **kwargs):
        if is_development_mode():
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            execution_time = end_time - start_time
            if execution_time > 0.1:  # Log slow operations
                print(f"PERF: {func.__name__} took {execution_time:.3f}s")
            return result
        return func(*args, **kwargs)

    return wrapper


# Use your existing imports - don't change these
from components.auth import handle_login, build_login_url, logout, is_running_locally, get_redirect_uri, check_token_expiry, refresh_access_token, setup_local_auth, AUTH_DISABLED

# Import component modules with lazy loading
_component_modules = {}


def lazy_import_module(module_name: str, import_path: str, fallback_func=None):
    """Lazy import modules only when needed"""
    if module_name not in _component_modules:
        try:
            module = __import__(import_path, fromlist=[module_name])
            _component_modules[module_name] = getattr(module, module_name)
        except ImportError as e:
            if fallback_func:
                _component_modules[module_name] = fallback_func
            else:
                # Capture the error message in the closure scope
                error_message = str(e)
                def error_func(*args, **kwargs):
                    st.error(f"{module_name} temporarily unavailable: {error_message}")
                _component_modules[module_name] = error_func
    return _component_modules[module_name]


# Import Nextcloud components - keep your existing ones
try:
    from components.nextcloud_module import nextcloud_module, validate_nextcloud_config, get_nextcloud_client
except ImportError:
    def nextcloud_module(workspace):
        st.error("Data Viewer and Uploader temporarily unavailable")


    def validate_nextcloud_config():
        return False


    def get_nextcloud_client(name):
        return None

from components.graphdb import GraphDBClient


# =============================================================================
# PERFORMANCE OPTIMIZATIONS
# =============================================================================

# Cache for workspace metadata
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_workspace_metadata_cached(workspace_id: str) -> dict:
    """Load workspace metadata with caching."""
    return load_workspace_metadata(workspace_id)


# Cache for workspace images
@st.cache_data(ttl=600)  # Cache for 10 minutes
def get_workspace_image_cached(workspace_id: str) -> Optional[bytes]:
    """Get workspace image with caching."""
    return get_workspace_image(workspace_id)


# Cache for base64 image conversion
@st.cache_data
def get_image_base64_cached(image_path: str) -> str:
    """Convert image to base64 with caching based on file path."""
    return _get_image_base64(image_path)


# Thread pool for async operations
executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)


def async_check_graphdb_connection():
    """Asynchronously check GraphDB connection"""
    client = st.session_state.get('workspace_client')
    if not client:
        return False

    try:
        future = executor.submit(_check_graphdb_connection_sync, client)
        return future.result(timeout=2)  # 2 second timeout
    except:
        return False


def _check_graphdb_connection_sync(client):
    """Synchronous GraphDB connection check"""
    try:
        test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
        result = client.sparql_api_query(test_query, out_format="response")
        return result and result.status_code == 200
    except:
        return False


# =============================================================================
# SETUP AND CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="Digicities Platform",
    page_icon="🏢",
    layout="wide",
    # Always open the sidebar on load. Without this Streamlit's "auto" default
    # collapses it on narrower windows / remembers a collapsed state — and the
    # control to reopen it lives in the header, which our CSS hides.
    initial_sidebar_state="expanded",
)

# Apply styles from separate file
apply_platform_styles()

# Sidebar Light/Dark appearance selector — our replacement for Streamlit's
# native theme toggle (removed from the menu in 1.59). Lets macOS / dark-mode
# users switch to Dark. Rendered every run so it's always available.
render_appearance_toggle()

# Add performance CSS for smoother transitions
st.markdown("""
<style>
/* Prevent layout shifts */
.stApp {
    transition: none !important;
}

/* Smooth module transitions */
.module-container {
    min-height: 500px;
    transition: opacity 0.2s ease-in-out;
}

/* Reduce rerender flicker */
.main .block-container {
    padding-top: 2rem;
    will-change: transform;
}

/* Cache-friendly image styles */
.workspace-image {
    will-change: transform;
    transform: translateZ(0);
}

/* REDUCE WHITESPACE */
div[data-testid="stVerticalBlock"] > [style*="gap"] {
    gap: 0.5rem !important;
}

/* Reduce spacing after success messages */
div.stAlert {
    margin-bottom: 0.5rem !important;
}

/* Reduce header spacing */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    margin-top: 0.5rem !important;
    margin-bottom: 0.5rem !important;
}

/* Reduce general block spacing */
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
}

/* Reduce spacing between elements */
.row-widget.stButton {
    margin-top: 0 !important;
    margin-bottom: 0.25rem !important;
}

/* Fix module content spacing */
.main-content {
    padding-top: 0.5rem !important;
}

/* Reduce expander spacing */
.streamlit-expanderHeader {
    margin-top: 0.25rem !important;
    margin-bottom: 0.25rem !important;
}
</style>
""", unsafe_allow_html=True)


def is_development_mode() -> bool:
    """Detect if the platform is running in development mode"""
    # Check multiple indicators for development mode
    development_indicators = [
        os.getenv('STREAMLIT_ENV') == 'development',
        os.getenv('DEBUG') == 'true',
        os.getenv('ENVIRONMENT') == 'dev',
        is_running_locally(),
        'localhost' in os.getenv('STREAMLIT_SERVER_HEADLESS', ''),
    ]
    return any(development_indicators)


# Display environment info in development only
if is_development_mode():
    with st.sidebar:
        if st.checkbox("Show Performance Stats", key="show_perf_stats"):
            placeholder = st.empty()
            # Performance stats will be updated here


# =============================================================================
# OPTIMIZED HELPER FUNCTIONS
# =============================================================================

@lru_cache(maxsize=10)
def load_logo():
    """Load main page logo image if available"""
    logo_path = "data/logo/logo with tag.png"
    if os.path.exists(logo_path):
        return logo_path
    return None


@lru_cache(maxsize=10)
def load_navigation_logo():
    """Load navigation logo image if available"""
    nav_logo_path = "data/logo/navigation_logo.png"
    if os.path.exists(nav_logo_path):
        return nav_logo_path
    return None


@lru_cache(maxsize=10)
def load_eranet_logo():
    """Load eranet logo image if available"""
    eranet_logo_path = "data/logo/eranet logo.png"
    if os.path.exists(eranet_logo_path):
        return eranet_logo_path
    return None


def _get_image_base64(image_path):
    """Convert image to base64 for embedding"""
    import base64
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()


@st.fragment
def display_header_with_logo():
    """Display header with logo - using fragment to prevent full rerun"""
    logo_path = load_logo()
    if logo_path:
        # Use cached base64 conversion
        logo_b64 = get_image_base64_cached(logo_path)
        st.markdown(f"""
        <div class="main-header">
            <div class="logo-container">
                <img src="data:image/png;base64,{logo_b64}" 
                     width="520" 
                     alt="Digicities Logo" 
                     class="workspace-image"
                     onclick="window.location.reload()" 
                     style="cursor: pointer; transition: opacity 0.2s ease;"
                     onmouseover="this.style.opacity='0.8'"
                     onmouseout="this.style.opacity='1'">
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.title("🏢 Digicities Platform")


def initialize_session_state():
    """Initialize all session state variables with better defaults."""
    # Use a single initialization flag to avoid repeated initialization
    if "initialized" not in st.session_state:
        st.session_state.initialized = True
        st.session_state.authenticated = False
        st.session_state.user_id = None
        st.session_state.current_workspace = None
        st.session_state.workspace_client = None
        st.session_state.nextcloud_client = None
        st.session_state.active_tab = "Digital Replica Explorer"
        st.session_state.module_loading = False
        st.session_state.previous_tab = "Digital Replica Explorer"
        st.session_state.hide_scenario_builder = False
        st.session_state.hide_api_submission = False
        st.session_state.workspace_metadata_cache = {}
        st.session_state.workspace_image_cache = {}
        st.session_state.last_connection_check = 0
        st.session_state.connection_status = None


def _registry_context_for(workspace_id: str):
    """Look up the workspace in the registry. Returns its WorkspaceContext or None."""
    try:
        from backend.workspace import load_registry
        return load_registry().by_id(workspace_id)
    except Exception:
        return None


def load_workspace_metadata(workspace_id: str) -> dict:
    """Load workspace_meta/metadata.json for a workspace.

    Priority:
    1. Registry-aware: read from the workspace's own storage (works for local FS,
       NextCloud-backed, or any other fsspec backend the registry knows about).
    2. Legacy fallback: global/workspace_meta/<id>/metadata.json on NextCloud.
    """
    # Session-state cache short-circuit
    cache_key = f"metadata_{workspace_id}"
    if cache_key in st.session_state.get('workspace_metadata_cache', {}):
        return st.session_state.workspace_metadata_cache[cache_key]

    import json

    metadata: dict = {}

    ctx = _registry_context_for(workspace_id)
    if ctx is not None:
        try:
            if ctx.storage.exists("workspace_meta/metadata.json"):
                metadata = json.loads(ctx.storage.read_text("workspace_meta/metadata.json"))
                if not isinstance(metadata, dict):
                    metadata = {}
        except Exception as e:
            if is_development_mode():
                print(f"DEBUG: registry-side metadata read failed for {workspace_id}: {e}")

    if not metadata:
        try:
            client = get_nextcloud_client("global")
            if client is not None:
                content = client.download_text_file(f"workspace_meta/{workspace_id}/metadata.json")
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                metadata = json.loads(content.strip())
                if not isinstance(metadata, dict):
                    metadata = {}
        except Exception as e:
            if is_development_mode():
                print(f"DEBUG: nextcloud-side metadata read failed for {workspace_id}: {e}")

    if metadata:
        st.session_state.setdefault('workspace_metadata_cache', {})[cache_key] = metadata

    return metadata


def get_workspace_image(workspace_id: str) -> bytes:
    """Load the workspace's thumbnail image.

    Priority:
    1. Registry-aware: workspace_meta/image.{png,jpg,jpeg} from the workspace's own storage.
    2. Legacy fallback: global/workspace_meta/<id>/image.{jpg,jpeg,png} on NextCloud.
    """
    # Session-state cache short-circuit
    cache_key = f"image_{workspace_id}"
    if cache_key in st.session_state.get('workspace_image_cache', {}):
        return st.session_state.workspace_image_cache[cache_key]

    img_data = None

    ctx = _registry_context_for(workspace_id)
    if ctx is not None:
        for fname in ("workspace_meta/image.png", "workspace_meta/image.jpg", "workspace_meta/image.jpeg"):
            try:
                if ctx.storage.exists(fname):
                    img_data = ctx.storage.read_bytes(fname)
                    if img_data:
                        break
            except Exception:
                continue

    if not img_data:
        try:
            client = get_nextcloud_client("global")
            if client is not None:
                for image_name in ("image.jpg", "image.jpeg", "image.png"):
                    try:
                        img_data = client.download_file(f"workspace_meta/{workspace_id}/{image_name}")
                        if img_data:
                            break
                    except Exception:
                        continue
        except Exception:
            pass

    if img_data:
        st.session_state.setdefault('workspace_image_cache', {})[cache_key] = img_data
        return img_data
    return None


def refresh_graphdb_connection():
    """Refresh the GraphDB connection without reloading the entire page"""
    try:
        if not st.session_state.current_workspace:
            st.error("No workspace selected")
            return False

        # First, try to refresh the access token if it's expired
        if not check_token_expiry():
            st.error("❌ Session expired. Attempting to refresh...")
            if not refresh_access_token():
                st.error("❌ Token refresh failed. Please log in again.")
                return False

        access_token = st.session_state.get("access_token")
        if not access_token:
            st.error("No access token available")
            return False

        workspace_id = st.session_state.current_workspace["id"]

        # Clear existing client
        st.session_state.workspace_client = None
        st.session_state.connection_status = None
        st.session_state.last_connection_check = 0

        # Create new client with fresh token
        new_client = GraphDBClient(
            token=access_token,
            selected_repo=workspace_id
        )

        # Test the new connection
        test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
        test_result = new_client.sparql_api_query(test_query, out_format="response")

        if test_result and test_result.status_code == 200:
            st.session_state.workspace_client = new_client
            st.session_state.connection_status = True
            st.session_state.last_connection_check = time.time()
            st.success("✅ Triplestore connection refreshed successfully!")
            return True
        else:
            st.error("❌ Connection test failed after refresh")
            return False

    except Exception as e:
        st.error(f"❌ Failed to refresh Triplestore connection: {str(e)}")
        if is_development_mode():
            import traceback
            st.code(traceback.format_exc())
        return False


def ensure_workspace_client():
    """Return a live GraphDB client for the current workspace, creating one if missing.

    Called from the module gate so a workspace connects automatically instead of
    requiring a manual "Create GraphDB Connection" click. Idempotent: if a client
    already exists it is returned unchanged.
    """
    client = st.session_state.get("workspace_client")
    if client is not None:
        return client

    workspace = st.session_state.get("current_workspace")
    access_token = st.session_state.get("access_token")
    if not workspace or not access_token:
        return None

    ctx = st.session_state.get("workspace_context")
    repo_id = ctx.graphdb_repository if ctx is not None else workspace["id"]
    try:
        client = GraphDBClient(token=access_token, selected_repo=repo_id)
        st.session_state.workspace_client = client
        st.session_state.connection_status = True
        st.session_state.last_connection_check = time.time()
        return client
    except Exception as e:
        print(f"[ensure_workspace_client] failed to create client for {repo_id}: {e}")
        return None


def check_graphdb_connection():
    """Check if GraphDB connection is working with caching"""
    # Check if we have a recent connection check result
    current_time = time.time()
    last_check = st.session_state.get('last_connection_check', 0)

    # If checked within last 30 seconds, return cached result
    if current_time - last_check < 30 and st.session_state.get('connection_status') is not None:
        return st.session_state.connection_status

    client = st.session_state.workspace_client
    if not client:
        st.session_state.connection_status = False
        return False

    try:
        test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
        result = client.sparql_api_query(test_query, out_format="response")
        status = result and result.status_code == 200

        # Cache the result
        st.session_state.connection_status = status
        st.session_state.last_connection_check = current_time

        return status
    except:
        st.session_state.connection_status = False
        return False


@st.fragment
def display_bottom_status_bar():
    """Display bottom status bar with GraphDB connection status - using fragment"""
    client = st.session_state.workspace_client

    if not client:
        status_class = "unknown"
        status_text = "Triplestore connection not initialized"
    else:
        # Use async connection check
        is_connected = async_check_graphdb_connection()
        if is_connected:
            status_class = "active"
            status_text = "Triplestore connection active"
        else:
            status_class = "inactive"
            status_text = "Triplestore connection failed"

    # Display status bar
    st.markdown(f"""
    <div class="status-bar">
        <div class="status-indicator">
            <span class="status-light {status_class}"></span>
            <span>{status_text}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def return_to_workspace_selector():
    """Return to workspace selector (home) - optimized to clear only necessary state"""
    # Only clear workspace-specific state
    st.session_state.current_workspace = None
    st.session_state.workspace_client = None
    st.session_state.module_loading = False
    # Clear caches
    st.session_state.workspace_metadata_cache = {}
    st.session_state.workspace_image_cache = {}
    st.session_state.connection_status = None
    st.session_state.last_connection_check = 0
    st.rerun()


# =============================================================================
# OPTIMIZED UI COMPONENTS
# =============================================================================

def render_login_section():
    """Render the login section after authentication."""
    access_token = st.session_state.get("access_token")
    nextcloud_token = st.session_state.get("nextcloud_token")
    payload = st.session_state.get("access_payload", {})
    username = payload.get("preferred_username", "Unknown User")
    groups = payload.get("groups", [])

    st.session_state.user_id = username

    return access_token, nextcloud_token, username, groups


def _refresh_workspace_list() -> int:
    """Re-scan workspaces (including NextCloud) and refresh the landing-page list.

    Returns the number of NextCloud-backed workspaces discovered. Called when the
    NextCloud connection changes so workspaces stored on the server import (or
    drop) immediately, without a restart.
    """
    try:
        from backend.workspace import load_registry
        from backend.workspace.registry import (
            clear_nextcloud_discovery_cache,
            _autodiscover_nextcloud_workspaces,
        )
        clear_nextcloud_discovery_cache()
        nc_count = len(_autodiscover_nextcloud_workspaces())  # populates the cache
        ids = [c.id for c in load_registry()]                 # reuses the cache
        payload = st.session_state.get("access_payload", {})
        payload["groups"] = ids
        st.session_state["access_payload"] = payload
        st.session_state.workspace_metadata_cache = {}
        st.session_state.workspace_image_cache = {}
        return nc_count
    except Exception as exc:
        print(f"[_refresh_workspace_list] {exc}")
        return 0


def render_nextcloud_connector():
    """Always-available sidebar panel to connect to NextCloud from the GUI.

    Writes credentials into the process env at runtime so every existing
    NextCloud code path works without editing .env or restarting. Session-only
    by default; an opt-in checkbox remembers them on this machine.
    """
    from backend.workspace import connections as nc

    with st.sidebar.expander("🔌 NextCloud connection", expanded=False):
        cur = nc.current_nextcloud_connection()
        if nc.nextcloud_is_configured():
            st.success(f"Connected as **{cur['username']}**")
            st.caption(cur["base_url"])
            try:
                from backend.workspace.registry import _autodiscover_nextcloud_workspaces
                n_ws = len(_autodiscover_nextcloud_workspaces())
                st.caption(f"☁️ {n_ws} workspace(s) on this NextCloud")
            except Exception:
                pass
            if st.button("Disconnect", key="nc_disconnect", use_container_width=True):
                nc.clear_nextcloud_connection(remove_saved=True)
                _refresh_workspace_list()
                st.toast("NextCloud disconnected")
                st.rerun()
        else:
            st.caption("Not connected. Local-filesystem workspaces work without this; "
                       "connect to enable NextCloud storage and data products.")

        # Pre-fill with the local NextCloud overlay defaults when nothing is set,
        # so the local stack connects with one click.
        prefill = nc.default_nextcloud_connection()
        with st.form("nc_connect_form", clear_on_submit=False):
            base = st.text_input("NextCloud URL", value=prefill["base_url"],
                                 placeholder="https://nextcloud.example.com",
                                 help="Server-side address. For the local overlay use http://nextcloud:80 "
                                      "(browse it from your host at http://localhost:8080).")
            user = st.text_input("Username", value=prefill["username"])
            pw = st.text_input("Password / app password", value=prefill["password"], type="password",
                               help="A NextCloud app password is recommended over your login password. "
                                    "Local overlay default: admin / admin.")
            remember = st.checkbox(
                "Remember on this machine", value=nc.saved_connection_exists(),
                help="Saves the credentials (plaintext) to a gitignored local file so the "
                     "connection is restored next time. Leave off to keep them for this session only.",
            )
            submitted = st.form_submit_button("Connect & test", type="primary", use_container_width=True)

        if submitted:
            ok, msg = nc.test_nextcloud_connection(base, user, pw)
            if ok:
                nc.apply_nextcloud_connection(base, user, pw)
                if remember:
                    nc.save_nextcloud_connection(base, user, pw)
                else:
                    nc.delete_saved()
                imported = _refresh_workspace_list()
                if imported:
                    st.toast(f"Imported {imported} workspace(s) from NextCloud", icon="☁️")
                else:
                    st.toast("Connected to NextCloud (no workspaces found yet)", icon="☁️")
                st.rerun()
            else:
                st.error(msg)


def render_create_workspace_form():
    """Landing-page form to create + initialise a brand-new workspace.

    Creates the canonical folder layout, registers the workspace, provisions its
    knowledge graph, then opens it so the user can work immediately.
    """
    import os

    with st.expander("➕ Create a new workspace", expanded=False):
        st.caption(
            "Initialise a fresh workspace with the standard folder layout, register it, and "
            "provision its knowledge graph so you can start working straight away."
        )
        with st.form("create_workspace_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            with c1:
                ws_name = st.text_input("Workspace name *", placeholder="My Test Workspace")
            with c2:
                ws_id = st.text_input(
                    "Workspace ID", placeholder="auto from name",
                    help="Folder + graph dataset name. Lowercase, no spaces. Leave blank to auto-generate.",
                )

            nc_configured = bool(
                os.environ.get("NEXTCLOUD_BASIC_USERNAME")
                and (os.environ.get("NEXTCLOUD_BASE_URL") or os.environ.get("NEXTCLOUD_BASIC_PASSWORD"))
            )
            backend_choices = ["Local filesystem"] + (["NextCloud"] if nc_configured else [])
            ws_backend = st.radio(
                "Where to store the workspace files? *",
                backend_choices, horizontal=True,
                help=(
                    "The knowledge graph is always created in the triplestore. This only chooses "
                    "where the workspace's files live."
                    + ("" if nc_configured else " NextCloud is disabled — set NEXTCLOUD_* env vars to enable it.")
                ),
            )

            c3, c4 = st.columns(2)
            with c3:
                ws_type = st.text_input("Type", placeholder="e.g. Forecasting")
            with c4:
                ws_location = st.text_input("Location", placeholder="e.g. Zurich, CH")
            ws_desc = st.text_area("Description", placeholder="What is this workspace for?")

            submitted = st.form_submit_button(
                "🚀 Create & open workspace", type="primary", use_container_width=True
            )

        if not submitted:
            return
        if not ws_name.strip():
            st.error("Workspace name is required.")
            return

        try:
            from backend.workspace import create_workspace
            backend_key = "nextcloud" if ws_backend == "NextCloud" else "local"
            with st.spinner("Creating workspace and provisioning its graph…"):
                ctx = create_workspace(
                    name=ws_name.strip(),
                    workspace_id=ws_id.strip() or None,
                    backend=backend_key,
                    description=ws_desc.strip(),
                    workspace_type=ws_type.strip(),
                    location=ws_location.strip(),
                )
        except Exception as e:
            st.error(f"Could not create workspace: {e}")
            return

        # Make the new workspace visible on the landing list. In AUTH_DISABLED mode
        # the "groups" are built from the registry at login, so add it to the
        # session payload here, and clear the metadata/image caches.
        payload = st.session_state.get("access_payload", {})
        grps = payload.get("groups", [])
        if ctx.id not in grps:
            grps.append(ctx.id)
            payload["groups"] = grps
            st.session_state["access_payload"] = payload
        st.session_state.workspace_metadata_cache = {}
        st.session_state.workspace_image_cache = {}

        open_workspace({
            "id": ctx.id,
            "name": ctx.name,
            "description": ctx.description,
            "type": ws_type.strip() or "Custom",
            "location": ws_location.strip() or ("NextCloud" if backend_key == "nextcloud" else "Local"),
        })


@measure_performance
@st.cache_data(ttl=120)
def _ws_last_updated_cached(ws_id: str):
    """Epoch seconds of the newest file in a (local) workspace, or None."""
    try:
        from backend.workspace import load_registry, workspace_last_updated
        ctx = load_registry().by_id(ws_id)
        if ctx is not None and getattr(ctx.storage, "protocol", "file") == "file":
            return workspace_last_updated(ctx.storage.root)
    except Exception:
        pass
    return None


def _ago(ts) -> str:
    """Compact 'how long ago' label for a workspace card."""
    if not ts:
        return ""
    from datetime import datetime
    delta = datetime.now() - datetime.fromtimestamp(ts)
    s = int(delta.total_seconds())
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{max(1, s // 60)} min ago"
    if s < 129600:                       # < 36 h
        return f"{max(1, s // 3600)} h ago"
    if s < 86400 * 30:
        return f"{s // 86400} d ago"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def render_groups_as_workspaces(groups):
    """Render available workspaces with clean card design - optimized."""
    st.subheader("🏢 Your Workspaces")

    # Entry point to create + initialise a brand-new workspace.
    render_create_workspace_form()

    # In Keycloak-auth mode, workspace group IDs are prefixed with "workspace_".
    # In AUTH_DISABLED mode, the registry populates groups directly with workspace IDs
    # (no prefix). Accept both — if anything in `groups` looks like a workspace ID
    # (it's known to the registry, or it has the legacy prefix), treat it as one.
    registry_ids: set[str] = set()
    ws_backend: dict[str, str] = {}
    demo_ids: set[str] = set()
    try:
        from backend.workspace import load_registry
        for ctx in load_registry():
            registry_ids.add(ctx.id)
            ws_backend[ctx.id] = ctx.storage_backend  # "file", "webdav", "s3", ...
            if "demo" in (getattr(ctx, "tags", None) or []):
                demo_ids.add(ctx.id)
    except Exception:
        pass

    workspace_groups = [
        g for g in groups
        if g.startswith("workspace_") or g in registry_ids
    ]

    # The bundled demo workspace is shown first, with an option to hide it.
    if demo_ids & set(workspace_groups):
        show_demo = st.checkbox(
            "Show the bundled demo workspace", value=True, key="ws_show_demo",
            help="The Energy Simulation example ships with the platform. Untick to hide it.",
        )
        if not show_demo:
            workspace_groups = [g for g in workspace_groups if g not in demo_ids]

    if not workspace_groups:
        st.info("You are not a member of any workspaces. Please contact the Administrator to get access")
        return

    def _source_of(ws_id: str) -> str:
        b = ws_backend.get(ws_id)
        if b == "webdav":
            return "NextCloud"
        if b and b != "file":
            return b.upper() if len(b) <= 3 else b.title()  # s3, gcs, ...
        return "Local"

    # --- Source filter + name search ---
    n_local = sum(1 for g in workspace_groups if _source_of(g) == "Local")
    n_nc = sum(1 for g in workspace_groups if _source_of(g) == "NextCloud")
    other_sources = sorted({_source_of(g) for g in workspace_groups} - {"Local", "NextCloud"})

    options = ["All"]
    if n_local:
        options.append("Local")
    if n_nc:
        options.append("NextCloud")
    options += other_sources
    labels = {
        "All": f"All ({len(workspace_groups)})",
        "Local": f"💻 Local ({n_local})",
        "NextCloud": f"☁️ NextCloud ({n_nc})",
    }

    fcol1, fcol2 = st.columns([3, 2])
    with fcol1:
        selected_source = st.radio(
            "Source", options, horizontal=True, key="ws_source_filter",
            label_visibility="collapsed", format_func=lambda o: labels.get(o, o),
        ) if len(options) > 1 else "All"
    with fcol2:
        search = st.text_input(
            "Search", key="ws_search_filter", label_visibility="collapsed",
            placeholder="🔍 Filter by name…",
        )

    filtered_groups = [
        g for g in workspace_groups
        if selected_source == "All" or _source_of(g) == selected_source
    ]

    # Demo workspace(s) first; everything else newest-first, so the workspace
    # you worked on last is always at the top.
    non_demo = [g for g in filtered_groups if g not in demo_ids]
    non_demo.sort(key=lambda g: _ws_last_updated_cached(g) or 0, reverse=True)
    filtered_groups = [g for g in filtered_groups if g in demo_ids] + non_demo

    # Bulk delete: a checkbox per (non-demo) card + a toolbar under the list.
    from components.workspace_admin import (
        apply_pending_bulk_selection, bulk_select_key, render_bulk_delete_toolbar)
    bulk_mode = st.toggle(
        "🗑️ Bulk delete mode", key="ws_bulk_delete_mode",
        help="Tick workspaces to delete several at once (or Select all). "
             "Bundled demo workspaces are protected.")
    if bulk_mode:
        apply_pending_bulk_selection([g for g in filtered_groups if g not in demo_ids])
    bulk_candidates = []

    # Pre-load metadata and images in parallel (filtered set only)
    if filtered_groups:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            metadata_futures = {ws_id: executor.submit(load_workspace_metadata_cached, ws_id)
                                for ws_id in filtered_groups}
            image_futures = {ws_id: executor.submit(get_workspace_image_cached, ws_id)
                             for ws_id in filtered_groups}
    else:
        metadata_futures, image_futures = {}, {}

    rendered = 0
    for group in filtered_groups:
        workspace_id = group

        # Get results from futures
        metadata = metadata_futures[workspace_id].result()
        img_data = image_futures[workspace_id].result()

        # Name/description search filter
        if search:
            haystack = f"{metadata.get('name', '')} {group} {metadata.get('description', '')}".lower()
            if search.lower() not in haystack:
                continue
        rendered += 1
        ws_source = _source_of(group)
        source_badge = "☁️ NextCloud" if ws_source == "NextCloud" else (
            "💻 Local" if ws_source == "Local" else f"🗄️ {ws_source}")
        if workspace_id in demo_ids:
            source_badge = "🎓 Demo · " + source_badge
        updated = _ago(_ws_last_updated_cached(workspace_id))
        if updated:
            source_badge += f" | 🕒 {updated}"

        workspace = {
            'id': workspace_id,
            'name': metadata.get('name', group.replace("workspace_", "").replace("_", " ").title()),
            'description': metadata.get('description', f"Group ID: {group}"),
            'type': metadata.get('type', "Group-Based Access"),
            'location': metadata.get('location', "Unknown Location"),
            'created_date': metadata.get('created_date', "N/A"),
            'last_access': metadata.get('last_access', "N/A")
        }

        # Create workspace card with cached image
        if img_data:
            import base64
            img_b64 = base64.b64encode(img_data).decode()
            mime_type = "image/jpeg"
            if workspace_id.endswith('.png') or any(fmt in workspace_id.lower() for fmt in ['png']):
                mime_type = "image/png"

            st.markdown(f"""
            <div class="workspace-card workspace-image" style="background-image: url('data:{mime_type};base64,{img_b64}');">
                <div class="workspace-card-content">
                    <h3>🏢 {workspace['name']}</h3>
                    <p>{workspace['description']}</p>
                    <p>📍 {workspace['location']} | 🏷️ {workspace['type']} | {source_badge}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="workspace-card">
                <div class="workspace-card-content">
                    <h3>🏢 {workspace['name']}</h3>
                    <p>{workspace['description']}</p>
                    <p>📍 {workspace['location']} | 🏷️ {workspace['type']} | {source_badge}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Action buttons - simplified
        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])

        with col1:
            if st.button(f"📂 Open", key=f"open_{workspace['id']}", use_container_width=True):
                open_workspace(workspace)

        with col2:
            # Use a simpler info display to reduce complexity
            with st.popover(f"ℹ️ Info", use_container_width=True):
                render_workspace_info(workspace, metadata)

        with col3:
            from components.workspace_admin import render_manage_button
            render_manage_button(workspace_id)

        if bulk_mode:
            with col4:
                if workspace_id in demo_ids:
                    st.caption("🎓 protected")
                else:
                    st.checkbox("🗑️ select for deletion",
                                key=bulk_select_key(workspace_id))
                    bulk_candidates.append(workspace_id)

        # Clear-contents / delete live in a panel under the card rather than in a
        # popover: they carry a type-to-confirm field, and a popover collapses on
        # the rerun its own widgets trigger.
        from components.workspace_admin import manage_toggle_key, render_danger_zone
        if st.session_state.get(manage_toggle_key(workspace_id), False):
            render_danger_zone(workspace, is_demo=workspace_id in demo_ids)

    if rendered == 0:
        st.caption("No workspaces match this filter.")

    if bulk_mode:
        st.divider()
        render_bulk_delete_toolbar(bulk_candidates)


def _reset_workspace_scoped_state():
    """Drop session state that belongs to one workspace, so it doesn't leak when
    the user switches workspace: converted scenarios, registered services, scenario
    picks, and submission history all pertain to the workspace they were made in."""
    keys = ['conversion_results', 'selected_scenarios', 'uploaded_scenarios',
            'service_submission_results', 'submission_history', 'validation_results',
            'registered_apis', 'suppressed_services', 'temp_files']
    for k in keys:
        st.session_state.pop(k, None)
    # Shared scenario-loader widget selections (keyed by per-caller prefix).
    for k in [k for k in list(st.session_state.keys())
              if k.endswith(('_ws_sel', '_kg_sel', '_source', '_upload'))]:
        st.session_state.pop(k, None)


def open_workspace(workspace, rerun=True):
    """Open a workspace - extracted for reusability.

    ``rerun`` controls the trailing st.rerun(): pass False when calling from a
    widget on_change callback (Streamlit reruns after a callback automatically, so
    an explicit rerun there is a no-op and logs a warning)."""
    access_token = st.session_state.get("access_token")

    # On an actual workspace change, reset per-workspace module state so converted
    # scenarios / registered services / scenario picks don't carry over.
    _prev = st.session_state.get("current_workspace")
    _prev_id = _prev.get("id") if isinstance(_prev, dict) else None
    if _prev_id is not None and _prev_id != workspace.get("id"):
        _reset_workspace_scoped_state()

    # NEW: Clear ontology manager state when switching workspaces
    ontology_keys = [
        'ontology_extensions', 'ontology_selected_extension', 'ontology_extension_loaded',
        'ontology_components', 'ontology_attributes', 'ontology_properties',
        'ontology_selected_component', 'ontology_component_range', 'ontology_is_core_mode',
        'ontology_mapping_inputs', 'ontology_selected_mapping', 'ontology_view_mode',
        'ontology_active_form', 'ontology_api_client', 'ontology_client_mode',
        'qudt_units', 'temporal_precisions', 'attribute_categories', 'categorical_attributes',
        'add_attr_type', 'confirm_remove_component', 'confirm_remove_attribute',
        'confirm_unlink', 'confirm_upload_graphdb'
    ]

    for key in ontology_keys:
        if key in st.session_state:
            del st.session_state[key]

    st.session_state.current_workspace = workspace

    # Resolve the workspace's WorkspaceContext + lazily provision its GraphDB
    # repository (create it + load core ontology + extensions + scenarios into
    # named graphs) on first open. Idempotent — re-uploading the workspace's
    # current TTLs on every open keeps GraphDB in sync with file edits.
    graphdb_repo = workspace["id"]
    try:
        from backend.workspace import load_registry, ensure_workspace_repo
        ctx = load_registry().by_id(workspace["id"])
        if ctx is not None:
            graphdb_repo = ctx.graphdb_repository
            st.session_state.workspace_context = ctx
            try:
                ensure_workspace_repo(ctx)
            except Exception as prov_exc:
                # Provisioning failure is non-fatal — UI works without GraphDB,
                # and the user can manually create the repo via Workbench.
                print(f"[open_workspace] GraphDB provisioning skipped: {prov_exc}")
                st.warning(
                    f"Triplestore repo `{graphdb_repo}` could not be provisioned automatically. "
                    "File-based modules still work; SPARQL queries will fail until the repo exists."
                )
    except Exception as exc:
        print(f"[open_workspace] registry lookup failed for {workspace['id']}: {exc}")

    # Try to create client
    try:
        st.session_state.workspace_client = GraphDBClient(
            token=access_token,
            selected_repo=graphdb_repo
        )
        st.session_state.connection_status = True
        st.session_state.last_connection_check = time.time()
    except Exception as e:
        st.error(f"Could not create Triplestore client: {e}")
        st.session_state.workspace_client = None
        st.session_state.connection_status = False

    st.success(f"Opening {workspace['name']}...")
    # Only rerun for direct (main-flow) callers. When invoked from a widget
    # on_change callback, Streamlit already reruns afterwards, so calling
    # st.rerun() here is a no-op (and warns).
    if rerun:
        st.rerun()


def render_workspace_info(workspace, metadata):
    """Render workspace info - simplified"""
    st.markdown(f"### 📊 {workspace['name']} Details")

    # Basic info
    st.markdown("**Basic Information:**")
    for key in ['name', 'type', 'location', 'description']:
        if key in workspace and workspace[key] and workspace[key] != "N/A":
            st.markdown(f"- **{key.title()}:** {workspace[key]}")

    # Additional metadata if available
    if metadata:
        with st.expander("Additional Details"):
            for k, v in metadata.items():
                if k not in ['name', 'type', 'location', 'description'] and v:
                    st.markdown(f"- **{k.replace('_', ' ').title()}:** {v}")


@measure_performance
def main_application():
    """Main application interface after workspace selection - optimized."""
    # Check token expiry and refresh if needed (automatic session maintenance)
    if not check_token_expiry():
        st.error("🔒 Your session has expired. Please log in again.")
        if st.button("🔐 Re-login"):
            logout()
        st.stop()

    workspace = st.session_state.current_workspace

    # Enhanced greeting with tighter spacing
    username = st.session_state.user_id
    workspace_name = workspace['name']

    # Use a container to control spacing better
    with st.container():
        st.success(f"👋 Hello, {username}! You're currently in the {workspace_name} workspace")

    # Sidebar navigation
    render_sidebar_navigation()

    # Main content area with module container - remove extra spacing
    render_active_module()

    # Display bottom status bar as fragment
    display_bottom_status_bar()


def render_sidebar_navigation():
    """Render sidebar navigation - extracted for clarity"""
    with st.sidebar:
        # Navigation logo
        nav_logo_path = load_navigation_logo()
        if nav_logo_path:
            logo_b64 = get_image_base64_cached(nav_logo_path)
            st.markdown(f"""
            <img src="data:image/png;base64,{logo_b64}" 
                 class="nav-logo workspace-image" 
                 alt="Navigation Logo">
            """, unsafe_allow_html=True)

        # Home button
        if st.button("🏠 Home", help="Return to workspace selector", key="nav_home", use_container_width=True):
            return_to_workspace_selector()

        st.title("Navigation")

        # Workspace switcher - optimized
        render_workspace_switcher()

        st.markdown("---")

        # Module selection - optimized
        render_module_selector()

        st.markdown("---")

        # Refresh section
        if st.button("🔄 Refresh Data"):
            clear_module_caches()
            st.rerun()

        # Token refresh section
        with st.expander("🔐 Session Management"):
            import time
            if st.session_state.get("token_timestamp"):
                token_age = time.time() - st.session_state["token_timestamp"]
                token_expires_in = st.session_state.get("token_expires_in", 28800)
                hours_remaining = (token_expires_in - token_age) / 3600

                if hours_remaining > 1:
                    st.success(f"✅ Session valid (~{hours_remaining:.1f}h remaining)")
                elif hours_remaining > 0:
                    st.warning(f"⚠️ Session expires soon (~{hours_remaining*60:.0f}m)")
                else:
                    st.error("❌ Session expired")

                if st.button("🔄 Refresh Session Now", use_container_width=True):
                    if refresh_access_token():
                        st.success("✅ Session refreshed!")
                        st.rerun()
                    else:
                        st.error("❌ Refresh failed. Please log in again.")
            else:
                st.info("Session info not available")

        # Workspace info
        render_workspace_info_sidebar()

        # System status — read-only overview of storage, GraphDB, services
        try:
            from components.system_status import render_system_status_sidebar
            render_system_status_sidebar(st.session_state.get("workspace_client"))
        except Exception as e:
            st.sidebar.warning(f"System Status unavailable: {e}")

        # Development debug
        if is_development_mode():
            render_development_debug()

        # About section
        render_about_section()

        # Eranet logo
        render_eranet_logo()


def render_workspace_switcher():
    """Render workspace switcher - optimized to prevent unnecessary reruns.

    Accepts both Keycloak-style 'workspace_*' prefixed group IDs and registry-
    listed workspace IDs (no prefix). Matches render_groups_as_workspaces so
    switching between local-FS and NextCloud workspaces works in the sidebar.
    """
    groups = st.session_state.get("access_payload", {}).get("groups", [])

    registry_ids: set[str] = set()
    try:
        from backend.workspace import load_registry
        registry_ids = {ctx.id for ctx in load_registry()}
    except Exception:
        pass

    workspace_ids = [
        g for g in groups
        if g.startswith("workspace_") or g in registry_ids
    ]

    if workspace_ids:
        current_id = st.session_state.current_workspace["id"]
        # If for some reason the current workspace isn't in the selectable list
        # (e.g. registry changed mid-session), include it so .index() succeeds.
        if current_id not in workspace_ids:
            workspace_ids = [current_id] + workspace_ids

        # Pre-load display names
        ws_display_names = {}
        for ws_id in workspace_ids:
            metadata = load_workspace_metadata_cached(ws_id)
            ws_display_names[ws_id] = metadata.get('name', ws_id.replace("workspace_", "").replace("_", " ").title())

        # Use on_change callback instead of checking after render
        def on_workspace_change():
            selected_ws_id = st.session_state.workspace_selector
            if selected_ws_id != current_id:
                metadata = load_workspace_metadata_cached(selected_ws_id)
                new_workspace = {
                    'id': selected_ws_id,
                    'name': metadata.get('name', ws_display_names[selected_ws_id]),
                    'description': metadata.get('description', f"Group ID: {selected_ws_id}"),
                    'type': metadata.get('type', "Group-Based Access"),
                    'location': metadata.get('location', "Unknown Location"),
                    'created_date': metadata.get('created_date', "N/A"),
                    'last_access': metadata.get('last_access', "N/A")
                }
                # In a callback: don't st.rerun() (Streamlit reruns after this).
                open_workspace(new_workspace, rerun=False)

        st.selectbox(
            "🔄 Switch Workspace",
            options=workspace_ids,
            format_func=lambda x: ws_display_names[x],
            index=workspace_ids.index(current_id),
            key="workspace_selector",
            on_change=on_workspace_change
        )


def render_module_selector():
    """Render module selector"""
    base_tab_options = [
        "Digital Replica Explorer",
        "Ontology Manager",
        "Replica Builder",
        "Query Manager",
        "Collections",
        "Data Viewer and Uploader",
        "Data Products"
    ]

    # Add Service Requirements Builder (doesn't need GraphDB or Nextcloud, so always available)
    base_tab_options.append("Service Requirements Builder")

    # Check module availability lazily
    if not st.session_state.get('hide_scenario_builder', False):
        try:
            # Quick import check without full import
            import importlib.util
            spec = importlib.util.find_spec("components.scenario_builder.scenario_builder")
            if spec is not None:
                base_tab_options.append("Scenario Builder")
        except:
            pass

    # Add Assumptions Module (NEW - always available)
    base_tab_options.append("Assumptions Module")

    if not st.session_state.get('hide_api_submission', False):
        try:
            import importlib.util
            spec = importlib.util.find_spec("components.api_submission_module")
            if spec is not None:
                base_tab_options.append("API Data Submission")
        except:
            pass

    # A module can hand off to another one (Explorer -> "Inspect instance" ->
    # Query Manager). Widget state can only be set BEFORE the widget exists in a
    # run, so the request is parked in pending_module_switch and applied here,
    # ahead of the checkbox and the radio it must steer.
    pending_switch = st.session_state.pop("pending_module_switch", None)
    if pending_switch:
        if pending_switch in ARCHIVED_MODULES:
            st.session_state.show_archived_modules = True
        st.session_state.previous_tab = st.session_state.get("active_tab")
        st.session_state.active_tab = pending_switch
        st.session_state.module_selector_radio = pending_switch

    # Archived modules are hidden by default; a toggle reveals them.
    show_archived = st.checkbox(
        "Show archived modules", value=False, key="show_archived_modules",
        help="Modules not yet part of the guided workflow (Data Viewer and Uploader, "
             "Data Products, Assumptions). Hidden by default.")
    if not show_archived:
        base_tab_options = [t for t in base_tab_options if t not in ARCHIVED_MODULES]

    # External modules (mounted at MODULES_DIR with a module.yaml manifest) get a
    # nav entry after the built-ins. See external_modules.py / docs/EXTERNAL_MODULES.md.
    try:
        from external_modules import discover_external_modules
        base_tab_options.extend(
            m["label"] for m in discover_external_modules() if m["label"] not in base_tab_options
        )
    except Exception as e:
        print(f"[external_modules] discovery failed: {e}")

    tab_options = base_tab_options

    # Ensure valid active tab
    if st.session_state.active_tab not in tab_options:
        st.session_state.active_tab = "Digital Replica Explorer"

    # Use on_change callback for better performance
    def on_module_change():
        new_module = st.session_state.module_selector_radio
        if new_module != st.session_state.active_tab:
            st.session_state.previous_tab = st.session_state.active_tab
            st.session_state.active_tab = new_module
            st.session_state.module_loading = True

    st.radio(
        "Select Module",
        tab_options,
        index=tab_options.index(st.session_state.active_tab),
        key="module_selector_radio",
        format_func=lambda m: f"{m}  📦" if m in ARCHIVED_MODULES else m,
        on_change=on_module_change
    )


def render_active_module():
    """Render the active module - WITH ASSUMPTIONS INTEGRATED"""
    client = st.session_state.workspace_client
    # Auto-connect: if a workspace is open but no client survived to this render,
    # create one now so GraphDB-backed modules work without a manual click.
    if client is None and st.session_state.get("current_workspace"):
        client = ensure_workspace_client()
    active_tab = st.session_state.active_tab

    # Clear loading state
    if st.session_state.get("module_loading", False):
        st.session_state.module_loading = False

    # Flag archived modules (shown only via the "Show archived modules" toggle).
    if active_tab in ARCHIVED_MODULES:
        st.warning(
            "📦 **Archived / under development.** This module isn't part of the guided "
            "workflow yet and may be incomplete. The supported end-to-end pipelines are "
            "**Replica Builder → Scenario Builder → API Data Submission** "
            "(energy simulation and the flexibility optimiser).")

    # Replica Builder module
    if active_tab == "Replica Builder":
        try:
            from components.replica_builder_main import replica_builder
            replica_builder(client)
        except Exception as e:
            handle_module_error("Replica Builder", e)

    # Module rendering with lazy imports
    elif active_tab == "Ontology Manager":
        try:
            ontology_manager = lazy_import_module("ontology_manager_module", "components.ontology_manager")
            ontology_manager(client)
        except Exception as e:
            handle_module_error("Ontology Manager", e, needs_graphdb=False)
            st.info("💡 Ontology Manager works independently and doesn't require a Triplestore")


    # Module rendering with lazy imports
    elif active_tab == "Digital Replica Explorer":
        if client:
            try:
                component_explorer = lazy_import_module("component_explorer", "components.component_explorer")
                component_explorer(client)
            except Exception as e:
                handle_module_error("Digital Replica Explorer", e, needs_graphdb=True)
        else:
            show_graphdb_required("Digital Replica Explorer")

    elif active_tab == "Query Manager":
        if client:
            try:
                query_manager = lazy_import_module("query_manager", "components.query_manager")
                query_manager(client)
            except Exception as e:
                handle_module_error("Query Manager", e, needs_graphdb=True)
        else:
            show_graphdb_required("Query Manager")

    elif active_tab == "Collections":
        if client:
            try:
                collections_explorer = lazy_import_module("collections_explorer", "components.collections_explorer")
                collections_explorer(client)
            except Exception as e:
                handle_module_error("Collections", e, needs_graphdb=True)
        else:
            show_graphdb_required("Collections")

    elif active_tab == "Data Viewer and Uploader":
        # Storage-agnostic: uses the active workspace's WorkspaceStorage
        # (local filesystem, NextCloud/WebDAV, or any fsspec backend), so it
        # works in local mode without a NextCloud server. The old NextCloud-only
        # module (nextcloud_module) is kept for reference but no longer gates
        # this tab.
        try:
            from components.data_viewer import data_viewer_and_uploader
            data_viewer_and_uploader(st.session_state.current_workspace)
        except Exception as e:
            handle_module_error("Data Viewer and Uploader", e)

    elif active_tab == "Service Requirements Builder":
        # Service Requirements Builder - doesn't need GraphDB or Nextcloud
        try:
            service_requirements_builder = lazy_import_module("service_requirements_builder", "components.service_requirements_builder")
            service_requirements_builder(client)
        except Exception as e:
            handle_module_error("Service Requirements Builder", e)

    elif active_tab == "Scenario Builder":
        if client:
            try:
                scenario_builder = lazy_import_module("scenario_builder", "components.scenario_builder.scenario_builder")
                scenario_builder(client)
            except Exception as e:
                handle_module_error("Scenario Builder", e, needs_graphdb=True)
        else:
            show_graphdb_required("Scenario Builder")

    # NEW: Assumptions Module
    elif active_tab == "Assumptions Module":  # <-- ADD THE SUFFIX!
        try:
            from components.assumptions import assumptions_module
            assumptions_module(client)
        except Exception as e:
            handle_module_error("Assumptions Module", e, needs_graphdb=False)
            st.info("💡 Assumptions Module works with workspace TTL files and doesn't require a Triplestore")

    elif active_tab == "API Data Submission":
        try:
            api_submission_module = lazy_import_module("api_submission_module", "components.api_submission_module")
            api_submission_module(client)
        except Exception as e:
            handle_module_error("API Data Submission", e)

    elif active_tab == "Data Products":
        try:
            data_products_module = lazy_import_module("data_products", "components.data_products")
            data_products_module(st.session_state.current_workspace)
        except Exception as e:
            handle_module_error("Data Products", e)

    else:
        # Not a built-in — try the external modules mounted at MODULES_DIR.
        try:
            from external_modules import find_external_module, render_external_module
            manifest = find_external_module(active_tab)
        except Exception as e:
            manifest = None
            print(f"[external_modules] lookup failed: {e}")
        if manifest:
            try:
                render_external_module(manifest, client)
            except Exception as e:
                handle_module_error(manifest["label"], e)
        else:
            st.error(f"Unknown module: {active_tab}")


def handle_module_error(module_name: str, error: Exception, needs_graphdb: bool = False):
    """Centralized error handling for modules"""
    st.error(f"{module_name} error: {error}")

    if needs_graphdb:
        if st.button(f"🔄 Try Refreshing Triplestore Connection", key=f"{module_name.lower().replace(' ', '_')}_refresh"):
            refresh_graphdb_connection()
            st.rerun()

    if is_development_mode():
        import traceback
        with st.expander("🐛 Debug Information"):
            st.code(traceback.format_exc())
    else:
        st.info(f"{module_name} is temporarily unavailable")


def show_graphdb_required(module_name: str):
    """Show GraphDB required message"""
    st.error("Triplestore client not available")
    if st.button(f"🔄 Create Triplestore Connection", key=f"{module_name.lower().replace(' ', '_')}_create"):
        refresh_graphdb_connection()
        st.rerun()


def clear_module_caches():
    """Clear module-specific caches"""
    cache_keys = ['scenario_components', 'scenario_name', 'file_list', 'nextcloud_client',
                  'registered_apis', 'validation_results', 'submission_history',
                  'selected_scenarios', 'conversion_results', 'uploaded_scenarios', 'temp_files',
                  'workspace_metadata_cache', 'workspace_image_cache', 'connection_status',
                  'last_connection_check', 'service_name', 'service_description', 'component_entries',
                  'ontology_uploaded', 'assumptions_baseline_scenario', 'assumptions_baseline_components',
                  'assumptions_generated_scenarios','ontology_extensions', 'ontology_selected_extension', 'ontology_extension_loaded',
'ontology_components', 'ontology_attributes', 'ontology_properties',
'ontology_api_client', 'qudt_units', 'temporal_precisions',
'attribute_categories', 'categorical_attributes']  # Added Assumptions cache keys

    for key in cache_keys:
        if key in st.session_state:
            del st.session_state[key]

    st.session_state.module_loading = False


def render_workspace_info_sidebar():
    """Render workspace info in sidebar"""
    workspace = st.session_state.current_workspace
    with st.expander("📊 Workspace Info"):
        st.markdown(f"""
        **Current Workspace:** {workspace['name']}
        **Type:** {workspace['type']}
        **Location:** {workspace['location']}
        **User:** {st.session_state.user_id}
        """)

        # For local (filesystem) workspaces, show the on-disk path so users can
        # open the folder in their OS file explorer. NextCloud/other backends
        # have no local path, so this is hidden for them.
        try:
            from components.workspace_selector import get_workspace_local_path
            local_path = get_workspace_local_path(workspace['id'])
            if local_path:
                st.markdown("**📂 Filesystem path:**")
                st.code(local_path, language=None)
        except Exception:
            pass

        # Show status indicators
        if validate_nextcloud_config():
            st.markdown("**Nextcloud:** ✅ Configured")
        else:
            st.markdown("**Nextcloud:** ❌ Not configured")

        client = st.session_state.workspace_client
        if client:
            st.markdown("**Triplestore:** ✅ Client available")
            st.write(f"**Repository:** {getattr(client, 'selected_repo', 'Unknown')}")
        else:
            st.markdown("**Triplestore:** ❌ Client not available")


def render_development_debug():
    """Render development debug info"""
    with st.expander("🔧 Development Debug"):
        st.markdown("**Development Mode Active**")
        st.write(f"**Active Tab:** {st.session_state.active_tab}")
        st.write(f"**Previous Tab:** {st.session_state.get('previous_tab', 'None')}")
        st.write(f"**Module Loading:** {st.session_state.get('module_loading', False)}")
        st.write(f"**Cache Sizes:**")
        st.write(f"  - Metadata: {len(st.session_state.get('workspace_metadata_cache', {}))}")
        st.write(f"  - Images: {len(st.session_state.get('workspace_image_cache', {}))}")
        st.write(f"**Connection Status:** {st.session_state.get('connection_status', 'Unknown')}")


def render_about_section():
    """Render about section - UPDATED WITH ASSUMPTIONS"""
    with st.expander("ℹ️ About"):
        st.markdown("""
        
        **Available Modules:**
        - **Digital Replica Explorer**: Browse component data from Triplestore (Default)
        - **Ontology Manager**: Manage components, attributes, properties, and mappings for the Digicities ontology
        - **Replica Builder**: Builds instances and system description according to the ontology
        - **Query Manager**: Create and run predefined SPARQL queries to extract linked data about the system  
        - **Data Viewer and Uploader**: Explore the resources of the workspace e.g. timeseries and geospatial data
        - **Data Product Explorer**: Explore data products including raw, geospatial and time series data visualization
        - **Service Requirements Builder**: Create service requirement YAML files with hierarchical component structure
        - **Scenario Builder**: Build scenarios using workspace TTL files and NextCloud data products for defined services
        - **Assumptions Module**: Apply predefined assumptions to baseline scenarios for consistent systematic modifications
        - **API Data Submission**: Upload scenario files and submit them to registered service APIs
        """)


def render_eranet_logo():
    """Render eranet logo with the required funding acknowledgement strapline."""
    eranet_logo_path = load_eranet_logo()
    if eranet_logo_path:
        logo_b64 = get_image_base64_cached(eranet_logo_path)
        st.markdown("---")
        st.markdown(f"""
        <div style="text-align: center; margin-top: 2rem;">
            <img src="data:image/png;base64,{logo_b64}"
                 width="150"
                 alt="ERA-Net Smart Energy Systems logo"
                 class="workspace-image"
                 style="opacity: 0.8;">
            <p style="font-size: 0.8rem; color: #666; max-width: 720px; margin: 1rem auto 0 auto; line-height: 1.4;">
                Digicities was an international three-year project funded through the SFOE P+D program
                under the framework of the joint programming initiative ERA-Net Smart Energy Systems&rsquo;
                focus initiative <em>Digital Transformation for the Energy Transition</em> under grant
                agreement No&nbsp;88397.
            </p>
        </div>
        """, unsafe_allow_html=True)


# =============================================================================
# MAIN APP LOGIC
# =============================================================================

def main():
    """Main application entry point - optimized."""
    initialize_session_state()

    # Restore a saved NextCloud connection (if any) into the process env once
    # per session, so GUI-configured credentials survive restarts.
    if not st.session_state.get("nc_bootstrapped"):
        try:
            from backend.workspace import connections as nc
            nc.bootstrap_from_saved()
        except Exception as exc:
            print(f"[main] NextCloud bootstrap skipped: {exc}")
        st.session_state.nc_bootstrapped = True

    display_header_with_logo()

    if AUTH_DISABLED and not st.session_state.get("authenticated"):
        setup_local_auth()

    if AUTH_DISABLED or handle_login():
        access_token, nextcloud_token, username, groups = render_login_section()

        if st.session_state.current_workspace is None:
            render_groups_as_workspaces(groups)
        else:
            main_application()

        # Sidebar NextCloud connector — rendered LAST so it sits at the bottom of
        # the sidebar, below the navigation (not above the logo/nav).
        render_nextcloud_connector()

    elif not st.session_state.get("authenticated"):
        if is_development_mode():
            st.info(f"🔧 **Development Mode**: Will redirect to `{get_redirect_uri()}` after login")

        if st.button("🔐 Login with Keycloak"):
            login_url = build_login_url()
            st.markdown(
                f"<meta http-equiv='refresh' content='0;URL={login_url}'>",
                unsafe_allow_html=True,
            )

    if not AUTH_DISABLED and st.session_state.get("authenticated") and st.button("🚪 Logout", key="main_logout"):
        logout()


if __name__ == "__main__":
    main()