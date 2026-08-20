# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Characterization tests for the Scenario Builder TTL emitter.

The emitter (``components.scenario_builder.scenario_builder_summary``) is headed
for extraction to ``backend/``. These tests pin its CURRENT behavior — including
quirks like booleans emitted as ``xsd:decimal`` and the ``linksInputyEntityTo``
typo — so the move can be proven behavior-preserving. They do not judge whether
that behavior is right.

The module reads ``st.session_state``; tests swap in a plain dict subclass with
attribute access, so no Streamlit runtime is needed. Everything else in the
fixture is fixed data: no timestamps, uuids, or network anywhere in the
characterized paths.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
st = pytest.importorskip("streamlit")

from components.scenario_builder import scenario_builder_summary as sbs  # noqa: E402

from tests.golden import assert_ttl_golden  # noqa: E402


class _MockState(dict):
    """st.session_state stand-in: a dict with attribute access."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value


WT_URI = "https://digicities.info/proj/ws_golden/WindTurbine/WT1"
EDP_URI = "https://digicities.info/proj/ws_golden/ElectricityDemandProfile/EDP1"
SCENARIO_URI = "https://digicities.info/proj/ws_golden/Golden_Scenario"


def _wind_turbine():
    """One component covering the plain attribute flavors: numeric with a QUDT
    unit, string, boolean, temporal-precision (EventAttribute), categorical."""
    return {
        "uri": WT_URI,
        "type": "WindTurbine",
        "label": "Turbine One",
        "source": "ttl_use_case",
        "workspace_id": "ws_golden",
        "attributes": {
            "hubHeight": {"value": 120, "unit": "m",
                          "attribute_type": "PhysicalAttribute"},
            "manufacturer": {"value": "Vestas", "unit": "text",
                             "attribute_type": "PhysicalAttribute"},
            "isOffshore": {"value": True, "unit": "dimensionless",
                           "attribute_type": "PhysicalAttribute"},
            "commissioningDate": {"value": "2020-05",
                                  "temporal_value": "2020-05",
                                  "temporal_precision": "YearMonth",
                                  "unit": "temporal",
                                  "attribute_type": "EventAttribute"},
            "turbineClass": {"value": "IEC Class II",
                             "category_value": "IEC Class II",
                             "unit": "category",
                             "attribute_type": "CategoricalAttribute"},
        },
    }


def _demand_profile():
    """One component with a nested time-series requirement, which the emitter
    must promote to a DynamicAttribute and back with a TimeSeries resource."""
    return {
        "uri": EDP_URI,
        "type": "ElectricityDemandProfile",
        "label": "Demand Profile One",
        "source": "data_products",
        "source_catalog": "catalog_a",
        "attributes": {
            "Power": {"value": "timeseries", "unit": "kW"},
        },
        "nested_properties": {
            "Power": {
                "hasHistoricTimeSeriesReference": "resources/demand.csv",
                "hasHistoricTimeSeries":
                    "https://digicities.info/proj/ws_golden/ts/demand",
                "unit": "kW",
            },
        },
    }


def _scenario_state():
    return _MockState({
        "scenario_name": "Golden Scenario",
        "current_workspace": {"id": "ws_golden", "name": "Golden Workspace"},
        "selected_requirements": {"service_name": "golden_service",
                                  "component_links": []},
        "ttl_specificity": "High",
        "required_attributes": {
            "WindTurbine": ["hubHeight", "manufacturer", "isOffshore",
                            "commissioningDate", "turbineClass"],
            "ElectricityDemandProfile": ["Power.hasHistoricTimeSeriesReference"],
        },
        "scenario_components": [_wind_turbine(), _demand_profile()],
        "scenario_links": [
            {"source": "scenario", "target": WT_URI,
             "link_type": "scenario_automatic"},
            {"source": EDP_URI, "target": WT_URI, "link_type": "feeds"},
        ],
    })


@pytest.fixture()
def scenario_state(monkeypatch):
    state = _scenario_state()
    monkeypatch.setattr(st, "session_state", state)
    return state


def test_full_ttl_golden(scenario_state):
    """The whole emitted scenario graph, pinned as an RDF-isomorphism golden.

    Covers: scenario header (label, builtForService, createdInWorkspace),
    source-tracking triples per component, High-specificity property names,
    Physical/Event/Categorical attribute declarations, the nested-property
    DynamicAttribute path, the TimeSeries resource block, and both automatic
    and manual ComponentLinks (with the linksInputyEntityTo spelling).
    """
    ttl = sbs.generate_full_ttl()
    assert_ttl_golden(ttl, "scenario_emitter_full.ttl")


def test_completeness_filter_keeps_and_drops(scenario_state):
    """Components missing a required attribute are silently dropped; note the
    filter is truthiness-based, so a legitimate 0 value also drops a component.
    That is current behavior and this test pins it."""
    kept = sbs.get_filtered_components_for_ttl()
    assert [c["label"] for c in kept] == ["Turbine One", "Demand Profile One"]

    # Zero-valued required attribute -> component excluded (truthiness check).
    st.session_state.scenario_components[0]["attributes"]["hubHeight"]["value"] = 0
    kept = sbs.get_filtered_components_for_ttl()
    assert [c["label"] for c in kept] == ["Demand Profile One"]


def test_link_filter_follows_components(scenario_state):
    """Links survive only when both endpoints survive; 'scenario' is always a
    valid source for automatic links."""
    kept = sbs.get_filtered_links_for_ttl(sbs.get_filtered_components_for_ttl())
    assert len(kept) == 2

    # Drop the WindTurbine: both links reference it, so both disappear.
    st.session_state.scenario_components[0]["attributes"]["manufacturer"]["value"] = ""
    kept = sbs.get_filtered_links_for_ttl(sbs.get_filtered_components_for_ttl())
    assert kept == []


@pytest.mark.parametrize("unit_str, expected", [
    # Mapped entries.
    ("MW", "<http://qudt.org/vocab/unit/MegaW>"),
    ("kW", "<http://qudt.org/vocab/unit/KiloW>"),
    ("kWh", "<http://qudt.org/vocab/unit/KiloW-HR>"),
    ("m/s", "<http://qudt.org/vocab/unit/M-PER-SEC>"),
    ("°C", "<http://qudt.org/vocab/unit/DEG_C>"),
    ("kg CO2/kWh", "<http://qudt.org/vocab/unit/KiloGM-PER-KiloW-HR>"),
    # Pseudo-units all collapse to UNITLESS.
    ("text", "<http://qudt.org/vocab/unit/UNITLESS>"),
    ("category", "<http://qudt.org/vocab/unit/UNITLESS>"),
    ("temporal", "<http://qudt.org/vocab/unit/UNITLESS>"),
    ("dimensionless", "<http://qudt.org/vocab/unit/UNITLESS>"),
    # Unknown units are synthesized: / -> -PER-, superscript 2 -> 2, space -> -.
    ("kWh/m²", "<http://qudt.org/vocab/unit/kWh-PER-m2>"),
    ("odd unit", "<http://qudt.org/vocab/unit/odd-unit>"),
])
def test_map_unit_to_uri(unit_str, expected):
    assert sbs.map_unit_to_uri(unit_str) == expected


def test_resolve_event_attribute(scenario_state):
    """EventAttribute resolution returns the temporal value, not 'value'."""
    value, unit, data = sbs.resolve_enhanced_attribute_value(
        st.session_state.scenario_components[0], "commissioningDate")
    assert value == "2020-05"
    assert unit == "temporal"
    assert data["temporal_precision"] == "YearMonth"


def test_resolve_categorical_attribute(scenario_state):
    value, unit, _ = sbs.resolve_enhanced_attribute_value(
        st.session_state.scenario_components[0], "turbineClass")
    assert value == "IEC Class II"
    assert unit == "category"


def test_resolve_nested_promotes_to_dynamic(scenario_state):
    """Resolving the base attribute of a component with nested TimeSeries
    properties merges those properties in and re-types it DynamicAttribute."""
    value, unit, data = sbs.resolve_enhanced_attribute_value(
        st.session_state.scenario_components[1], "Power")
    assert value == "timeseries"
    assert unit == "kW"
    assert data["attribute_type"] == "DynamicAttribute"
    assert data["hasHistoricTimeSeriesReference"] == "resources/demand.csv"

    # And the dotted path resolves the nested property directly; the unit
    # reported is the merged base attribute's unit, not the 'text' default.
    nested, nested_unit, _ = sbs.resolve_enhanced_attribute_value(
        st.session_state.scenario_components[1],
        "Power.hasHistoricTimeSeriesReference")
    assert nested == "resources/demand.csv"
    assert nested_unit == "kW"


def test_resolve_missing_attribute_returns_none_triple(scenario_state):
    assert sbs.resolve_enhanced_attribute_value(
        st.session_state.scenario_components[0], "noSuchAttr") == (None, None, None)


def test_enhanced_attribute_declaration_lines(scenario_state):
    """The standalone declaration helper, pinned line by line (it emits TTL
    fragments, not a parseable document). Booleans hit the isinstance(int)
    branch and come out as xsd:decimal — current behavior, pinned on purpose."""
    lines = []
    sbs.generate_enhanced_attribute_declaration(
        lines, f"{WT_URI}/hubHeight", "hubHeight",
        {"value": 120, "unit": "m", "attribute_type": "PhysicalAttribute"},
        120, "m", SCENARIO_URI, "ttl_use_case")
    assert lines == [
        f"<{WT_URI}/hubHeight> a dici_onto:hubHeight ;",
        "    a dici_onto:PhysicalAttribute ;",
        '    dici_onto:sourceType "ttl_use_case" ;',
        '    qudt:value "120"^^xsd:decimal ;',
        "    qudt:unit <http://qudt.org/vocab/unit/M> ;",
        f"    dici_onto:usedInScenario <{SCENARIO_URI}> .",
        "",
    ]

    lines = []
    sbs.generate_enhanced_attribute_declaration(
        lines, f"{WT_URI}/isOffshore", "isOffshore",
        {"value": True, "unit": "dimensionless",
         "attribute_type": "PhysicalAttribute"},
        True, "dimensionless", SCENARIO_URI, "ttl_use_case")
    assert '    qudt:value "True"^^xsd:decimal ;' in lines


def test_time_series_resources_deduplicate(scenario_state):
    """Two components pointing at the same TimeSeries URI produce one resource
    block with merged properties."""
    second = _demand_profile()
    second["uri"] = EDP_URI + "_b"
    components = [_demand_profile(), second]

    lines = []
    sbs.generate_time_series_resources(lines, components, SCENARIO_URI)
    ts_headers = [l for l in lines if l.startswith("<")]
    assert ts_headers == [
        "<https://digicities.info/proj/ws_golden/ts/demand> a dici_onto:TimeSeries ;"
    ]
    assert '    dici_onto:storedAt "resources/demand.csv"^^xsd:string ;' in lines
    assert "    qudt:unit <http://qudt.org/vocab/unit/KiloW> ;" in lines
