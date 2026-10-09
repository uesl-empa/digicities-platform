# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
TTL Parser Module - IMPROVED VERSION
File: components/data_products/ttl_parser.py

Handles TTL parsing and attribute extraction using RDFLib. What is a component
and what is an attribute, and which value shape an attribute has, is read from
the ontology hierarchy (``backend.ontology_kinds``), never from class names.
"""

from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional, Any, Set
from rdflib import OWL, Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS

from backend.ontology_kinds import (
    DICI, AttributeKind, core_graph, dici_local_name, is_attribute_class,
    is_attribute_node, is_attribute_predicate, is_component_class, is_subclass_of,
    kind_for_class, kind_of_node, with_core,
)

# The display category of each value shape.
_KIND_CATEGORY = {
    AttributeKind.PHYSICAL: 'physical',
    AttributeKind.SIMPLE_COST: 'cost',
    AttributeKind.UNIT_BASED_COST: 'cost',
    AttributeKind.GEOSPATIAL: 'geospatial',
    AttributeKind.DYNAMIC: 'dynamic',
    AttributeKind.CURVE: 'curve',
    AttributeKind.CATEGORICAL: 'categorical',
    AttributeKind.EVENT: 'temporal',
    AttributeKind.ANNOTATION: 'annotation',
}


def _local_name(uri) -> str:
    """The last segment of an IRI, for display and as a dictionary key."""
    uri = str(uri)
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


@lru_cache(maxsize=1)
def _non_component_roots() -> FrozenSet[URIRef]:
    """The core's top classes other than Component (Scenario, Reference,
    ComponentLink, TimeSeries, Collection, the QUDT unit classes, ...): their
    instances are never components."""
    core = core_graph()
    classes = {c for c in core.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)}
    roots = {c for c in classes
             if not any(sup in classes for sup in core.objects(c, RDFS.subClassOf))}
    return frozenset(roots - {DICI.Component})


def _may_be_component(view: Graph, cls: URIRef) -> bool:
    """A class the hierarchy places under Component is one. A class it places
    under an attribute class or another core top class is not. A class it does
    not know (a data product without its schema) is taken as a component, as
    the data typed something with it."""
    if is_component_class(view, cls):
        return True
    if is_attribute_class(view, cls):
        return False
    return not any(is_subclass_of(view, cls, root) for root in _non_component_roots())


class TTLParser:
    """Parser for TTL files and RDF graphs"""

    def __init__(self):
        """Initialize with namespaces"""
        # Define namespaces
        self.DICI = Namespace("https://digicities.info/ontology#")
        self.QUDT = Namespace("http://qudt.org/schema/qudt/")
        self.UNIT = Namespace("http://qudt.org/vocab/unit/")
        self.XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
        self.CUR = Namespace("http://qudt.org/vocab/currency/")
        # Legacy alias kept so old workspace TTLs (pre-cur switch) still parse cleanly.
        self.ISO4217 = Namespace("http://example.org/currency/")

    def parse_ttl_content(self, ttl_content: str) -> Optional[Graph]:
        """Parse TTL content into RDFLib graph"""
        try:
            graph = Graph()

            # Bind namespaces
            graph.bind("dici_onto", self.DICI)
            graph.bind("qudt", self.QUDT)
            graph.bind("unit", self.UNIT)
            graph.bind("rdfs", RDFS)
            graph.bind("xsd", self.XSD)
            graph.bind("cur", self.CUR)
            graph.bind("iso4217", self.ISO4217)  # legacy

            # Parse TTL
            graph.parse(data=ttl_content, format="turtle")
            return graph

        except Exception as e:
            print(f"Error parsing TTL content: {e}")
            return None

    def extract_components_from_graph(self, graph: Graph) -> Dict[str, List[Dict]]:
        """Extract all components from RDFLib graph.

        Attribute nodes are the objects of attribute edges
        (``rdfs:subPropertyOf* dici_onto:hasAttribute``) and the nodes typed
        under ``dici_onto:Attribute``; everything else typed in ``dici_onto:``
        may be a component (see ``_may_be_component``). The hierarchy comes from
        the vendored core plus whatever schema the data product carries."""
        view = with_core(graph)
        attribute_nodes = self._attribute_nodes(graph, view)
        components_by_type = {}

        for subject, predicate, obj in graph.triples((None, RDF.type, None)):
            component_type = dici_local_name(obj)
            if component_type is not None:
                if subject in attribute_nodes or not _may_be_component(view, obj):
                    continue

                component_data = self._extract_component_data(
                    graph, view, subject, component_type, attribute_nodes)

                if component_data:
                    if component_type not in components_by_type:
                        components_by_type[component_type] = []
                    components_by_type[component_type].append(component_data)

        return components_by_type

    def _attribute_nodes(self, graph: Graph, view: Graph) -> Set[URIRef]:
        """Every node that is an attribute: the object of an attribute edge, or
        typed under ``dici_onto:Attribute``."""
        attribute_edge: Dict[URIRef, bool] = {}
        nodes: Set[URIRef] = set()
        for subject, predicate, obj in graph:
            if not isinstance(obj, URIRef):
                continue
            if predicate not in attribute_edge:
                attribute_edge[predicate] = is_attribute_predicate(view, predicate)
            if attribute_edge[predicate]:
                nodes.add(obj)
        for subject in set(graph.subjects(RDF.type, None)):
            if isinstance(subject, URIRef) and is_attribute_node(view, subject):
                nodes.add(subject)
        return nodes

    def _extract_component_data(self, graph: Graph, view: Graph, component_uri: URIRef,
                                component_type: str, attribute_nodes: Set[URIRef]) -> Optional[Dict]:
        """Extract complete component data. The component's attributes are the
        attribute nodes it links to; each is keyed by its own IRI's local name."""
        try:
            component = {
                'uri': str(component_uri),
                'label': self._get_label(graph, component_uri),
                'type': component_type,
                'attributes': {},
                'resources': {}
            }

            for attr_uri in sorted(set(graph.objects(component_uri, None)) & attribute_nodes):
                attr_name = _local_name(attr_uri)
                attr_data = self._extract_attribute_details(graph, view, attr_uri, attr_name)
                if attr_data:
                    component['attributes'][attr_name] = attr_data

                    # Track resource references
                    if attr_data.get('resource_reference'):
                        component['resources'][attr_name] = attr_data['resource_reference']

            return component

        except Exception as e:
            return None

    def _get_label(self, graph: Graph, uri: URIRef) -> str:
        """Get rdfs:label for a URI"""
        for label in graph.objects(uri, RDFS.label):
            return str(label)
        return str(uri).split('/')[-1]

    def _extract_attribute_details(self, graph: Graph, view: Graph, attr_uri: URIRef,
                                   attr_name: str) -> Optional[Dict]:
        """Extract attribute details including resource references. The value
        shape is the node's ``AttributeKind``, read from the hierarchy."""
        try:
            attr_data = {
                'uri': str(attr_uri),
                'attribute_type': 'unknown',
                'category': 'unknown',
                'name': attr_name
            }

            kind = kind_of_node(view, attr_uri)
            if kind is not None and kind.class_uri is not None:
                attr_data['attribute_type'] = _local_name(kind.class_uri)
                attr_data['category'] = _KIND_CATEGORY.get(kind, 'unknown')

            # Extract data based on type
            if kind in (AttributeKind.PHYSICAL, AttributeKind.GEOSPATIAL):
                self._extract_physical_attribute_data(graph, attr_uri, attr_data)
            elif kind is AttributeKind.SIMPLE_COST:
                self._extract_cost_attribute_data(graph, attr_uri, attr_data, simple=True)
            elif kind is AttributeKind.UNIT_BASED_COST:
                self._extract_cost_attribute_data(graph, attr_uri, attr_data, simple=False)
            elif kind is AttributeKind.DYNAMIC:
                self._extract_dynamic_attribute_data(graph, attr_uri, attr_data)
            elif kind is AttributeKind.CURVE:
                self._extract_curve_attribute_data(graph, attr_uri, attr_data)
            elif kind is AttributeKind.CATEGORICAL:
                self._extract_categorical_attribute_data(graph, view, attr_uri, attr_data)
            elif kind is AttributeKind.EVENT:
                self._extract_event_attribute_data(graph, attr_uri, attr_data)
            elif kind is AttributeKind.ANNOTATION:
                self._extract_annotation_attribute_data(graph, attr_uri, attr_data)
            else:
                self._extract_generic_attribute_data(graph, attr_uri, attr_data)

            return attr_data

        except Exception:
            return None

    def _extract_physical_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract physical/geospatial attribute data"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

    def _extract_cost_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict, simple: bool = True):
        """Extract cost attribute data"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for currency in graph.objects(attr_uri, self.DICI.currency):
            attr_data['currency'] = self._map_currency_uri_to_string(str(currency))

        if not simple:
            for unit in graph.objects(attr_uri, self.QUDT.unit):
                attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

        if attr_data.get('currency') is not None and attr_data.get('unit') is None:
            attr_data['unit'] = attr_data['currency']

    def _extract_dynamic_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract dynamic attribute data with resource references"""
        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

        # Check for time series references
        time_series_props = [
            ('hasLiveTimeSeriesReference', 'live'),
            ('hasHistoricTimeSeriesReference', 'historic'),
            ('hasFutureTimeSeriesReference', 'future'),
            ('hasTimeSeriesReference', 'generic')
        ]

        for prop_name, series_type in time_series_props:
            prop_uri = getattr(self.DICI, prop_name)
            for ref_value in graph.objects(attr_uri, prop_uri):
                ref_str = str(ref_value)
                attr_data['time_series_reference'] = ref_str
                attr_data['time_series_type'] = series_type
                attr_data['value'] = f"Time series: {ref_str}"

                # Check if it's a resource reference
                if 'resources/' in ref_str or '.csv' in ref_str:
                    attr_data['resource_reference'] = ref_str
                break

    def _extract_curve_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract curve attribute data"""
        for data_points in graph.objects(attr_uri, self.DICI.hasDataPoints):
            data_points_str = str(data_points)
            attr_data['data_points'] = data_points_str
            attr_data['value'] = data_points_str
            attr_data['unit'] = 'data_points'
            attr_data['data_type'] = 'curve'

            # Check if it's a resource reference
            if 'resources/' in data_points_str or '.csv' in data_points_str:
                attr_data['resource_reference'] = data_points_str

        for x_unit in graph.objects(attr_uri, self.DICI.xUnit):
            attr_data['x_unit'] = self._map_unit_uri_to_string(str(x_unit))

        for y_unit in graph.objects(attr_uri, self.DICI.yUnit):
            attr_data['y_unit'] = self._map_unit_uri_to_string(str(y_unit))

    def _extract_categorical_attribute_data(self, graph: Graph, view: Graph,
                                            attr_uri: URIRef, attr_data: Dict):
        """Extract categorical attribute data.

        The category is the node's ``dici_onto:hasCategoricalValue``. Without
        one, it is the node's only type that is not an attribute class; when the
        data product carries no schema for the attribute's own class, that
        class and the category look alike and no value is guessed. The
        attribute's own class is its type that is neither a kind class nor the
        category."""
        types = list(graph.objects(attr_uri, RDF.type))
        category = next(iter(graph.objects(attr_uri, self.DICI.hasCategoricalValue)), None)
        if category is None:
            candidates = [t for t in types if not is_attribute_class(view, t)]
            category = candidates[0] if len(candidates) == 1 else None

        own_class = [t for t in types if kind_for_class(t) is None and t != category]
        if len(own_class) == 1:
            attr_data['specific_attribute_type'] = _local_name(own_class[0])

        if category is not None:
            category_value = _local_name(category)
            attr_data['value'] = category_value
            attr_data['category_value'] = category_value
            attr_data['unit'] = 'category'
            attr_data['data_type'] = 'categorical'

    def _extract_event_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract event/temporal attribute data"""
        for temporal_value in graph.objects(attr_uri, self.DICI.hasTemporalValue):
            temporal_str = str(temporal_value)
            attr_data['temporal_value'] = temporal_str
            attr_data['value'] = temporal_str
            attr_data['unit'] = 'temporal'
            attr_data['data_type'] = 'temporal'

        for precision in graph.objects(attr_uri, self.DICI.hasTemporalPrecision):
            precision_str = dici_local_name(precision) or str(precision)
            attr_data['temporal_precision'] = precision_str

    def _extract_annotation_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract annotation attribute data"""
        for annotation_value in graph.objects(attr_uri, self.DICI.hasAnnotationValue):
            annotation_str = str(annotation_value)
            attr_data['annotation_value'] = annotation_str
            attr_data['value'] = annotation_str
            attr_data['unit'] = 'annotation'
            attr_data['data_type'] = 'annotation'

            # Check if it's a resource reference
            if 'resources/' in annotation_str:
                attr_data['resource_reference'] = annotation_str

    def _extract_generic_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Fallback generic attribute extraction"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

    def _convert_literal_value(self, literal_value):
        """Convert RDF literal to appropriate Python type"""
        if hasattr(literal_value, 'datatype'):
            datatype = str(literal_value.datatype) if literal_value.datatype else None

            if datatype:
                if 'decimal' in datatype or 'float' in datatype or 'double' in datatype:
                    try:
                        return float(str(literal_value))
                    except:
                        return str(literal_value)
                elif 'int' in datatype:
                    try:
                        return int(str(literal_value))
                    except:
                        return str(literal_value)

        return str(literal_value)

    def _map_unit_uri_to_string(self, unit_uri: str) -> str:
        """Map QUDT unit URIs to readable strings"""
        # An absence must render as nothing, not as the word "None" — see
        # backend.units for the shapes a missing unit arrives in.
        from backend.units import is_missing_unit
        if is_missing_unit(unit_uri):
            return ''

        unit_mapping = {
            'http://qudt.org/vocab/unit/MegaW': 'MW',
            'http://qudt.org/vocab/unit/KiloW': 'kW',
            'http://qudt.org/vocab/unit/M': 'm',
            'http://qudt.org/vocab/unit/DEG': '°',
            'http://qudt.org/vocab/unit/M-PER-SEC': 'm/s',
            'unit:M-PER-SEC': 'm/s',
            'unit:M': 'm',
            'unit:MegaW': 'MW',
            'unit:KiloW': 'kW',
            'unit:DEG': '°'
        }

        if unit_uri.startswith('unit:'):
            return unit_mapping.get(unit_uri, unit_uri.replace('unit:', ''))

        return unit_mapping.get(unit_uri, unit_uri.split('/')[-1])

    def _map_currency_uri_to_string(self, currency_uri: str) -> str:
        """Map currency URIs to readable strings"""
        currency_mapping = {
            # Current — QUDT currency vocabulary
            'http://qudt.org/vocab/currency/CHF': 'CHF',
            'http://qudt.org/vocab/currency/EUR': 'EUR',
            'http://qudt.org/vocab/currency/USD': 'USD',
            'cur:CHF': 'CHF',
            'cur:EUR': 'EUR',
            'cur:USD': 'USD',
            # Legacy — pre-cur switch
            'http://example.org/currency/CHF': 'CHF',
            'http://example.org/currency/EUR': 'EUR',
            'http://example.org/currency/USD': 'USD',
            'iso4217:CHF': 'CHF',
            'iso4217:EUR': 'EUR',
            'iso4217:USD': 'USD',
        }

        return currency_mapping.get(currency_uri, currency_uri.split('/')[-1])


def get_component_summary(components: Dict[str, List[Dict]]) -> Dict:
    """Generate a summary of components and their attributes"""
    summary = {
        'total_components': 0,
        'component_types': [],
        'total_attributes': 0,
        'attribute_categories': {},
        'components_with_resources': 0
    }

    for comp_type, comp_list in components.items():
        summary['total_components'] += len(comp_list)
        summary['component_types'].append({
            'type': comp_type,
            'count': len(comp_list)
        })

        for comp in comp_list:
            # Count attributes
            attrs = comp.get('attributes', {})
            summary['total_attributes'] += len(attrs)

            # Count resources
            if comp.get('resources'):
                summary['components_with_resources'] += 1

            # Categorize attributes
            for attr_name, attr_data in attrs.items():
                if isinstance(attr_data, dict):
                    category = attr_data.get('category', 'unknown')
                    if category not in summary['attribute_categories']:
                        summary['attribute_categories'][category] = 0
                    summary['attribute_categories'][category] += 1

    return summary