# SPDX-License-Identifier: Apache-2.0

"""Replica Builder and Ontology Manager read what a class or predicate IS from
the hierarchy (real vendored core), never from its spelling.

Each case below names things so that the old name tests got them wrong: an
attribute predicate without "Attribute" in its name, an attribute class under a
kind's subclass, a category class whose name does not end in "Attribute", a
component link whose predicate starts with "has", a value kind kept when an
attribute moves.
"""
from __future__ import annotations

import pandas as pd
import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef

from backend.ontology_kinds import DICI, AttributeKind
from backend.ontology_manager.functions.attribute_ops import AttributeMixin
from backend.ontology_manager.functions.component_ops import ComponentMixin
from backend.ontology_scaffold import ensure_scaffold
from backend.replica_builder import graph_loader
from backend.replica_builder import ontology_queries
from backend.replica_builder.attribute_rules import (
    WorkbookColumn, parse_column_type, validate_attribute_config,
)
from backend.replica_builder.model import component_type_names
from backend.replica_builder.utils.ttl_attribute_helpers import generate_attribute_ttl

EX = Namespace("https://example.org/proj#")


def _standalone_graph() -> Graph:
    g = Graph()
    b1 = URIRef("https://example.org/proj/Building/B1")
    area = URIRef(str(b1) + "/FloorSize")
    profile = URIRef(str(b1) + "/Demand")
    site = URIRef("https://example.org/proj/Site/S1")
    # A declared attribute predicate with no "Attribute" in its name.
    g.add((EX.hasFloorSize, RDFS.subPropertyOf, DICI.hasComponentAttribute))
    g.add((b1, RDF.type, DICI.Building))
    g.add((b1, EX.hasFloorSize, area))
    g.add((area, RDF.type, DICI.PhysicalAttribute))
    # A minted, undeclared attribute predicate next to hasAttribute.
    g.add((b1, DICI.hasAttribute, profile))
    g.add((b1, DICI.hasBuildingDemandAttribute, profile))
    # ElectricityDemandProfile is under DynamicAttribute in the core.
    g.add((profile, RDF.type, DICI.ElectricityDemandProfile))
    # A component link whose predicate starts with "has".
    g.add((b1, DICI.hasLocation, site))
    g.add((site, RDF.type, DICI.Location))
    return g


def test_local_parse_finds_attributes_and_links_by_hierarchy():
    insts = {i.uri: i for i in graph_loader.parse_local_replica_graph(_standalone_graph())}
    b1 = insts["https://example.org/proj/Building/B1"]
    assert set(b1.attributes) == {"FloorSize", "Demand"}
    assert b1.attributes["Demand"]["type"] == AttributeKind.DYNAMIC
    # hasLocation is a link, kept; the minted attribute predicate is not.
    assert b1.class_objects == {"hasLocation": "https://example.org/proj/Site/S1"}
    # The attribute node reached via ex:hasFloorSize is not an instance.
    assert "https://example.org/proj/Building/B1/FloorSize" not in insts


def test_category_value_skips_extension_attribute_classes():
    data = Graph()
    node = URIRef("https://example.org/proj/Turbine/T1/Make")
    data.add((node, RDF.type, DICI.Make))
    data.add((node, RDF.type, DICI.CategoricalAttribute))
    data.add((node, RDF.type, DICI.TurbineCategory))      # an attribute class, by hierarchy
    data.add((node, RDF.type, DICI.Vestas))
    onto = Graph()
    onto.add((DICI.TurbineCategory, RDFS.subClassOf, DICI.TurbineAttribute))
    # The attribute's own class, as the workspace extension declares it.
    onto.add((DICI.Make, RDFS.subClassOf, DICI.CategoricalAttribute))
    schema = graph_loader.schema_view(data, onto)
    for _ in range(5):  # rdf:type iteration order must not matter
        got = graph_loader.parse_single_attribute(data, node, schema=schema)
        assert got["category_value"] == "Vestas"


def test_kind_map_uses_kind_iris_and_precedence():
    rows = pd.DataFrame({
        "attribute": ["a1", "a1", "a2", "a3"],
        "kind": [str(DICI.PhysicalAttribute), str(DICI.DynamicAttribute),
                 str(DICI.SimpleCostAttribute), str(DICI.TurbineAttribute)],
    })
    assert graph_loader._kind_map(rows) == {"a1": "Dynamic", "a2": "SimpleCost"}


