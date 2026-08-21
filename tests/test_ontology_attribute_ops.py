# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Tests for the Ontology Manager's attribute operations
(``backend.ontology_manager.functions.attribute_ops``).

``OntologyFunctions`` is constructed headlessly the same way the REST API
does it (``apps/api/ontology.py`` + ``deps.py``): a ``WorkspaceStorage``
rooted at a tmp workspace, no GraphDB client. Each test scaffolds a fresh
extension through the same backend path the extension/create endpoint uses,
edits it, and asserts on the resulting TTL with rdflib — never string
matching.
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import OWL, RDF, RDFS, Namespace, URIRef  # noqa: E402

from backend.ontology_manager import OntologyFunctions  # noqa: E402
from backend.workspace.storage import WorkspaceStorage  # noqa: E402

DICI = Namespace("https://digicities.info/ontology#")
UNIT = Namespace("http://qudt.org/vocab/unit/")
EXT = "test_ext.ttl"


@pytest.fixture()
def funcs(tmp_path):
    """Headless OntologyFunctions over a tmp workspace with one fresh extension."""
    of = OntologyFunctions(storage=WorkspaceStorage.local(str(tmp_path)),
                           workspace_id="test_ws")
    ok, msg = of.create_new_extension("test_ext")
    assert ok, msg
    ok, msg = of.load_extension_and_update(EXT)
    assert ok, msg
    return of


def _ext_graph(funcs) -> "rdflib.Graph":
    """Parse the persisted extension file — what actually got written to disk."""
    return funcs.load_extension(EXT)


# ── scaffolding ──────────────────────────────────────────────────────────────
def test_new_extension_is_listed_and_loadable(funcs):
    files = funcs.list_extension_files()
    assert EXT in files
    assert "CORE_ONTOLOGY_MODIFICATION" in files
    # temp working graph exists after load (merged with the core ontology)
    g = funcs._load_temp_graph(EXT)
    assert g is not None and len(g) > 0


# ── add_attribute variants ───────────────────────────────────────────────────
def test_add_physical_attribute_writes_class_and_unit(funcs):
    ok, msg = funcs.add_attribute(EXT, "Physical", "Roof Area", qudt_unit="M2")
    assert ok, msg
    g = _ext_graph(funcs)
    attr = DICI.RoofArea  # label whitespace collapses into the local name
    assert (attr, RDF.type, OWL.Class) in g
    assert (attr, RDFS.subClassOf, DICI.PhysicalAttribute) in g
    assert (attr, DICI.hasDefaultUnit, UNIT.M2) in g
    labels = [str(o) for o in g.objects(attr, RDFS.label)]
    assert labels == ["Roof Area"]


def test_add_physical_attribute_requires_unit(funcs):
    ok, msg = funcs.add_attribute(EXT, "Physical", "RoofArea")
    assert not ok
    assert "QUDT unit is required" in msg


def test_add_event_attribute_writes_temporal_precision(funcs):
    ok, msg = funcs.add_attribute(EXT, "Event", "InstallDate",
                                  temporal_precision="YearMonth")
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.InstallDate, RDFS.subClassOf, DICI.EventAttribute) in g
    assert (DICI.InstallDate, DICI.hasDefaultTemporalPrecision,
            DICI.YearMonth) in g


def test_add_event_attribute_requires_precision(funcs):
    ok, msg = funcs.add_attribute(EXT, "Event", "InstallDate")
    assert not ok
    assert "Temporal precision is required" in msg


def test_add_categorical_attribute(funcs):
    ok, msg = funcs.add_attribute(EXT, "Categorical", "HeatingSupply")
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.HeatingSupply, RDFS.subClassOf,
            DICI.CategoricalAttribute) in g


