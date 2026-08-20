# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Direct tests for backend.service_requirements — the headless half of the
Service Requirements Builder.

The characterization tests (test_characterize_service_requirements.py) pin the
generator through the OLD Streamlit import path against goldens; these drive
the backend package directly, including the paths the REST API took over from
its hand-written f-strings: the rdflib-built requirements TTL (hostile labels
must be escaped by the serializer, never break the document) and the
type-tree → template pipeline.
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
import yaml  # noqa: E402

from backend.service_requirements import (  # noqa: E402
    build_service_template,
    entries_from_type_tree,
    parse_yaml_to_components,
    requirements_ttl,
    service_file_id,
)

BASE = "https://digicities.info/proj/ws1/services/"
DICI = "https://digicities.info/ontology#"


# ── requirements TTL ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("label", [
    'the "flexible" one',
    "line one\nline two",
    "unicode: Zürich ↔ Dübendorf 🏙",
    'backslash \\ and "both"',
])
def test_requirements_ttl_hostile_labels_roundtrip(label):
    ttl = requirements_ttl("Svc", label, [("Building", ["floorArea"])], [], BASE)
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    got = [str(o) for o in g.objects(rdflib.URIRef(f"{BASE}Svc"), rdflib.RDFS.label)]
    assert got == [label]


def test_requirements_ttl_numbers_attr_reqs_before_links():
    ttl = requirements_ttl(
        "Svc", "",
        [("Building", ["floorArea", "height"]), ("HeatPump", ["cop"])],
        [("Location", "Building")],
        BASE,
    )
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    attr_req = rdflib.URIRef(DICI + "ComponentAttributeRequirement")
    link_req = rdflib.URIRef(DICI + "ComponentComponentRequirement")
    attr_nodes = {str(s) for s in g.subjects(rdflib.RDF.type, attr_req)}
    link_nodes = {str(s) for s in g.subjects(rdflib.RDF.type, link_req)}
    assert attr_nodes == {f"{BASE}req_1", f"{BASE}req_2", f"{BASE}req_3"}
    assert link_nodes == {f"{BASE}req_4"}
    # the link requirement names both endpoint classes
    ents = {str(o) for o in g.objects(rdflib.URIRef(f"{BASE}req_4"),
                                      rdflib.URIRef(DICI + "hasInputEntity"))}
    assert ents == {DICI + "Location", DICI + "Building"}


def test_requirements_ttl_empty_label_falls_back_to_name():
    ttl = requirements_ttl("my flex service", "", [], [], BASE)
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    svc = rdflib.URIRef(f"{BASE}MyFlexService")
    assert [str(o) for o in g.objects(svc, rdflib.RDFS.label)] == ["my flex service"]


def test_service_file_id_shape():
    assert service_file_id("my flex service") == "MyFlexService"
    assert service_file_id("x" * 60) == "X" + "x" * 39  # capped at 40
    assert service_file_id("") == "Service"
    # no word characters: pascal_case falls back to the input unchanged
    # (same as the API's old _pascal did)
    assert service_file_id("!!!") == "!!!"


# ── type tree → template ──────────────────────────────────────────────────────
def _tree():
    return [
        ("Building", None, ["floorArea"]),
        ("HeatPump", "Building", ["cop"]),
        ("Sensor", "HeatPump", ["reading"]),      # grandchild
        ("Ghost", "NotThere", ["x"]),             # orphan parent: dropped
    ]


def test_entries_from_type_tree_levels_and_links():
    entries = entries_from_type_tree(_tree())
    by_type = {e.component_type: e for e in entries}
    assert by_type["Building"].level == 1
    assert by_type["HeatPump"].level == 2
    assert by_type["Sensor"].level == 3
    assert by_type["HeatPump"].link_pattern == "CL.Building.HeatPump"
    assert by_type["Sensor"].link_pattern == "CL.HeatPump.Sensor"


def test_build_service_template_nests_grandchildren():
    doc = build_service_template(
        "demo", entries_from_type_tree(_tree()),
        description="d", connection={"url": "http://svc:9/run"})
    sd = doc["scenario_data"]
    building = sd["building"]
    assert building["uri"] == "Building.URI"
    hp = building["heatPump"]
    assert hp["link"] == "CL.Building.HeatPump"
    assert hp["template"]["cop"] == "HeatPump.cop"
    # a grandchild hangs off the child NODE (sibling of link/template), the
    # convention the shipped templates use — pinned by the characterization golden
    sensor = hp["sensor"]
    assert sensor["link"] == "CL.HeatPump.Sensor"
    assert sensor["template"]["reading"] == "Sensor.reading"
    assert "ghost" not in sd and "ghost" not in building


def test_parent_cycle_terminates():
    cyc = [("A", "B", []), ("B", "A", [])]
    entries = entries_from_type_tree(cyc)   # must not recurse forever
    doc = build_service_template("demo", entries)
    assert set(doc["scenario_data"]) == {"uri", "label"}  # no root → nothing rendered


def test_template_roundtrip_through_parser():
    doc = build_service_template("demo", entries_from_type_tree(_tree()))
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    name, parsed = parse_yaml_to_components(text)
    assert name == "demo"
    assert any(e.component_type == "Building" and e.level == 1 for e in parsed)
    assert any(e.component_type == "HeatPump" and e.level == 2
               and e.link_pattern == "CL.Building.HeatPump" for e in parsed)
    assert any(e.component_type == "Sensor" and e.level == 3 for e in parsed)
