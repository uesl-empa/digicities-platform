# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
TTL Parser Module - IMPROVED VERSION
File: components/data_products/ttl_parser.py

Handles TTL parsing and attribute extraction using RDFLib.
Better distinguishes between components and attributes.
"""

from typing import Dict, List, Optional, Any, Set
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS


class TTLParser:
    """Parser for TTL files and RDF graphs"""

    def __init__(self):
        """Initialize with namespaces and attribute type definitions"""
        # Define namespaces
        self.DICI = Namespace("https://digicities.info/ontology#")
        self.QUDT = Namespace("http://qudt.org/schema/qudt/")
        self.UNIT = Namespace("http://qudt.org/vocab/unit/")
        self.XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
        self.CUR = Namespace("http://qudt.org/vocab/currency/")
        # Legacy alias kept so old workspace TTLs (pre-cur switch) still parse cleanly.
        self.ISO4217 = Namespace("http://example.org/currency/")

        # Define known attribute types (these are NOT components)
        self.KNOWN_ATTRIBUTE_TYPES = {
            'PhysicalAttribute', 'SimpleCostAttribute', 'UnitBasedCostAttribute',
            'GeospatialAttribute', 'DynamicAttribute', 'CurveAttribute',
            'CategoricalAttribute', 'EventAttribute', 'AnnotationAttribute',
            'TemporalAttribute', 'TimeSeriesAttribute'
        }

        # Define attribute type patterns that indicate it's an attribute, not a component
        self.ATTRIBUTE_PATTERNS = [
            'Attribute',  # Anything ending with Attribute
            'Cost', 'Price', 'CAPEX', 'OPEX',  # Cost-related
            'Power', 'Energy', 'Capacity',  # Energy-related
            'Height', 'Width', 'Length', 'Diameter', 'Radius', 'Area', 'Volume',  # Physical dimensions
            'Latitude', 'Longitude', 'Elevation', 'Coordinate',  # Geospatial
            'Temperature', 'Pressure', 'Humidity',  # Environmental
            'Efficiency', 'Performance', 'Rating',  # Performance metrics
            'TimeSeries', 'Curve', 'Profile',  # Data series
            'Production', 'Consumption', 'Generation',  # Process-related
            'Roughness', 'Density', 'Weight', 'Mass',  # Material properties
            'Irradiance', 'Radiation', 'Luminosity',  # Light/radiation
            'Speed', 'Velocity', 'Acceleration',  # Motion
            'Flow', 'Rate', 'Flux',  # Rates and flows
            'Voltage', 'Current', 'Resistance',  # Electrical
            'Status', 'State', 'Mode', 'Type',  # Categorical
            'Year', 'Date', 'Time', 'Duration', 'Period',  # Temporal
            'Reference', 'Index', 'ID', 'Code',  # Identifiers
            'Annotation', 'Note', 'Description', 'Comment'  # Annotations
        ]

        # Define attribute types and their properties
        self.ATTRIBUTE_TYPES = {
            'PhysicalAttribute': {
                'required_props': ['qudt:value', 'qudt:unit'],
                'category': 'physical'
            },
            'SimpleCostAttribute': {
                'required_props': ['qudt:value', 'dici_onto:currency'],
                'category': 'cost'
            },
            'UnitBasedCostAttribute': {
                'required_props': ['qudt:value', 'qudt:unit', 'dici_onto:currency'],
                'category': 'cost'
            },
            'GeospatialAttribute': {
                'required_props': ['qudt:value', 'qudt:unit'],
                'category': 'geospatial'
            },
            'DynamicAttribute': {
                'required_props': ['qudt:unit'],
                'category': 'dynamic'
            },
            'CurveAttribute': {
                'required_props': ['dici_onto:hasDataPoints'],
                'category': 'curve'
            },
            'CategoricalAttribute': {
                'required_props': [],
                'category': 'categorical'
            },
            'EventAttribute': {
                'required_props': ['dici_onto:hasTemporalValue'],
                'category': 'temporal'
            },
            'AnnotationAttribute': {
                'required_props': ['dici_onto:hasAnnotationValue'],
                'category': 'annotation'
            }
        }

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
        """Extract all components from RDFLib graph"""
        components_by_type = {}

        # First pass: identify all attribute instances
        attribute_uris = self._identify_all_attributes(graph)

        # Second pass: extract only non-attribute components
        for subject, predicate, obj in graph.triples((None, RDF.type, None)):
            if str(obj).startswith(str(self.DICI)):
                component_type = str(obj).replace(str(self.DICI), "")

                # Skip if this is an attribute instance
                if str(subject) in attribute_uris:
                    continue

                # Skip if this type is an attribute type
                if self._is_attribute_type(component_type):
                    continue

                component_data = self._extract_component_data(graph, subject, component_type)

                if component_data:
                    if component_type not in components_by_type:
                        components_by_type[component_type] = []
                    components_by_type[component_type].append(component_data)

        return components_by_type

    def _identify_all_attributes(self, graph: Graph) -> Set[str]:
        """Identify all URIs that are attributes (not components)"""
        attribute_uris = set()

        # Find all subjects that have attribute types
        for subject, predicate, obj in graph.triples((None, RDF.type, None)):
            if str(obj).startswith(str(self.DICI)):
                type_name = str(obj).replace(str(self.DICI), "")
                if self._is_attribute_type(type_name):
                    attribute_uris.add(str(subject))

        # Also find all objects of hasAttribute predicates
        for subject, predicate, obj in graph.triples((None, None, None)):
            predicate_str = str(predicate)
            if 'hasAttribute' in predicate_str or (
                predicate_str.startswith(str(self.DICI)) and
                any(pattern in predicate_str for pattern in self.ATTRIBUTE_PATTERNS)
            ):
                attribute_uris.add(str(obj))

        return attribute_uris

    def _is_attribute_type(self, type_name: str) -> bool:
        """Check if a type name represents an attribute type (not a component type)"""
        # Check if it's a known attribute type
        if type_name in self.KNOWN_ATTRIBUTE_TYPES:
            return True

        # Check if it contains any attribute pattern
        for pattern in self.ATTRIBUTE_PATTERNS:
            if pattern in type_name:
                return True

        # Additional checks for specific patterns
        # Types that end with specific attribute suffixes
        attribute_suffixes = [
            'Attribute', 'Cost', 'Value', 'Parameter', 'Property',
            'Metric', 'Measurement', 'Index', 'Ratio', 'Factor'
        ]
        for suffix in attribute_suffixes:
            if type_name.endswith(suffix):
                return True

        # Types that are clearly attributes based on their structure
        # e.g., WindTurbineHeightAttribute, PVEfficiencyAttribute
        if 'Attribute' in type_name:
            return True

        return False

    def _is_attribute_instance(self, type_name: str) -> bool:
        """Legacy method - redirects to _is_attribute_type"""
        return self._is_attribute_type(type_name)

    def _extract_component_data(self, graph: Graph, component_uri: URIRef, component_type: str) -> Optional[Dict]:
        """Extract complete component data"""
        try:
            component = {
                'uri': str(component_uri),
                'label': self._get_label(graph, component_uri),
                'type': component_type,
                'attributes': {},
                'resources': {}
            }

            # Extract attributes
            for predicate, attr_uri in graph.predicate_objects(component_uri):
                predicate_str = str(predicate)

                if 'hasAttribute' in predicate_str or (predicate_str.startswith(str(self.DICI)) and 'Attribute' in predicate_str):
                    attr_name = self._extract_attribute_name_from_predicate(predicate_str)
                    if attr_name:
                        attr_data = self._extract_attribute_details(graph, attr_uri, attr_name)
                        if attr_data:
                            component['attributes'][attr_name] = attr_data

                            # Track resource references
                            if attr_data.get('resource_reference'):
                                component['resources'][attr_name] = attr_data['resource_reference']

            # Also check for attributes defined as sub-URIs of the component
            component_uri_str = str(component_uri)
            for subject in graph.subjects():
                subject_str = str(subject)
                # Check if this is a sub-URI of the component (e.g., component/attribute)
                if subject_str.startswith(component_uri_str + '/'):
                    # This might be an attribute
                    attr_name = subject_str.split('/')[-1]

                    # Check if it has attribute types
                    for obj in graph.objects(subject, RDF.type):
                        if str(obj).startswith(str(self.DICI)):
                            type_name = str(obj).replace(str(self.DICI), "")
                            if self._is_attribute_type(type_name):
                                attr_data = self._extract_attribute_details(graph, subject, attr_name)
                                if attr_data:
                                    component['attributes'][attr_name] = attr_data
                                    if attr_data.get('resource_reference'):
                                        component['resources'][attr_name] = attr_data['resource_reference']
                                break

            return component

        except Exception as e:
            return None

    def _get_label(self, graph: Graph, uri: URIRef) -> str:
        """Get rdfs:label for a URI"""
        for label in graph.objects(uri, RDFS.label):
            return str(label)
        return str(uri).split('/')[-1]

    def _extract_attribute_name_from_predicate(self, predicate_str: str) -> Optional[str]:
        """Extract attribute name from predicate URI"""
        if str(self.DICI) in predicate_str:
            local_part = predicate_str.replace(str(self.DICI), "")

            if local_part.startswith('has') and local_part.endswith('Attribute'):
                attr_part = local_part[3:-9]

                # Remove component type prefix if present
                component_types = [
                    'WindTurbine', 'GlobalWindAtlasSite', 'Region', 'EnergyCarrier',
                    'PV', 'SolarPanel', 'Battery', 'Grid', 'Load', 'Generator', 'Building'
                ]
                for comp_type in component_types:
                    if attr_part.startswith(comp_type):
                        attr_part = attr_part[len(comp_type):]
                        break

                return attr_part if attr_part else None
            elif local_part == 'hasAttribute':
                return 'hasAttribute'

        return None

    def _extract_attribute_details(self, graph: Graph, attr_uri: URIRef, attr_name: str) -> Optional[Dict]:
        """Extract attribute details including resource references"""
        try:
            attr_data = {
                'uri': str(attr_uri),
                'attribute_type': 'unknown',
                'category': 'unknown',
                'name': attr_name
            }

            # Get attribute types
            attribute_types = []
            for attr_type in graph.objects(attr_uri, RDF.type):
                if str(attr_type).startswith(str(self.DICI)):
                    type_name = str(attr_type).replace(str(self.DICI), "")
                    attribute_types.append(type_name)

            # Determine primary type
            primary_type = self._determine_primary_attribute_type(attribute_types)
            if primary_type:
                attr_data['attribute_type'] = primary_type
                attr_data['category'] = self.ATTRIBUTE_TYPES.get(primary_type, {}).get('category', 'unknown')

            # Extract data based on type
            if primary_type == 'PhysicalAttribute' or primary_type == 'GeospatialAttribute':
                self._extract_physical_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'SimpleCostAttribute':
                self._extract_cost_attribute_data(graph, attr_uri, attr_data, simple=True)
            elif primary_type == 'UnitBasedCostAttribute':
                self._extract_cost_attribute_data(graph, attr_uri, attr_data, simple=False)
            elif primary_type == 'DynamicAttribute':
                self._extract_dynamic_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'CurveAttribute':
                self._extract_curve_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'CategoricalAttribute':
                self._extract_categorical_attribute_data(graph, attr_uri, attr_data, attribute_types)
            elif primary_type == 'EventAttribute':
                self._extract_event_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'AnnotationAttribute':
                self._extract_annotation_attribute_data(graph, attr_uri, attr_data)
            else:
                self._extract_generic_attribute_data(graph, attr_uri, attr_data)

            return attr_data if 'value' in attr_data or 'resource_reference' in attr_data else attr_data

        except Exception:
            return None

    def _determine_primary_attribute_type(self, attribute_types: List[str]) -> Optional[str]:
        """Determine primary attribute type from list"""
        priority_order = [
            'EventAttribute',
            'AnnotationAttribute',
            'CategoricalAttribute',
            'DynamicAttribute',
            'CurveAttribute',
            'UnitBasedCostAttribute',
            'SimpleCostAttribute',
            'GeospatialAttribute',
            'PhysicalAttribute'
        ]

        for priority_type in priority_order:
            if priority_type in attribute_types:
                return priority_type

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

        if 'currency' in attr_data and 'unit' not in attr_data:
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

    def _extract_categorical_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict, attribute_types: List[str]):
        """Extract categorical attribute data"""
        uri_fragment = str(attr_uri).split('/')[-1]

        # Find categorical value
        category_value = None
        for attr_type in attribute_types:
            if attr_type != 'CategoricalAttribute' and attr_type != uri_fragment:
                category_value = attr_type
                break

        if category_value:
            attr_data['value'] = category_value
            attr_data['category_value'] = category_value
            attr_data['unit'] = 'category'
            attr_data['data_type'] = 'categorical'
            attr_data['specific_attribute_type'] = uri_fragment

    def _extract_event_attribute_data(self, graph: Graph, attr_uri: URIRef, attr_data: Dict):
        """Extract event/temporal attribute data"""
        for temporal_value in graph.objects(attr_uri, self.DICI.hasTemporalValue):
            temporal_str = str(temporal_value)
            attr_data['temporal_value'] = temporal_str
            attr_data['value'] = temporal_str
            attr_data['unit'] = 'temporal'
            attr_data['data_type'] = 'temporal'

        for precision in graph.objects(attr_uri, self.DICI.hasTemporalPrecision):
            precision_str = str(precision).replace(str(self.DICI), "")
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