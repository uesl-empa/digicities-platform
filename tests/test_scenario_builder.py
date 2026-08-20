# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Unit tests for backend.scenario_builder — the headless scenario-TTL builder.

Guards the TTL structure the rest of the pipeline consumes (scenario node,
usedInScenario per component, directed dici_onto:ComponentLink edges), so a
format regression here fails loudly.
"""
from __future__ import annotations

import rdflib

from backend.scenario_builder import build_scenario_ttl, scenario_uri_for

NS = "https://digicities.info/ontology#"
PROJ = "https://digicities.info/proj/ws1"


def _build():
    sc = scenario_uri_for("ws1", "My Scenario")
    ttl = build_scenario_ttl(
        scenario_name="My Scenario", workspace_id="ws1",
        service_name="demo_service", description="desc",
        components=[f"{PROJ}/Location/L",
                    {"uri": f"{PROJ}/Building/B", "type": "Building", "label": "B"}],
        links=[(sc, f"{PROJ}/Location/L"),
               (f"{PROJ}/Location/L", f"{PROJ}/Building/B")],
    )
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return sc, ttl, g


def test_uri_convention():
    assert scenario_uri_for("ws1", "My Scenario") == "https://digicities.info/proj/ws1/My_Scenario"


def test_scenario_node_declared():
    sc, _ttl, g = _build()
    assert (rdflib.URIRef(sc), rdflib.RDF.type, rdflib.URIRef(NS + "Scenario")) in g


def test_components_used_in_scenario():
    sc, ttl, g = _build()
    used = list(g.subjects(rdflib.URIRef(NS + "usedInScenario"), rdflib.URIRef(sc)))
    comp_used = [u for u in used if "/ComponentLink_" not in str(u)]
    assert len(comp_used) == 2                       # the Location + the Building
    assert 'dici_onto:builtForService "demo_service"' in ttl


def test_component_links_are_directed():
    sc, _ttl, g = _build()
    links = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(NS + "ComponentLink")))
    assert len(links) == 2
    sources = {str(next(g.objects(l, rdflib.URIRef(NS + "hasInputEntity")))) for l in links}
    assert sc in sources                             # Scenario -> Location
    assert f"{PROJ}/Location/L" in sources           # Location -> Building (nested)


def test_uri_only_components_emit_used_in_scenario_only():
    sc = scenario_uri_for("ws1", "S")
    ttl = build_scenario_ttl("S", "ws1",
                             components=[f"{PROJ}/Building/B"], links=[])
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    # a bare URI component gets usedInScenario but no rdfs:label re-declaration
    assert (rdflib.URIRef(f"{PROJ}/Building/B"),
            rdflib.URIRef(NS + "usedInScenario"), rdflib.URIRef(sc)) in g
    assert (rdflib.URIRef(f"{PROJ}/Building/B"), rdflib.RDFS.label, None) not in g
