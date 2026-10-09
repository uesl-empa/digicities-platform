# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Scenario TTL → editable builder draft, headless.

The inverse of the scenario emitters: parse a saved ``scenarios/*.ttl`` back
into the ``{scenario_name, service_name, components, links}`` shape the
builder UIs edit, so an existing scenario can be reloaded, changed, and
rebuilt instead of being view-only. Port of the Streamlit builder's
``_reconstruct_scenario_from_ttl``, minus the data-product component
extractor (the builder draft only needs uri/type/label; attributes stay in
the workspace graph and are re-resolved at validate/build time).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

DICI = "https://digicities.info/ontology#"


def draft_from_ttl(ttl_text: str,
                   instance_types: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Parse a scenario TTL into an editable draft.

    Returns ``{scenario_name, scenario_uri, service_name, description,
    components: [{uri, type, label}], links: [{source, target, link_type,
    pattern}], warnings: [...]}``. Scenario→component links come back with the
    ``'scenario'`` pseudo-source the builders (and POST /scenario/build) use.

    A component's type is its ``rdf:type`` in the scenario TTL, else its type
    in the workspace graph (``instance_types``: instance IRI → class local
    name, see ``graph_lookups.instance_types``). A thin scenario that only
    references an instance carries no type of its own; when neither source
    has one the type is None and ``warnings`` says so. It is never read off
    the IRI.
    """
    from rdflib import Graph, Namespace
    from rdflib.namespace import OWL, RDF, RDFS

    from backend.ontology_kinds import (
        is_attribute_node, is_attribute_predicate, is_time_series_predicate, with_core,
    )

    dici = Namespace(DICI)
    g = Graph()
    g.parse(data=ttl_text, format="turtle")
    # The scenario TTL plus the core hierarchy, for every "what is this" question.
    onto = with_core(g)
    # rdf:types that are never the component's concrete class in a scenario TTL.
    skip_types = {dici.Scenario, dici.ComponentLink, dici.Component,
                  OWL.NamedIndividual, OWL.Thing, RDFS.Resource}

    scenario_uri = None
    scenario_name = None
    service_name = None
    description = None
    for s in g.subjects(RDF.type, dici.Scenario):
        scenario_uri = str(s)
        for lbl in g.objects(s, RDFS.label):
            scenario_name = str(lbl)
        for svc in g.objects(s, dici.builtForService):
            service_name = str(svc)
        for d in g.objects(s, Namespace("http://purl.org/dc/terms/").description):
            description = str(d)
        break

    # Components: everything marked usedInScenario that isn't the scenario
    # itself, a ComponentLink node, or an ATTRIBUTE INDIVIDUAL — full-emitter
    # TTLs mark attribute nodes with usedInScenario too, and the Streamlit
    # reconstruction had to filter them the same way. An attribute individual
    # is typed under dici_onto:Attribute (the emitter always adds its kind
    # class) or is the object of a link under dici_onto:hasAttribute; a
    # TimeSeries resource is typed TimeSeries or hangs off a hasTimeSeries link.
    link_nodes = set(g.subjects(RDF.type, dici.ComponentLink))
    attribute_nodes: set[str] = set()
    for s, p, o in g:
        if is_attribute_predicate(onto, p) or is_time_series_predicate(onto, p):
            attribute_nodes.add(str(o))
    for s in set(g.subjects(dici.usedInScenario, None)):
        if is_attribute_node(onto, s):
            attribute_nodes.add(str(s))
    for ts in g.subjects(RDF.type, dici.TimeSeries):
        attribute_nodes.add(str(ts))
    components: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for s in g.subjects(dici.usedInScenario, None):
        uri = str(s)
        if s in link_nodes or uri == scenario_uri or uri in seen or uri in attribute_nodes:
            continue
        seen.add(uri)
        ctype = None
        for t in g.objects(s, RDF.type):
            if t not in skip_types:
                ctype = str(t).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                break
        if ctype is None:
            ctype = (instance_types or {}).get(uri)
        if ctype is None:
            warnings.append(f"{uri} has no rdf:type in the scenario or the workspace "
                            "graph, so its type is unknown")
        label = None
        for lbl in g.objects(s, RDFS.label):
            label = str(lbl)
            break
        components.append({
            "uri": uri,
            "type": ctype,
            "label": label or uri.rstrip("/").rsplit("/", 1)[-1],
        })

    components.sort(key=lambda c: c["uri"])
    type_by_uri = {c["uri"]: c["type"] for c in components}
    links: list[dict[str, Any]] = []
    for link in sorted(link_nodes, key=str):
        srcs = list(g.objects(link, dici.hasInputEntity))
        tgts = list(g.objects(link, dici.linksInputyEntityTo))
        if not srcs or not tgts:
            continue
        src, tgt = str(srcs[0]), str(tgts[0])
        tgt_type = type_by_uri.get(tgt) or "Component"
        declared = [str(t) for t in g.objects(link, dici.linkType)]
        if src == scenario_uri:
            links.append({"source": "scenario", "target": tgt,
                          "link_type": declared[0] if declared else "scenario_automatic",
                          "pattern": f"CL.Scenario.{tgt_type}"})
        else:
            src_type = type_by_uri.get(src) or "Component"
            links.append({"source": src, "target": tgt,
                          "link_type": declared[0] if declared else "manual",
                          "pattern": f"CL.{src_type}.{tgt_type}"})

    return {
        "scenario_name": scenario_name,
        "scenario_uri": scenario_uri,
        "service_name": service_name,
        "description": description,
        "components": components,
        "links": links,
        "warnings": warnings,
    }