def test_add_custom_ratio_attribute_writes_ratio_units(funcs):
    ok, msg = funcs.add_attribute(EXT, "CustomPhysicalRatio", "HeatLossRate",
                                  x_unit="KiloW", y_qudt_unit="K")
    assert ok, msg
    g = _ext_graph(funcs)
    ratio_nodes = list(g.objects(DICI.HeatLossRate, DICI.hasRatioUnits))
    assert len(ratio_nodes) == 1
    assert (ratio_nodes[0], DICI.numeratorUnit, UNIT.KiloW) in g
    assert (ratio_nodes[0], DICI.denominatorUnit, UNIT.K) in g


def test_add_attribute_under_parent_property(funcs):
    """With a parent given, the new class hangs under it instead of a base type."""
    ok, msg = funcs.add_attribute(EXT, "Physical", "GrossFloorArea",
                                  qudt_unit="M2")
    assert ok, msg
    ok, msg = funcs.add_attribute(
        EXT, "Physical", "HeatedFloorArea", qudt_unit="M2",
        parent_property=str(DICI.GrossFloorArea))
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.HeatedFloorArea, RDFS.subClassOf, DICI.GrossFloorArea) in g
    assert (DICI.HeatedFloorArea, RDFS.subClassOf,
            DICI.PhysicalAttribute) not in g


# ── default unit management ──────────────────────────────────────────────────
def test_set_default_unit_replaces_existing(funcs):
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    ok, msg = funcs.set_default_unit(EXT, "PanelArea", "KiloW")
    assert ok, msg
    g = _ext_graph(funcs)
    units = list(g.objects(DICI.PanelArea, DICI.hasDefaultUnit))
    assert units == [UNIT.KiloW]  # replaced, not appended


def test_set_default_unit_rejects_unknown_code(funcs):
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    ok, msg = funcs.set_default_unit(EXT, "PanelArea", "NotAUnit")
    assert not ok
    assert "not a recognised QUDT unit code" in msg


# ── linking attributes to components ─────────────────────────────────────────
def test_link_attribute_builds_property_stack(funcs):
    """Linking creates the general has<Comp>Attribute property, the specific
    has<Comp><Attr> subproperty with domain+range, and reclassifies the
    attribute under the component's attribute category."""
    funcs.add_component(EXT, "SolarPanel", str(DICI.Component))
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    ok, msg = funcs.link_attribute(EXT, str(DICI.SolarPanel),
                                   str(DICI.PanelArea))
    assert ok, msg

    g = _ext_graph(funcs)
    general = DICI.hasSolarPanelAttribute
    specific = DICI.hasSolarPanelPanelArea
    assert (general, RDFS.range, DICI.PanelArea) in g
    assert (general, RDFS.domain, DICI.SolarPanel) in g
    assert (specific, RDF.type, OWL.ObjectProperty) in g
    assert (specific, RDFS.subPropertyOf, general) in g
    assert (specific, RDFS.range, DICI.PanelArea) in g
    assert (specific, RDFS.domain, DICI.SolarPanel) in g
    assert (DICI.PanelArea, RDFS.subClassOf, DICI.SolarPanelAttribute) in g


def test_link_attribute_is_idempotent_on_range(funcs):
    funcs.add_component(EXT, "SolarPanel", str(DICI.Component))
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    funcs.link_attribute(EXT, str(DICI.SolarPanel), str(DICI.PanelArea))
    funcs.link_attribute(EXT, str(DICI.SolarPanel), str(DICI.PanelArea))
    g = _ext_graph(funcs)
    ranges = list(g.triples((DICI.hasSolarPanelAttribute, RDFS.range,
                             DICI.PanelArea)))
    assert len(ranges) == 1


def test_remove_attribute_link_drops_property_stack(funcs):
    funcs.add_component(EXT, "SolarPanel", str(DICI.Component))
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    funcs.link_attribute(EXT, str(DICI.SolarPanel), str(DICI.PanelArea))

    ok, msg = funcs.remove_attribute_link(EXT, str(DICI.SolarPanel),
                                          str(DICI.PanelArea))
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.hasSolarPanelAttribute, RDFS.range, DICI.PanelArea) not in g
    assert not list(g.triples((DICI.hasSolarPanelPanelArea, None, None)))
    # the attribute class itself survives — only the link went away
    assert (DICI.PanelArea, RDF.type, OWL.Class) in g


