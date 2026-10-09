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


def workspace_schema(storage, *, skipped: Optional[list] = None):
    """The workspace's ontology extension as one rdflib graph (its classes and
    properties under the core hierarchy), for the "what is this" questions the
    materializer and the converter ask. None when there is no storage or the
    extension cannot be read; the reason is printed and, when a list is passed
    as ``skipped``, appended to it as ``{"file": ..., "error": ...}``, so the
    caller can say that only the core hierarchy was used."""
    if storage is None:
        return None
    from backend.scenario_builder.graph_lookups import workspace_extensions
    try:
        return workspace_extensions(storage)
    # Storage errors (OSError, NextCloud's requests errors included) and Turtle
    # parse errors (rdflib's BadSyntax is a SyntaxError): reported, never hidden.
    except (OSError, SyntaxError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[materialize] ERROR: the workspace ontology extension could not be "
              f"read; only the core hierarchy is used. {error}")
        if skipped is not None:
            skipped.append({"file": "ontology/extensions", "error": error})
        return None


def materialize_against_workspace(storage, scenario_text: str, client=None,
                                  *, skipped: Optional[list] = None,
                                  ontology_graph=None) -> str:
    """Merge a scenario with the workspace replica into a self-contained TTL.

    Returns the original text on any problem (not a scenario, no replica to
    merge, parse failure) — materialization must never make conversion worse.
    When a graph client is given, the derived collections graph is merged in
    too, so projected aggregate attributes ride along.

    A replica file that does not parse is skipped (the rest still merges) but
    never silently: an error naming the file is printed, and when a list is
    passed as ``skipped`` each skipped file is appended to it as
    ``{"file": rel, "error": "..."}`` so callers can surface it — every
    component and attribute in that file is missing from the result.

    ``ontology_graph`` is the workspace schema (``workspace_schema``); it is
    read from ``storage`` when not given.
    """
    def _record_skip(rel: str, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[materialize] ERROR: replica file {rel} could not be parsed and was "
              f"SKIPPED; its components and attributes are missing from this "
              f"conversion. {error}")
        if skipped is not None:
            skipped.append({"file": rel, "error": error})

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
                    except Exception as exc:
                        _record_skip(rel, exc)
        except Exception as exc:
            _record_skip("ingestion/output (listing)", exc)

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

        if ontology_graph is None:
            ontology_graph = workspace_schema(storage, skipped=skipped)
        materialized: Optional[str] = materialize_scenario_graphs(
            scn, rep, str(scenarios[0]), ontology_graph=ontology_graph)
        return materialized or scenario_text
    except Exception:
        return scenario_text


__all__ = ["materialize_against_workspace", "workspace_schema"]
