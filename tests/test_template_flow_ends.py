# SPDX-License-Identifier: Apache-2.0

"""A template reads a flow's two ends: ``<Flow>.hasSource`` / ``.hasDestination``.

A flow leaves one component and enters another (core hasSource /
hasDestination). A component link only says two things are joined, so the
service is given each flow's two ends, by URI, and decides what in and out
mean for it. Here: gas bus -> boiler -> heat bus, the boiler's heat also
straight into a tank.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402

P = "https://digicities.info/proj/flows/"
TTL = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <{P}> .

ex:Baseline a dici_onto:Scenario ; rdfs:label "Baseline" .
ex:gas a dici_onto:Junction ; rdfs:label "gas" .
ex:heat a dici_onto:Junction ; rdfs:label "heat" .
ex:boiler a dici_onto:EnergyConverter ; rdfs:label "boiler" .
ex:tank a dici_onto:EnergyStorage ; rdfs:label "tank" .
ex:Gas a dici_onto:EnergyCarrier ; rdfs:label "Gas" .
ex:Heat a dici_onto:EnergyCarrier ; rdfs:label "Heat" .
ex:gas_to_boiler a dici_onto:EnergyCarrierFlow ; rdfs:label "gas to boiler" ;
    dici_onto:hasSource ex:gas ; dici_onto:hasDestination ex:boiler ; dici_onto:linksComponent ex:Gas .
ex:boiler_to_heat a dici_onto:EnergyCarrierFlow ; rdfs:label "boiler to heat" ;
    dici_onto:hasSource ex:boiler ; dici_onto:hasDestination ex:heat ; dici_onto:linksComponent ex:Heat .
ex:boiler_to_tank a dici_onto:EnergyCarrierFlow ; rdfs:label "boiler to tank" ;
    dici_onto:hasSource ex:boiler ; dici_onto:hasDestination ex:tank ; dici_onto:linksComponent ex:Heat .
"""
LINKS = [("Baseline", "gas"), ("Baseline", "heat"), ("Baseline", "Gas"), ("Baseline", "Heat"),
         ("gas", "gas_to_boiler"), ("boiler", "gas_to_boiler"), ("boiler", "boiler_to_heat"),
         ("heat", "boiler_to_heat"), ("boiler", "boiler_to_tank"), ("tank", "boiler_to_tank"),
         ("Gas", "gas_to_boiler"), ("Heat", "boiler_to_heat"), ("Heat", "boiler_to_tank")]
TTL += "".join(f"""
ex:CL_{i} a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:{a} ;
    dici_onto:linksInputyEntityTo ex:{b} ; dici_onto:usedInScenario ex:Baseline .
""" for i, (a, b) in enumerate(LINKS))

TEMPLATE = {
    "service_name": "flows",
    "scenario_data": {
        "flows": {
            "link": "CL.EnergyCarrier.EnergyCarrierFlow",
            "template": {
                "uri": "EnergyCarrierFlow.URI",
                "carrier": {"link": "CL.EnergyCarrierFlow.EnergyCarrier", "template": "EnergyCarrier.label"},
                "source": "EnergyCarrierFlow.hasSource",
                "destination": "EnergyCarrierFlow.hasDestination",
            },
        },
        "boilers": {
            "link": "CL.EnergyCarrierFlow.EnergyConverter",
            "template": {
                "uri": "EnergyConverter.URI",
                "flows": {"link": "CL.EnergyConverter.EnergyCarrierFlow", "template": "EnergyCarrierFlow.URI"},
            },
        },
    },
}


@pytest.fixture(scope="module")
def payload():
    return convert_scenario(TEMPLATE, TTL)["scenario_data"]


def test_each_flow_carries_its_source_and_destination(payload):
    flows = {f["uri"].rsplit("/", 1)[-1]: f for f in payload["flows"]}
    assert flows["gas_to_boiler"]["source"] == [P + "gas"]
    assert flows["gas_to_boiler"]["destination"] == [P + "boiler"]
    assert flows["boiler_to_heat"]["source"] == [P + "boiler"]
    assert flows["boiler_to_heat"]["destination"] == [P + "heat"]
    assert flows["boiler_to_tank"]["destination"] == [P + "tank"]
    assert flows["gas_to_boiler"]["carrier"] == ["Gas"]


def test_a_component_lists_every_flow_it_touches_by_uri(payload):
    (boiler,) = payload["boilers"]
    assert sorted(boiler["flows"]) == sorted(P + f for f in ("gas_to_boiler", "boiler_to_heat", "boiler_to_tank"))


def test_a_property_under_has_source_counts_as_the_source():
    ttl = TTL.replace("@prefix ex:", "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n@prefix ex:") + f"""
ex:leaves rdfs:subPropertyOf dici_onto:hasSource .
ex:pump_flow a dici_onto:EnergyCarrierFlow ; ex:leaves ex:heat ; dici_onto:linksComponent ex:Heat .
ex:CL_pump a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Heat ;
    dici_onto:linksInputyEntityTo ex:pump_flow ; dici_onto:usedInScenario ex:Baseline .
"""
    flows = {f["uri"].rsplit("/", 1)[-1]: f for f in convert_scenario(TEMPLATE, ttl)["scenario_data"]["flows"]}
    assert flows["pump_flow"]["source"] == [P + "heat"]


def test_any_other_member_is_still_an_attribute(payload):
    tpl = {"service_name": "x", "scenario_data": {"flows": {
        "link": "CL.EnergyCarrier.EnergyCarrierFlow",
        "template": {"uri": "EnergyCarrierFlow.URI", "nothing": "EnergyCarrierFlow.linksComponent"}}}}
    flows = convert_scenario(tpl, TTL)["scenario_data"]["flows"]
    assert all("nothing" not in f for f in flows)        # not an end, not an attribute: dropped
