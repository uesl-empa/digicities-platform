# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Streamlit shell for the GraphDB client.

The client logic lives in ``backend.graphdb``. This module adds the
Streamlit-specific bits: a Keycloak-aware token refresher, an error hook
that surfaces failures via ``st.error``/retry buttons, and the
session-state caching helper ``get_or_refresh_graphdb_client``.
"""

from typing import Optional

import streamlit as st

from backend.graphdb.client import (
    GraphDBClient as _BaseGraphDBClient,
    Transaction,
    UnifiedGraphDBClient as _BaseUnifiedGraphDBClient,
)
from backend.graphdb.utils import (
    df_from_json,
    dict_from_json,
    save_debug_report,
    split_graph,
)

__all__ = [
    "GraphDBClient",
    "Transaction",
    "UnifiedGraphDBClient",
    "df_from_json",
    "dict_from_json",
    "get_or_refresh_graphdb_client",
    "save_debug_report",
    "split_graph",
]


def _streamlit_token_refresher() -> Optional[str]:
    """Refresh the Keycloak access token and pull the new one from session_state."""
    try:
        from components.auth import refresh_access_token
    except Exception as e:
        print(f"DEBUG [GraphDB]: could not import refresh_access_token: {e}")
        refresh_access_token = None

    if refresh_access_token is not None:
        try:
            if refresh_access_token():
                token = getattr(st.session_state, "access_token", None)
                if token:
                    return token
        except Exception as e:
            print(f"DEBUG [GraphDB]: refresh_access_token raised: {e}")

    # Fallback: whatever is currently in session state
    return getattr(st.session_state, "access_token", None)


class _StreamlitErrorUIMixin:
    """Surface query-failure errors via Streamlit widgets."""

    def _on_query_error(self, message: str, query: str) -> None:
        try:
            st.error(f"❌ Database query failed. {message}")
            col1, col2, _ = st.columns([1, 1, 2])
            with col1:
                if st.button("🔄 Retry Query", key=f"retry_{hash(query)}"):
                    st.rerun()
            with col2:
                if st.button("🔧 Reset Connection", key=f"reset_{hash(query)}"):
                    self._create_session()
                    st.success("Connection reset. Please try again.")
                    st.rerun()
        except Exception as e:
            print(f"DEBUG [GraphDB]: could not render Streamlit error UI: {e}")


class UnifiedGraphDBClient(_StreamlitErrorUIMixin, _BaseUnifiedGraphDBClient):
    """Streamlit-aware ``UnifiedGraphDBClient`` with UI error reporting."""

    def __init__(self, *args, token_refresher=None, **kwargs):
        if token_refresher is None:
            token_refresher = _streamlit_token_refresher
        super().__init__(*args, token_refresher=token_refresher, **kwargs)


class GraphDBClient(_StreamlitErrorUIMixin, _BaseGraphDBClient):
    """Streamlit-aware ``GraphDBClient`` with UI error reporting."""

    def __init__(self, *args, token_refresher=None, **kwargs):
        if token_refresher is None:
            token_refresher = _streamlit_token_refresher
        super().__init__(*args, token_refresher=token_refresher, **kwargs)


def get_or_refresh_graphdb_client(workspace_id: str) -> Optional[GraphDBClient]:
    """Get an existing GraphDB client from session state, or create one with a fresh token."""
    access_token = st.session_state.get("access_token")
    if not access_token:
        st.error("🔒 No access token available. Please log in again.")
        return None

    current_client = st.session_state.get("workspace_client")
    if (current_client is None
            or current_client.token != access_token
            or current_client.selected_repo != workspace_id):

        client = GraphDBClient(
            token=access_token,
            selected_repo=workspace_id,
        )

        if client.test_connection():
            st.session_state.workspace_client = client
            return client
        else:
            st.error("❌ Failed to connect to Triplestore. Please check your connection.")
            return None

    return current_client
