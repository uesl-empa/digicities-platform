# SPDX-License-Identifier: Apache-2.0

"""What a node, class or predicate IS, read from the ontology hierarchy.

Never from its name. ``GroundFloorArea`` is an attribute class although its
name has no "Attribute" in it; ``hasTurbineAttribute`` is an attribute link
because it is ``rdfs:subPropertyOf* dici_onto:hasAttribute``, not because of
how it is spelt. Every question here is answered with ``rdfs:subClassOf*`` /
``rdfs:subPropertyOf*`` over the graph you pass in.

The graph you pass usually holds instance data only. ``with_core(g)`` returns a
read-only view of ``g`` plus the vendored core ontology, so the hierarchy is
there; pass a graph that also holds the workspace extension when extension
classes matter.

``AttributeKind`` is the closed set of value shapes the editors and emitters
know how to read and write. A node's kind comes from ``attribute_kind`` (or
``kind_for_class`` for a kind class IRI a SPARQL query already returned);
code then dispatches on the enum member, never on a class name.
"""
from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Set

from rdflib import RDF, RDFS, Graph, Namespace, URIRef
from rdflib.graph import ReadOnlyGraphAggregate

DICI = Namespace("https://digicities.info/ontology#")


class AttributeKind(str, Enum):
    """The value shape of an attribute. The value is the editor's kind tag."""
    PHYSICAL = "Physical"
    DYNAMIC = "Dynamic"
    CATEGORICAL = "Categorical"
    EVENT = "Event"
    CURVE = "Curve"
    SIMPLE_COST = "SimpleCost"
    UNIT_BASED_COST = "UnitBasedCost"
    RESOURCE = "Resource"
    SIMPLE_VALUE = "SimpleValue"
    CUSTOM_PHYSICAL_RATIO = "CustomPhysicalRatio"
    GEOSPATIAL = "Geospatial"
    ANNOTATION = "Annotation"
    # No kind class: an identifier is the object of a
    # ``rdfs:subPropertyOf* dici_onto:hasIdentifier`` link.
    IDENTIFIER = "Identifier"

    @property
    def class_uri(self) -> Optional[URIRef]:
        return KIND_CLASS.get(self)

    # A member written into Turtle, a message or a file is its tag, never
    # "AttributeKind.CURVE".
    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


# Core class of each kind, in precedence order: when a node is typed under
# more than one kind class, the first one listed wins. The specific value
# shapes come before the generic Physical quantity and the Resource branch of
# the ComponentAttribute tree.
KIND_CLASS = {
    AttributeKind.CATEGORICAL: DICI.CategoricalAttribute,
    AttributeKind.EVENT: DICI.EventAttribute,
    AttributeKind.CURVE: DICI.CurveAttribute,
    AttributeKind.DYNAMIC: DICI.DynamicAttribute,
    AttributeKind.UNIT_BASED_COST: DICI.UnitBasedCostAttribute,
    AttributeKind.SIMPLE_COST: DICI.SimpleCostAttribute,
    AttributeKind.CUSTOM_PHYSICAL_RATIO: DICI.CustomPhysicalRatioAttribute,
    AttributeKind.GEOSPATIAL: DICI.GeospatialAttribute,
    AttributeKind.ANNOTATION: DICI.AnnotationAttribute,
    AttributeKind.SIMPLE_VALUE: DICI.SimpleValueAttribute,
    AttributeKind.PHYSICAL: DICI.PhysicalAttribute,
    AttributeKind.RESOURCE: DICI.ResourceAttribute,
}
_KIND_BY_CLASS = {uri: kind for kind, uri in KIND_CLASS.items()}


