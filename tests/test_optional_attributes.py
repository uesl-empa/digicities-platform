# SPDX-License-Identifier: Apache-2.0
"""A template's ``optional_attributes`` stay in the payload but never make an
instance incomplete — the scenario sync must not drop instances the source
data describes just because one sparse value is missing."""
from __future__ import annotations

from backend.scenario_builder.requirements import (drop_optional_requirements,
                                                   extract_required_attributes_enhanced)

TEMPLATE = {
    "service_name": "Traffic",
    "scenario_data": {
        "uri": "Scenario.URI",
        "roadSegment": {
            "uri": "RoadSegment.URI",
            "Length": "RoadSegment.Length",
            "VehicleCount": "RoadSegment.VehicleCount.hasHistoricTimeSeriesReference",
        },
    },
}


def test_without_the_key_everything_is_required():
    req, nested = extract_required_attributes_enhanced(TEMPLATE)
    assert "VehicleCount" in req["RoadSegment"]
    assert "VehicleCount.hasHistoricTimeSeriesReference" in req["RoadSegment"]
    assert "Length" in req["RoadSegment"]


def test_optional_attributes_are_not_required():
    t = dict(TEMPLATE, optional_attributes=["RoadSegment.VehicleCount"])
    req, nested = extract_required_attributes_enhanced(t)
    assert "Length" in req["RoadSegment"]
    assert not any(a.startswith("VehicleCount") for a in req["RoadSegment"])
    assert "VehicleCount" not in nested.get("RoadSegment", {})


def test_unknown_optional_entries_are_ignored():
    req = {"A": ["x", "y"]}
    drop_optional_requirements({"optional_attributes": ["B.x", "A", "A.z"]}, req)
    assert req == {"A": ["x", "y"]}


def test_sync_keeps_an_instance_missing_an_optional_value():
    from backend.scenario_builder.emitter import get_filtered_components_for_ttl
    t = dict(TEMPLATE, optional_attributes=["RoadSegment.VehicleCount"])
    req, _ = extract_required_attributes_enhanced(t)
    comps = [{"uri": "u1", "type": "RoadSegment",
              "attributes": {"URI": {"value": "u1"}, "Length": {"value": 1}},
              "nested_properties": {}}]
    assert [c["uri"] for c in get_filtered_components_for_ttl(comps, req)] == ["u1"]
