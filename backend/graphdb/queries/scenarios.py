# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Scenario discovery and extraction queries.

Pure, UI-independent helpers to (a) list the scenarios stored in a workspace's
``<http://scenarios>`` graph and (b) pull a single scenario back out as a
self-contained Turtle document that the API-submission converter (and the
Scenario Builder / Assumptions loaders) can consume.

Scenarios are written by the Scenario Builder both as ``scenarios/*.ttl`` files
and into the ``SCENARIOS_GRAPH`` named graph. This module reads them back from
the graph, so a user can load a scenario that only exists in the triplestore.
"""

from __future__ import annotations

from typing import Optional, Set

import pandas as pd
import rdflib
from rdflib import Graph, URIRef
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import RDF

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SCENARIOS_GRAPH,
    from_clause,
)
from backend.graphdb.queries._exec import run_df
from backend.graphdb.queries.graph_io import construct_named_graph
from backend.ontology_kinds import core_graph, is_attribute_node, is_attribute_predicate

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
)

_DICI = rdflib.Namespace("https://digicities.info/ontology#")

_SCENARIO_COLS = ["scenario", "label", "workspace", "service"]


def list_scenarios(client) -> pd.DataFrame:
    """List every scenario in the workspace's scenarios graph.

    Semantic: matches ``dici_onto:Scenario`` and any subclass via
    ``rdfs:subClassOf*`` rather than string-matching the class name. Returns a
    DataFrame with columns ``scenario``, ``label``, ``workspace``, ``service``
    (the ``builtForService`` value, empty when the scenario declares none).
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?scenario ?label ?workspace ?service
    {from_clause(ONTOLOGY_GRAPH, SCENARIOS_GRAPH)}WHERE {{
      ?scenario rdf:type/rdfs:subClassOf* dici_onto:Scenario .
      OPTIONAL {{ ?scenario rdfs:label ?label }}
      OPTIONAL {{ ?scenario dici_onto:createdInWorkspace ?workspace }}
      OPTIONAL {{ ?scenario dici_onto:builtForService ?service }}
    }}
    ORDER BY ?label ?scenario
    """
    return run_df(client, query, _SCENARIO_COLS)


def materialize_scenario_graphs(scenario_graph: Graph, replica_graph: Graph,
                                scenario_uri,
                                ontology_graph: Optional[Graph] = None) -> Optional[str]:
    """Materialize one scenario into a self-contained Turtle document.

    A scenario references the canonical replica components (``usedInScenario`` /
    ComponentLink chains) and may override attributes via
    ``dici_onto:supersedesAttribute``. This merges the two so a consumer (the
    converter) sees the full picture: each component's replica attributes, with
    the scenario's overrides applied, plus the scenario's own structure
    (ComponentLinks). Works for self-contained scenarios too (the replica graph
    can be empty), since component/attribute triples are read from whichever
    graph holds them.

    An edge from a component counts as an attribute edge when the ontology says
    so: its predicate is ``rdfs:subPropertyOf* dici_onto:hasAttribute``, or its
    object is typed under ``dici_onto:Attribute``. ``ontology_graph`` is the
    workspace schema (core + extension); the vendored core is always included,
    so a typed predicate declared only in the extension is still recognised
    through the attribute node's own core kind type.
    """
    scn, rep = scenario_graph, replica_graph
    DICI = _DICI
    USED, SUP, CL = DICI.usedInScenario, DICI.supersedesAttribute, DICI.ComponentLink

    suri = URIRef(str(scenario_uri).strip().strip("<>"))
    scenario_triples = list(scn.predicate_objects(suri))
    if not scenario_triples:
        return None

    out = Graph()
    for prefix, ns in list(rep.namespaces()) + list(scn.namespaces()):
        try:
            out.bind(prefix, ns, replace=True)
        except Exception:
            pass
    for p, o in scenario_triples:
        out.add((suri, p, o))

    # Reach the scenario's components + links. Prefer STRICT usedInScenario
    # scoping: the Scenario Builder tags a scenario's own links and components
    # with usedInScenario <suri>. Scoping by that tag is essential when many
    # scenarios live in the same <scenarios> graph and SHARE a component (e.g. a
    # common Location) — a chain walk would otherwise pull in every other
    # scenario that touches the shared node, producing a multi-scenario soup.
    tagged_nodes = set(scn.subjects(USED, suri))
    tagged_links = {ln for ln in scn.subjects(RDF.type, CL) if (ln, USED, suri) in scn}

    links: Set = set()
    if tagged_links or tagged_nodes:
        links = set(tagged_links)
        reached = {suri} | tagged_nodes
        for ln in links:
            reached |= set(scn.objects(ln, DICI.hasInputEntity))
            reached |= set(scn.objects(ln, DICI.linksInputyEntityTo))
    else:
        # Fallback for a self-contained scenario with no usedInScenario tags:
        # follow the ComponentLink chain FORWARD from the scenario (source in
        # reached), and never traverse into another Scenario node.
        reached = {suri}
        changed = True
        while changed:
            changed = False
            for ln in scn.subjects(RDF.type, CL):
                ie = set(scn.objects(ln, DICI.hasInputEntity))
                to = set(scn.objects(ln, DICI.linksInputyEntityTo))
                if ln in reached or (ie & reached):
                    if ln not in links:
                        links.add(ln)
                        changed = True
                    for n in {ln} | ie | to:
                        if n != suri and (n, RDF.type, DICI.Scenario) in scn:
                            continue  # don't cross into another scenario
                        if n not in reached:
                            reached.add(n)
                            changed = True

    # ComponentLinks: emit from the scenario graph (its structure).
    for ln in links:
        for p, o in scn.predicate_objects(ln):
            out.add((ln, p, o))

    # Override map: superseded attribute -> superseding attribute.
    old_to_new = {old_a: new_a for new_a, _, old_a in scn.triples((None, SUP, None))}

    view = ReadOnlyGraphAggregate(
        [g for g in (scn, rep, ontology_graph) if g is not None] + [core_graph()])
    attr_pred: dict = {}

    def _is_attr_edge(p, o) -> bool:
        if p not in attr_pred:
            attr_pred[p] = is_attribute_predicate(view, p)
        return attr_pred[p] or is_attribute_node(view, o)

    def _po_union(node):
        seen = set()
        for g in (rep, scn):
            for p, o in g.predicate_objects(node):
                if (p, o) not in seen:
                    seen.add((p, o))
                    yield p, o

    # Components: emit from replica ∪ scenario, redirecting superseded attributes
    # to their overrides, then emit each attribute node.
    for comp in reached:
        if comp == suri or comp in links:
            continue
        attrs: Set = set()
        for p, o in _po_union(comp):
            if isinstance(o, URIRef) and _is_attr_edge(p, o):
                tgt = old_to_new.get(o, o)
                out.add((comp, p, tgt))
                attrs.add(tgt)
            else:
                out.add((comp, p, o))
        for a in attrs:
            for p, o in _po_union(a):
                out.add((a, p, o))

    if len(out) == 0:
        return None
    return out.serialize(format="turtle")


def construct_scenario_ttl(client, scenario_uri: str) -> Optional[str]:
    """Return one scenario, materialized against the replica, as Turtle.

    Reads the scenarios graph and the component-instance (replica) graph, then
    merges the scenario's structure + overrides with the canonical replica
    attributes (see ``materialize_scenario_graphs``). Returns None if the graph
    can't be read or the scenario isn't present.
    """
    scn = construct_named_graph(client, SCENARIOS_GRAPH)
    if scn is None:
        return None

    uri = URIRef(scenario_uri.strip().strip("<>"))
    if uri not in set(scn.subjects()):
        return None

    rep = construct_named_graph(client, CLASSES_AND_ATTRIBUTES_GRAPH) or Graph()
    onto = construct_named_graph(client, ONTOLOGY_GRAPH)
    return materialize_scenario_graphs(scn, rep, uri, ontology_graph=onto)
