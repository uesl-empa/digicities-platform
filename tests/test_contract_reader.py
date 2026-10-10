# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""One reader for every contract consumer (SERVICE_REQUIREMENTS_SPEC.md section 13).

The Scenario Builder's completeness gate, payload validation, the converter and
its clean step read a contract through ``backend.service_requirements.contract``:

* issue 1: "required" has one default everywhere, required unless listed optional;
* issue 2: the control lists hold references (``T.A``), never payload field names;
* issue 3: the control lists never reach the payload (see the spec test);
* issue 9: free text that mentions ``.URI`` / ``.label`` is data;
* issue 12: one reference shape.
"""
from __future__ import annotations

import pytest
from rdflib import Graph

from backend.api_submission.ttl_converter import (
    _is_unresolved_placeholder, clean_placeholder_values, convert_scenario,
)
from backend.api_submission.validation import _is_reference, validate_payload
from backend.scenario_builder.requirements import extract_required_attributes_enhanced
from backend.service_requirements.contract import (
    is_reference, parse_link, parse_reference, required_references,
)

CONTRACT = {
    "service_name": "Heat",
    "optional_attributes": ["Site.Height", "Building.Roof"],
    "derived_attributes": ["Building.AreaMean"],
    "scenario_data": {
        "uri": "Scenario.URI",
        "building": {
            "uri": "Building.URI",
            "Height": "Building.Height",
            "Roof": "Building.Roof",
            "AreaMean": "Building.AreaMean",
            "Load_live": "Building.Load.hasLiveTimeSeriesReference",
            "site": {
                "link": "CL.Building.Site",
                "template": {"uri": "Site.URI", "Height": "Site.Height"},
            },
        },
    },
}


def _payload(**missing):
    site = {"uri": "urn:s1", "Height": 12.0}
    building = {"uri": "urn:b1", "Height": 30.0, "Roof": "Flat", "AreaMean": 2.0,
                "Load_live": "load.stream", "site": [site]}
    for field in missing:
        (site if field.startswith("site_") else building).pop(field.removeprefix("site_"))
    return {"service_name": "Heat", "scenario_data": {"uri": "urn:scn", "building": [building]}}


def test_gate_and_validation_require_the_same_references():
    """Issue 1: a reference the gate requires is an error when missing in
    validation; one the gate exempts is a warning."""
    required, _ = extract_required_attributes_enhanced(CONTRACT)
    assert required["Building"] == ["Height", "Load", "Load.hasLiveTimeSeriesReference", "URI"]
    assert required["Site"] == ["URI"]
    assert {r.text for r in required_references(CONTRACT)} == {
        "Scenario.URI", "Building.URI", "Building.Height",
        "Building.Load.hasLiveTimeSeriesReference", "Site.URI"}

    for field, blocks in [("Height", True), ("Load_live", True),
                          ("Roof", False), ("AreaMean", False), ("site_Height", False)]:
        vr = validate_payload(_payload(**{field: None}), CONTRACT)
        assert vr.is_valid is not blocks, field
        assert (len(vr.errors) == 1) is blocks, (field, vr.errors)


def test_the_lists_hold_references_not_field_names():
    """Issue 2: Site.Height is optional, Building.Height is not, though both
    payload fields are called Height."""
    assert validate_payload(_payload(site_Height=None), CONTRACT).is_valid
    vr = validate_payload(_payload(Height=None), CONTRACT)
    assert not vr.is_valid
    assert vr.missing_fields == ["scenario_data.building[1].Height"]


def test_an_optional_attribute_exempts_its_nested_reference():
    contract = dict(CONTRACT, optional_attributes=["Building.Load"])
    assert validate_payload(_payload(Load_live=None), contract).is_valid
    required, nested = extract_required_attributes_enhanced(contract)
    assert "Load" not in required["Building"] and "Building" not in nested


@pytest.mark.parametrize("leaf, ref", [
    ("Building.Height", True),
    ("Building.Load.hasLiveTimeSeriesReference", True),
    ("building_v2.height", True),       # a local name may start lower-case (grammar)
    ("Acme.Industries", True),          # the shape; only the context makes it data
    ("CL.Building.Site", False),        # a link, never a reference
    ("v1.2", False),
    ("e.g. a sentence", False),
    ("Building.", False),
    ("Building", False),
    (4.2, False),
])
def test_one_reference_shape_for_every_reader(leaf, ref):
    """Issue 12: the converter, the validator and the clean step agree."""
    assert is_reference(leaf) is ref
    assert (parse_reference(leaf) is not None) is ref
    assert _is_reference(leaf) is ref
    if isinstance(leaf, str):
        assert _is_unresolved_placeholder(leaf, leaf) is ref


def test_links_have_exactly_three_parts():
    assert parse_link("CL.Building.Site") == ("Building", "Site")
    assert parse_link("CL.Building") is None
    assert parse_link("CL.A.B.C") is None
    assert parse_link("Building.Height") is None


def test_free_text_mentioning_uri_or_label_reaches_the_service():
    """Issue 9: the clean step decides by the template's reference, not by a
    substring."""
    contract = {"service_name": "S", "description": "Reads Building.URI",
                "scenario_data": {"note": "Join on Site.label, see docs",
                                  "uri": "Scenario.URI"}}
    raw = {"service_name": "S", "description": "Reads Building.URI",
           "scenario_data": {"note": "Join on Site.label, see docs", "uri": "urn:scn"}}
    assert clean_placeholder_values(raw, contract) == raw


def test_an_identity_field_of_a_scenario_subclass_is_the_scenario():
    """The converter asks the ontology which class is a Scenario instead of
    comparing the reference to the text "Scenario.URI"."""
    onto = Graph().parse(data="""
        @prefix d: <https://digicities.info/ontology#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        d:Retrofit rdfs:subClassOf d:Scenario .
    """, format="turtle")
    ttl = """
        @prefix d: <https://digicities.info/ontology#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <urn:scn> a d:Scenario ; rdfs:label "Base" .
    """
    contract = {"service_name": "S", "scenario_data": {
        "uri": "Retrofit.URI", "name": "Scenario.label", "id": "Scenario.uri"}}
    data = convert_scenario(contract, ttl, ontology_graph=onto)["scenario_data"]
    assert data == {"uri": "urn:scn", "name": "Base", "id": "urn:scn"}


def test_the_streamlit_builder_reads_contracts_through_the_backend():
    import backend.scenario_builder.requirements as new
    import components.scenario_builder.scenario_builder as old

    for name in ("extract_component_links", "extract_all_required_component_types",
                 "extract_component_types_from_templates",
                 "extract_required_attributes_enhanced"):
        assert getattr(old, name) is getattr(new, name), name


def test_the_bundled_demo_is_complete_and_sends_its_categories():
    """Under "required unless optional" the bundled energy-simulation demo must
    still validate. Its categories are written the older way (the node is typed
    with a category class under the attribute class), and ElectricallyHeated
    sits under both DHWSupply and HeatingSupply, so each field must read the
    node typed with its own attribute class."""
    from pathlib import Path

    import yaml
    from rdflib import URIRef
    from rdflib.namespace import RDF

    from backend.graphdb.queries.scenarios import materialize_scenario_graphs

    ws = Path(__file__).resolve().parents[1] / "demo_workspaces" / "energy-simulation"
    contract = yaml.safe_load((ws / "services" / "demo_energy_simulator.yaml").read_text(encoding="utf-8"))
    replica = Graph().parse(ws / "ingestion" / "output" / "energy_sim_buildings.ttl")
    onto = Graph().parse(ws / "ontology" / "extensions" / "energy_sim_extension.ttl")
    expected = {"energy_sim_baseline.ttl": ("GasHeated", "GasHeated"),
                "energy_sim_retrofit.ttl": ("AirHeated", "ElectricallyHeated")}
    for name, (heating, dhw) in expected.items():
        scn = Graph().parse(ws / "scenarios" / name)
        suri = next(scn.subjects(RDF.type, URIRef("https://digicities.info/ontology#Scenario")))
        ttl = materialize_scenario_graphs(scn, replica, suri, ontology_graph=onto)
        raw = convert_scenario(contract, ttl, clean=False, ontology_graph=onto)
        report = validate_payload(raw, contract)
        assert report.is_valid, (name, report.errors)
        (building,) = raw["scenario_data"]["location"][0]["buildings"]
        assert (building["HeatingSupply"], building["DHWSupply"]) == (heating, dhw), name
        assert building["SIA2024BuildingType"] == "MFH"