def test_get_component_attributes_reads_linked_range(funcs):
    funcs.add_component(EXT, "SolarPanel", str(DICI.Component))
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    funcs.link_attribute(EXT, str(DICI.SolarPanel), str(DICI.PanelArea))
    attrs = funcs.get_component_attributes(EXT, str(DICI.SolarPanel))
    assert str(DICI.PanelArea) in [a["class"] for a in attrs]


# ── removal ──────────────────────────────────────────────────────────────────
def test_remove_attribute_erases_every_reference(funcs):
    funcs.add_component(EXT, "SolarPanel", str(DICI.Component))
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    funcs.link_attribute(EXT, str(DICI.SolarPanel), str(DICI.PanelArea))

    ok, msg = funcs.remove_attribute(EXT, str(DICI.PanelArea))
    assert ok, msg
    g = _ext_graph(funcs)
    assert not list(g.triples((DICI.PanelArea, None, None)))
    assert not list(g.triples((None, None, DICI.PanelArea)))
    # Known residue, pinned: the specific property's own declaration triples
    # (type/subPropertyOf/domain) survive — the sweep only removes triples
    # whose *predicate* carries the attribute name, and its range triple went
    # with the object sweep. What matters is that no triple points at the
    # attribute class anymore (asserted above).
    leftovers = list(g.triples((DICI.hasSolarPanelPanelArea, None, None)))
    assert all(o != DICI.PanelArea for _, _, o in leftovers)


# ── categorical attributes + named individuals ───────────────────────────────
def test_named_individual_roundtrip(funcs):
    funcs.add_attribute(EXT, "Categorical", "HeatingSupply")
    ok, msg = funcs.add_named_individual(EXT, "District Heating",
                                         str(DICI.HeatingSupply))
    assert ok, msg

    g = _ext_graph(funcs)
    ind = DICI.DistrictHeating  # label whitespace collapses into the id
    assert (ind, RDF.type, OWL.NamedIndividual) in g
    assert (ind, RDF.type, DICI.HeatingSupply) in g
    assert [str(o) for o in g.objects(ind, RDFS.label)] == ["District Heating"]

    # readable back through the query side (runs on the merged temp graph)
    individuals = funcs.get_named_individuals(EXT, str(DICI.HeatingSupply))
    assert [i["uri"] for i in individuals] == [str(ind)]

    ok, msg = funcs.remove_named_individual(EXT, str(ind))
    assert ok, msg
    assert not list(_ext_graph(funcs).triples((ind, None, None)))


def test_categorical_attribute_visible_in_explorer_queries(funcs):
    funcs.add_attribute(EXT, "Categorical", "HeatingSupply")
    cats = funcs.get_categorical_attributes(EXT)
    assert str(DICI.HeatingSupply) in [c["class"] for c in cats]
    # and in the untyped attribute explorer as well
    attrs = funcs.explore_attributes(EXT)
    assert str(DICI.HeatingSupply) in [a["class"] for a in attrs]


def test_attribute_category_membership_roundtrip(funcs):
    funcs.add_attribute(EXT, "Physical", "PanelArea", qudt_unit="M2")
    ok, msg = funcs.add_attribute_to_category(
        EXT, str(DICI.PanelArea), str(DICI.GeospatialAttribute))
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.PanelArea, RDFS.subClassOf, DICI.GeospatialAttribute) in g

    ok, msg = funcs.remove_attribute_from_category(
        EXT, str(DICI.PanelArea), str(DICI.GeospatialAttribute))
    assert ok, msg
    g = _ext_graph(funcs)
    assert (DICI.PanelArea, RDFS.subClassOf, DICI.GeospatialAttribute) not in g
