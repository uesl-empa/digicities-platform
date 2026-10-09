# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The headless TTL use-case loader (``backend.scenario_builder.use_case_loader``).

Drives the backend class directly — no Streamlit, no session state — against a
small fixture data product covering the attribute flavors the extractors
handle (physical + QUDT unit, costs/currency, categorical, dynamic time
series with nested properties, curve, temporal event). The extracted
structure is pinned as golden JSON.

Also pins the parameterized seams introduced by the Phase 4a move:
* the default (no ``on_status`` callback) is silent and never raises;
* an injected duck-typed data processor powers the data-product paths;
* ``enabled_data_products`` is an explicit argument, no session state;
* QUDT unit *codes* round-trip (``KiloW``, never ``kW``) — the same
  semantics ``tests/test_unit_code_roundtrip.py`` guards via the shim.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from backend.scenario_builder.use_case_loader import NextCloudTTLUseCaseLoader
from tests.golden import assert_json_golden

# The data product as a replica writes it: components link to their attributes.
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "use_case_data_product_linked.ttl"
FIXTURE_TTL = FIXTURE.read_text(encoding="utf-8")


def _loader(**kwargs) -> NextCloudTTLUseCaseLoader:
    kwargs.setdefault("ontology", _extension())
    return NextCloudTTLUseCaseLoader(workspace_id="test-ws", **kwargs)


class FakeDataProcessor:
    """Duck-typed stand-in for the Streamlit-side DataProductProcessor."""

    def __init__(self, ttl: str):
        self._ttl = ttl
        self.process_calls = []

    def list_private_folders(self):
        return ["battery_fixture"]

    def list_open_folders(self):
        return ["shared_fixture"]

    def process_data_product(self, name, is_private=True):
        self.process_calls.append((name, is_private))
        return {"ttl_content": self._ttl}


# ---------------------------------------------------------------- extraction

