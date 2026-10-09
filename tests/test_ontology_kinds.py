# SPDX-License-Identifier: Apache-2.0

"""backend.ontology_kinds answers from the hierarchy of the REAL vendored core.

The extension below names its classes so that spelling would mislead: an
attribute class without "Attribute" in its name, a component class ending in
"Attribute"-free names, a typed attribute predicate. Only the hierarchy decides.
"""
from __future__ import annotations

from rdflib import RDF, RDFS, Graph, Namespace, URIRef

from backend.ontology_kinds import (
    DICI, KIND_CLASS, AttributeKind, attribute_kind, is_attribute_class,
    is_attribute_node, is_attribute_predicate, is_component_class,
    is_link_predicate, kind_for_class, kind_of_node, with_core,
)

EX = Namespace("https://example.org/ws#")


def _graph() -> Graph:
    g = Graph()
    # Extension: an attribute class whose name hides what it is.
    g.add((EX.GroundFloorArea, RDFS.subClassOf, DICI.ComponentAttribute))
    g.add((EX.HubHeight, RDFS.subClassOf, DICI.TurbineAttribute))
    g.add((EX.Turbine, RDFS.subClassOf, DICI.Component))
    g.add((EX.BuildingType, RDFS.subClassOf, DICI.ComponentAttribute))
    g.add((EX.MFH, RDF.type, RDFS.Class))
    g.add((EX.hasAreaAttribute, RDFS.subPropertyOf, DICI.hasComponentAttribute))
    # Instance data, dual-typed per the URI convention.
    g.add((EX.t1, RDF.type, EX.Turbine))
    g.add((EX.t1, EX.hasAreaAttribute, EX.t1_area))
    g.add((EX.t1_area, RDF.type, EX.GroundFloorArea))
    g.add((EX.t1_area, RDF.type, DICI.PhysicalAttribute))
    g.add((EX.t1_type, RDF.type, EX.BuildingType))
    g.add((EX.t1_type, RDF.type, DICI.CategoricalAttribute))
    g.add((EX.t1_type, RDF.type, EX.MFH))
    g.add((EX.t1_power, RDF.type, EX.HubHeight))
    g.add((EX.t1_power, RDF.type, DICI.DynamicAttribute))
    g.add((EX.t1_power, RDF.type, DICI.PhysicalAttribute))
    return with_core(g)


def test_classes_by_hierarchy_not_name():
    g = _graph()
    assert is_attribute_class(g, EX.GroundFloorArea)
    assert is_attribute_class(g, EX.HubHeight)        # via core TurbineAttribute
    assert not is_attribute_class(g, EX.Turbine)
    assert is_component_class(g, EX.Turbine)
    assert not is_attribute_class(g, EX.MFH)          # a category, not an attribute


def test_predicates_by_hierarchy_not_name():
    g = _graph()
    assert is_attribute_predicate(g, EX.hasAreaAttribute)
    assert is_attribute_predicate(g, DICI.hasIdentifier)
    assert not is_attribute_predicate(g, DICI.partOf)
    assert is_link_predicate(g, DICI.hasLocation)
    assert not is_link_predicate(g, DICI.hasAttribute)


def test_kind_of_node_and_precedence():
    g = _graph()
    assert kind_of_node(g, EX.t1_area) is AttributeKind.PHYSICAL
    assert kind_of_node(g, EX.t1_type) is AttributeKind.CATEGORICAL
    # Dynamic AND Physical: the specific value shape wins.
    assert kind_of_node(g, EX.t1_power) is AttributeKind.DYNAMIC
    assert kind_of_node(g, EX.t1) is None
    assert kind_of_node(g, EX.t1_area, predicate=DICI.hasIdentifier) is AttributeKind.IDENTIFIER
    assert is_attribute_node(g, EX.t1_area) and not is_attribute_node(g, EX.t1)


def test_kind_classes_exist_in_core_and_round_trip():
    g = with_core(Graph())
    for kind, cls in KIND_CLASS.items():
        assert is_attribute_class(g, cls), cls
        assert kind_for_class(cls) is kind
        assert attribute_kind(g, [cls]) is kind
    assert kind_for_class(URIRef(DICI.TurbineAttribute)) is None


def test_scenario_link_and_time_series_predicates():
    from backend.ontology_kinds import (
        is_attribute_value_predicate, is_component_link_class, is_instance_of,
        is_scenario_class, is_time_series_predicate, is_time_series_reference_predicate,
    )
    g = _graph()
    assert is_scenario_class(g, DICI.Scenario) and not is_scenario_class(g, EX.Turbine)
    assert is_component_link_class(g, DICI.ComponentLink)
    assert is_instance_of(g, EX.t1, DICI.Component) and not is_instance_of(g, EX.t1, DICI.Attribute)
    assert is_time_series_predicate(g, DICI.hasHistoricTimeSeries)
    assert not is_time_series_predicate(g, DICI.hasHistoricTimeSeriesReference)
    assert is_time_series_reference_predicate(g, DICI.hasLiveTimeSeriesReference)
    assert is_attribute_value_predicate(g, DICI.hasTemporalValue)
    # an object property: the category IRI, not a literal value
    assert not is_attribute_value_predicate(g, DICI.hasCategoricalValue)


def test_member_serialises_as_its_tag():
    import json
    import yaml
    k = AttributeKind.CURVE
    assert str(k) == "Curve" and f"{k}" == "Curve" and f"<{k:>6}>" == "< Curve>"
    assert json.dumps({"type": k}) == '{"type": "Curve"}'
    assert yaml.safe_load(yaml.safe_dump({"type": k})) == {"type": "Curve"}
    assert k == "Curve" and AttributeKind("Curve") is k


def test_namespace_membership_is_exact():
    from backend.ontology_kinds import dici_local_name, in_dici_namespace, in_namespace, namespace_of
    assert in_dici_namespace(DICI.Turbine) and dici_local_name(DICI.Turbine) == "Turbine"
    # A prefix test would accept both of these.
    assert not in_dici_namespace(URIRef(str(DICI) + "Turbine/hub"))
    assert not in_dici_namespace(URIRef("https://digicities.info/ontology#"))
    assert dici_local_name(EX.Turbine) is None
    assert namespace_of("http://qudt.org/vocab/unit/M2") == "http://qudt.org/vocab/unit/"
    assert in_namespace("http://qudt.org/vocab/unit/M2", "http://qudt.org/vocab/unit/")
    assert not in_namespace("http://qudt.org/vocab/unit/M2/x", "http://qudt.org/vocab/unit/")
