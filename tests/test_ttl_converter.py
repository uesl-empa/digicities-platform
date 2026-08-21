# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Tests for ``backend.api_submission.ttl_converter.convert_scenario``.

The whole submission pipeline flows through this converter: it walks a
scenario's ComponentLink graph and applies a service template's attribute →
ontology-term mapping to produce the payload a service receives.

The fixtures are built with the platform's own machinery so the conventions
are the real ones, not hand-approximations:

* the service template comes from ``backend.service_requirements``
  (``entries_from_type_tree`` + ``build_service_template``) — the CL.X.Y link
  patterns and ``<Type>.<attr>`` references the shipped templates use;
* the scenario TTL comes from ``backend.scenario_builder.emitter`` driven by a
  ``ScenarioDraft`` — the same graph shape the Scenario Builder publishes
  (``has<Type><attr>Attribute`` predicates, ComponentLink nodes, dual-typed
  attribute instances).
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("yaml")

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402
from backend.scenario_builder import emitter  # noqa: E402
from backend.scenario_builder.draft import ScenarioDraft  # noqa: E402
from backend.service_requirements import (  # noqa: E402
    build_service_template,
    entries_from_type_tree,
)

WS = "convert_ws"
BLD_URI = f"https://digicities.info/proj/{WS}/Building/B1"
HP_URI = f"https://digicities.info/proj/{WS}/HeatPump/HP1"
HP2_URI = f"https://digicities.info/proj/{WS}/HeatPump/HP_unlinked"


def _template() -> dict:
    """A real generated template: Building root (floorArea + extras) with a
    HeatPump child (cop) hanging off a CL.Building.HeatPump link."""
    entries = entries_from_type_tree([
        ("Building", None, ["floorArea", "heatingSupply", "commissioningDate",
                            "manufacturer", "height"]),
        ("HeatPump", "Building", ["cop"]),
    ])
    return build_service_template(
        "demo_service", entries,
        description="test description",
        connection={"url": "http://svc:9000/run", "transport": "http"},
    )


def _building() -> dict:
    return {
        "uri": BLD_URI,
        "type": "Building",
        "label": "Building One",
        "source": "ttl_use_case",
        "workspace_id": WS,
        "attributes": {
            "floorArea": {"value": 420.5, "unit": "m",
                          "attribute_type": "PhysicalAttribute"},
            "manufacturer": {"value": "ACME", "unit": "text",
                             "attribute_type": "PhysicalAttribute"},
            "heatingSupply": {"value": "ElectricallyHeated",
                              "category_value": "ElectricallyHeated",
                              "unit": "category",
                              "attribute_type": "CategoricalAttribute"},
            "commissioningDate": {"value": "2019-06",
                                  "temporal_value": "2019-06",
                                  "temporal_precision": "YearMonth",
                                  "unit": "temporal",
                                  "attribute_type": "EventAttribute"},
            # note: no "height" attribute — the template asks for it anyway
        },
    }


def _heat_pump(uri: str = HP_URI, label: str = "Heat Pump One") -> dict:
    return {
        "uri": uri,
        "type": "HeatPump",
        "label": label,
        "source": "ttl_use_case",
        "workspace_id": WS,
        "attributes": {
            "cop": {"value": 3.5, "unit": "dimensionless",
                    "attribute_type": "PhysicalAttribute"},
        },
    }


# The emitter only writes attributes named here — the Scenario Builder's
# "required attributes" contract — so list everything the template reads.
REQUIRED = {
    "Building": ["floorArea", "manufacturer", "heatingSupply",
                 "commissioningDate"],
    "HeatPump": ["cop"],
}


def _scenario_ttl(extra_components=(), extra_links=()) -> str:
    required = REQUIRED
    draft = ScenarioDraft(
        scenario_name="Convert Scenario",
        workspace_id=WS,
        workspace_name="Convert Workspace",
        service_name="demo_service",
        ttl_specificity="High",
        required_attributes=required,
        components=[_building(), _heat_pump(), *extra_components],
        links=[
            {"source": "scenario", "target": BLD_URI,
             "link_type": "scenario_automatic"},
            {"source": BLD_URI, "target": HP_URI, "link_type": "contains"},
            *extra_links,
        ],
    )
    return emitter.generate_full_ttl(draft)


@pytest.fixture(scope="module")
def payload():
    return convert_scenario(_template(), _scenario_ttl())


