# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_graph_uploader.py
"""
Graph Uploader for Replica Builder
Uploads TTL content to named graphs via the backend-agnostic client
(works against GraphDB and Fuseki — see backend/triplestore/).
"""
import streamlit as st
from typing import Optional

# Workspace-relative file that mirrors the replica's instances into the
# canonical `ingestion/output/` folder. Workspace provisioning rebuilds
# <classes_and_attributes> from `ingestion/output/*.ttl` (PUT/replace) on every
# workspace open, so instances uploaded only to the live graph would be wiped on
# reopen. Persisting them here makes them survive the round-trip.
WORKSPACE_INSTANCE_FILE = "ingestion/output/replica_builder_instances.ttl"


def persist_instances_to_workspace(classes_ttl: str, mode: str) -> Optional[str]:
    """Mirror the replica's instance TTL into the workspace `ingestion/output/`
    folder via ctx.storage, so provisioning restores it on the next workspace
    open. Returns the saved workspace-relative path, or None if there is no
    active workspace storage.

    'replace' overwrites the replica-builder output file; 'append' merges it with
    whatever is already there (rdflib set-union, so re-uploads don't duplicate).
    """
    ctx = st.session_state.get("workspace_context")
    storage = getattr(ctx, "storage", None) if ctx is not None else None
    if storage is None:
        return None

    out_ttl = classes_ttl
    try:
        if mode == "append" and storage.exists(WORKSPACE_INSTANCE_FILE):
            import rdflib
            g = rdflib.Graph()
            g.parse(data=storage.read_text(WORKSPACE_INSTANCE_FILE), format="turtle")
            g.parse(data=classes_ttl, format="turtle")
            out_ttl = g.serialize(format="turtle")
        storage.write_text(WORKSPACE_INSTANCE_FILE, out_ttl)
        return WORKSPACE_INSTANCE_FILE
    except Exception as e:
        st.warning(
            "Uploaded to the graph, but could not save the instances to the "
            f"workspace — they may not survive a workspace reopen: {e}"
        )
        return None


def upload_graphs(client, classes_ttl: str, system_ttl: Optional[str], mode: str) -> bool:
    """
    Upload TTL content to the replica named graphs.

    Args:
        client: GraphDB/Fuseki client (UnifiedGraphDBClient)
        classes_ttl: TTL content for classes_and_attributes
        system_ttl: TTL content for system_description (optional)
        mode: 'append' or 'replace'

    Returns:
        True if successful, False otherwise
    """

    if not client:
        st.error("No triplestore client available")
        return False

    try:
        # Upload classes_and_attributes graph
        classes_success = upload_to_named_graph(
            client,
            "http://classes_and_attributes",
            classes_ttl,
            mode
        )

        if not classes_success:
            st.error("Failed to upload classes_and_attributes graph")
            return False

        st.success("✅ Uploaded classes_and_attributes graph")

        # Upload system_description graph if provided
        if system_ttl:
            system_success = upload_to_named_graph(
                client,
                "http://system_description",
                system_ttl,
                mode
            )

            if not system_success:
                st.error("Failed to upload system_description graph")
                return False

            st.success("✅ Uploaded system_description graph")

        return True

    except Exception as e:
        st.error(f"Upload error: {e}")
        return False


def upload_to_named_graph(client, graph_uri: str, ttl_content: str, mode: str) -> bool:
    """
    Upload TTL content to a specific named graph through the client's
    backend-aware Graph Store endpoint.

    'replace' uses an HTTP PUT, which replaces the whole named graph;
    'append' uses POST, which merges into the existing graph. Both URL and
    auth are resolved per active backend (GraphDB ?context= / Fuseki ?graph=),
    so this works without hand-building GraphDB-only URLs.

    Args:
        client: GraphDB/Fuseki client
        graph_uri: bare IRI of the named graph (e.g. "http://classes_and_attributes")
        ttl_content: TTL content to upload
        mode: 'append' or 'replace'

    Returns:
        True if successful, False otherwise
    """

    try:
        response = client.upload_ttl(
            ttl_str=ttl_content,
            graph_name=graph_uri.strip("<>"),
            replace_existing=(mode == "replace"),
        )

        status = getattr(response, "status_code", None)
        if status is None or status in (200, 201, 204):
            return True

        st.error(f"Upload failed with status {status}: {getattr(response, 'text', '')}")
        return False

    except Exception as e:
        st.error(f"Error uploading to {graph_uri}: {e}")
        return False
