# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/component_display_utils.py
"""
Pure, dependency-free helpers for shaping component dicts for display.

Relocated out of the legacy ``ttl_use_case_loader`` so the Scenario Builder,
Assumptions, and links modules can share them without importing that loader.
These operate on plain dicts/URIs only — no graph, storage, or network access.
"""
from typing import Dict, Optional


def get_uri_fragment(uri: str) -> str:
    """Extract the last part of a URI (after the last '/' or '#')."""
    if '#' in uri:
        return uri.split('#')[-1]
    elif '/' in uri:
        return uri.split('/')[-1]
    return uri


def format_ttl_component_for_display(component: Dict) -> Dict:
    """Normalise a component dict into the shape the Scenario Builder UI renders."""
    formatted = {
        'uri': component['uri'],
        'label': component['label'],
        'uri_fragment': get_uri_fragment(component['uri']),
        'source': component.get('source', 'ttl_use_case'),
        'workspace_id': component.get('workspace_id'),
        'data_product_name': component.get('data_product_name'),
        'data_product_type': component.get('data_product_type'),
        'attributes': {},
        'nested_properties': component.get('nested_properties', {}),
        'instance_declaration': f"<{component['uri']}> a dici_onto:{component['type']} ; rdfs:label \"{component['label']}\" ."
    }

    for attr_name, attr_data in component.get('attributes', {}).items():
        if isinstance(attr_data, dict) and ('value' in attr_data or 'temporal_value' in attr_data):
            formatted_attr = {
                'value': attr_data.get('value', attr_data.get('temporal_value')),
                'unit': attr_data.get('unit', 'dimensionless'),
                'attribute_type': attr_data.get('attribute_type', 'unknown'),
                'category': attr_data.get('category', 'unknown')
            }

            if attr_data.get('currency'):
                formatted_attr['currency'] = attr_data['currency']

            if attr_data.get('time_series_reference'):
                formatted_attr['time_series_reference'] = attr_data['time_series_reference']
                formatted_attr['time_series_type'] = attr_data.get('time_series_type', 'unknown')

            if attr_data.get('time_series_uri'):
                formatted_attr['time_series_uri'] = attr_data['time_series_uri']

            if attr_data.get('data_type') == 'curve':
                formatted_attr['data_type'] = 'curve'
                if 'x_unit' in attr_data:
                    formatted_attr['x_unit'] = attr_data['x_unit']
                if 'y_unit' in attr_data:
                    formatted_attr['y_unit'] = attr_data['y_unit']
                if 'data_points' in attr_data:
                    formatted_attr['data_points'] = attr_data['data_points']

            if attr_data.get('attribute_type') == 'CategoricalAttribute':
                formatted_attr['data_type'] = 'categorical'
                if 'category_value' in attr_data:
                    formatted_attr['category_value'] = attr_data['category_value']
                if 'specific_attribute_type' in attr_data:
                    formatted_attr['specific_attribute_type'] = attr_data['specific_attribute_type']

            if attr_data.get('attribute_type') == 'EventAttribute':
                formatted_attr['data_type'] = 'temporal'
                if 'temporal_value' in attr_data:
                    formatted_attr['temporal_value'] = attr_data['temporal_value']
                if 'temporal_precision' in attr_data:
                    formatted_attr['temporal_precision'] = attr_data['temporal_precision']

            formatted['attributes'][attr_name] = formatted_attr

    return formatted


def get_nested_property_from_ttl_component(component: Dict, property_path: str) -> Optional[str]:
    """Resolve a dotted ``Attribute.nestedProp`` path against a component dict.

    Pure: reads only the component's ``attributes`` / ``nested_properties`` maps.
    """
    if '.' not in property_path:
        return None
    parts = property_path.split('.')
    if len(parts) < 2:
        return None

    base_attribute, nested_property = parts[0], parts[1]
    if base_attribute in component.get('attributes', {}):
        nested_props = component.get('nested_properties', {}).get(base_attribute, {})
        if nested_property in nested_props:
            return nested_props[nested_property]
        attr_data = component['attributes'][base_attribute]
        if nested_property in attr_data:
            return attr_data[nested_property]
    return None
