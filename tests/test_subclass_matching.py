# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""A requirement on a class is met by instances of its subclasses.

James 2026-10-10: class matching accepts subclasses everywhere
(``rdfs:subClassOf*``). A service that needs an EnergyConverter takes a PV
system, which must still carry the attributes the requirement lists. The
hierarchy is the workspace extension (which places the workspace's classes
under core) plus the REAL vendored core. Names never decide: neither a
spelling variant of an attribute nor a field name's suffix.
"""
from __future__ import annotations

from rdflib import Graph

from backend.scenario_builder.emitter import (
    get_filtered_components_for_ttl,
    validate_enhanced_component_attributes,
)
from backend.scenario_builder.semantics import requirement_classes, requirements_for

D = "https://digicities.info/ontology#"

EXTENSION = Graph().parse(data=f"""
    @prefix dici_onto: <{D}> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    dici_onto:PV rdfs:subClassOf dici_onto:EnergyConverter .
    dici_onto:RooftopPV rdfs:subClassOf dici_onto:PV .
    dici_onto:Building rdfs:subClassOf dici_onto:Component .
    dici_onto:RatedPower rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:PhysicalAttribute .
    dici_onto:PeakPower rdfs:subClassOf dici_onto:RatedPower .
""", format="turtle")

REQUIRED = {"EnergyConverter": ["RatedPower"]}


def _comp(uri, ctype, **attrs):
    attributes = {"URI": {"value": uri}, "label": {"value": uri}}
    attributes.update({k: {"value": v} for k, v in attrs.items()})
    return {"uri": uri, "type": ctype, "label": uri, "attributes": attributes,
            "nested_properties": {}}


# ── Scenario Builder completeness gate (spec issue 5) ─────────────────────────
def test_a_pv_system_meets_a_requirement_on_energy_converter():
    complete = _comp("pv1", "PV", RatedPower=8.0)
    incomplete = _comp("pv2", "PV")
    deeper = _comp("pv3", "RooftopPV")
    other = _comp("b1", "Building")
    kept = get_filtered_components_for_ttl(
        [complete, incomplete, deeper, other], REQUIRED, EXTENSION)
    assert [c["uri"] for c in kept] == ["pv1", "b1"]
    missing = validate_enhanced_component_attributes([incomplete, deeper], REQUIRED, EXTENSION)
    assert [(m["component"], m["missing_attribute"]) for m in missing] == [
        ("pv2", "RatedPower"), ("pv3", "RatedPower")]


def test_requirements_on_a_class_and_its_subclass_add_up():
    required = {"EnergyConverter": ["RatedPower"], "PV": ["Tilt"], "Building": ["Height"]}
    assert requirement_classes("PV", required, EXTENSION) == ["EnergyConverter", "PV"]
    assert requirements_for("PV", required, EXTENSION) == ["RatedPower", "Tilt"]
    assert requirements_for("Building", required, EXTENSION) == ["Height"]


def test_without_the_workspace_schema_only_the_core_hierarchy_counts():
    """Core places Turbine under EnergyConverter; PV is the workspace's own
    class, so without its extension a PV has no EnergyConverter requirement."""
    assert requirements_for("Turbine", REQUIRED) == ["RatedPower"]
    assert requirements_for("PV", REQUIRED) == []


# ── template parser (spec issue 8) ────────────────────────────────────────────
def test_the_reference_property_decides_the_flavor_not_the_field_name():
    from backend.service_requirements.template import extract_attributes_from_dict
    attrs = extract_attributes_from_dict({
        "uri": "Weather.URI",
        "WindSpeed_live": "Weather.WindSpeed.hasHistoricTimeSeriesReference",
        "gusts": "Weather.Gusts.hasLiveTimeSeriesReference",
        "outlook": "Weather.Outlook.hasFutureTimeSeriesReference",
    }, "Weather")
    assert attrs == {"WindSpeed": ["Historic"], "Gusts": ["Live"], "Outlook": ["Future"]}


def test_a_reference_to_another_class_is_not_an_attribute_of_the_block():
    """``WindTurbineType.X`` contains the text ``WindTurbine`` but names
    another class: it is not an attribute of the WindTurbine block."""
    from backend.service_requirements.template import extract_attributes_from_dict
    attrs = extract_attributes_from_dict({
        "hub": "WindTurbine.HubHeight",
        "kind": "WindTurbineType.Model",
    }, "WindTurbine")
    assert attrs == {"HubHeight": ["Static"]}


# ── assumptions engine targeting ──────────────────────────────────────────────
def _baseline():
    return {"scenario_uri": "https://x/Baseline", "component_links": [], "components": [
        {"uri": "https://x/PV/pv1", "type": "PV", "label": "pv1",
         "attributes": {"PeakPower": {"uri": "https://x/PV/pv1/PeakPower", "value": "8.0"}}},
        {"uri": "https://x/Building/b1", "type": "Building", "label": "b1",
         "attributes": {"RatedPower": {"uri": "https://x/Building/b1/RatedPower", "value": "5.0"}}},
    ]}


def test_an_assumption_on_a_class_modifies_its_subclass_instances():
    from backend.assumptions.assumption_engine import apply_single_assumption
    assumption = {"name": "x2", "target_component": "EnergyConverter",
                  "target_attribute": "RatedPower", "modifier": "*",
                  "modifier_value": "2", "type": "single"}
    out = apply_single_assumption(_baseline(), assumption, "Double", namespace="https://x",
                                  schema=EXTENSION)
    assert out["modified_count"] == 1
    assert [(d["component"], d["attribute"], d["new_value"])
            for d in out["modification_log"]] == [("pv1", "PeakPower", 16.0)]


def test_an_attribute_is_found_by_class_never_by_spelling():
    from backend.assumptions.assumption_engine import find_target_attribute
    from backend.assumptions.assumption_types import is_attribute_match
    comp = {"attributes": {"PeakPower": {"value": "8"}, "rated_power": {"value": "1"}}}
    assert find_target_attribute(comp, "RatedPower", EXTENSION)[0] == "PeakPower"
    assert find_target_attribute(comp, "ratedpower", EXTENSION) == (None, None)
    assert not is_attribute_match("RatedPowerDerated", "RatedPower", EXTENSION)
    assert not is_attribute_match("rated_power", "RatedPower", EXTENSION)
