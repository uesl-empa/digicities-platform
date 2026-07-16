# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_nextcloud_integration.py
"""
Timeseries file upload/listing for the Replica Builder.

Routes all file I/O through the one workspace storage abstraction
(``ctx.storage``), so it works on local disk, NextCloud (WebDAV) and any other
fsspec backend — no NextCloud-specific client. Files live in the workspace's
canonical ``timeseries/`` directory.

(The module name is kept for import stability; it is no longer NextCloud-specific.)
"""
import streamlit as st
from typing import List, Optional, Tuple

from backend.workspace.storage import WorkspaceStorage

TIMESERIES_DIR = "timeseries"


def _ws_storage() -> Optional[WorkspaceStorage]:
    """The active workspace's storage handle, or None if no workspace is open."""
    ctx = st.session_state.get("workspace_context")
    return getattr(ctx, "storage", None) if ctx is not None else None


def upload_file_to_nextcloud(uploaded_file, filename: str = None) -> Tuple[bool, str, str]:
    """Upload a file to the workspace ``timeseries/`` directory.

    Returns (success, filename, error_message). Name kept for call-site stability.
    """
    storage = _ws_storage()
    if storage is None:
        return False, "", "No workspace storage available. Open a workspace first."

    target_filename = filename if filename else uploaded_file.name
    try:
        content = uploaded_file.read()
        if isinstance(content, str):
            content = content.encode("utf-8")
        storage.write_bytes(f"{TIMESERIES_DIR}/{target_filename}", content)
        return True, target_filename, ""
    except Exception as e:
        return False, "", f"Upload error: {str(e)}"


def list_timeseries_files(file_types: Optional[List[str]] = None) -> Tuple[bool, List[str], str]:
    """List files in the workspace ``timeseries/`` directory.

    Optionally filter by extension (e.g. ``['csv', 'json']``).
    Returns (success, sorted_filenames, error_message).
    """
    storage = _ws_storage()
    if storage is None:
        return False, [], "No workspace storage available. Open a workspace first."

    try:
        names = [p.split("/")[-1] for p in storage.glob(f"{TIMESERIES_DIR}/*")]
        if file_types:
            exts = tuple(f".{t.lower().lstrip('.')}" for t in file_types)
            names = [n for n in names if n.lower().endswith(exts)]
        return True, sorted(names), ""
    except Exception as e:
        return False, [], f"Error listing files: {str(e)}"


def render_file_selector(
        label: str = "File Source",
        help_text: str = "Upload a new file or select an existing one",
        file_types: List[str] = None,
        key_prefix: str = "file_selector"
) -> Tuple[str, str]:
    """Render a file selector that uploads or picks an existing timeseries file.

    Returns (mode, filename) where mode is "upload"/"existing"/"manual"/"none".
    """
    st.write(f"**{label}**")
    mode = st.radio(
        "Choose option:",
        options=["Upload new file", "Select existing file", "Enter manually"],
        key=f"{key_prefix}_mode",
        horizontal=True,
        help=help_text
    )

    if mode == "Upload new file":
        uploaded_file = st.file_uploader(
            "Choose file", type=file_types, key=f"{key_prefix}_uploader",
            help="File will be uploaded to the workspace timeseries directory"
        )
        if uploaded_file:
            with st.spinner(f"Uploading {uploaded_file.name}..."):
                success, filename, error = upload_file_to_nextcloud(uploaded_file)
                if success:
                    st.success(f"✓ Uploaded: {filename}")
                    return "upload", filename
                st.error(f"Upload failed: {error}")
                return "none", ""
        return "none", ""

    elif mode == "Select existing file":
        success, files, error = list_timeseries_files(file_types=file_types)
        if not success:
            st.error(f"Could not list files: {error}")
            return "none", ""
        if not files:
            st.info("No files found in timeseries directory. Upload a file first.")
            return "none", ""
        selected_file = st.selectbox("Select file:", options=files, key=f"{key_prefix}_selector")
        if selected_file:
            st.caption(f"✓ Selected: {selected_file}")
            return "existing", selected_file
        return "none", ""

    else:  # Enter manually
        manual_filename = st.text_input(
            "Enter filename:", placeholder="e.g., timeseries_data.csv",
            key=f"{key_prefix}_manual",
            help="Filename that exists or will exist in the workspace timeseries directory"
        )
        if manual_filename:
            return "manual", manual_filename
        return "none", ""


def check_nextcloud_configured() -> bool:
    """True when workspace storage is available (a workspace is open).

    Name kept for call-site stability; no longer NextCloud-specific.
    """
    return _ws_storage() is not None


def show_nextcloud_status():
    """Display workspace storage status and timeseries file count."""
    storage = _ws_storage()
    if storage is None:
        st.warning("⚠ No workspace open — file upload needs an active workspace.")
        return

    st.success("✓ Workspace storage available")
    st.caption(f"**Backend:** {storage.protocol}")
    st.caption(f"**Files location:** `{TIMESERIES_DIR}/`")
    try:
        ok, files, _ = list_timeseries_files()
        if ok:
            st.caption(f"**Files found:** {len(files)}")
    except Exception as e:
        st.caption(f"Could not list timeseries files: {e}")
