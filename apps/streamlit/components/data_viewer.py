# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Storage-agnostic Data Viewer and Uploader.

Browses, previews, uploads and downloads files in the active workspace using
the WorkspaceStorage abstraction (backend/workspace/storage.py). Because that
abstraction is backend-agnostic, this module works identically over a local
filesystem workspace, a NextCloud/WebDAV workspace, or any fsspec backend.

It replaces the NextCloud-only `nextcloud_module` for the "Data Viewer and
Uploader" tab, which errored with "Nextcloud not configured" in local mode
even though the workspace files were sitting right there on disk.
"""

from __future__ import annotations

import io
import os
from typing import List, Optional

import pandas as pd
import streamlit as st


# Canonical workspace subfolders worth browsing/uploading into. Mirrors the
# layout in backend/workspace/storage.py (CANONICAL_SUBDIRS).
BROWSABLE_DIRS = [
    "ingestion/input",
    "ingestion/output",
    "ontology/extensions",
    "ontology/exports",
    "private_data_products",
    "timeseries",
    "scenarios",
    "services",
    "queries",
    "docs",
]

_TEXT_EXTS = (".ttl", ".rq", ".sparql", ".md", ".txt", ".json", ".yaml", ".yml", ".csv")


def _active_storage():
    """Return (ctx, storage) for the open workspace, or (None, None)."""
    ctx = st.session_state.get("workspace_context")
    if ctx is None or getattr(ctx, "storage", None) is None:
        return None, None
    return ctx, ctx.storage


def data_viewer_and_uploader(workspace: Optional[dict] = None) -> None:
    """Entry point for the Data Viewer and Uploader tab."""
    st.header("📂 Data Viewer and Uploader")

    ctx, storage = _active_storage()
    if storage is None:
        st.error("❌ No active workspace storage. Open a workspace first.")
        return

    st.caption(f"Workspace: **{ctx.name}**  ·  storage backend: `{storage.protocol}`")

    browse_tab, upload_tab = st.tabs(["Browse & preview", "Upload"])
    with browse_tab:
        _browse(storage)
    with upload_tab:
        _upload(storage)


def _list_files(storage, rel_dir: str) -> List[str]:
    """Workspace-relative paths of files (not dirs) directly under rel_dir."""
    try:
        if not storage.exists(rel_dir):
            return []
        out = []
        for entry in storage.glob(f"{rel_dir}/*"):
            try:
                if storage.isdir(entry):
                    continue
            except Exception:
                pass
            # Skip placeholder files that exist only to keep empty dirs in git.
            if os.path.basename(entry) == ".gitkeep":
                continue
            out.append(entry)
        return sorted(out)
    except Exception as exc:
        st.warning(f"Could not list `{rel_dir}`: {exc}")
        return []


def _browse(storage) -> None:
    folder = st.selectbox("Folder", BROWSABLE_DIRS, key="dv_browse_folder")
    files = _list_files(storage, folder)
    if not files:
        st.info(f"No files in `{folder}` yet. Use the Upload tab to add some.")
        return

    st.write(f"**{len(files)}** file(s) in `{folder}`:")
    rel = st.selectbox(
        "File", files, key="dv_browse_file",
        format_func=os.path.basename,
    )
    if not rel:
        return

    try:
        data = storage.read_bytes(rel)
    except Exception as exc:
        st.error(f"Could not read `{rel}`: {exc}")
        return

    st.caption(f"`{rel}` · {len(data):,} bytes")
    _preview(rel, data)
    st.download_button(
        "⬇️ Download", data=data,
        file_name=os.path.basename(rel),
        key="dv_browse_download",
    )


def _preview(rel: str, data: bytes) -> None:
    name = rel.lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(data))
            st.dataframe(df.head(200), use_container_width=True)
            st.caption(f"{len(df):,} rows × {len(df.columns)} columns (showing first 200)")
        elif name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(data))
            st.dataframe(df.head(200), use_container_width=True)
            st.caption(f"{len(df):,} rows × {len(df.columns)} columns (showing first 200)")
        elif name.endswith(_TEXT_EXTS):
            text = data.decode("utf-8", errors="replace")
            lang = "turtle" if name.endswith(".ttl") else (
                "sparql" if name.endswith((".rq", ".sparql")) else None)
            st.code(text[:20000], language=lang)
            if len(text) > 20000:
                st.caption("(truncated to first 20,000 characters — download for the full file)")
        else:
            st.info("No inline preview for this file type. Use Download.")
    except Exception as exc:
        st.warning(f"Preview failed ({exc}). Use Download for the raw file.")


def _upload(storage) -> None:
    folder = st.selectbox("Destination folder", BROWSABLE_DIRS, key="dv_upload_folder")
    uploaded = st.file_uploader(
        "Select one or more files to upload to the workspace",
        accept_multiple_files=True,
        key="dv_upload_files",
    )
    if not uploaded:
        return
    if st.button(f"Upload {len(uploaded)} file(s) to `{folder}`", key="dv_upload_btn"):
        ok, fail = 0, 0
        for f in uploaded:
            rel = f"{folder}/{f.name}"
            try:
                storage.write_bytes(rel, f.getvalue())
                st.success(f"✅ Uploaded `{rel}`")
                ok += 1
            except Exception as exc:
                st.error(f"❌ `{f.name}`: upload failed — {exc}")
                fail += 1
        st.caption(f"{ok} uploaded, {fail} failed.")
