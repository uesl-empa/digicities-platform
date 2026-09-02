# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""backend.scenario_builder.requirements — the service-template constraint
extraction the Scenario Builder runs on (ported verbatim from the Streamlit
layer; these pin the behaviour the emitter's completeness gate depends on)."""
from __future__ import annotations

from backend.scenario_builder.requirements import (
    extract_all_required_component_types,
    extract_component_links,
    extract_required_attributes_enhanced,
    parse_service_requirements,
)

# Mirrors the bundled demo_energy_simulator.yaml: template-nested children.
DEMO = {
    "service_name": "demo_energy_simulator",
    "connection": {"transport": "http", "url": "http://x", "method": "POST"},
    "scenario_data": {
        "uri": "Scenario.URI",
        "name": "Scenario.label",
        "location": {
            "link": "CL.Scenario.Location",
            "template": {
                "uri": "Location.URI",
                "weather_data": "Location.WeatherEPW",
                "buildings": {
                    "link": "CL.Location.Building",
                    "template": {
                        "uri": "Building.URI",
                        "SIA2024BuildingType": "Building.SIA2024BuildingType",
                        "GroundFloorArea": "Building.GroundFloorArea",
                    },
                },
            },
        },
    },
}

# Dotted nested requirement (time-series) + sibling-style child block.
WIND = {
    "service_name": "wind_forecaster",
    "scenario_data": {
        "site": {
            "name": "GlobalWindAtlasSite.label",
            "turbines": {
                "link": "CL.GlobalWindAtlasSite.WindTurbine",
                "template": {
                    "rated_power": "WindTurbine.RatedPower",
                    "history": "WindTurbine.Power.hasHistoricTimeSeriesReference",
                },
            },
        },
    },
}


def test_component_links_found_at_any_depth():
    assert extract_component_links(DEMO) == ["CL.Location.Building", "CL.Scenario.Location"]


def test_required_component_types_exclude_scenario():
    types = extract_all_required_component_types(DEMO)
    assert "Scenario" not in types
    assert {"Location", "Building"} <= set(types)


def test_required_attributes_simple():
    required, nested = extract_required_attributes_enhanced(DEMO)
    assert set(required["Building"]) == {"URI", "SIA2024BuildingType", "GroundFloorArea"}
    assert set(required["Location"]) == {"URI", "WeatherEPW"}
    assert nested == {}


def test_required_attributes_dotted_nested():
    required, nested = extract_required_attributes_enhanced(WIND)
    # Base attribute AND the full dotted path are both required — the emitter
    # resolves the dotted form; the base keeps the simple check meaningful.
    assert set(required["WindTurbine"]) == {
        "RatedPower", "Power", "Power.hasHistoricTimeSeriesReference",
    }
    assert nested["WindTurbine"] == {"Power": ["hasHistoricTimeSeriesReference"]}


def test_parse_service_requirements_shape():
    out = parse_service_requirements(DEMO)
    assert out["service_name"] == "demo_energy_simulator"
    assert out["component_links"] == ["CL.Location.Building", "CL.Scenario.Location"]
    assert "Building" in out["required_attributes"]
    assert out["nested_requirements"] == {}
