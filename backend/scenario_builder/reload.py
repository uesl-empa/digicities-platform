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

from typing import Any

DICI = "https://digicities.info/ontology#"

# rdf:types that are never the component's concrete class in a scenario TTL.
_SKIP_TYPES = {"Scenario", "ComponentLink", "Component", "NamedIndividual", "Thing", "Resource"}


def draft_from_ttl(ttl_text: str) -> dict[str, Any]:
    """Parse a scenario TTL into an editable draft.

    Returns ``{scenario_name, scenario_uri, service_name, description,
    components: [{uri, type, label}], links: [{source, target, link_type,
    pattern}]}``. Scenario→component links come back with the ``'scenario'``
    pseudo-source the builders (and POST /scenario/build) use.
    """
    from rdflib import Graph, Namespace
    from rdflib.namespace import RDF, RDFS

    dici = Namespace(DICI)
    g = Graph()
    g.parse(data=ttl_text, format="turtle")

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
    # is recognisable as the object of a has…Attribute edge (or a hasAttribute
    # itself); TimeSeries resources are skipped by type.
    link_nodes = set(g.subjects(RDF.type, dici.ComponentLink))
    attribute_nodes: set[str] = set()
    for s, p, o in g:
        local_p = str(p).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if local_p.startswith("has") and (local_p.endswith("Attribute") or local_p == "hasAttribute"):
            attribute_nodes.add(str(o))
    for ts in g.subjects(RDF.type, dici.TimeSeries):
        attribute_nodes.add(str(ts))
    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in g.subjects(dici.usedInScenario, None):
        uri = str(s)
        if s in link_nodes or uri == scenario_uri or uri in seen or uri in attribute_nodes:
            continue
        seen.add(uri)
        ctype = None
        for t in g.objects(s, RDF.type):
            local = str(t).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            if local not in _SKIP_TYPES:
                ctype = local
                break
        if ctype is None:
            # Thin scenarios may reference instances without redeclaring the
            # class; the path-style URI convention carries the type as the
            # second-to-last segment (…/WindTurbine/Alkmaar_1) — same fallback
            # the Streamlit builder used.
            parts = uri.rstrip("/").split("/")
            if len(parts) >= 2 and parts[-2] not in ("", "proj"):
                ctype = parts[-2]
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
    }
