# SPDX-License-Identifier: Apache-2.0

"""A template's `optional_attributes` are inputs the service can run without.

The source has them for some instances and not others: three of six road
segments carry loop-detector counts, and the other three are forecast all the
same. The onboarding agent marks those inputs optional and writes the key onto
the service template it registers — and nothing here read it, so every consumer
of `extract_required_attributes_enhanced` (the emitter's completeness gate, and
`scenario_builder.sync`) re-imposed the full set and dropped exactly the
instances the template asked to keep. The agent's own gate kept them; `sync`
then rewrote the scenario without them, minutes later.

Deterministic only:  pytest tests/test_template_optional_attributes.py -q
"""
from __future__ import annotations

import copy

from backend.scenario_builder.requirements import extract_required_attributes_enhanced

TEMPLATE = {
    "service_name": "ZurichTrafficForecast",
    "scenario_data": {
        "roadSegment": [{
            "Length": "RoadSegment.Length",
            "Capacity": "RoadSegment.Capacity",
            "HistoricVehicleCount":
                "RoadSegment.HistoricVehicleCount.hasHistoricTimeSeriesReference",
        }],
    },
}


def _with(*optional):
    doc = copy.deepcopy(TEMPLATE)
    doc["optional_attributes"] = list(optional)
    return doc


def test_without_the_key_nothing_changes():
    required, nested = extract_required_attributes_enhanced(copy.deepcopy(TEMPLATE))
    assert required["RoadSegment"] == [
        "Capacity", "HistoricVehicleCount",
        "HistoricVehicleCount.hasHistoricTimeSeriesReference", "Length"]
    assert nested["RoadSegment"] == {"HistoricVehicleCount": ["hasHistoricTimeSeriesReference"]}


def test_an_optional_attribute_drops_its_nested_path_too():
    # `Power` and `Power.hasHistoricTimeSeriesReference` are one requirement in
    # two forms; leaving the dotted one behind would drop the instance anyway.
    required, nested = extract_required_attributes_enhanced(
        _with("RoadSegment.HistoricVehicleCount"))
    assert required["RoadSegment"] == ["Capacity", "Length"]
    assert "RoadSegment" not in nested


def test_a_plain_optional_attribute_is_dropped():
    required, _ = extract_required_attributes_enhanced(_with("RoadSegment.Capacity"))
    assert required["RoadSegment"] == [
        "HistoricVehicleCount", "HistoricVehicleCount.hasHistoricTimeSeriesReference",
        "Length"]


def test_a_type_with_nothing_left_required_disappears():
    # An empty requirement list must not linger: the gate reads "this type has
    # requirements" from the key being there.
    required, _ = extract_required_attributes_enhanced(
        _with("RoadSegment.Length", "RoadSegment.Capacity",
              "RoadSegment.HistoricVehicleCount"))
    assert "RoadSegment" not in required


def test_another_types_attribute_of_the_same_name_is_untouched():
    doc = copy.deepcopy(TEMPLATE)
    doc["scenario_data"]["roadNetwork"] = [{"Length": "RoadNetwork.Length"}]
    doc["optional_attributes"] = ["RoadSegment.Length"]
    required, _ = extract_required_attributes_enhanced(doc)
    assert "Length" not in required["RoadSegment"]
    assert required["RoadNetwork"] == ["Length"]


def test_an_attribute_the_template_does_not_have_is_harmless():
    required, _ = extract_required_attributes_enhanced(_with("RoadSegment.Nonexistent"))
    assert required["RoadSegment"] == [
        "Capacity", "HistoricVehicleCount",
        "HistoricVehicleCount.hasHistoricTimeSeriesReference", "Length"]


def test_a_malformed_entry_is_ignored():
    required, _ = extract_required_attributes_enhanced(_with("RoadSegment", "", "."))
    assert required["RoadSegment"] == [
        "Capacity", "HistoricVehicleCount",
        "HistoricVehicleCount.hasHistoricTimeSeriesReference", "Length"]
