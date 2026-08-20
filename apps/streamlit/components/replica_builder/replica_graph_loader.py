# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_graph_loader.py
"""
Graph Loader for Replica Builder — UI shell over the backend load-back.

The rdflib parse-back moved to ``backend/replica_builder/graph_loader.py``
(Phase 5 of the backend/UI split). What stays here is the Streamlit wiring:
``load_existing_graphs`` orchestrating the load into session state with its
st.success/st.error reporting, the status expander, and session-state adapters
with the old signatures (``parse_links_from_graph(graph)`` resolves against
the session's instances, as before).
"""
import streamlit as st
from typing import Optional, Dict, List, Any
from rdflib import Graph

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
)
from backend.graphdb.queries import graph_io
from backend.graphdb.queries import components as components_q

from backend.replica_builder import graph_loader as _loader

# Pure parse functions, re-exported verbatim from the backend (same objects).
from backend.replica_builder.graph_loader import (  # noqa: F401
    DICI,
    parse_instances_from_graph,
    parse_attributes_from_graph,
    parse_single_attribute,
    convert_to_replica_instances,
    _local_name,
    _kind_map,
)


def load_existing_graphs(client, populate_instances=False) -> bool:
    """Load existing graphs from GraphDB and optionally populate instances"""
    if not client:
        return False

    try:
        # Load classes_and_attributes graph
        classes_graph = load_classes_and_attributes_graph(client)
        if classes_graph:
            st.session_state.replica_existing_classes_graph = classes_graph

            # Optionally populate instances from the loaded graph
            if populate_instances:
                # Discover instances, their leaf component type, and their
                # attribute nodes with SPARQL over the ontology hierarchy
                # (rdfs:subClassOf* / rdfs:subPropertyOf*). The constructed graph
                # below is used only to read literal values off those nodes.
                discovered = components_q.get_all_component_instances(client)
                attr_links = components_q.get_all_instance_attribute_links(client)
                attr_kinds = components_q.get_attribute_kinds(client)
                instances = parse_instances_from_graph(classes_graph, discovered)
                attributes = parse_attributes_from_graph(classes_graph, attr_links, attr_kinds)

                # Convert to replica builder format (must be done before links!)
                st.session_state.replica_instances = convert_to_replica_instances(instances, attributes)
                st.success(f"✅ Loaded {len(st.session_state.replica_instances)} instances from classes_and_attributes graph")

        # Load system_description graph
        system_graph = load_system_description_graph(client)
        if system_graph:
            st.session_state.replica_existing_system_graph = system_graph

            # Optionally populate links from the loaded graph (must be AFTER instances!)
            if populate_instances and st.session_state.replica_instances:
                links = parse_links_from_graph(system_graph)
                st.session_state.replica_links = links
                if links:
                    st.success(f"✅ Loaded {len(st.session_state.replica_links)} links from system_description graph")
                else:
                    st.info("ℹ️ No links found in system_description graph")

        return True

    except Exception as e:
        st.error(f"Failed to load existing graphs: {e}")
        import traceback
        st.error(traceback.format_exc())
        return False


def load_classes_and_attributes_graph(client) -> Optional[Graph]:
    """Load the classes_and_attributes named graph (via backend.graphdb.queries.graph_io)."""
    graph = graph_io.construct_named_graph(client, CLASSES_AND_ATTRIBUTES_GRAPH)
    if graph is None:
        st.warning("Could not load classes_and_attributes graph")
    return graph


def load_system_description_graph(client) -> Optional[Graph]:
    """Load the system_description named graph (via backend.graphdb.queries.graph_io)."""
    graph = graph_io.construct_named_graph(client, SYSTEM_DESCRIPTION_GRAPH)
    if graph is None:
        st.warning("Could not load system_description graph")
    return graph


def parse_links_from_graph(graph: Graph) -> List[Dict[str, Any]]:
    """Parse links from system_description graph (against session instances)."""
    return _loader.parse_links_from_graph(graph, st.session_state.replica_instances)


def show_existing_graphs_status(client):
    """Display status of existing graphs"""

    with st.expander("Existing Graphs in Triplestore", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📥 Load Graphs", type="secondary", use_container_width=True):
                with st.spinner("Loading graphs from Triplestore..."):
                    if load_existing_graphs(client, populate_instances=False):
                        st.success("✅ Graphs loaded successfully")
                        st.rerun()

        with col2:
            # Show populate button only if graphs are loaded
            if st.session_state.replica_existing_classes_graph:
                if st.button("📋 Populate Instances", type="primary", use_container_width=True):
                    with st.spinner("Populating instances from graphs..."):
                        if load_existing_graphs(client, populate_instances=True):
                            st.rerun()

        with col3:
            if st.session_state.replica_existing_classes_graph or st.session_state.replica_existing_system_graph:
                if st.button("🗑️ Clear", use_container_width=True):
                    st.session_state.replica_existing_classes_graph = None
                    st.session_state.replica_existing_system_graph = None
                    st.session_state.replica_instances = []
                    st.session_state.replica_links = []
                    st.rerun()

        st.markdown("---")

        # Show status
        if st.session_state.replica_existing_classes_graph:
            classes_graph = st.session_state.replica_existing_classes_graph
            triple_count = len(classes_graph)
            discovered = components_q.get_all_component_instances(client)
            instance_count = 0 if discovered is None else len(discovered)

            st.success(f"**classes_and_attributes**: {triple_count} triples, {instance_count} instances found")

            # Show if instances have been populated
            if st.session_state.replica_instances:
                st.info(f"📋 {len(st.session_state.replica_instances)} instances loaded into replica builder")
        else:
            st.info("**classes_and_attributes**: Not loaded")

        if st.session_state.replica_existing_system_graph:
            system_graph = st.session_state.replica_existing_system_graph
            triple_count = len(system_graph)
            links = parse_links_from_graph(system_graph)

            st.success(f"**system_description**: {triple_count} triples, {len(links)} links found")

            # Show if links have been populated
            if st.session_state.replica_links:
                st.info(f"🔗 {len(st.session_state.replica_links)} links loaded into replica builder")
        else:
            st.info("**system_description**: Not loaded")

        # Help text
        st.markdown("---")
        st.caption("**ℹ️ How to use:**")
        st.caption("""
        **1. Load Graphs** → Fetch existing data from Triplestore
        **2. Populate Instances** → Import data into replica builder
        **3. Clear** → Remove loaded graphs and instances
        """)
