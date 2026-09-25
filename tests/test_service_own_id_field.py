# SPDX-License-Identifier: Apache-2.0
"""A running service can name the field that carries an instance's own id.

The building-comfort service identifies each room by ``room_id`` ("101") and
echoes it in its result. The template only ever sent a room's full URI, so a
payload could never satisfy that contract although the folder had every id.
A ``"<path>|label|Static"`` custom name now sends the instance's label (its id
when it has none) under the service's field name, in a root block and in a
nested one, and survives a parse -> regenerate round trip.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("yaml")

import yaml  # noqa: E402

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402
from backend.scenario_builder import emitter  # noqa: E402
from backend.scenario_builder.draft import ScenarioDraft  # noqa: E402
from backend.service_requirements import (  # noqa: E402
    build_service_template,
    entries_from_type_tree,
)
from backend.service_requirements.template import parse_service_template  # noqa: E402

WS = "own_id_ws"
BLD = f"https://digicities.info/proj/{WS}/Building/B42"
ROOMS = [f"https://digicities.info/proj/{WS}/Room/{r}" for r in ("101", "102")]


def _entries():
    return entries_from_type_tree([
        ("Building", None, ["ComfortBand"]),
        ("Room", "Building", ["FloorArea"]),
    ])


def _template(custom=None):
    return build_service_template("comfort", _entries(), custom_field_names=custom)


def test_nothing_changes_without_a_custom_id_name():
    sd = _template()["scenario_data"]
    assert sd["building"]["name"] == "Building.label"
    assert "label" not in str(sd["building"]["room"]["template"])


def test_a_nested_block_gains_the_id_field():
    sd = _template({"room|label|Static": "room_id"})["scenario_data"]
    assert sd["building"]["room"]["template"]["room_id"] == "Room.label"


def test_a_root_block_keeps_name_and_gains_the_id_field():
    sd = _template({"building|label|Static": "building_id"})["scenario_data"]
    assert sd["building"]["name"] == "Building.label"          # still parsed as a component
    assert sd["building"]["building_id"] == "Building.label"


def test_the_field_survives_a_parse_regenerate_round_trip():
    custom = {"room|label|Static": "room_id"}
    text = yaml.safe_dump(_template(custom))
    name, entries, description, connection = parse_service_template(text)
    again = build_service_template(name, entries, custom_field_names=custom)
    assert again["scenario_data"]["building"]["room"]["template"]["room_id"] == "Room.label"


def test_the_payload_carries_each_rooms_own_id():
    comps = [{"uri": BLD, "type": "Building", "label": "Riverside", "source": "t",
              "workspace_id": WS,
              "attributes": {"ComfortBand": {"value": 2.0, "unit": "K",
                                             "attribute_type": "PhysicalAttribute"}}}]
    for uri in ROOMS:
        comps.append({"uri": uri, "type": "Room", "label": uri.rsplit("/", 1)[-1],
                      "source": "t", "workspace_id": WS,
                      "attributes": {"FloorArea": {"value": 24, "unit": "m2",
                                                   "attribute_type": "PhysicalAttribute"}}})
    draft = ScenarioDraft(
        scenario_name="Own id", workspace_id=WS, workspace_name="Own id",
        service_name="comfort", ttl_specificity="High",
        required_attributes={"Building": ["ComfortBand"], "Room": ["FloorArea"]},
        components=comps,
        links=[{"source": "scenario", "target": BLD, "link_type": "scenario_automatic"}]
        + [{"source": BLD, "target": r, "link_type": "contains"} for r in ROOMS])
    payload = convert_scenario(_template({"room|label|Static": "room_id"}),
                               emitter.generate_full_ttl(draft))
    rooms = payload["scenario_data"]["building"][0]["room"]
    assert sorted(r["room_id"] for r in rooms) == ["101", "102"]
