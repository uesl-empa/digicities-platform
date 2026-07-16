# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Module
File: components/ontology_manager/__init__.py

Main module for managing the Digicities ontology - components, attributes,
properties, and mappings.

Runs in integrated mode only: direct GraphDB + local/NextCloud storage
access. (The legacy Flask-backed API mode was removed as part of the
open source release.)
"""

import streamlit as st
import os
from typing import Optional, Dict, Any

# Import submodules
try:
    from .api_client import OntologyAPIClient
    from .forms import render_forms_content
    from .displays import render_main_display
    API_CLIENT_AVAILABLE = True
except ImportError:
    API_CLIENT_AVAILABLE = False

# Import NextCloud clients
try:
    from components.nextcloud_client import NextcloudClient
    from components.nextcloud_global_client import NextcloudGlobalClient
    NEXTCLOUD_AVAILABLE = True
except ImportError:
    NEXTCLOUD_AVAILABLE = False
    print("⚠️ NextCloud clients not available")

# Import GraphDB client
try:
    from components.graphdb import UnifiedGraphDBClient, GraphDBClient
    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False
    print("⚠️ GraphDB client not available")


def get_ontology_directory() -> Optional[str]:
    """Resolve the local-filesystem ontology directory the Ontology Manager
    should read from when running in LOCAL mode.

    Returns None for non-local-filesystem workspaces (NextCloud-backed,
    S3-backed, etc.) — those should route through their own backend client
    in OntologyBase, not through a local FS path.

    Priority:
    1. Active workspace's `ontology/` dir, only if its storage backend
       is the local filesystem.
    2. `$ONTOLOGY_DIR` env var (fallback for non-workspace contexts).
    3. None — OntologyBase falls back to the vendored platform copy.
    """
    ctx = st.session_state.get("workspace_context") if "session_state" in dir(st) else None
    if ctx is not None:
        try:
            # Only return a local path when the workspace is local-FS-backed.
            # For webdav / s3 / etc., the ontology lives behind the storage
            # adapter, not on the platform container's local disk.
            if getattr(ctx, "storage_backend", "file") == "file":
                return f"{ctx.storage.root}/ontology"
        except Exception:
            pass
    return os.getenv("ONTOLOGY_DIR", None)


def initialize_session_state():
    """Initialize session state for ontology manager module"""
    if 'ontology_extensions' not in st.session_state:
        st.session_state.ontology_extensions = []
    if 'ontology_selected_extension' not in st.session_state:
        st.session_state.ontology_selected_extension = ""
    if 'ontology_extension_loaded' not in st.session_state:
        st.session_state.ontology_extension_loaded = False
    if 'ontology_components' not in st.session_state:
        st.session_state.ontology_components = []
    if 'ontology_attributes' not in st.session_state:
        st.session_state.ontology_attributes = []
    if 'ontology_properties' not in st.session_state:
        st.session_state.ontology_properties = []
    if 'ontology_selected_component' not in st.session_state:
        st.session_state.ontology_selected_component = ""
    if 'ontology_component_range' not in st.session_state:
        st.session_state.ontology_component_range = []
    if 'ontology_is_core_mode' not in st.session_state:
        st.session_state.ontology_is_core_mode = False
    if 'ontology_mapping_inputs' not in st.session_state:
        st.session_state.ontology_mapping_inputs = []
    if 'ontology_selected_mapping' not in st.session_state:
        st.session_state.ontology_selected_mapping = ""
    if 'ontology_view_mode' not in st.session_state:
        st.session_state.ontology_view_mode = "components"
    if 'ontology_active_form' not in st.session_state:
        st.session_state.ontology_active_form = None
    if 'ontology_api_client' not in st.session_state:
        st.session_state.ontology_api_client = None


def get_graphdb_client(workspace: Optional[Dict] = None) -> Optional[Any]:
    """
    Get or create GraphDB client

    Args:
        workspace: Workspace dictionary that may contain graphdb_client

    Returns:
        GraphDB client instance or None
    """
    if not GRAPHDB_AVAILABLE:
        return None

    # Try to get from workspace first
    if workspace and isinstance(workspace, dict):
        graphdb_client = workspace.get('graphdb_client')
        if graphdb_client:
            return graphdb_client

    # Try to get from session state
    if hasattr(st.session_state, 'workspace_client') and st.session_state.workspace_client:
        return st.session_state.workspace_client

    # Try to create from session state access token
    if hasattr(st.session_state, 'access_token') and st.session_state.access_token:
        workspace_id = workspace.get('workspace_id') if workspace else None
        if workspace_id:
            try:
                client = UnifiedGraphDBClient(
                    token=st.session_state.access_token,
                    selected_repo=workspace_id
                )
                return client
            except Exception as e:
                print(f"Failed to create GraphDB client: {e}")

    return None


@st.dialog("Form", width="large")
def show_form_dialog(api_client, form_type):
    """Show form in a modal dialog - centered overlay

    IMPORTANT: Dialog stays open until form explicitly closes itself
    """

    # Get form title
    form_titles = {
        "addComponent": "➕ Add Component",
        "removeComponent": "🗑️ Remove Component",
        "changeParent": "↕️ Change Parent",
        "addAttribute": "➕ Add Attribute",
        "removeAttribute": "🗑️ Remove Attribute",
        "linkAttribute": "🔗 Link Attribute",
        "removeAttributeLink": "❌ Unlink Attribute",
        "bulkLinkAttributes": "🔗 Bulk Link Attributes",
        "manageAttributeCategories": "📂 Manage Categories",
        "manageNamedIndividuals": "👤 Manage Individuals",
        "mapComponent": "🗺️ Map Component",
        "mapAttribute": "🗺️ Map Attribute",
        "mapProperty": "🗺️ Map Property",
        "managePropertyMappings": "🔧 Manage Mappings",
        "uploadToGraphDB": "📤 Upload to Triplestore",
        "proposeUpstream": "🌱 Propose Upstream",
    }

    st.subheader(form_titles.get(form_type, "Form"))
    st.markdown("---")

    # Render the form content
    render_forms_content(api_client, form_type)


def render_mode_configuration():
    """Render the integrated-mode status UI."""
    st.subheader("⚙️ Configuration")

    st.markdown("**🔧 Integrated Mode**")

    if NEXTCLOUD_AVAILABLE:
        st.success("✅ NextCloud clients available")
    else:
        st.info("ℹ️ NextCloud clients not available — using local file storage")

    if GRAPHDB_AVAILABLE:
        st.success("✅ Triplestore client available")
    else:
        st.warning("⚠️ Triplestore client not available (upload disabled)")

    st.markdown("""
    **Storage Structure:**
    - **Global (read-only):** `global/ontology/`
      - Core ontology: `dici_onto_core.ttl`
      - Imports: `imports/`

    - **Workspace (editable):** `<workspace>/ontology/`
      - Extensions: `extensions/`
      - Exports: `exports/`
      - Mappings: `mappings/input/` and `mappings/output/`
      - Temp: `temp/`
    """)


def ontology_manager_module(workspace_or_client=None):
    """
    Main ontology manager interface

    Args:
        workspace_or_client: Either:
            - A workspace dict with 'workspace_id' or 'id' and optionally 'graphdb_client'
            - A GraphDBClient object
            - None (will try to get from session state)
    """

    st.header("🔧 Digicities Ontology Manager")

    # Check if API client is available
    if not API_CLIENT_AVAILABLE:
        st.error("❌ Ontology Manager components not available")
        st.info("💡 Please ensure all module files are installed")
        return

    # Initialize session state
    initialize_session_state()

    # Extract workspace ID and GraphDB client
    workspace_id = None
    graphdb_client = None

    if workspace_or_client:
        if hasattr(workspace_or_client, 'upload_ttl'):
            # It's already a GraphDBClient
            graphdb_client = workspace_or_client
        elif isinstance(workspace_or_client, dict):
            # It's a workspace dict
            workspace_id = workspace_or_client.get('workspace_id') or workspace_or_client.get('id')
            graphdb_client = workspace_or_client.get('graphdb_client')

    # If still no workspace_id, try session state (following data_loader pattern)
    if not workspace_id:
        # Try current_workspace (used by data_loader and other components)
        current_workspace = st.session_state.get('current_workspace')
        if current_workspace and isinstance(current_workspace, dict):
            workspace_id = current_workspace.get('id')

        # Fallback to selected_workspace (string)
        if not workspace_id:
            workspace_id = getattr(st.session_state, 'selected_workspace', None)

    # If STILL no workspace_id, show helpful error
    if not workspace_id:
        st.error("❌ No workspace ID available")
        st.info("""
        **To use the Ontology Manager, please provide a workspace:**
        
        The Ontology Manager needs a workspace context to operate. Please ensure:
        - You are running within a workspace context
        - `st.session_state.current_workspace` is set with workspace info
