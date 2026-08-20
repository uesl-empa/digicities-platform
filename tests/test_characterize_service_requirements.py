# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Characterization tests for the Service Requirements Builder YAML logic.

``components.service_requirements_builder`` is headed for extraction to
``backend/``; these tests pin what it does today. Three things are pinned:

* ``generate_yaml_structure`` — the exact service-template structure the UI
  assembles (golden YAML, compared as parsed structure)
* the round trip — a generated template fed back through
  ``parse_yaml_to_components`` must reconstruct the same component model
* ``validate_component_attributes`` — the validation report shape (golden JSON)

The module reads ``st.session_state``; tests swap in a dict subclass with
attribute access. All inputs are fixed; nothing touches the network or a
triplestore.
"""
from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("rdflib")
st = pytest.importorskip("streamlit")
yaml = pytest.importorskip("yaml")

from components import service_requirements_builder as srb  # noqa: E402
from components.service_requirements_builder import ComponentEntry  # noqa: E402

from tests.golden import assert_json_golden, assert_yaml_golden  # noqa: E402


class _MockState(dict):
    """st.session_state stand-in: a dict with attribute access."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value


def _entries():
    """A root Region with a nested Building child, mirroring what the UI
    assembles: static attributes plus a dynamic attribute with two
    time-series flavors."""
    return [
        ComponentEntry(
            path="region",
            component_type="Region",
            link_pattern="",
            parent_path="",
            level=1,
            configured_attributes={"label": ["Static"], "area": ["Static"]},
        ),
        ComponentEntry(
            path="buildings",
            component_type="Building",
            link_pattern="CL.Region.Building",
            parent_path="region",
            level=2,
            configured_attributes={
                "label": ["Static"],
                "floorArea": ["Static"],
                "power": ["Historic", "Live"],
            },
        ),
    ]


def _builder_state(**overrides):
    state = _MockState({
        "service_name": "golden_service",
        "service_description": "Characterization fixture service",
        "service_connection": {"protocol": "redis", "host": "localhost",
                               "port": 6379},
        "component_entries": _entries(),
        "custom_field_names": {},
        "ontology_components": {},
        "ontology_attributes": {},
        "graphdb_components": {},
        "graphdb_attributes": {},
        "component_attribute_mappings": {},
    })
    state.update(overrides)
    return state


@pytest.fixture()
def builder_state(monkeypatch):
    state = _builder_state()
    monkeypatch.setattr(st, "session_state", state)
    return state


def test_yaml_structure_golden(builder_state):
    """The generated service template, pinned as a golden. Covers the metadata
    block (description, connection), the scenario_data header, root component
    name/uri fields, the child link/template block, and the *_historic/_live
    field naming for dynamic attributes."""
    structure = srb.generate_yaml_structure()
    assert structure, "generator returned an empty structure"
    assert_yaml_golden(yaml.safe_dump(structure, sort_keys=False),
                       "service_requirements_structure.yaml")


def test_yaml_structure_empty_without_service_name(builder_state):
    st.session_state.service_name = ""
    assert srb.generate_yaml_structure() == {}


def test_custom_field_names_rename_fields(builder_state):
    """A custom field name replaces the default field key but keeps the same
    reference string, so the semantic target is unchanged."""
    st.session_state.custom_field_names = {
        "buildings|power|Historic": "power_measured",
    }
    # Children nest INSIDE their parent's block, keyed by their own path.
    structure = srb.generate_yaml_structure()
    template = structure["scenario_data"]["region"]["buildings"]["template"]
    assert "power_historic" not in template
    assert template["power_measured"] == "Building.power.hasHistoricTimeSeriesReference"
    # use_custom_names=False restores the default naming.
    structure = srb.generate_yaml_structure(use_custom_names=False)
    template = structure["scenario_data"]["region"]["buildings"]["template"]
    assert template["power_historic"] == "Building.power.hasHistoricTimeSeriesReference"


def test_round_trip_preserves_component_model(builder_state):
    """generate -> YAML text -> parse must reconstruct the same components.

    One known loss, pinned here: the generator skips every Static 'label'
    before the level check, so a CHILD component's label never reaches its
    template and the round trip drops it (the root keeps its label through the
    'name' field). The parser appends children before their parent, so order is
    compared path-sorted. Dataclass equality covers path, type, link pattern,
    parent, level, and the full attribute/type map.
    """
    yaml_text = yaml.safe_dump(srb.generate_yaml_structure(), sort_keys=False)
    service_name, parsed = srb.parse_yaml_to_components(yaml_text)

    assert service_name == "golden_service"

    expected = _entries()
    building = next(e for e in expected if e.path == "buildings")
    del building.configured_attributes["label"]  # the pinned round-trip loss

    key = lambda e: e.path  # noqa: E731
    assert sorted(parsed, key=key) == sorted(expected, key=key)


def test_round_trip_survives_custom_field_names(builder_state):
    """Custom field names don't break the round trip: the parser recovers the
    canonical attribute name and type from the reference string."""
    st.session_state.custom_field_names = {
        "buildings|power|Historic": "power_measured",
    }
    yaml_text = yaml.safe_dump(srb.generate_yaml_structure(), sort_keys=False)
    _, parsed = srb.parse_yaml_to_components(yaml_text)
    building = next(e for e in parsed if e.path == "buildings")
    assert building.configured_attributes["power"] == ["Historic", "Live"]


def test_parse_rejects_missing_service_name():
    with pytest.raises(ValueError):
        srb.parse_yaml_to_components("scenario_data: {}")


def test_extract_attributes_from_dict():
    """Reference strings map to (attribute, type); 'name' fields referencing
    label are normalized to 'label'; *_historic/_live/_future field suffixes
    win over the reference when classifying the type."""
    attrs = srb.extract_attributes_from_dict({
        "uri": "Building.URI",
        "name": "Building.label",
        "floorArea": "Building.floorArea",
        "power_historic": "Building.power.hasHistoricTimeSeriesReference",
        "power_live": "Building.power.hasLiveTimeSeriesReference",
        "forecast_future": "Building.forecast.hasFutureTimeSeriesReference",
    }, "Building")
    assert attrs == {
        "label": ["Static"],
        "floorArea": ["Static"],
        "power": ["Historic", "Live"],
        "forecast": ["Future"],
    }


def test_validation_report_golden(monkeypatch):
    """The full validation report for a mixed fixture: one valid component with
    one valid, one invalid attribute; one component unknown to the ontology.
    'label' is always valid without a mapping. Pinned as golden JSON."""
    state = _builder_state(
        ontology_components={"Region": object(), "Building": object()},
        component_attribute_mappings={
            "Region": ["area"],
            "Building": ["floorArea"],  # 'power' intentionally missing
        },
        component_entries=_entries() + [
            ComponentEntry(path="plants", component_type="FusionPlant",
                           link_pattern="CL.Region.FusionPlant",
                           parent_path="region", level=2,
                           configured_attributes={"output": ["Static"]}),
        ],
    )
    monkeypatch.setattr(st, "session_state", state)

    report = srb.validate_component_attributes()
    assert_json_golden(report, "service_requirements_validation.json")


def test_validation_empty_when_no_entries(monkeypatch):
    monkeypatch.setattr(st, "session_state", _builder_state(component_entries=[]))
    report = srb.validate_component_attributes()
    assert report["warnings"] == ["No components configured to validate"]
    assert report["summary"]["total_attributes"] == 0
