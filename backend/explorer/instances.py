# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Component types and their instance data, fetched from the triplestore.

The SPARQL itself lives in ``backend.graphdb.queries`` (subClassOf* /
subPropertyOf* property paths, backend-agnostic FROM clauses). These functions
run those queries and shape the DataFrame results into the binding-dict form
(``{'instance': {'value': ...}, ...}``) that the attribute pipeline consumes.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.graphdb import queries as gdb_queries

from backend.explorer.uris import extract_property_name


def get_component_types_with_instances(client) -> pd.DataFrame:
    """Get component types that actually have instances in the knowledge graph.

    Thin wrapper over ``backend.graphdb.queries`` (the SPARQL lives there, UI-free).
    """
    return gdb_queries.get_component_types_with_instances(client)


def get_component_instances(client, component_type_label: str) -> Optional[List[Dict[str, Any]]]:
    """Get all instances of a specific component type.

    Queries via ``backend.graphdb.queries`` and shapes the result into the
    binding-dict form the explorer's rendering expects.
    """
    result_df = gdb_queries.get_component_instances(client, component_type_label)

    instances = []
    for _, row in result_df.iterrows():
        instance_data = {'instance': {'value': row.get('instance', '')}}
        if 'instanceLabel' in row and pd.notna(row['instanceLabel']):
            instance_data['instanceLabel'] = {'value': row['instanceLabel']}
        instances.append(instance_data)
    return instances


def get_component_attributes_comprehensive(client, component_type_label: str) -> Optional[List[Dict[str, Any]]]:
    """Get comprehensive attribute data for all instances of a component type.

    Queries via ``backend.graphdb.queries`` (which uses a
    ``subPropertyOf* hasAttribute`` property path so typed attribute predicates
    are picked up on any backend) and shapes the result into binding dicts.
    """
    result_df = gdb_queries.get_component_attributes_comprehensive(client, component_type_label)

    attributes = []
    for _, row in result_df.iterrows():
        attributes.append({
            'instance': {'value': row.get('instance', '')},
            'attribute': {'value': row.get('attribute', '')},
            'property': {'value': row.get('property', '')},
            'value': {'value': row.get('value', '')}
        })
    return attributes


def get_component_basic_properties(client, component_type_label: str) -> Optional[List[Dict[str, Any]]]:
    """Get basic (non-attribute) properties of component instances.

    Queries via ``backend.graphdb.queries`` and shapes the result into binding dicts.
    """
    result_df = gdb_queries.get_component_basic_properties(client, component_type_label)

    properties = []
    for _, row in result_df.iterrows():
        properties.append({
            'instance': {'value': row.get('instance', '')},
            'property': {'value': row.get('property', '')},
            'value': {'value': row.get('value', '')}
        })
    return properties


def get_component_data_unified(client, component_type_label: str) -> Tuple[List[Dict], List[Dict]]:
    """Unified method to get component instances and their attributes"""
    instances = get_component_instances(client, component_type_label)

    attributes = None
    try:
        attributes = get_component_attributes_comprehensive(client, component_type_label)
        if attributes and len(attributes) > 0:
            print(f"DEBUG: Successfully got {len(attributes)} attribute properties")
        else:
            attributes = []
    except Exception as e:
        print(f"DEBUG: Comprehensive query failed: {e}")
        attributes = []

    # REMOVED: The section that merges basic properties into attributes
    # This was causing the unwanted columns

    return instances or [], attributes or []
    # Also get basic properties and merge them
    try:
        basic_props = get_component_basic_properties(client, component_type_label)
        if basic_props and len(basic_props) > 0:
            for prop in basic_props:
                prop_name = extract_property_name(prop.get('property', {}).get('value', ''))
                attributes.append({
                    'instance': prop.get('instance'),
                    'attribute': {'value': f"{prop.get('instance', {}).get('value', '')}/_{prop_name}"},
                    'property': {'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#value'},
                    'value': prop.get('value')
                })
            print(f"DEBUG: Added {len(basic_props)} basic properties")
    except Exception as e:
        print(f"DEBUG: Error getting basic properties: {e}")

    return instances or [], attributes or []
