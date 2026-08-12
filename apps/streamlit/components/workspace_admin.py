# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/workspace_admin.py

"""Destructive workspace actions for the landing page: clear the contents of a
workspace, or delete it outright.

Both wrap `backend.workspace` and both are irreversible, so both require the
workspace id to be typed back before the button does anything. Bundled demo
workspaces are refused here and again in the backend.

Kept in its own component because two different workspace listings render it.
"""
from __future__ import annotations

import streamlit as st


def _registry_context(workspace_id: str):
    try:
        from backend.workspace import load_registry
        return load_registry().by_id(workspace_id)
    except Exception:
        return None


def _is_open_workspace(ws_id: str) -> bool:
    current = st.session_state.get("current_workspace")
    if isinstance(current, dict):
        return current.get("id") == ws_id
    return current == ws_id


def _close_workspace_if_open(ws_id: str) -> None:
    """Drop the session's handle on a workspace we just emptied or removed, so the
    app can't keep querying a dataset that no longer holds what it expects."""
    if _is_open_workspace(ws_id):
        for key in ("current_workspace", "workspace_client", "workspace_context"):
            st.session_state.pop(key, None)


def manage_toggle_key(ws_id: str) -> str:
    return f"show_manage_{ws_id}"


def render_manage_button(ws_id: str, *, key_prefix: str = "", label: str = "⚙️ Manage") -> None:
    """A toggle, not a transient render: the panel holds forms whose own buttons
    trigger a rerun, and a panel rendered straight from the click would disappear
    on that rerun before it could be used."""
    key = manage_toggle_key(ws_id)
    if st.button(label, key=f"{key_prefix}manage_{ws_id}", use_container_width=True):
        st.session_state[key] = not st.session_state.get(key, False)


def render_danger_zone(workspace: dict, *, is_demo: bool = False) -> None:
    """Clear-contents and delete controls for one workspace."""
    ws_id = workspace["id"]
    is_demo = is_demo or "demo" in (workspace.get("tags") or [])

    with st.expander(f"⚙️ Manage `{ws_id}`", expanded=True):
        if is_demo:
            st.caption(
                "This is a bundled demo workspace that ships with the platform, so it "
                "can't be cleared or deleted. Create your own workspace to experiment in."
            )
            return

        st.markdown("#### ⚠️ Danger zone")
        st.caption("Both actions are irreversible. Type the workspace id to enable them.")

        clear_col, delete_col = st.columns(2)

        with clear_col:
            st.markdown("**🧹 Clear contents**")
            st.caption(
                "Deletes every file in the workspace (ontology extensions, replica, "
                "scenarios, services, queries, data products) and empties its triplestore, "
                "then reloads the core ontology. The workspace itself stays, ready to reuse."
            )
            typed = st.text_input(f"Type `{ws_id}` to confirm", key=f"clear_confirm_{ws_id}",
                                  placeholder=ws_id)
            if st.button("🧹 Clear this workspace", key=f"do_clear_{ws_id}",
                         disabled=typed.strip() != ws_id, use_container_width=True):
                _do_clear(ws_id)

        with delete_col:
            st.markdown("**🗑️ Delete workspace**")
            st.caption(
                "Removes the workspace folder, drops its triplestore dataset and "
                "unregisters it. This cannot be undone."
            )
            typed_d = st.text_input(f"Type `{ws_id}` to confirm ", key=f"delete_confirm_{ws_id}",
                                    placeholder=ws_id)
            keep = st.checkbox("Keep the triplestore dataset", key=f"keep_ds_{ws_id}", value=False)
            if st.button("🗑️ Delete permanently", key=f"do_delete_{ws_id}",
                         disabled=typed_d.strip() != ws_id, use_container_width=True,
                         type="primary"):
                _do_delete(ws_id, drop_dataset=not keep)


def _do_clear(ws_id: str) -> None:
    from backend.workspace import WorkspaceProtected, clear_workspace
    ctx = _registry_context(ws_id)
    if ctx is None:
        st.error(f"Couldn't resolve workspace '{ws_id}' — nothing was changed.")
        return
    try:
        with st.spinner(f"Clearing {ws_id}…"):
            result = clear_workspace(ctx)
    except WorkspaceProtected as exc:
        st.warning(str(exc))
        return
    except Exception as exc:
        st.error(f"Clearing '{ws_id}' failed: {exc}")
        return

    if not result["graphs_cleared"]:
        st.warning(
            f"Removed {result['files_deleted']} file(s), but the triplestore didn't "
            "confirm the clear — check the dataset before reusing this workspace."
        )
        return
    _close_workspace_if_open(ws_id)
    st.session_state[manage_toggle_key(ws_id)] = False
    st.success(
        f"✅ Cleared `{ws_id}`: {result['files_deleted']} file(s) removed and the graph emptied"
        + (", core ontology reloaded." if result["core_reloaded"] else ".")
    )
    _refresh_and_rerun()


def _do_delete(ws_id: str, drop_dataset: bool = True) -> None:
    from backend.workspace import WorkspaceProtected, delete_workspace
    try:
        with st.spinner(f"Deleting {ws_id}…"):
            result = delete_workspace(ws_id, drop_dataset=drop_dataset)
    except WorkspaceProtected as exc:
        st.warning(str(exc))
        return
    except Exception as exc:
        st.error(f"Deleting '{ws_id}' failed: {exc}")
        return

    if not result["files_removed"]:
        st.error(
            f"Couldn't remove the folder for '{ws_id}' — nothing else was changed. "
            "It may be open in another program."
        )
        return
    _close_workspace_if_open(ws_id)
    st.session_state.pop(manage_toggle_key(ws_id), None)
    note = " (triplestore dataset kept)" if not drop_dataset else ""
    st.success(f"🗑️ Deleted workspace `{ws_id}`{note}.")
    _refresh_and_rerun()


def _refresh_and_rerun() -> None:
    """The landing page lists workspaces from a cached registry read, so the list
    has to be rebuilt or a deleted workspace lingers until the next restart."""
    try:
        st.cache_data.clear()
    except Exception:
        pass
    st.rerun()
