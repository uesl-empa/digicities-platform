# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Persisting an emitted scenario TTL — headless halves of the Streamlit
upload buttons (Phase 4b).

The Streamlit shim (``scenario_builder_summary.upload_scenario_to_workspace`` /
``upload_scenario_to_graph``) resolves the storage handle and graph client from
session state and renders st.success/st.error; the mechanics live here so the
REST API and scripts can do the same without a UI.
"""
from __future__ import annotations

from typing import Optional


def save_scenario_to_workspace(storage, ttl_content: str, filename: str) -> str:
    """Write the scenario TTL to the workspace ``scenarios/`` folder via a
    WorkspaceStorage handle (``ctx.storage``). Returns the workspace-relative
    path. Raises whatever the storage backend raises on failure."""
    rel = f"scenarios/{filename}"
    storage.write_text(rel, ttl_content)
    return rel


def push_scenario_to_graph(client, ttl_content: str,
                           graph_name: Optional[str] = None,
                           replace_existing: bool = False) -> tuple[bool, Optional[int], object]:
    """Append the scenario TTL to the ``<scenarios>`` named graph (or an
    explicit ``graph_name``) through the backend-agnostic triplestore client.

    Returns ``(ok, status_code, response)`` — ``ok`` follows the UI's original
    rule: a missing status code or 200/201/204 counts as success.
    """
    from backend.graphdb.graphs import SCENARIOS_GRAPH

    response = client.upload_ttl(
        ttl_str=ttl_content,
        graph_name=graph_name or SCENARIOS_GRAPH,
        replace_existing=replace_existing,
    )
    status = getattr(response, "status_code", None)
    ok = status is None or status in (200, 201, 204)
    return ok, status, response


def remove_scenario_from_graph(client, scenario_uri: str,
                               graph_name: Optional[str] = None) -> None:
    """Remove one scenario's triples from the ``<scenarios>`` named graph.

    The graph accumulates every pushed scenario, so removal must be scoped to
    exactly what this scenario's TTL added: everything marked
    ``usedInScenario <scenario>`` (component re-declarations + ComponentLink
    nodes) and the scenario node itself. Other scenarios' triples — including
    a shared component's marks for them — are untouched. Raises on transport
    failure (callers treat cleanup as best-effort)."""
    import re

    from backend.graphdb.graphs import SCENARIOS_GRAPH

    # The URI is interpolated into a SPARQL update — refuse anything that
    # couldn't be a legal IRI in angle brackets.
    if not re.fullmatch(r"[^<>\"{}|\\^`\s]+", scenario_uri or ""):
        raise ValueError(f"not a usable scenario IRI: {scenario_uri!r}")
    graph = graph_name or SCENARIOS_GRAPH
    statement = f"""
PREFIX dici_onto: <https://digicities.info/ontology#>
DELETE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}
WHERE  {{ GRAPH <{graph}> {{ ?s dici_onto:usedInScenario <{scenario_uri}> . ?s ?p ?o }} }};
DELETE WHERE {{ GRAPH <{graph}> {{ <{scenario_uri}> ?p ?o }} }}
"""
    client.sparql_update(statement)


__all__ = ["save_scenario_to_workspace", "push_scenario_to_graph", "remove_scenario_from_graph"]
