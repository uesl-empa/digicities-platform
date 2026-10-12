# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""A scenario applies its own overrides only.

Every variant lives in the one ``<http://scenarios>`` graph. Two variants that
override the same replica attribute must each see their own value, and a
variant that overrides nothing must see the replica value. The scenarios are
written by the real Assumptions engine + thin-scenario writer, so the test
covers the path a multi-variant experiment takes.
"""
from __future__ import annotations

import pytest
from rdflib import Graph, URIRef

from backend.assumptions.assumption_engine import apply_single_assumption
from backend.assumptions.thin_scenario_ttl import build_thin_scenario_ttl
from backend.graphdb.queries.scenarios import materialize_scenario_graphs

D = "https://digicities.info/ontology#"
QUDT_VALUE = URIRef("http://qudt.org/schema/qudt/value")
P = "https://digicities.info/proj/ws"
WT = f"{P}/WindTurbine/WT1"
POWER = f"{WT}/RatedPower"
BASELINE = f"{P}/Baseline"

ONTOLOGY = f"""
@prefix dici_onto: <{D}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:WindTurbine rdfs:subClassOf dici_onto:Component .
dici_onto:RatedPower rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:PhysicalAttribute .
dici_onto:hasWindTurbineRatedPowerAttribute rdfs:subPropertyOf dici_onto:hasAttribute .
"""

REPLICA = f"""
@prefix dici_onto: <{D}> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{WT}> a dici_onto:WindTurbine ;
    dici_onto:hasWindTurbineRatedPowerAttribute <{POWER}> .
<{POWER}> a dici_onto:RatedPower, dici_onto:PhysicalAttribute ;
    qudt:value 2.0 .
"""


def _baseline() -> dict:
    return {
        "scenario_uri": BASELINE,
        "workspace": "ws",
        "components": [{
            "uri": WT, "type": "WindTurbine", "label": "WT1",
            "attributes": {"RatedPower": {
                "uri": POWER, "value": "2.0", "unit": "MegaW",
                "attribute_type": "PhysicalAttribute", "category": "physical"}},
        }],
        "component_links": [],
    }


def _variant(name: str, factor: str) -> str:
    assumption = {"name": f"x{factor}", "target_component": "WindTurbine",
                  "target_attribute": "RatedPower", "modifier": "*",
                  "modifier_value": factor, "type": "single"}
    return build_thin_scenario_ttl(
        apply_single_assumption(_baseline(), assumption, name, namespace=P))


def _scenarios_graph(*ttls: str) -> Graph:
    g = Graph()
    g.parse(data=f"@prefix dici_onto: <{D}> . <{BASELINE}> a dici_onto:Scenario .",
            format="turtle")
    for ttl in ttls:
        g.parse(data=ttl, format="turtle")
    return g


def _power(scn: Graph, scenario: str) -> set:
    ttl = materialize_scenario_graphs(
        scn, Graph().parse(data=REPLICA, format="turtle"), f"{P}/{scenario}",
        ontology_graph=Graph().parse(data=ONTOLOGY, format="turtle"))
    out = Graph().parse(data=ttl, format="turtle")
    attrs = set(out.objects(URIRef(WT), URIRef(f"{D}hasWindTurbineRatedPowerAttribute")))
    return {float(v) for a in attrs for v in out.objects(a, QUDT_VALUE)}, out


def test_two_variants_overriding_one_attribute_each_see_their_own_value():
    scn = _scenarios_graph(_variant("Plus50", "1.5"), _variant("Double", "2.0"))
    plus50, out50 = _power(scn, "Plus50")
    double, out2 = _power(scn, "Double")
    assert plus50 == {3.0}
    assert double == {4.0}
    # The materialised document names its own scenario only.
    used = URIRef(f"{D}usedInScenario")
    assert set(out50.objects(URIRef(WT), used)) == {URIRef(f"{P}/Plus50")}
    assert set(out2.objects(URIRef(WT), used)) == {URIRef(f"{P}/Double")}


def test_a_variant_without_an_override_keeps_the_replica_value():
    untouched = (f"@prefix dici_onto: <{D}> .\n"
                 f"<{P}/Untouched> a dici_onto:Scenario .\n"
                 f"<{WT}> dici_onto:usedInScenario <{P}/Untouched> .\n")
    scn = _scenarios_graph(_variant("Plus50", "1.5"), _variant("Double", "2.0"), untouched)
    value, _ = _power(scn, "Untouched")
    assert value == {2.0}


def test_two_overrides_of_one_attribute_in_one_scenario_are_refused():
    clash = f"""
        @prefix dici_onto: <{D}> .
        @prefix qudt: <http://qudt.org/schema/qudt/> .
        <{P}/Clash> a dici_onto:Scenario .
        <{WT}> dici_onto:usedInScenario <{P}/Clash> .
        <{POWER}_a> a dici_onto:RatedPower ; qudt:value 3.0 ;
            dici_onto:supersedesAttribute <{POWER}> ; dici_onto:usedInScenario <{P}/Clash> .
        <{POWER}_b> a dici_onto:RatedPower ; qudt:value 4.0 ;
            dici_onto:supersedesAttribute <{POWER}> ; dici_onto:usedInScenario <{P}/Clash> .
    """
    with pytest.raises(ValueError, match="twice"):
        _power(_scenarios_graph(clash), "Clash")
