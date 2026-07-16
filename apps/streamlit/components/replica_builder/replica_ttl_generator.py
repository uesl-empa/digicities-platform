# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_ttl_generator.py
"""
TTL Generator for Replica Builder
Generates TTL content for both graphs
FIXED: Proper semicolon handling in instance declarations
"""
import streamlit as st
from typing import Dict, List, Any, Optional
from backend.replica_builder.utils.ttl_attribute_helpers import (
    format_decimal,
    escape_ttl_string,
    process_curve_data_string,
    generate_attribute_ttl,
)


def generate_classes_and_attributes_ttl(instances=None) -> str:
    """Generate TTL for the classes_and_attributes graph.

    ``instances`` defaults to the whole replica (``st.session_state.replica_instances``);
    pass a subset (e.g. one component type's instances) to export just that slice.
    """

    if instances is None:
        instances = st.session_state.replica_instances

    lines = []

    # Add prefixes
    lines.extend([
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix cur: <http://qudt.org/vocab/currency/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        ""
    ])

    # Process each instance
    for instance in instances:
        instance_lines = generate_instance_ttl(instance)
        lines.extend(instance_lines)
        lines.append("")

    return "\n".join(lines)


def generate_instance_ttl(instance) -> List[str]:
    """Generate TTL for a single instance - FIXED semicolon handling"""
    lines = []

    # Instance declaration with proper semicolons
    lines.append(f"<{instance.uri}> a dici_onto:{instance.component_type} ;")

    # Add annotations (rdfs properties)
    if instance.annotations:
        for key, value in instance.annotations.items():
            escaped_value = escape_ttl_string(value)
            lines.append(f'\trdfs:{key} "{escaped_value}" ;')

    # Add class object relationships (direct predicates)
    if hasattr(instance, 'class_objects') and instance.class_objects:
        for predicate, target_uri in instance.class_objects.items():
            lines.append(f'\tdici_onto:{predicate} <{target_uri}> ;')

    # Add label
    lines.append(f'\trdfs:label "{escape_ttl_string(instance.label)}"')

    # Collect attribute URIs
    attribute_uris = []
    attribute_declarations = []

    for attr_name, attr_data in instance.attributes.items():
        attr_uri = f"{instance.uri}/{attr_name}"
        attribute_uris.append(f"<{attr_uri}>")

        # Generate attribute declaration
        attr_lines = generate_attribute_ttl(attr_uri, attr_name, attr_data, instance.component_type)
        attribute_declarations.extend(attr_lines)

    # Add hasAttribute predicates
    if attribute_uris:
        lines.append(f' ;\n\tdici_onto:hasAttribute {", ".join(attribute_uris)}')

    # Close instance declaration with period
    lines[-1] = lines[-1] + " ."

    # Add specific attribute predicates
    if attribute_uris:
        lines.append("")
        for attr_name, attr_uri_str in zip(instance.attributes.keys(), attribute_uris):
            lines.append(f"<{instance.uri}> dici_onto:has{instance.component_type}{attr_name}Attribute {attr_uri_str} .")

    # Add attribute declarations
    if attribute_declarations:
        lines.append("")
        lines.extend(attribute_declarations)

    return lines


def generate_system_description_ttl() -> str:
    """Generate TTL for system_description graph"""

    lines = []

    # Add prefixes
    lines.extend([
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        ""
    ])

    # Process each link
    for link in st.session_state.replica_links:
        lines.append(f"<{link['source_uri']}> dici_onto:{link['property']} <{link['target_uri']}> .")

    return "\n".join(lines)


def validate_ttl(ttl_content: str) -> tuple:
    """Validate TTL syntax"""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=ttl_content, format="turtle")
        return True, None
    except Exception as e:
        return False, str(e)


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