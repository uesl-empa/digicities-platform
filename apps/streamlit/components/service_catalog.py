# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: the service catalog moved to ``backend.service_catalog``.

The one Streamlit-specific bit stays here: registering the session-state
workspace storage as the backend's default, so no-arg calls like
``list_workspace_services()`` keep reading the active workspace.
"""

import streamlit as st

import backend.service_catalog as _backend
from backend.service_catalog import (  # noqa: F401
    ServiceRef,
    list_global_services,
    list_services,
    list_workspace_services,
    read_service_text,
    services_by_name,
    set_storage_provider,
)


def _session_storage():
    """The active workspace's storage handle, from Streamlit session state."""
    ctx = st.session_state.get("workspace_context")
    return getattr(ctx, "storage", None) if ctx is not None else None


_backend.set_storage_provider(_session_storage)
