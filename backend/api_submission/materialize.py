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

import re
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


def _template_attribute_classes(template) -> set:
    """The attribute classes a service template names: the ``Attr`` of every
    ``Component.Attr`` reference (``Tree.WeightMean`` names ``WeightMean``),
    as dici_onto: IRIs. Link specs (``CL.A.B``) and nested references
    (``A.B.hasLiveTimeSeriesReference``) name no derived value."""
    from backend.ontology_kinds import DICI
    classes: set = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            parts = node.split(".")
            if len(parts) == 2 and parts[0] != "CL" and _LOCAL_NAME.fullmatch(parts[1]):
                classes.add(DICI[parts[1]])

    walk(template)
    return classes


_LOCAL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")


def derived_value_query(classes) -> str:
    """CONSTRUCT the projected aggregate attributes of the given classes from
    the collections graph: each container's edge to the node and the node's
    own triples (type, value, unit, label, statistic), but not ``aggregateOf``,
    which points into the collection itself."""
    from backend.graphdb.graphs import COLLECTIONS_GRAPH
    values = " ".join(f"<{c}>" for c in sorted(classes))
    return f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    CONSTRUCT {{ ?container ?edge ?node . ?node ?p ?o }}
    WHERE {{
      GRAPH <{COLLECTIONS_GRAPH}> {{
        VALUES ?cls {{ {values} }}
        ?node a dici_onto:AggregateAttribute , ?cls .
        ?container ?edge ?node .
        ?node ?p ?o .
        FILTER(?p != dici_onto:aggregateOf)
      }}
    }}
    """


def derived_values(client, template, *, skipped: Optional[list] = None):
    """The derived values ``template`` asks for, read from the collections
    graph, as an rdflib Graph (empty when it asks for none). A read that fails
    is reported in ``skipped`` (``{"file": "collections", "error": ...}``): the
    template asked for values the conversion then cannot see."""
    from rdflib import Graph

    from backend.graphdb.queries.graph_io import construct_ttl

    graph = Graph()
    classes = _template_attribute_classes(template)
    if not classes:
        return graph
    ttl = construct_ttl(client, derived_value_query(classes))
    if ttl is None:
        error = "the derived values the service template asks for could not be read"
        print(f"[materialize] ERROR: {error} from the collections graph")
        if skipped is not None:
            skipped.append({"file": "collections", "error": error})
        return graph
    if ttl.strip():
        graph.parse(data=ttl, format="turtle")
    return graph


def with_derived_values(scenario_ttl: str, client, template, *,
                        skipped: Optional[list] = None) -> str:
    """An already materialized scenario plus the derived values ``template``
    asks for, on the scenario's own components only (a container the
    scenario does not hold gets nothing). For a caller that materializes
    before it knows the template, such as a scenario picker. Returns the text
    unchanged when nothing is added."""
    from rdflib import Graph

    derived = derived_values(client, template, skipped=skipped)
    if len(derived) == 0:
        return scenario_ttl
    scn = Graph()
    scn.parse(data=scenario_ttl, format="turtle")
    held = set(scn.subjects())
    nodes = {node for container, _, node in derived if container in held}
    added = 0
    for s, p, o in derived:
        if (s in held and o in nodes) or s in nodes:
            scn.add((s, p, o))
            added += 1
    return scn.serialize(format="turtle") if added else scenario_ttl


def materialize_against_workspace(storage, scenario_text: str, client=None,
                                  *, skipped: Optional[list] = None,
                                  ontology_graph=None, template=None) -> str:
    """Merge a scenario with the workspace replica into a self-contained TTL.

    Returns the original text on any problem (not a scenario, no replica to
    merge, parse failure) — materialization must never make conversion worse.
    When a graph client and the service ``template`` are given, the derived
    values the template asks for (projected aggregates such as
    ``Tree.WeightMean``) are read from the collections graph and ride along.
    Nothing else of the collections enters the scenario.

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

        # The derived values the template asks for (``Tree.WeightMean``) live
        # only in the collections graph. Only those values come in; the
        # collections themselves (sets, groups, statistics, membership) are
        # not part of any scenario.
        if client is not None and template is not None:
            rep += derived_values(client, template, skipped=skipped)

        if ontology_graph is None:
            ontology_graph = workspace_schema(storage, skipped=skipped)
        materialized: Optional[str] = materialize_scenario_graphs(
            scn, rep, str(scenarios[0]), ontology_graph=ontology_graph)
        return materialized or scenario_text
    except Exception:
        return scenario_text


__all__ = ["derived_value_query", "derived_values", "materialize_against_workspace",
           "with_derived_values", "workspace_schema"]
