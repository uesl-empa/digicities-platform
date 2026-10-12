# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The open workspace's ontology extension, for the Scenario Builder's class
questions: a requirement on a class applies to its subclasses, and the
workspace's own classes sit under core in its extension."""
from __future__ import annotations

import streamlit as st

from backend.api_submission.materialize import workspace_schema


def session_workspace_schema():
    """The extension of the workspace open in this session, or None (core
    hierarchy only) with a visible warning when it cannot be read."""
    ctx = st.session_state.get("workspace_context")
    storage = getattr(ctx, "storage", None) if ctx is not None else None
    skipped: list = []
    schema = workspace_schema(storage, skipped=skipped)
    for e in skipped:
        st.warning(f"⚠️ {e['file']}: {e['error']}. Only the core class hierarchy is used "
                   f"to match requirements to component classes.")
    return schema
