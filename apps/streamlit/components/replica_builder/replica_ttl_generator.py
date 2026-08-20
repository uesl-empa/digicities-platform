# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_ttl_generator.py
"""
TTL Generator for Replica Builder — UI shell over the backend generators.

The generators moved to ``backend/replica_builder/ttl.py`` (Phase 5 of the
backend/UI split) and take the model explicitly. What stays here is the
Streamlit wiring: the Preview & Export tab and session-state adapters with the
old signatures (``generate_classes_and_attributes_ttl()`` defaulting to the
session's instances, ``generate_system_description_ttl()`` reading the
session's links). Output is unchanged.
"""
import streamlit as st
from typing import Dict, List, Any, Optional

from backend.replica_builder import ttl as _ttl

# Pure helpers + validators, re-exported verbatim from the backend (same objects).
from backend.replica_builder.ttl import (  # noqa: F401
    format_decimal,
    escape_ttl_string,
    process_curve_data_string,
    generate_attribute_ttl,
    generate_instance_ttl,
    validate_ttl,
)


def generate_classes_and_attributes_ttl(instances=None) -> str:
    """Generate TTL for the classes_and_attributes graph.

    ``instances`` defaults to the whole replica (``st.session_state.replica_instances``);
    pass a subset (e.g. one component type's instances) to export just that slice.
    """
    if instances is None:
        instances = st.session_state.replica_instances
    return _ttl.generate_classes_and_attributes_ttl(instances)


def generate_system_description_ttl() -> str:
    """Generate TTL for system_description graph (from session links)."""
    return _ttl.generate_system_description_ttl(st.session_state.replica_links)


def tab_preview_and_export(client):
    """Tab for previewing and exporting TTL"""
    st.subheader("Preview & Export")

    if not st.session_state.replica_instances:
        st.info("Create instances first to generate TTL")
        return

    # Generate TTL
    classes_ttl = generate_classes_and_attributes_ttl()
    system_ttl = generate_system_description_ttl() if st.session_state.replica_links else None

    # Preview section
    st.write("### Preview Generated TTL")

    tab1, tab2 = st.tabs(["classes_and_attributes", "system_description"])

    with tab1:
        st.write(f"**Instances:** {len(st.session_state.replica_instances)}")

        # Validate
        is_valid, error = validate_ttl(classes_ttl)
        if is_valid:
            st.success("Valid TTL syntax")
        else:
            st.error(f"Invalid TTL: {error}")

        st.code(classes_ttl, language="turtle")

        # Download button
        st.download_button(
            "Download classes_and_attributes.ttl",
            data=classes_ttl,
            file_name="classes_and_attributes.ttl",
            mime="text/turtle"
        )

    with tab2:
        if system_ttl:
            st.write(f"**Links:** {len(st.session_state.replica_links)}")

            # Validate
            is_valid, error = validate_ttl(system_ttl)
            if is_valid:
                st.success("Valid TTL syntax")
            else:
                st.error(f"Invalid TTL: {error}")

            st.code(system_ttl, language="turtle")

            # Download button
            st.download_button(
                "Download system_description.ttl",
                data=system_ttl,
                file_name="system_description.ttl",
                mime="text/turtle"
            )
        else:
            st.info("No links created yet")

    st.write("---")

    # Upload section
    st.write("### Upload to Triplestore")

    _mode_labels = {
        "append": "Append to existing graphs",
        "replace": "Replace existing graphs",
    }
    selected_label = st.radio(
        "Upload mode",
        options=list(_mode_labels.values()),
        index=0 if st.session_state.replica_graph_mode == "append" else 1,
        help=(
            "**Append** merges into the existing named graphs. "
            "**Replace** overwrites each named graph with the current replica."
        ),
        key="replica_graph_mode_radio",
    )
    st.session_state.replica_graph_mode = next(
        m for m, label in _mode_labels.items() if label == selected_label
    )

    # Upload button
    if st.button("Upload to Triplestore", type="primary", use_container_width=True):
        from components.replica_builder.replica_graph_uploader import (
            upload_graphs,
            persist_instances_to_workspace,
        )

        with st.spinner("Uploading graphs to Triplestore..."):
            mode = st.session_state.replica_graph_mode
            success = upload_graphs(client, classes_ttl, system_ttl, mode)

            if success:
                # Mirror the instances into the workspace so they survive a
                # workspace reopen (provisioning rebuilds <classes_and_attributes>
                # from ingestion/output/*.ttl, replacing whatever the upload put
                # in the live graph).
                saved_path = persist_instances_to_workspace(classes_ttl, mode)
                st.success("Graphs uploaded successfully!")
                if saved_path:
                    st.caption(f"Saved to workspace `{saved_path}` so it persists across reopen.")
                st.balloons()
            else:
                st.error("Upload failed")