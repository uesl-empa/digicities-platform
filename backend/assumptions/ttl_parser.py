# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# ============================================================================
# components/assumptions/ttl_parser.py
"""
TTL parser for baseline scenarios
Lightweight parser leveraging existing infrastructure
"""


def parse_ttl_scenario(ttl_content):
    """
    Parse TTL content into scenario structure
    Leverages existing scenario builder infrastructure
    """
    try:
        from rdflib import Graph, Namespace, URIRef
        from rdflib.namespace import RDF, RDFS

        # Create graph
        graph = Graph()
        graph.parse(data=ttl_content, format="turtle")

        # Define namespaces
        DICI = Namespace("https://digicities.info/ontology#")
        QUDT = Namespace("http://qudt.org/schema/qudt/")

        # Extract scenario URI and name
        scenario_uri = None
        scenario_name = None

        for s, p, o in graph.triples((None, RDF.type, DICI.Scenario)):
            scenario_uri = str(s)
            for label in graph.objects(s, RDFS.label):
                scenario_name = str(label)
            break

        if not scenario_uri:
            return {'error': 'No scenario found in TTL'}

        if not scenario_name:
            scenario_name = scenario_uri.split('/')[-1]

        # Extract namespace from scenario URI
        namespace = '/'.join(scenario_uri.split('/')[:-1])

        # Extract components
        components = []

        for subject in graph.subjects():
            subject_uri = str(subject)

            # Skip scenario itself and attributes
            if subject_uri == scenario_uri:
                continue

            # Get component types (excluding attribute types)
            component_types = []
            for comp_type in graph.objects(subject, RDF.type):
                type_str = str(comp_type)
                if str(DICI) in type_str:
                    type_name = type_str.replace(str(DICI), "")
                    # Skip if it's an attribute type
                    if not is_attribute_type(type_name):
                        component_types.append(type_name)

            if not component_types:
                continue

            # Use first non-attribute type as component type
            component_type = component_types[0]

            # Get label
            component_label = None
            for label in graph.objects(subject, RDFS.label):
                component_label = str(label)
                break

            if not component_label:
                component_label = subject_uri.split('/')[-1]

            # Extract attributes
            attributes = {}

            # Look for attribute relationships
            for pred, attr_uri in graph.predicate_objects(subject):
                pred_str = str(pred)

                # Check if this is an attribute relationship
                if 'hasAttribute' in pred_str or 'Attribute' in pred_str:
                    attr_name = extract_attribute_name_from_predicate(pred_str)

                    if attr_name:
                        attr_data = extract_attribute_data(graph, attr_uri, QUDT, DICI)
                        if attr_data:
                            attributes[attr_name] = attr_data

            # Create component
            component = {
                'uri': subject_uri,
                'type': component_type,
                'label': component_label,
                'attributes': attributes,
                'nested_properties': {}
            }

            components.append(component)

        return {
            'scenario_uri': scenario_uri,
            'scenario_name': scenario_name,
            'namespace': namespace,
            'components': components,
            'component_links': []
        }

    except Exception as e:
        return {'error': f'Failed to parse TTL: {str(e)}'}


def is_attribute_type(type_name):
    """Check if type name is an attribute type"""
    attribute_indicators = [
        'Attribute', 'Cost', 'Power', 'Curve', 'Production',
        'Height', 'Diameter', 'Elevation', 'Latitude', 'Longitude'
    ]
    return any(indicator in type_name for indicator in attribute_indicators)


def extract_attribute_name_from_predicate(predicate_str):
    """Extract attribute name from predicate URI"""
    # Remove namespace
    local_part = predicate_str.split('#')[-1].split('/')[-1]

    # Handle has...Attribute pattern
    if local_part.startswith('has') and local_part.endswith('Attribute'):
        attr_name = local_part[3:-9]  # Remove 'has' and 'Attribute'

        # Remove component type prefix if present
        component_types = [
            'WindTurbine', 'GlobalWindAtlasSite', 'Region',
            'PV', 'Building', 'EnergyCarrier'
        ]
        for comp_type in component_types:
            if attr_name.startswith(comp_type):
                attr_name = attr_name[len(comp_type):]
                break

        return attr_name if attr_name else None

    return None


def extract_attribute_data(graph, attr_uri, QUDT, DICI):
    """Extract attribute data from graph"""
    from rdflib import RDF

    attr_data = {
        'uri': str(attr_uri),
        'attribute_type': 'PhysicalAttribute',
        'category': 'unknown'
    }

    # Get attribute type
    for attr_type in graph.objects(attr_uri, RDF.type):
        type_str = str(attr_type)
        if 'Attribute' in type_str:
            attr_data['attribute_type'] = type_str.split('#')[-1].split('/')[-1]

            # Determine category
            if 'Cost' in type_str:
                attr_data['category'] = 'cost'
            elif 'Physical' in type_str:
                attr_data['category'] = 'physical'
            elif 'Dynamic' in type_str:
                attr_data['category'] = 'dynamic'
            elif 'Categorical' in type_str:
                attr_data['category'] = 'categorical'

    # Get value
    for value in graph.objects(attr_uri, QUDT.value):
        attr_data['value'] = str(value)

    # Get unit
    for unit in graph.objects(attr_uri, QUDT.unit):
        unit_str = str(unit)
        attr_data['unit'] = unit_str.split('/')[-1]

    # Get currency for cost attributes
    for currency in graph.objects(attr_uri, DICI.currency):
        currency_str = str(currency)
        attr_data['currency'] = currency_str.split('/')[-1].split(':')[-1]

    return attr_data if 'value' in attr_data or 'category' in attr_data else None
