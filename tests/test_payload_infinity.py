# SPDX-License-Identifier: Apache-2.0

"""An infinite value ("no limit") reaches the payload as the text "inf".

The replica holds it as "INF"^^xsd:double. Strict JSON has no number for it,
and leaving it out told a service the last finite value held: ehubX read a
capacity of "1 GW in 2030, no limit from 2040" as 1 GW. The payload says it
as the tools write it: "inf" / "-inf". A payload with it stays strict JSON.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("rdflib")

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402

P = "https://digicities.info/proj/inf/"
TTL = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <{P}> .

ex:Baseline a dici_onto:Scenario ; rdfs:label "Baseline" .
ex:ccgt a dici_onto:EnergyConverter ; rdfs:label "ccgt" ;
    dici_onto:hasAttribute ex:ccgt_CapMax2030, ex:ccgt_CapMax2040, ex:ccgt_Floor .
ex:ccgt_CapMax2030 a dici_onto:CapMax2030, dici_onto:PhysicalAttribute ; qudt:value "1000000.0"^^xsd:double .
ex:ccgt_CapMax2040 a dici_onto:CapMax2040, dici_onto:PhysicalAttribute ; qudt:value "INF"^^xsd:double .
ex:ccgt_Floor a dici_onto:Floor, dici_onto:PhysicalAttribute ; qudt:value "-INF"^^xsd:double .
dici_onto:CapMax2030 rdfs:subClassOf dici_onto:PhysicalAttribute .
dici_onto:CapMax2040 rdfs:subClassOf dici_onto:PhysicalAttribute .
dici_onto:Floor rdfs:subClassOf dici_onto:PhysicalAttribute .
ex:CL_1 a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Baseline ;
    dici_onto:linksInputyEntityTo ex:ccgt ; dici_onto:usedInScenario ex:Baseline .
"""
TEMPLATE = {"service_name": "inf", "scenario_data": {"converters": {
    "link": "CL.Scenario.EnergyConverter",
    "template": {"cap_2030": "EnergyConverter.CapMax2030", "cap_2040": "EnergyConverter.CapMax2040",
                 "floor": "EnergyConverter.Floor"}}}}


def test_infinity_is_the_text_inf_and_the_payload_stays_strict_json():
    payload = convert_scenario(TEMPLATE, TTL)
    (item,) = payload["scenario_data"]["converters"]
    assert item == {"cap_2030": 1000000.0, "cap_2040": "inf", "floor": "-inf"}
    json.dumps(payload, allow_nan=False)          # strict JSON: no Infinity / NaN numbers
