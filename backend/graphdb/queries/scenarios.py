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

from typing import Dict, List, Optional, Set

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
from backend.ontology_kinds import (
    core_graph, is_attribute_node, is_attribute_predicate, is_subproperty_of,
)

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
)

_DICI = rdflib.Namespace("https://digicities.info/ontology#")

_SCENARIO_COLS = ["scenario", "label", "workspace", "service"]


class ScenarioMaterializationError(ValueError):
    """A scenario cannot be materialised as written: its lineage has a cycle
    or two parents, or it overrides one attribute twice."""


def scenario_parents(scn: Graph, suri: URIRef, schema) -> List[URIRef]:
    """The scenarios ``suri`` is based on: objects of any property that is
    ``rdfs:subPropertyOf* dici_onto:basedOn`` in ``schema`` (so the deprecated
    ``derivedFrom`` alias counts too)."""
    return sorted({o for p, o in scn.predicate_objects(suri)
                   if isinstance(o, URIRef) and is_subproperty_of(schema, p, _DICI.basedOn)})


def scenario_lineage(scn: Graph, suri: URIRef, schema,
                     warnings: Optional[list] = None) -> List[URIRef]:
    """``[suri, parent, grandparent, ...]`` following basedOn.

    A cycle or a scenario with two parents raises
    :class:`ScenarioMaterializationError`. A parent that is not in ``scn``
    ends the lineage; that is reported (printed, and appended to ``warnings``
    when a list is given), because its overrides are then not inherited."""
    lineage = [suri]
    while True:
        parents = scenario_parents(scn, lineage[-1], schema)
        if not parents:
            return lineage
        if len(parents) > 1:
            raise ScenarioMaterializationError(
                f"Scenario {lineage[-1]} is based on {len(parents)} scenarios "
                f"({', '.join(map(str, parents))}); a scenario has one parent.")
        parent = parents[0]
        if parent in lineage:
            chain = " -> ".join(map(str, lineage + [parent]))
            raise ScenarioMaterializationError(f"Scenario lineage has a cycle: {chain}")
        if next(scn.predicate_objects(parent), None) is None:
            msg = (f"Scenario {lineage[-1]} is based on {parent}, which is not in the "
                   f"scenarios read; its overrides are not inherited.")
            print(f"[scenarios] WARNING: {msg}")
            if warnings is not None:
                warnings.append(msg)
            return lineage
        lineage.append(parent)


def _own_overrides(scn: Graph, suri: URIRef) -> Dict[URIRef, URIRef]:
    """superseded attribute -> override, for the overrides tagged
    ``usedInScenario <suri>`` only. Two overrides of one attribute in one
    scenario raise :class:`ScenarioMaterializationError`."""
    used, sup = _DICI.usedInScenario, _DICI.supersedesAttribute
    own: Dict[URIRef, URIRef] = {}
    for new_a, _, old_a in scn.triples((None, sup, None)):
        if (new_a, used, suri) not in scn:
            continue
        if old_a in own and own[old_a] != new_a:
            raise ScenarioMaterializationError(
                f"Scenario {suri} overrides {old_a} twice "
                f"({own[old_a]} and {new_a}); keep one override.")
        own[old_a] = new_a
    return own


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
                                ontology_graph: Optional[Graph] = None,
                                warnings: Optional[list] = None) -> Optional[str]:
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

    Lineage: a scenario inherits the attribute overrides of the scenarios it is
    based on (``basedOn``, followed recursively; nearest override wins). Its
    structure (components, ComponentLinks) is its own: every writer states it
    in full. ``warnings`` collects lineage notes (a parent not found).
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

    view = ReadOnlyGraphAggregate(
        [g for g in (scn, rep, ontology_graph) if g is not None] + [core_graph()])
    attr_pred: dict = {}

    # Override map: superseded attribute -> the attribute that finally replaces
    # it. A scenario inherits the overrides of the scenarios it is based on
    # (rdfs:subPropertyOf* dici_onto:basedOn), farthest ancestor first, so the
    # nearest scenario's override wins. Each scenario's overrides are scoped by
    # its own usedInScenario tag: the scenarios graph holds every variant.
    lineage = scenario_lineage(scn, suri, view, warnings=warnings)
    old_to_new: dict = {}
    for level in reversed(lineage):
        for old_a, new_a in _own_overrides(scn, level).items():
            for k, v in list(old_to_new.items()):
                if v == old_a:  # this level overrides an ancestor's override
                    old_to_new[k] = new_a
            old_to_new[old_a] = new_a
    inherited = {new_a for new_a in old_to_new.values() if (new_a, USED, suri) not in scn}

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
            if p == USED and o != suri:
                continue  # another scenario's anchor on a shared component
            if isinstance(o, URIRef) and _is_attr_edge(p, o):
                tgt = old_to_new.get(o, o)
                out.add((comp, p, tgt))
                attrs.add(tgt)
            else:
                out.add((comp, p, o))
        for a in attrs:
            for p, o in _po_union(a):
                if p == USED and o != suri:
                    continue  # an ancestor's tag: re-tagged below
                out.add((a, p, o))
                # A series node (rdfs:subPropertyOf* hasTimeSeries) holds the
                # series' unit and currency: without it a contract field that
                # names a unit could not check the series it is sent.
                if isinstance(o, URIRef) and is_subproperty_of(view, p, DICI.hasTimeSeries):
                    for sp, so in _po_union(o):
                        out.add((o, sp, so))
            if a in inherited:
                out.add((a, USED, suri))

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
