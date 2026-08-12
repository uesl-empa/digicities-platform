# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/workspace_selector.py
from __future__ import annotations

import streamlit as st
import json
import base64
import os
from components.nextcloud_module import get_nextcloud_client
from components.graphdb import GraphDBClient


def _registry_context(workspace_id: str):
    """Look up the workspace in the registry, return its WorkspaceContext or None."""
    try:
        from backend.workspace import load_registry
        return load_registry().by_id(workspace_id)
    except Exception:
        return None


def _native_local_path(ctx) -> str | None:
    """Native OS path for a local (file-backed) WorkspaceContext, else None."""
    try:
        if ctx is None or getattr(ctx.storage, "protocol", None) != "file":
            return None
        return os.path.normpath(ctx.storage.root)
    except Exception:
        return None


def _candidate_local_roots():
    """Directories a local workspace folder might live under, most-specific first."""
    roots = []
    env_dir = os.environ.get("USECASES_DIR")
    if env_dir:
        roots.append(env_dir)
    try:
        from backend.workspace.registry import DEFAULT_USECASES_DIR, BUNDLED_DEMO_DIR
        roots.append(str(DEFAULT_USECASES_DIR))
        roots.append(str(BUNDLED_DEMO_DIR))
    except Exception:
        pass
    # De-dup while preserving order.
    seen, out = set(), []
    for r in roots:
        key = os.path.normpath(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _to_host_display_path(path: str) -> str | None:
    """Translate a container path under USECASES_DIR to its host path.

    The app usually runs in Docker, where the workspace root is a bind mount
    (`${USECASES_HOST_PATH}:/app/data/usecases`). A path like
    `/app/data/usecases/foo` is meaningless on the user's machine, so we swap the
    container root (USECASES_DIR) for the host root (USECASES_HOST_PATH). Returns
    None when either env var is missing or `path` isn't under the mount (e.g. when
    running outside Docker, where the path is already a real host path).
    """
    host_root = os.environ.get("USECASES_HOST_PATH")
    ws_dir = os.environ.get("USECASES_DIR")
    if not host_root or not ws_dir:
        return None
    p = str(path).replace("\\", "/").rstrip("/")
    wd = ws_dir.replace("\\", "/").rstrip("/")
    if p != wd and not p.startswith(wd + "/"):
        return None
    rel = p[len(wd):].lstrip("/")
    host_root = host_root.rstrip("/\\")
    # A Windows host root ("C:/...") is rendered with backslashes so it pastes
    # straight into File Explorer; POSIX roots keep forward slashes.
    if len(host_root) >= 2 and host_root[1] == ":":
        base = host_root.replace("/", "\\")
        return base + ("\\" + rel.replace("/", "\\") if rel else "")
    return host_root + ("/" + rel if rel else "")


def get_workspace_local_path(workspace_id: str) -> str | None:
    """Return the navigable on-disk path for a *local* (filesystem) workspace.

    Only local workspaces live at a navigable OS path; NextCloud and other
    fsspec backends return None. Resolution order (each independent of the
    others, so a mis-set USECASES_DIR can't hide the path):

    1. The live WorkspaceContext the app opened with (session state) — the
       authoritative root, always matches the running app's config.
    2. A fresh registry lookup by id.
    3. A direct scan of candidate local roots for
       `<root>/<id>/workspace_meta/metadata.json`.

    The resolved path may be a *container* path when running in Docker; it is
    translated to the host path (see `_to_host_display_path`) so the user can
    open it on their own machine.
    """
    resolved = None

    # 1. Live session context (only if it's the workspace we're asking about).
    try:
        ctx = st.session_state.get("workspace_context")
        if ctx is not None and getattr(ctx, "id", None) == workspace_id:
            resolved = _native_local_path(ctx)
    except Exception:
        pass

    # 2. Registry lookup.
    if not resolved:
        resolved = _native_local_path(_registry_context(workspace_id))

    # 3. Filesystem scan of candidate roots.
    if not resolved:
        for root in _candidate_local_roots():
            candidate = os.path.join(root, workspace_id)
            marker = os.path.join(candidate, "workspace_meta", "metadata.json")
            if os.path.isfile(marker):
                resolved = os.path.normpath(candidate)
                break

    if not resolved:
        return None
    return _to_host_display_path(resolved) or resolved


def load_workspace_metadata(workspace_id: str) -> dict:
    """Load workspace metadata.

    Priority:
    1. workspace_meta/metadata.json read from the workspace's own storage (registry-aware,
       works for both local and NextCloud workspaces).
    2. Legacy fallback: global/workspace_meta/<id>/metadata.json on NextCloud.
    """
    ctx = _registry_context(workspace_id)
    if ctx is not None:
        try:
            if ctx.storage.exists("workspace_meta/metadata.json"):
                return json.loads(ctx.storage.read_text("workspace_meta/metadata.json"))
        except Exception as e:
            print(f"[workspace_selector] registry-side metadata read failed for {workspace_id}: {e}")

    try:
        client = get_nextcloud_client("global")
        metadata_content = client.download_text_file(f"workspace_meta/{workspace_id}/metadata.json")
        return json.loads(metadata_content)
    except Exception as e:
        print(f"Could not load metadata for workspace {workspace_id}: {e}")
        return {}


def get_workspace_image(workspace_id: str) -> bytes:
    """Get workspace image bytes.

    Priority:
    1. workspace_meta/image.{png,jpg} from the workspace's own storage (registry-aware).
    2. Legacy fallback: global/workspace_meta/<id>/image.{jpg,png} on NextCloud.
    """
    ctx = _registry_context(workspace_id)
    if ctx is not None:
        for fname in ("workspace_meta/image.png", "workspace_meta/image.jpg"):
            try:
                if ctx.storage.exists(fname):
                    return ctx.storage.read_bytes(fname)
            except Exception:
                pass

    try:
        client = get_nextcloud_client("global")
        try:
            return client.download_image(f"workspace_meta/{workspace_id}/image.jpg")
        except:
            return client.download_image(f"workspace_meta/{workspace_id}/image.png")
    except Exception:
        return None


def create_workspace_card(workspace: dict, user_groups: list) -> None:
    """
    Create a beautiful workspace card with background image and hover effects.

    Args:
        workspace: Workspace dictionary with metadata
        user_groups: User's available groups for access checking
    """
    workspace_id = workspace['id']

    # Get workspace image for background
    img_data = get_workspace_image(workspace_id)

    # Create background style
    if img_data:
        img_b64 = base64.b64encode(img_data).decode()
        background_style = f"""
        background: linear-gradient(rgba(31, 119, 180, 0.85), rgba(255, 127, 14, 0.85)), 
                    url(data:image/jpeg;base64,{img_b64});
        background-size: cover;
        background-position: center;
        background-blend-mode: overlay;
        """
    else:
        background_style = "background: linear-gradient(135deg, #1f77b4 0%, #ff7f0e 100%);"

    # Create the card with custom CSS
    card_html = f"""
    <div style="
        {background_style}
        color: white;
        padding: 2rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        position: relative;
        overflow: hidden;
        transition: all 0.3s ease;
        cursor: pointer;
        border: 2px solid transparent;
    " 
    onmouseover="this.style.transform='translateY(-4px)'; this.style.boxShadow='0 12px 48px rgba(0, 0, 0, 0.3)'; this.style.border='2px solid rgba(255,255,255,0.3)';"
    onmouseout="this.style.transform='translateY(0px)'; this.style.boxShadow='0 8px 32px rgba(0, 0, 0, 0.2)'; this.style.border='2px solid transparent';"
    >
        <!-- Decorative element -->
        <div style="
            position: absolute;
            top: -50px;
            right: -50px;
            width: 100px;
            height: 100px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            backdrop-filter: blur(10px);
        "></div>

        <!-- Content overlay with backdrop blur -->
        <div style="
            backdrop-filter: blur(2px); 
            padding: 1.5rem; 
            border-radius: 12px; 
            background: rgba(0, 0, 0, 0.15);
            position: relative;
            z-index: 2;
        ">
            <!-- Header -->
            <div style="display: flex; align-items: center; margin-bottom: 1rem;">
                <div style="
                    background: rgba(255, 255, 255, 0.2);
                    padding: 0.5rem;
                    border-radius: 8px;
                    margin-right: 1rem;
                ">
                    🏢
                </div>
                <h3 style="
                    margin: 0; 
                    color: white; 
                    font-size: 1.6rem; 
                    font-weight: 600;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                ">{workspace['name']}</h3>
            </div>

            <!-- Description -->
            <p style="
                margin: 0 0 1rem 0; 
                opacity: 0.95; 
                font-size: 1.1rem;
                line-height: 1.4;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
            ">
                {workspace['description']}
            </p>

            <!-- Metadata badges -->
            <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem;">
                <span style="
                    background: rgba(255, 255, 255, 0.2);
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.9rem;
                    backdrop-filter: blur(10px);
                ">📍 {workspace['location']}</span>

                <span style="
                    background: rgba(255, 255, 255, 0.2);
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.9rem;
                    backdrop-filter: blur(10px);
                ">🏷️ {workspace['type']}</span>

                <span style="
                    background: rgba(255, 255, 255, 0.2);
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.9rem;
                    backdrop-filter: blur(10px);
                ">📅 {workspace.get('last_access', 'N/A')}</span>
            </div>
        </div>
    </div>
    """

    st.markdown(card_html, unsafe_allow_html=True)


def render_workspace_actions(workspace: dict) -> None:
    """
    Render action buttons for a workspace.

    Args:
        workspace: Workspace dictionary
    """
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

    with col1:
        if st.button(f"🚀 Open Workspace", key=f"open_{workspace['id']}", use_container_width=True):
            access_token = st.session_state.get("access_token")
            st.session_state.current_workspace = workspace
            st.session_state.workspace_client = GraphDBClient(
                token=access_token,
                selected_repo=workspace["id"]
            )
            st.success(f"✨ Opening {workspace['name']}...")
            st.rerun()

    with col2:
        if st.button(f"📊 Quick Stats", key=f"stats_{workspace['id']}", use_container_width=True):
            show_workspace_stats(workspace)

    with col3:
        if st.button(f"ℹ️ Details", key=f"info_{workspace['id']}", use_container_width=True):
            show_workspace_details(workspace)

    with col4:
        # Toggled, not transient: the Settings panel now contains forms whose own
        # buttons trigger a rerun, and a panel rendered straight from the click
        # would disappear on that rerun before it could be used.
        panel = f"show_settings_{workspace['id']}"
        if st.button(f"🔧 Settings", key=f"settings_{workspace['id']}", use_container_width=True):
            st.session_state[panel] = not st.session_state.get(panel, False)
    if st.session_state.get(f"show_settings_{workspace['id']}", False):
        show_workspace_settings(workspace)


def show_workspace_stats(workspace: dict) -> None:
    """Show workspace statistics in an expander."""
    with st.expander(f"📊 {workspace['name']} - Quick Statistics", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                label="🏷️ Workspace Type",
                value=workspace.get('type', 'Unknown')
            )

        with col2:
            st.metric(
                label="📅 Last Access",
                value=workspace.get('last_access', 'N/A')
            )

        with col3:
            st.metric(
                label="📍 Location",
                value=workspace.get('location', 'Unknown')
            )

        # Try to get additional stats from workspace
        try:
            metadata = load_workspace_metadata(workspace['id'])
            if 'data_sources' in metadata:
                st.write("**📡 Data Sources:**")
                for source in metadata['data_sources']:
                    st.write(f"• {source}")

            if 'key_metrics' in metadata:
                st.write("**📈 Key Metrics:**")
                for metric in metadata['key_metrics']:
                    st.write(f"• {metric}")

        except Exception as e:
            st.info("Additional statistics not available")


def show_workspace_details(workspace: dict) -> None:
    """Show detailed workspace information."""
    with st.expander(f"ℹ️ {workspace['name']} - Detailed Information", expanded=True):
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown(f"""
            ### 🏢 Workspace Overview

            **Name:** {workspace['name']}  
            **Type:** {workspace['type']}  
            **Location:** {workspace['location']}  
            **Description:** {workspace['description']}  

            **📅 Timeline:**
            - Created: {workspace.get('created_date', 'N/A')}
            - Last Access: {workspace.get('last_access', 'N/A')}
            - Version: {workspace.get('version', 'N/A')}

            **👤 Contact Information:**
            - Contact: {workspace.get('contact_person', 'N/A')}
            - Email: {workspace.get('contact_email', 'N/A')}
            """)

            # Show the on-disk path for local workspaces so users can browse
            # the files directly in their OS file explorer. (NextCloud and other
            # backends have no local path, so this is hidden for them.)
            local_path = get_workspace_local_path(workspace['id'])
            if local_path:
                st.markdown("**📂 Filesystem location:**")
                st.code(local_path, language=None)
                st.caption("Copy this path into your file explorer to browse the workspace files.")

            # Show tags if available
            if 'tags' in workspace and workspace['tags']:
                st.write("**🏷️ Tags:**")
                tag_html = ""
                for tag in workspace['tags']:
                    tag_html += f'<span style="background: #e1f5fe; color: #01579b; padding: 0.2rem 0.5rem; border-radius: 12px; margin: 0.2rem; display: inline-block;">{tag}</span>'
                st.markdown(tag_html, unsafe_allow_html=True)

        with col2:
            # Show workspace image if available
            img_data = get_workspace_image(workspace['id'])
            if img_data:
                st.image(img_data, caption=f"{workspace['name']} Image", use_container_width=True)
            else:
                st.info("No workspace image available")


def show_workspace_settings(workspace: dict) -> None:
    """Show workspace settings and configuration options."""
    with st.expander(f"🔧 {workspace['name']} - Settings & Configuration", expanded=True):
        st.markdown(f"""
        ### ⚙️ Workspace Configuration

        **Workspace ID:** `{workspace['id']}`  
        **Status:** {workspace.get('status', 'Unknown')}  
        **Version:** {workspace.get('version', 'N/A')}  

        ### 🔧 Advanced Settings
        """)

        # Add some configuration options
        col1, col2 = st.columns(2)

        with col1:
            st.checkbox("🔔 Enable Notifications", value=True, key=f"notifications_{workspace['id']}")
            st.checkbox("📊 Auto-refresh Data", value=False, key=f"autorefresh_{workspace['id']}")

        with col2:
            st.selectbox(
                "🎨 Theme",
                ["Default", "Dark", "Light", "Custom"],
                key=f"theme_{workspace['id']}"
            )
            st.selectbox(
                "📈 Default View",
                ["Component Explorer", "Query Manager", "Nextcloud Manager"],
                key=f"default_view_{workspace['id']}"
            )

        st.info("💡 Settings are saved automatically per user session")

        render_danger_zone(workspace)


def render_danger_zone(workspace: dict) -> None:
    """Clear-contents / delete controls. Implementation lives in
    components.workspace_admin so the live landing page (app.render_groups_as_workspaces)
    and this card view share one copy."""
    from components.workspace_admin import render_danger_zone as _dz
    _dz(workspace)


def workspace_selector():
    """
    Enhanced workspace selector with global metadata integration.
    """
    # Custom CSS for better styling
    st.markdown("""
    <style>
    .workspace-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        text-align: center;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

    # Header section
    st.markdown("""
    <div class="workspace-header">
        <h1 style="margin: 0; font-size: 2.5rem; font-weight: 700;">🏢 Your Workspaces</h1>
        <p style="margin: 0.5rem 0 0 0; font-size: 1.2rem; opacity: 0.9;">
            Select a workspace to begin your data exploration journey
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Get user groups and filter workspace groups
    payload = st.session_state.get("access_payload", {})
    username = payload.get("preferred_username", "Unknown User")
    groups = payload.get("groups", [])
    workspace_groups = [g for g in groups if g.startswith("workspace_")]

    if not workspace_groups:
        st.error("🚫 No workspaces available")
        st.info("Please contact your administrator to get workspace access")
        return None

    # Create workspace cards
    st.subheader(f"👋 Welcome back, {username}")
    st.write(f"You have access to **{len(workspace_groups)}** workspace{'s' if len(workspace_groups) != 1 else ''}")

    # Add search/filter functionality
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search_term = st.text_input("🔍 Search workspaces...", placeholder="Type to filter workspaces")
    with col2:
        sort_by = st.selectbox("📊 Sort by", ["Name", "Type", "Last Access"])
    with col3:
        view_mode = st.radio("👁️ View", ["Cards", "List"], horizontal=True)

    # Load and process workspaces
    workspaces = []
    for group in workspace_groups:
        workspace_id = group
        metadata = load_workspace_metadata(workspace_id)

        workspace = {
            'id': workspace_id,
            'name': metadata.get('name', group.replace("workspace_", "").replace("_", " ").title()),
            'description': metadata.get('description', f"Workspace: {group}"),
            'type': metadata.get('type', "Unknown"),
            'location': metadata.get('location', "Unknown Location"),
            'created_date': metadata.get('created_date', "N/A"),
            'last_access': metadata.get('last_access', "N/A"),
            'contact_person': metadata.get('contact_person', "N/A"),
            'contact_email': metadata.get('contact_email', "N/A"),
            'tags': metadata.get('tags', []),
            'version': metadata.get('version', "N/A"),
            'status': metadata.get('status', "active")
        }

        # Apply search filter
        if search_term:
            search_fields = [workspace['name'], workspace['description'], workspace['type'], workspace['location']]
            if not any(search_term.lower() in field.lower() for field in search_fields):
                continue

        workspaces.append(workspace)

    # Sort workspaces
    if sort_by == "Name":
        workspaces.sort(key=lambda x: x['name'])
    elif sort_by == "Type":
        workspaces.sort(key=lambda x: x['type'])
    elif sort_by == "Last Access":
        workspaces.sort(key=lambda x: x['last_access'], reverse=True)

    if not workspaces:
        st.info("🔍 No workspaces match your search criteria")
        return None

    # Display workspaces
    if view_mode == "Cards":
        for workspace in workspaces:
            create_workspace_card(workspace, groups)
            render_workspace_actions(workspace)
            st.markdown("---")

    else:  # List view
        st.subheader("📋 Workspace List")

        # Create a nice table view
        workspace_data = []
        for ws in workspaces:
            workspace_data.append({
                "🏢 Name": ws['name'],
                "🏷️ Type": ws['type'],
                "📍 Location": ws['location'],
                "📅 Last Access": ws['last_access'],
                "🔧 Actions": f"open_{ws['id']}"
            })

        df = st.dataframe(
            workspace_data,
            use_container_width=True,
            hide_index=True
        )

        # Add action buttons below the table
        st.write("**Select a workspace to open:**")
        cols = st.columns(min(len(workspaces), 4))
        for i, workspace in enumerate(workspaces):
            with cols[i % 4]:
                if st.button(f"🚀 {workspace['name']}", key=f"list_open_{workspace['id']}", use_container_width=True):
                    access_token = st.session_state.get("access_token")
                    st.session_state.current_workspace = workspace
                    st.session_state.workspace_client = GraphDBClient(
                        token=access_token,
                        selected_repo=workspace["id"]
                    )
                    st.success(f"✨ Opening {workspace['name']}...")
                    st.rerun()

    return st.session_state.get('current_workspace')