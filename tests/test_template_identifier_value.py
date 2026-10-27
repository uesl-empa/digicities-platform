# SPDX-License-Identifier: Apache-2.0

"""An identifier attribute reaches the payload as the text it holds.

The replica writes an identifier's value as ``dici_onto:identifierValue``; the
converter read only numbers, data paths and categories, so every identifier
(a tool's own id for a technology, a network name) arrived as null.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402

P = "https://digicities.info/proj/ids/"
TTL = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <{P}> .

ex:Baseline a dici_onto:Scenario ; rdfs:label "Baseline" .
ex:boiler a dici_onto:EnergyConverter ; rdfs:label "boiler at H1" ;
    dici_onto:hasIdentifier ex:boiler_TechId .
ex:boiler_TechId a dici_onto:TechId, dici_onto:IdentifierAttribute ;
    dici_onto:identifierValue "007" .
dici_onto:TechId rdfs:subClassOf dici_onto:IdentifierAttribute .
ex:CL_1 a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Baseline ;
    dici_onto:linksInputyEntityTo ex:boiler ; dici_onto:usedInScenario ex:Baseline .
"""


def test_an_identifier_arrives_as_its_text():
    tpl = {"service_name": "ids", "scenario_data": {"converters": {
        "link": "CL.Scenario.EnergyConverter",
        "template": {"uri": "EnergyConverter.URI", "tech_id": "EnergyConverter.TechId"}}}}
    (item,) = convert_scenario(tpl, TTL)["scenario_data"]["converters"]
    assert item["tech_id"] == "007"