def test_ontology_queries_kind_from_iri(monkeypatch):
    df = pd.DataFrame({
        "class": [str(DICI.HubPower)] * 2 + [str(DICI.Fee)],
        "label": [None, None, None], "defaultUnit": [None] * 3, "quantityKind": [None] * 3,
        "attrType": [str(DICI.PhysicalAttribute), str(DICI.DynamicAttribute),
                     str(DICI.UnitBasedCostAttribute)],
    })
    monkeypatch.setattr(ontology_queries.gq_ont, "get_attributes_with_constraints", lambda c: df)
    got = ontology_queries.query_attributes_with_constraints(None)
    assert got["HubPower"].attribute_type == "Dynamic"
    assert got["Fee"].attribute_type == "UnitBasedCost"


def test_workbook_column_types_parse_once_and_refuse_unknown():
    assert parse_column_type("Simple Cost") is AttributeKind.SIMPLE_COST
    assert parse_column_type("ClassObject") is WorkbookColumn.CLASS_OBJECT
    assert parse_column_type("Unnamed: 3") is None
    with pytest.raises(ValueError, match="unknown column type 'decimal'"):
        parse_column_type("decimal", "Building.floorArea")
    assert validate_attribute_config("decimal", {}) == ["Unknown attribute type: decimal"]


def test_dynamic_kind_is_written():
    lines = generate_attribute_ttl("https://x/B1/P", "P", {"type": "Dynamic", "value": 1}, "Building")
    assert any("dici_onto:DynamicAttribute" in line for line in lines)


def test_component_type_names_keeps_components_with_attribute_like_names():
    assert component_type_names({"MeterAttribute": 1, "PV": 2}) == ["MeterAttribute", "PV"]


def test_moving_a_component_keeps_its_attributes_value_kind():
    """The category moves with its component; the attribute under it keeps both
    its category and its value kind."""
    g = Graph()
    g.parse("data/ontology/dici_onto_core.ttl")
    g.add((DICI.Pump, RDF.type, OWL.Class))
    g.add((DICI.Pump, RDFS.subClassOf, DICI.Storage))
    ensure_scaffold(g, g, DICI.Pump)
    g.add((DICI.FlowSpeed, RDF.type, OWL.Class))
    g.add((DICI.FlowSpeed, RDFS.subClassOf, DICI.PumpAttribute))
    g.add((DICI.FlowSpeed, RDFS.subClassOf, DICI.PhysicalAttribute))
    g.remove((DICI.Pump, RDFS.subClassOf, DICI.Storage))
    g.add((DICI.Pump, RDFS.subClassOf, DICI.Process))
    ensure_scaffold(g, g, DICI.Pump)
    assert set(g.objects(DICI.PumpAttribute, RDFS.subClassOf)) == {DICI.ProcessAttribute}
    assert (DICI.FlowSpeed, RDFS.subClassOf, DICI.PhysicalAttribute) in g
    assert (DICI.FlowSpeed, RDFS.subClassOf, DICI.PumpAttribute) in g


def test_removed_component_takes_only_its_own_empty_category():
    g = Graph()
    for c in ("Pump", "PumpAttribute", "HubHeightAttribute"):
        g.add((DICI[c], RDF.type, OWL.Class))
    g.add((DICI.HubHeightAttribute, RDFS.subClassOf, DICI.TurbineAttribute))
    m = type("M", (ComponentMixin,), {})()
    m.cleanup_orphaned_attribute_classes(g, [DICI.PumpAttribute])
    assert (DICI.PumpAttribute, None, None) not in g
    # A leaf attribute class that merely ends in "Attribute" stays.
    assert (DICI.HubHeightAttribute, RDF.type, OWL.Class) in g


def test_attribute_categories_by_domain_and_range_not_spelling():
    g = Graph()
    g.parse("data/ontology/dici_onto_core.ttl")
    g.add((DICI.Pump, RDFS.subClassOf, DICI.Component))
    g.add((DICI.PumpAttribute, RDFS.subClassOf, DICI.ComponentAttribute))
    g.add((DICI.PumpAttribute, RDFS.label, Literal("Pump Attribute")))
    g.add((DICI.hasPumpAttribute, RDFS.subPropertyOf, DICI.hasComponentAttribute))
    g.add((DICI.hasPumpAttribute, RDFS.domain, DICI.Pump))
    g.add((DICI.hasPumpAttribute, RDFS.range, DICI.PumpAttribute))
    # A leaf attribute class named with the suffix is not a category.
    g.add((DICI.HeadAttribute, RDFS.subClassOf, DICI.PumpAttribute))
    g.add((DICI.HeadAttribute, RDFS.label, Literal("Head")))
    cats = AttributeMixin._category_classes(None, g)
    assert DICI.PumpAttribute in cats and DICI.TurbineAttribute in cats
    assert DICI.PhysicalAttribute in cats and DICI.Attribute in cats
    assert DICI.HeadAttribute not in cats and DICI.Efficiency not in cats