# ── header fields ────────────────────────────────────────────────────────────
def test_service_name_and_description_pass_through(payload):
    assert payload["service_name"] == "demo_service"
    assert payload["description"] == "test description"


def test_connection_block_is_stripped_from_payload(payload):
    """'connection' is registration metadata, never part of the payload."""
    assert "connection" not in payload


def test_scenario_uri_and_label_resolve(payload):
    sd = payload["scenario_data"]
    assert sd["uri"] == f"https://digicities.info/proj/{WS}/Convert_Scenario"
    assert sd["label"] == "Convert Scenario"


# ── root component resolution ────────────────────────────────────────────────
def test_root_component_resolves_as_array_with_uri_name(payload):
    buildings = payload["scenario_data"]["building"]
    assert isinstance(buildings, list) and len(buildings) == 1
    assert buildings[0]["uri"] == BLD_URI
    assert buildings[0]["name"] == "Building One"


def test_scalar_attribute_resolves_to_typed_python_value(payload):
    b = payload["scenario_data"]["building"][0]
    assert b["floorArea"] == 420.5  # xsd:decimal → float
    assert b["manufacturer"] == "ACME"  # string literal stays str


def test_categorical_attribute_resolves_to_category_value(payload):
    """The category class (not the attribute's own kind class) is the value."""
    b = payload["scenario_data"]["building"][0]
    assert b["heatingSupply"] == "ElectricallyHeated"


def test_event_attribute_resolves_to_year_date(payload):
    b = payload["scenario_data"]["building"][0]
    assert b["commissioningDate"] == "01-01-2019"


def test_missing_attribute_is_omitted(payload):
    """The template asks for Building.height; the instance has no height
    attribute, so the key is dropped rather than emitted as null."""
    assert "height" not in payload["scenario_data"]["building"][0]


# ── CL.Parent.Child link walking ─────────────────────────────────────────────
def test_child_link_resolves_linked_component(payload):
    hps = payload["scenario_data"]["building"][0]["heatPump"]
    assert isinstance(hps, list) and len(hps) == 1
    assert hps[0]["uri"] == HP_URI
    assert hps[0]["cop"] == 3.5


def test_unlinked_component_of_right_type_is_excluded():
    """A second HeatPump instance with no ComponentLink to the Building must
    not appear in the CL.Building.HeatPump results."""
    ttl = _scenario_ttl(extra_components=[_heat_pump(HP2_URI, "Unlinked HP")])
    result = convert_scenario(_template(), ttl)
    hps = result["scenario_data"]["building"][0]["heatPump"]
    assert [hp["uri"] for hp in hps] == [HP_URI]


def test_reverse_direction_link_also_resolves():
    """Link direction is symmetric: HeatPump→Building resolves the same as
    Building→HeatPump."""
    draft = ScenarioDraft(
        scenario_name="Convert Scenario", workspace_id=WS,
        workspace_name="Convert Workspace",
        required_attributes=REQUIRED,
        components=[_building(), _heat_pump()],
        links=[
            {"source": "scenario", "target": BLD_URI,
             "link_type": "scenario_automatic"},
            {"source": HP_URI, "target": BLD_URI, "link_type": "serves"},
        ],
    )
    result = convert_scenario(_template(), emitter.generate_full_ttl(draft))
    hps = result["scenario_data"]["building"][0]["heatPump"]
    assert [hp["uri"] for hp in hps] == [HP_URI]


# ── cleaning and error behavior ──────────────────────────────────────────────
def test_cleaning_drops_uri_label_placeholders_only():
    """Pin the cleaner's exact contract: unresolved ``.URI``/``.label``
    placeholders are dropped, but a plain ``<Type>.<attr>`` reference that
    found no component passes through as its literal string (clean or not)."""
    template = _template()
    template["scenario_data"]["ghost"] = {"uri": "Ghost.URI",
                                          "power": "Ghost.power"}
    ttl = _scenario_ttl()

    raw = convert_scenario(template, ttl, clean=False)
    assert raw["scenario_data"]["ghost"] == {"uri": "Ghost.URI",
                                             "power": "Ghost.power"}

    cleaned = convert_scenario(template, ttl)
    assert cleaned["scenario_data"]["ghost"] == {"power": "Ghost.power"}


def test_no_scenario_in_ttl_raises():
    ttl = """
    @prefix dici_onto: <https://digicities.info/ontology#> .
    <urn:b1> a dici_onto:Building .
    """
    with pytest.raises(ValueError, match="No scenario found"):
        convert_scenario(_template(), ttl)
