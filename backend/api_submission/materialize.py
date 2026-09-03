# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Materialize a scenario against the workspace before conversion.

A thin scenario references canonical replica components (usedInScenario +
ComponentLink chains) without carrying their attribute values — the values
live in the replica (ingestion/output) and, for projected aggregates, in the
derived collections graph. The converter reads a single TTL document, so a
thin scenario must be merged with the replica first; Streamlit's Convert tab
and the onboarding agent both did this in their own layers. This is that
step behind the backend seam, so the REST convert sees the same full picture.
"""
from __future__ import annotations

from typing import Optional


def materialize_against_workspace(storage, scenario_text: str, client=None) -> str:
    """Merge a scenario with the workspace replica into a self-contained TTL.

    Returns the original text on any problem (not a scenario, no replica to
    merge, parse failure) — materialization must never make conversion worse.
    When a graph client is given, the derived collections graph is merged in
    too, so projected aggregate attributes ride along.
    """
    try:
        from rdflib import Graph
        from rdflib.namespace import RDF

        from backend.graphdb.queries.scenarios import _DICI, materialize_scenario_graphs

        scn = Graph()
        scn.parse(data=scenario_text, format="turtle")
        scenarios = list(scn.subjects(RDF.type, _DICI.Scenario))
        if not scenarios:
            return scenario_text

        rep = Graph()
        try:
            if storage is not None and storage.exists("ingestion/output"):
                for rel in storage.glob("ingestion/output/*.ttl"):
                    try:
                        rep.parse(data=storage.read_text(rel), format="turtle")
                    except Exception:
                        pass
        except Exception:
            pass

        # Derived collections (projected aggregates) live only in the graph —
        # fetch the named graph via the graph-store endpoint (typed Turtle,
        # same channel provisioning writes through).
        try:
            if client is not None and getattr(client, "repository", None):
                import requests

                from backend.graphdb.graphs import COLLECTIONS_GRAPH
                from backend.triplestore import get_backend

                backend = get_backend()
                r = requests.get(
                    backend.graph_store_url(client.repository, COLLECTIONS_GRAPH),
                    headers={"Accept": "text/turtle"},
                    auth=getattr(backend, "auth", None), timeout=30)
                if r.status_code == 200 and r.text.strip():
                    rep.parse(data=r.text, format="turtle")
        except Exception:
            pass                      # collections are optional enrichment

        materialized: Optional[str] = materialize_scenario_graphs(scn, rep, str(scenarios[0]))
        return materialized or scenario_text
    except Exception:
        return scenario_text


__all__ = ["materialize_against_workspace"]
