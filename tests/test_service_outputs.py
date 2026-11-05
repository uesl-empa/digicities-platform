# SPDX-License-Identifier: Apache-2.0
"""A contract says what comes back and which input component it belongs to.
Optional: a contract without the block behaves as it always did."""
from __future__ import annotations

import copy

import rdflib

from backend.service_requirements.contract import (
    NON_PAYLOAD_KEYS,
    OutputBlock,
    output_problems,
    parse_outputs,
    payload_template,
    required_references,
)
from backend.service_requirements.requirements import requirements_ttl

DICI = "https://digicities.info/ontology#"
BASE = "https://digicities.info/proj/ws/services/"
REQUEST = {
    "service_name": "HarbourPlanner",
    "scenario_data": {
        "uri": "Scenario.URI",
        "harbour": {
            "uri": "Harbour.URI",
            "kiosks": {"link": "CL.Harbour.Kiosk", "template": {
                "uri": "Kiosk.URI", "Floors": "Kiosk.Floors"}},
        },
    },
}
OUTPUTS = [
    {"component": "Kiosk", "stream": "plans.kiosk", "identified_by": "kiosk_uri", "attributes": {
        "roof_kw": {"ref": "Kiosk.RoofLoad", "unit": "KiloW"}, "Shade": "Kiosk.Shade",
        "cost": {"ref": "Kiosk.Cost", "currency": "CHF"}}},
    {"component": "Harbour", "attributes": {"peak": {"ref": "Harbour.PeakLoad", "unit": "KiloW"}}},
    {"component": "Scenario", "attributes": {"total": "Scenario.TotalCost"}},
]


def _contract(outputs=OUTPUTS):
    return {**copy.deepcopy(REQUEST), "outputs": outputs}


def test_a_contract_without_the_block_has_no_outputs_and_no_problems():
    assert parse_outputs(REQUEST) == [] and output_problems(REQUEST) == []


def test_the_block_says_which_component_each_result_belongs_to():
    blocks = parse_outputs(_contract())
    assert [b.component for b in blocks] == ["Kiosk", "Harbour", "Scenario"]
    kiosk = blocks[0]
    assert kiosk.stream == "plans.kiosk" and kiosk.identified_by == "kiosk_uri"
    assert (kiosk.attributes[0].attribute, kiosk.attributes[0].field, kiosk.attributes[0].unit) == \
        ("RoofLoad", "roof_kw", "KiloW")
    assert (kiosk.attributes[1].attribute, kiosk.attributes[1].field, kiosk.attributes[1].unit) == \
        ("Shade", "Shade", None)
    assert kiosk.attributes[2].currency == "CHF" and kiosk.attributes[2].unit is None


def test_the_block_never_reaches_the_payload():
    assert "outputs" in NON_PAYLOAD_KEYS
    assert "outputs" not in payload_template(_contract())


def test_the_block_changes_nothing_about_what_a_service_requires():
    assert [r.text for r in required_references(_contract())] == \
        [r.text for r in required_references(REQUEST)]


def test_a_result_for_a_component_the_request_does_not_read_is_refused():
    problems = output_problems(_contract([{"component": "Ferry", "attributes": {"v": "Ferry.Speed"}}]))
    assert len(problems) == 1 and "`Ferry` is not an input" in problems[0]
    assert "Harbour, Kiosk, Scenario" in problems[0]


def test_a_block_must_say_what_it_belongs_to_and_what_comes_back():
    assert "which input component" in output_problems(_contract([{"attributes": {"v": "Kiosk.V"}}]))[0]
    assert "what comes back" in output_problems(_contract([{"component": "Kiosk"}]))[0]
    assert "what comes back" in output_problems(_contract([{"component": "Kiosk", "attributes": ["Kiosk.V"]}]))[0]
    assert "must be a list" in output_problems(_contract({"component": "Kiosk"}))[0]


def test_a_field_must_read_a_reference():
    problems = output_problems(_contract([{"component": "Kiosk", "attributes": {"v": "just words"}}]))
    assert "`v` names no reference" in problems[0]


def test_a_field_must_read_the_component_its_block_belongs_to():
    problems = output_problems(_contract([{"component": "Kiosk", "attributes": {"v": "Harbour.PeakLoad"}}]))
    assert "`v` reads `Harbour.PeakLoad`" in problems[0] and "belong to `Kiosk`" in problems[0]


def test_a_block_that_cannot_be_read_is_left_out_not_fatal():
    assert parse_outputs(_contract("nonsense")) == []
    assert parse_outputs(_contract(["nonsense", {"attributes": {}}])) == []
    assert parse_outputs(_contract([{"component": "Kiosk", "attributes": {"v": "words"}}]))[0].attributes == ()


def test_the_service_description_records_each_output_and_its_component():
    ttl = requirements_ttl("HarbourPlanner", "", [("Kiosk", ["Floors"])], [], BASE,
                           outputs=parse_outputs(_contract()))
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    term = lambda name: rdflib.URIRef(DICI + name)  # noqa: E731
    roof = next(g.subjects(term("hasResultField"), rdflib.Literal("roof_kw")))
    assert (roof, rdflib.RDF.type, term("ComponentAttributeOutput")) in g
    assert (roof, term("providesOutputEntity"), term("Kiosk")) in g
    assert (roof, term("providesOutputAttribute"), term("RoofLoad")) in g
    assert (roof, term("atStreamAddress"), rdflib.Literal("plans.kiosk")) in g
    assert (roof, term("hasUnitLabel"), rdflib.Literal("KiloW")) in g
    assert (roof, term("identifiedByField"), rdflib.Literal("kiosk_uri")) in g
    assert len(list(g.subjects(rdflib.RDF.type, term("ComponentAttributeOutput")))) == 5
    peak = next(g.subjects(term("hasResultField"), rdflib.Literal("peak")))
    assert (peak, term("providesOutputEntity"), term("Harbour")) in g
    total = next(g.subjects(term("providesOutputAttribute"), term("TotalCost")))
    assert (total, term("providesOutputEntity"), term("Scenario")) in g


def test_the_earlier_triples_still_work():
    ttl = requirements_ttl("S", "", [], [], BASE, outputs=[("Kiosk", ["Shade"], "plans")])
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    out = next(g.subjects(rdflib.RDF.type, rdflib.URIRef(DICI + "ComponentAttributeOutput")))
    assert (out, rdflib.URIRef(DICI + "atStreamAddress"), rdflib.Literal("plans")) in g


def test_an_output_block_is_hashable_and_comparable():
    assert parse_outputs(_contract())[2] == OutputBlock("Scenario", parse_outputs(_contract())[2].attributes)