def _ontology_dir() -> Path:
    env_dir = os.environ.get("ONTOLOGY_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parents[1] / "data" / "ontology"


@lru_cache(maxsize=1)
def core_graph() -> Graph:
    """The vendored core ontology (parsed once per process)."""
    g = Graph()
    g.parse(_ontology_dir() / "dici_onto_core.ttl", format="turtle")
    return g


def with_core(g: Graph) -> Graph:
    """A read-only view of ``g`` plus the core ontology."""
    return ReadOnlyGraphAggregate([g, core_graph()])


def superclasses(g: Graph, cls: URIRef) -> Set[URIRef]:
    """``cls`` and every class it is ``rdfs:subClassOf+``."""
    return set(g.transitive_objects(URIRef(cls), RDFS.subClassOf))


def superproperties(g: Graph, prop: URIRef) -> Set[URIRef]:
    """``prop`` and every property it is ``rdfs:subPropertyOf+``."""
    return set(g.transitive_objects(URIRef(prop), RDFS.subPropertyOf))


def is_subclass_of(g: Graph, cls: URIRef, sup: URIRef) -> bool:
    """``cls rdfs:subClassOf* sup``."""
    return URIRef(sup) in superclasses(g, cls)


def is_subproperty_of(g: Graph, prop: URIRef, sup: URIRef) -> bool:
    """``prop rdfs:subPropertyOf* sup``."""
    return URIRef(sup) in superproperties(g, prop)


def is_attribute_class(g: Graph, cls: URIRef) -> bool:
    return is_subclass_of(g, cls, DICI.Attribute)


def is_component_class(g: Graph, cls: URIRef) -> bool:
    return is_subclass_of(g, cls, DICI.Component)


def is_attribute_predicate(g: Graph, prop: URIRef) -> bool:
    """Links a thing to one of its attributes (identifiers included)."""
    return is_subproperty_of(g, prop, DICI.hasAttribute)


def is_identifier_predicate(g: Graph, prop: URIRef) -> bool:
    return is_subproperty_of(g, prop, DICI.hasIdentifier)


def is_link_predicate(g: Graph, prop: URIRef) -> bool:
    """Links one component to another."""
    return is_subproperty_of(g, prop, DICI.linksComponent)


def is_attribute_node(g: Graph, node: URIRef) -> bool:
    return any(is_attribute_class(g, t) for t in g.objects(URIRef(node), RDF.type))


def kind_for_class(cls: URIRef) -> Optional[AttributeKind]:
    """The kind whose kind class IS ``cls`` (exact IRI), else None. For kind
    class IRIs a ``rdfs:subClassOf*`` query has already returned."""
    return _KIND_BY_CLASS.get(URIRef(cls))


def attribute_kind(g: Graph, types: Iterable[URIRef],
                   predicate: Optional[URIRef] = None) -> Optional[AttributeKind]:
    """The kind of an attribute typed ``types`` (and reached via ``predicate``,
    if given): the first kind in precedence order whose class one of the types
    is ``rdfs:subClassOf*``. An identifier link makes it IDENTIFIER."""
    if predicate is not None and is_identifier_predicate(g, predicate):
        return AttributeKind.IDENTIFIER
    reached: Set[URIRef] = set()
    for t in types:
        reached |= superclasses(g, t)
    for kind, cls in KIND_CLASS.items():
        if cls in reached:
            return kind
    return None


def kind_of_node(g: Graph, node: URIRef,
                 predicate: Optional[URIRef] = None) -> Optional[AttributeKind]:
    """``attribute_kind`` of an attribute node from its ``rdf:type``s in ``g``."""
    return attribute_kind(g, g.objects(URIRef(node), RDF.type), predicate)


def is_instance_of(g: Graph, node: URIRef, cls: URIRef) -> bool:
    """``node rdf:type/rdfs:subClassOf* cls``."""
    return any(is_subclass_of(g, t, cls) for t in g.objects(URIRef(node), RDF.type))


def is_scenario_class(g: Graph, cls: URIRef) -> bool:
    return is_subclass_of(g, cls, DICI.Scenario)


def is_component_link_class(g: Graph, cls: URIRef) -> bool:
    return is_subclass_of(g, cls, DICI.ComponentLink)


def is_time_series_predicate(g: Graph, prop: URIRef) -> bool:
    """Links an attribute to a TimeSeries node (historic / live / future)."""
    return is_subproperty_of(g, prop, DICI.hasTimeSeries)


def is_time_series_reference_predicate(g: Graph, prop: URIRef) -> bool:
    """Holds a time series reference (a path or URL literal)."""
    return is_subproperty_of(g, prop, DICI.hasTimeSeriesReference)


def is_attribute_value_predicate(g: Graph, prop: URIRef) -> bool:
    """Holds an attribute's own value (categorical, temporal, annotation, ...)."""
    return is_subproperty_of(g, prop, DICI.hasAttributeValue)


def namespace_of(iri) -> Optional[str]:
    """The namespace an IRI's local name hangs off: everything up to and
    including its last ``#`` or ``/``. None when there is no local name."""
    s = str(iri)
    cut = max(s.rfind("#"), s.rfind("/"))
    return s[:cut + 1] if 0 <= cut < len(s) - 1 else None


def in_namespace(iri, ns) -> bool:
    """The IRI's namespace IS ``ns`` (exact equality, never a prefix test, so
    ``dici_onto:`` does not swallow ``https://digicities.info/ontology#x/y``)."""
    return namespace_of(iri) == str(ns)


def in_dici_namespace(iri) -> bool:
    """A term of the DigiCities vocabulary namespace. What the term IS comes
    from the hierarchy; this only says whose vocabulary it belongs to."""
    return in_namespace(iri, DICI)


def dici_local_name(iri) -> Optional[str]:
    """The local name of a ``dici_onto:`` term, else None."""
    return str(iri)[len(str(DICI)):] if in_dici_namespace(iri) else None


def _register_yaml() -> None:
    """yaml.safe_dump writes a member as its tag (contracts and specs are YAML)."""
    try:
        import yaml
    except ImportError:  # yaml is optional for the platform core
        return
    yaml.SafeDumper.add_representer(
        AttributeKind, lambda dumper, kind: dumper.represent_str(kind.value))


_register_yaml()