# The workspace extension the fixture's categorical attribute belongs to: the
# attribute class under CategoricalAttribute, the value a named individual of it.
EXTENSION_TTL = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:Battery rdfs:subClassOf dici_onto:EnergyStorage .
dici_onto:Building rdfs:subClassOf dici_onto:EnergyConsumer .
dici_onto:ChemistryType rdfs:subClassOf dici_onto:CategoricalAttribute .
dici_onto:LithiumIon a owl:NamedIndividual, dici_onto:ChemistryType .
"""


def _extension() -> Graph:
    return Graph().parse(data=EXTENSION_TTL, format="turtle")


def test_extracted_structure_matches_golden():
    """The full extracted component structure, pinned.

    Read against the workspace extension, as a real build is: the categorical
    attribute's value is the named individual of its attribute class, and the
    categorical attribute node is never mistaken for a component.
    """
    loader = _loader()
    graph = Graph()
    graph.parse(data=FIXTURE_TTL, format="turtle")

    components = loader.extract_components_from_graph(graph, "fixture")
    assert_json_golden(components, "use_case_loader_components.json")


def test_kinds_and_components_come_from_the_hierarchy_not_the_names():
    """Without the extension nothing is guessed from spelling.

    The old loader matched type names: any type containing "Height", "Cost",
    "Curve" ... was an attribute, and the category value was the type whose
    name differed from the URI fragment. Here an attribute class named like a
    component and a component class named like an attribute are told apart by
    the hierarchy alone, and an unplaced categorical value stays unknown.
    """
    from backend.ontology_kinds import AttributeKind

    ttl = """
    @prefix dici_onto: <https://digicities.info/ontology#> .
    @prefix qudt: <http://qudt.org/schema/qudt/> .
    @prefix unit: <http://qudt.org/vocab/unit/> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    dici_onto:CostCentre rdfs:subClassOf dici_onto:EnergyConsumer .
    dici_onto:Rotor rdfs:subClassOf dici_onto:TurbineAttribute .
    <https://x.org/CostCentre/c1> a dici_onto:CostCentre ;
        dici_onto:hasRotorAttribute <https://x.org/CostCentre/c1/Rotor> ;
        dici_onto:hasAttribute <https://x.org/CostCentre/c1/Kind> .
    <https://x.org/CostCentre/c1/Rotor> a dici_onto:Rotor, dici_onto:PhysicalAttribute ;
        qudt:value "3.0" ; qudt:unit unit:M .
    <https://x.org/CostCentre/c1/Kind> a dici_onto:CategoricalAttribute,
        dici_onto:KindType, dici_onto:Special .
    """
    msgs = []
    loader = _loader(on_status=lambda level, message: msgs.append(message), ontology=None)
    out = loader.extract_components_from_graph(Graph().parse(data=ttl, format="turtle"), "t")

    # "CostCentre" contains "Cost": still a component. "Rotor" is no component.
    assert sorted(out) == ["CostCentre"]
    attrs = out["CostCentre"][0]["attributes"]
    assert attrs["Rotor"]["attribute_type"] is AttributeKind.PHYSICAL
    assert attrs["Kind"]["attribute_type"] is AttributeKind.CATEGORICAL
    assert attrs["Kind"]["category_value"] == "Unknown"
    assert any("categorical value" in m for m in msgs)


def test_unit_strings_are_qudt_codes_never_abbreviations():
    """Same load-bearing semantics as tests/test_unit_code_roundtrip.py."""
    loader = _loader()
    assert loader._map_unit_uri_to_string("http://qudt.org/vocab/unit/KiloW") == "KiloW"
    assert loader._map_unit_uri_to_string("http://qudt.org/vocab/unit/KiloW-HR") == "KiloW-HR"
    assert loader._map_unit_uri_to_string("unit:KiloW-HR") == "KiloW-HR"
    assert loader._map_unit_uri_to_string("unit:KiloW") != "kW"
    # Absences render as '', never a made-up code (see backend.units).
    assert loader._map_unit_uri_to_string("unit:None") == ""

    graph = Graph()
    graph.parse(data=FIXTURE_TTL, format="turtle")
    battery = loader.extract_components_from_graph(graph, "fixture")["Battery"][0]
    assert battery["attributes"]["StorageCapacity"]["unit"] == "KiloW-HR"
    assert battery["attributes"]["ChargeEfficiencyCurve"]["y_unit"] == ""


# ------------------------------------------------------------ callback seam

def test_no_callback_default_is_silent(capsys):
    """Without on_status, degraded paths stay quiet and never raise."""
    loader = NextCloudTTLUseCaseLoader()  # no workspace at all
    assert loader.nextcloud_client is None
    assert loader.data_processor is None
    assert loader.get_available_private_data_products() == []
    assert loader.get_components_by_type("Battery") == []
    assert loader.load_data_product_ttl({"name": "x", "type": "private"}) is None
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_on_status_reports_the_old_streamlit_messages():
    events = []
    loader = NextCloudTTLUseCaseLoader(
        on_status=lambda level, message: events.append((level, message)))
    assert events == [("warning", "⚠️ No workspace available for TTL loading")]

    # Missing data processor for a requested data product -> the old warning.
    loader.workspace_id = "test-ws"
    loader.load_data_product_ttl({"name": "dp1", "type": "private"})
    assert events[-1] == ("warning", "Data processor not available for dp1")


# ----------------------------------------------------- data-product plumbing

def test_injected_data_processor_drives_data_product_listing():
    fake = FakeDataProcessor(FIXTURE_TTL)
    loader = _loader(data_processor=fake)

    private = loader.get_available_private_data_products()
    assert private == [{
        "name": "battery_fixture",
        "path": "test-ws/private_data_products/battery_fixture",
        "type": "private",
        "workspace": "test-ws",
        "description": "Private data product: battery_fixture",
    }]
    assert [dp["name"] for dp in loader.get_available_global_data_products()] \
        == ["shared_fixture"]


def test_components_from_data_product_stamp_provenance():
    fake = FakeDataProcessor(FIXTURE_TTL)
    loader = _loader(data_processor=fake)

    by_type = loader.get_components_from_data_product(
        {"name": "battery_fixture", "type": "private"})
    battery = by_type["Battery"][0]
    assert battery["source"] == "data_product"
    assert battery["data_product_name"] == "battery_fixture"
    assert battery["data_product_type"] == "private"
    assert battery["workspace_id"] == "test-ws"
    assert battery["source_file"] == "data_product_private_battery_fixture"
    assert fake.process_calls == [("battery_fixture", True)]

    # A global product is attributed to the 'global' workspace.
    loader2 = _loader(data_processor=FakeDataProcessor(FIXTURE_TTL))
    by_type2 = loader2.get_components_from_data_product(
        {"name": "shared_fixture", "type": "global"})
    assert by_type2["Battery"][0]["workspace_id"] == "global"


def test_enabled_data_products_is_an_explicit_argument():
    """No session state: callers name the enabled products; results are cached."""
    fake = FakeDataProcessor(FIXTURE_TTL)
    loader = _loader(data_processor=fake)

    assert loader.get_components_by_type("Battery") == []  # default: none enabled

    enabled = ["private:battery_fixture"]
    batteries = loader.get_components_by_type("Battery", enabled_data_products=enabled)
    assert [b["label"] for b in batteries] == ["Home Battery 1"]
    assert "Building" in loader.get_all_component_types(enabled_data_products=enabled)

    # Second identical call is served from cache — the processor isn't re-asked.
    calls_before = len(fake.process_calls)
    assert loader.get_components_by_type("Battery", enabled_data_products=enabled) \
        == batteries
    assert len(fake.process_calls) == calls_before


# ------------------------------------------------------------------- shim

def test_streamlit_shim_subclasses_the_backend_loader():
    """The old import path serves a subclass with identical unit semantics."""
    from components.scenario_builder.ttl_use_case_loader import (
        NextCloudTTLUseCaseLoader as ShimLoader,
    )

    assert issubclass(ShimLoader, NextCloudTTLUseCaseLoader)
    assert ShimLoader._map_unit_uri_to_string \
        is NextCloudTTLUseCaseLoader._map_unit_uri_to_string
    assert ShimLoader.extract_components_from_graph \
        is NextCloudTTLUseCaseLoader.extract_components_from_graph


def test_attributes_come_from_links_not_uri_paths():
    """An attribute node the component does not link to is not its attribute,
    however its IRI is spelt; the old loader took every <component>/<name>
    node. A class the hierarchy cannot place is reported and skipped, never
    guessed to be a component."""
    ttl = """
    @prefix dici_onto: <https://digicities.info/ontology#> .
    @prefix qudt: <http://qudt.org/schema/qudt/> .
    <https://x.org/Building/b1> a dici_onto:Building ;
        dici_onto:hasAttribute <https://x.org/elsewhere/Area> .
    <https://x.org/elsewhere/Area> a dici_onto:PhysicalAttribute ; qudt:value "10" .
    <https://x.org/Building/b1/Height> a dici_onto:PhysicalAttribute ; qudt:value "3" .
    <https://x.org/Gizmo/g1> a dici_onto:Gizmo .
    """
    msgs = []
    loader = _loader(on_status=lambda level, message: msgs.append(message))
    out = loader.extract_components_from_graph(Graph().parse(data=ttl, format="turtle"), "t")
    assert sorted(out) == ["Building"]
    assert sorted(out["Building"][0]["attributes"]) == ["Area", "URI", "label"]
    assert any("Gizmo" in m and "not placed" in m for m in msgs)