```python
        # Your application should set:
        st.session_state.current_workspace = {
            'id': 'your-workspace-id',
            'name': 'Your Workspace Name'
        }
```
        
        Or pass workspace directly:
```python
        workspace = {'workspace_id': 'your-workspace-id'}
        ontology_manager_module(workspace)
```
        """)
        return

    # If still no graphdb_client, try to get it
    if not graphdb_client:
        graphdb_client = get_graphdb_client(workspace_or_client if isinstance(workspace_or_client, dict) else None)

    # All workspace file I/O goes through the one storage abstraction
    # (ctx.storage), which already handles local disk, NextCloud (WebDAV) and any
    # other fsspec backend. OntologyBase routes everything through this handle.
    workspace_ctx = st.session_state.get("workspace_context")
    storage = getattr(workspace_ctx, "storage", None) if workspace_ctx is not None else None

    # Rebuild the Ontology Manager client whenever the active workspace OR its
    # storage changes — switching workspaces, or reconnecting NextCloud after it
    # was offline. Without this, a client built against an empty/stale context
    # stays cached for the whole session and the extensions list looks empty even
    # though the files exist.
    client_key = (
        workspace_id,
        getattr(storage, "protocol", None),
        getattr(storage, "root", None),
    )

    # Initialize or reinitialize API client if needed
    if (st.session_state.ontology_api_client is None
            or st.session_state.get("ontology_api_client_key") != client_key):
        # Always use integrated mode
        try:
            # Local fallback for non-workspace contexts (no active ctx.storage).
            ontology_dir = get_ontology_directory()

            # Create the API client with all available integrations
            try:
                st.session_state.ontology_api_client = OntologyAPIClient(
                    storage=storage,
                    workspace_id=workspace_id,
                    graphdb_client=graphdb_client,
                    ontology_dir=ontology_dir
                )
                st.session_state.ontology_api_client_key = client_key

                # Silent initialization - no success messages needed

            except Exception as init_error:
                st.error(f"❌ Failed to create OntologyAPIClient: {str(init_error)}")
                import traceback
                with st.expander("🔍 Initialization Error Details", expanded=True):
                    st.code(traceback.format_exc())
                # Set to None explicitly
                st.session_state.ontology_api_client = None
                return

        except Exception as e:
            st.error(f"❌ Failed to initialize client: {str(e)}")
            import traceback
            with st.expander("🔍 Error Details", expanded=True):
                st.code(traceback.format_exc())
            # Set to None explicitly
            st.session_state.ontology_api_client = None
            return

    api_client = st.session_state.ontology_api_client

    # Safety check - ensure client was initialized
    if api_client is None:
        st.error("❌ API client is None after initialization")
        st.info("Please check the error messages above")
        return

    # Extension selection section. The Ontology Manager opens here (Load existing
    # / Create new). The core ontology is available to view/extend via the
    # "🔴 Modify Core Ontology" entry in the Load Extensions list (offered in
    # both local and NextCloud modes).
    if not st.session_state.ontology_extension_loaded:
        render_extension_selection(api_client)
    else:
        render_loaded_extension_interface(api_client)

    # Show form dialog if active
    if st.session_state.ontology_active_form:
        show_form_dialog(api_client, st.session_state.ontology_active_form)


def render_extension_selection(api_client):
    """Render the clean extension selection interface"""

    # Simple welcome message
    st.markdown("""
    ### Welcome to the Ontology Manager
    
    Get started by loading an existing extension or creating a new one.
    """)

    st.markdown("---")

    # Two main action cards side by side
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📂 Load Existing Extension")
        st.markdown("Work with an existing ontology extension file")

        if st.button("🔄 Load Extensions", key="load_extensions_btn",
                    type="primary", use_container_width=True):
            with st.spinner("Loading extensions..."):
                extensions = api_client.fetch_extensions()
                if extensions is not None:
                    st.session_state.ontology_extensions = extensions
                    if len(extensions) > 0:
                        st.success(f"✅ Found {len(extensions)} extension(s)")
                    else:
                        st.info("📁 No extensions found. Create a new one!")
                    st.rerun()

        # Show selector if extensions are loaded
        if st.session_state.ontology_extensions:
            st.markdown("---")

            # Fetch active extension metadata once
            active_info = api_client.get_active_extension()
            active_name = active_info.get("extension") if active_info else None

            # Create display names for extensions
            extension_options = st.session_state.ontology_extensions
            display_names = []
            for ext in extension_options:
                if ext == "CORE_ONTOLOGY_MODIFICATION":
                    display_names.append("🔴 Modify Core Ontology")
                elif ext == active_name:
                    display_names.append(f"{ext}  ✓ active")
                else:
                    display_names.append(ext)

            if active_info and active_name in extension_options:
                st.caption(f"Active version: **{active_name}** — uploaded {active_info.get('uploaded_at', 'unknown')}")

            if display_names:
                selected_display = st.selectbox(
                    "Select Extension",
                    options=display_names,
                    index=0,
                    key="extension_selector",
                    label_visibility="collapsed"
                )

                # Get actual extension value
                selected_idx = display_names.index(selected_display)
                st.session_state.ontology_selected_extension = extension_options[selected_idx]

                # Load button
                if st.button("✅ Load Selected", key="load_extension_btn",
                           type="secondary", use_container_width=True):
                    load_extension(api_client, st.session_state.ontology_selected_extension)

    with col2:
        st.markdown("### ✨ Create New Extension")
        st.markdown("Start fresh with a new ontology extension file")

        with st.form("create_extension_form"):
            extension_name = st.text_input(
                "Extension Name",
                placeholder="e.g., my_extension",
                help="Name for your extension file (without .ttl extension)",
                label_visibility="collapsed"
            )

            submitted = st.form_submit_button("🚀 Create Extension",
                                            type="primary",
                                            use_container_width=True)

            if submitted:
                if not extension_name or not extension_name.strip():
                    st.error("❌ Please enter a name for the extension")
                else:
                    with st.spinner(f"Creating extension '{extension_name}'..."):
                        success, message = api_client.functions.create_new_extension(extension_name.strip())

                        if success:
                            st.success(message)
                            # Refresh the extensions list
                            extensions = api_client.fetch_extensions()
                            if extensions is not None:
                                st.session_state.ontology_extensions = extensions
                            st.rerun()
                        else:
                            st.error(message)


def load_extension(api_client, extension_filename):
    """Load the selected extension"""
    if not extension_filename:
        st.error("Please select an extension file")
        return

    is_core_mode = extension_filename == "CORE_ONTOLOGY_MODIFICATION"

    # In NextCloud mode the global core is read-only — you can VIEW it but not
    # save changes back. Allow loading it for inspection (saving is blocked
    # downstream), just flag the read-only state.
    if is_core_mode and api_client.is_nextcloud_mode():
        st.info("ℹ️ Core ontology is read-only in NextCloud mode — you can view its "
                "components and attributes, but to make changes create an extension.")

    st.session_state.ontology_is_core_mode = is_core_mode

    with st.spinner(f"Loading {'core ontology' if is_core_mode else extension_filename}..."):
        success = api_client.load_extension(extension_filename)

        if success:
            st.session_state.ontology_extension_loaded = True

            # Fetch initial data
            st.session_state.ontology_components = api_client.fetch_components(extension_filename)
            st.session_state.ontology_attributes = api_client.fetch_attributes(extension_filename)
            st.session_state.ontology_properties = api_client.fetch_properties(extension_filename)
            st.session_state.ontology_mapping_inputs = api_client.fetch_mapping_inputs()

            # Set initial component selection
            if st.session_state.ontology_components:
                st.session_state.ontology_selected_component = st.session_state.ontology_components[0]['class']

            message = "Core ontology loaded for modification!" if is_core_mode else f"Extension {extension_filename} loaded successfully!"
            st.success(message)
            st.rerun()
        else:
            st.error("Failed to load extension")


def render_loaded_extension_interface(api_client):
    """Render the main interface after extension is loaded"""

    # Header with extension info
    extension_name = st.session_state.ontology_selected_extension
    mode_text = "Core Ontology Modification" if st.session_state.ontology_is_core_mode else extension_name

    st.markdown(f"### 📋 {mode_text}")

    # Reset button
    if st.button("🔙 Select Different Extension", key="reset_extension"):
        st.session_state.ontology_extension_loaded = False
        st.session_state.ontology_active_form = None
        st.rerun()

    st.markdown("---")

    # Mapping input selection
    st.subheader("🗺️ Mapping Input")
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.ontology_mapping_inputs:
            selected_mapping = st.selectbox(
                "Select Mapping Input File",
                options=[""] + st.session_state.ontology_mapping_inputs,
                index=0 if not st.session_state.ontology_selected_mapping else
                      st.session_state.ontology_mapping_inputs.index(st.session_state.ontology_selected_mapping) + 1,
                key="mapping_selector"
            )
            st.session_state.ontology_selected_mapping = selected_mapping
        else:
            st.info("No mapping input files available")

    with col2:
        if st.button("🔄 Refresh", key="refresh_mappings"):
            st.session_state.ontology_mapping_inputs = api_client.fetch_mapping_inputs()
            st.rerun()

    st.markdown("---")

    # GraphDB Upload + Upstream Propose Section
    st.subheader("📤 Publish")

    col_pub1, col_pub2 = st.columns(2)
    with col_pub1:
        if api_client.is_integrated_mode() and not api_client.graphdb_client:
            st.warning("⚠️ Triplestore client not configured. Upload functionality disabled.")
            st.caption("💡 Pass a workspace with a Triplestore client to enable Triplestore operations")
        else:
            if st.button("📤 Upload to Triplestore", key="upload_graphdb_btn", type="primary", use_container_width=True):
                st.session_state.ontology_active_form = "uploadToGraphDB"
                st.rerun()
            st.caption("Push the merged TTL into your workspace's Triplestore repo.")
    with col_pub2:
        if st.button("🌱 Propose Upstream", key="propose_upstream_btn", use_container_width=True):
            st.session_state.ontology_active_form = "proposeUpstream"
            st.rerun()
        st.caption("Open a PR adding this extension to the public digicities-ontology repo.")

    st.markdown("---")

    # Main content area with tabs
    tab1, tab2, tab3 = st.tabs(["📦 Classes & Attributes", "🔗 Object Properties", "📋 Operations"])

    with tab1:
        render_classes_tab(api_client)

    with tab2:
        render_properties_tab(api_client)

    with tab3:
        render_operations_tab(api_client)


def render_classes_tab(api_client):
    """Render the classes and attributes tab"""
    st.subheader("Classes (subClasses of owl:Thing)")

    # Action buttons
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("👁️ Components", key="show_components"):
            st.session_state.ontology_view_mode = "components"
            st.rerun()
    with col2:
        if st.button("👁️ Attributes", key="show_attributes"):
            st.session_state.ontology_view_mode = "attributes"
            st.rerun()
    with col3:
        if st.button("➕ Add Component", key="add_component_btn"):
            st.session_state.ontology_active_form = "addComponent"
            st.rerun()
    with col4:
        if st.button("➕ Add Attribute", key="add_attribute_btn"):
            st.session_state.ontology_active_form = "addAttribute"
            st.rerun()

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        if st.button("🔗 Link Attribute", key="link_attribute_btn"):
            st.session_state.ontology_active_form = "linkAttribute"
            st.rerun()
    with col6:
        if st.button("🔗 Bulk Link", key="bulk_link_btn", help="Bulk link attributes"):
            st.session_state.ontology_active_form = "bulkLinkAttributes"
            st.rerun()
    with col7:
        if st.button("🗺️ Map Component", key="map_component_btn",
                    disabled=not st.session_state.ontology_selected_mapping):
            st.session_state.ontology_active_form = "mapComponent"
            st.rerun()
    with col8:
        if st.button("🗺️ Map Attribute", key="map_attribute_btn",
                    disabled=not st.session_state.ontology_selected_mapping):
            st.session_state.ontology_active_form = "mapAttribute"
            st.rerun()

    # Destructive actions
    st.markdown("**🔧 Modification Actions:**")
    col9, col10, col11, col12 = st.columns(4)
    with col9:
        if st.button("🗑️ Remove Component", key="remove_component_btn"):
            st.session_state.ontology_active_form = "removeComponent"
            st.rerun()
    with col10:
        if st.button("↕️ Change Parent", key="change_parent_btn"):
            st.session_state.ontology_active_form = "changeParent"
            st.rerun()
    with col11:
        if st.button("🗑️ Remove Attribute", key="remove_attribute_btn"):
            st.session_state.ontology_active_form = "removeAttribute"
            st.rerun()
    with col12:
        if st.button("❌ Unlink Attribute", key="unlink_attribute_btn"):
            st.session_state.ontology_active_form = "removeAttributeLink"
            st.rerun()

    col13, col14 = st.columns([1, 1])
    with col13:
        if st.button("📂 Manage Categories", key="manage_categories_btn"):
            st.session_state.ontology_active_form = "manageAttributeCategories"
            st.rerun()
    with col14:
        if st.button("👤 Manage Individuals", key="manage_individuals_btn"):
            st.session_state.ontology_active_form = "manageNamedIndividuals"
            st.rerun()

    st.markdown("---")

    # Display section
    render_main_display(api_client, st.session_state.ontology_view_mode)


def render_properties_tab(api_client):
    """Render the object properties tab"""
    st.subheader("Object Properties (subProperties of owl:topObjectProperty)")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("👁️ Show Properties", key="show_properties"):
            st.session_state.ontology_view_mode = "properties"
            st.rerun()
    with col2:
        if st.button("🗺️ Map Property", key="map_property_btn",
                    disabled=not st.session_state.ontology_selected_mapping):
            st.session_state.ontology_active_form = "mapProperty"
            st.rerun()
    with col3:
        if st.button("🔧 Manage Mappings", key="manage_mappings_btn",
                    disabled=not st.session_state.ontology_selected_mapping):
            st.session_state.ontology_active_form = "managePropertyMappings"
            st.rerun()

    st.markdown("---")

    # Display properties
    render_main_display(api_client, "properties")


def render_operations_tab(api_client):
    """Render the operations summary tab"""
    st.subheader("📊 Ontology Statistics")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Components", len(st.session_state.ontology_components))
    with col2:
        st.metric("Attributes", len(st.session_state.ontology_attributes))
    with col3:
        st.metric("Properties", len(st.session_state.ontology_properties))

    st.markdown("---")

    st.subheader("🔄 Data Refresh")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔄 Refresh Components", key="refresh_components"):
            with st.spinner("Refreshing components..."):
                st.session_state.ontology_components = api_client.fetch_components(
                    st.session_state.ontology_selected_extension
                )
                st.success("✅ Components refreshed")
                st.rerun()

    with col2:
        if st.button("🔄 Refresh Attributes", key="refresh_attributes"):
            with st.spinner("Refreshing attributes..."):
                st.session_state.ontology_attributes = api_client.fetch_attributes(
                    st.session_state.ontology_selected_extension
                )
                st.success("✅ Attributes refreshed")
                st.rerun()

    with col3:
        if st.button("🔄 Refresh Properties", key="refresh_properties"):
            with st.spinner("Refreshing properties..."):
                st.session_state.ontology_properties = api_client.fetch_properties(
                    st.session_state.ontology_selected_extension
                )
                st.success("✅ Properties refreshed")
                st.rerun()

    st.markdown("---")

    st.subheader("📄 Extension Information")

    mode_indicator = "🔧 Integrated Mode"
    storage_type = " (NextCloud Storage)" if api_client.is_nextcloud_mode() else " (Local Storage)"

    st.info(f"""
    **Current Extension:** {st.session_state.ontology_selected_extension}
    
    **Mode:** {'🔴 Core Ontology Modification' if st.session_state.ontology_is_core_mode else '📦 Extension Mode'}
    
    **Mapping File:** {st.session_state.ontology_selected_mapping or 'None selected'}
    
    **Operation Mode:** {mode_indicator}{storage_type}
    """)


# Export the main function
__all__ = ['ontology_manager_module']

# Also export with alternative name
ontology_manager = ontology_manager_module