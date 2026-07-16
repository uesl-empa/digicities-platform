# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Manual modification engine for scenario components.
Handles direct user-specified changes to component attributes.
"""
import uuid

DEFAULT_BASELINE_NAMESPACE = 'https://digicities.info/proj/REFORMERS'


def apply_manual_modifications(baseline_data, target_component_uri, modifications, new_scenario_name, namespace=None):
    """
    Apply manual modifications to a specific component to create new scenario.

    Args:
        baseline_data: The baseline scenario data
        target_component_uri: URI of the component being modified
        modifications: Dict of attribute modifications {attr_name: {old_value, new_value, ...}}
        new_scenario_name: Name for the new scenario
        namespace: Baseline namespace (defaults to ``DEFAULT_BASELINE_NAMESPACE``)

    Returns:
        Modified scenario data structure
    """
    baseline_components = baseline_data['components']
    all_components = []
    modification_id = str(uuid.uuid4())[:8]

    if namespace is None:
        namespace = DEFAULT_BASELINE_NAMESPACE

    modification_log = []

    for component in baseline_components:
        if component['uri'] == target_component_uri:
            modified_component = create_manually_modified_component(
                component,
                modifications,
                modification_id,
                namespace,
                modification_log
            )
            all_components.append(modified_component)
        else:
            unmodified_component = create_unmodified_component(
                component,
                namespace
            )
            all_components.append(unmodified_component)

    return {
        'scenario_name': new_scenario_name,
        'components': all_components,
        'component_links': baseline_data.get('component_links', []),
        'modification_type': 'manual',
        'modification_id': modification_id,
        'type': 'manual_modification',
        'modified_count': len(modifications),
        'modification_log': modification_log,
        'namespace': namespace,
        'target_component_uri': target_component_uri,
        'manual_modifications': modifications
    }


def create_manually_modified_component(component, modifications, modification_id, namespace, modification_log):
    """Create a modified component with manually changed attributes."""
    original_uri_parts = component['uri'].split('/')
    component_identifier = '/'.join(original_uri_parts[-2:])

    modified_component = {
        'uri': f"{namespace}/{component_identifier}_manual_{modification_id}",
        'type': component['type'],
        'label': f"{component['label']} (Manual Mod)",
        'attributes': {},
        'nested_properties': component.get('nested_properties', {}).copy(),
        'source': 'manual_modified',
        'modification_id': modification_id,
        'derived_from': component['uri']
    }

    for attr_name, attr_data in component.get('attributes', {}).items():
        if attr_name in ['URI', 'label'] or not isinstance(attr_data, dict):
            continue

        if attr_name in modifications:
            mod_data = modifications[attr_name]
            new_value = mod_data['new_value']
            old_value = mod_data['old_value']

            modified_component['attributes'][attr_name] = {
                'uri': f"{modified_component['uri']}/{attr_name}",
                'type': attr_data.get('type', 'PhysicalAttribute'),
                'value': str(new_value),
                'unit': attr_data.get('unit', ''),
                'attribute_type': attr_data.get('attribute_type', 'PhysicalAttribute'),
                'category': attr_data.get('category', 'physical')
            }

            try:
                old_float = float(old_value)
                new_float = float(new_value)
                change_pct = ((new_float - old_float) / old_float * 100) if old_float != 0 else 0

                modification_log.append({
                    'component': component['label'],
                    'attribute': attr_name,
                    'old_value': old_float,
                    'new_value': new_float,
                    'change_percent': change_pct,
                    'modification_type': 'manual'
                })
            except (ValueError, TypeError):
                modification_log.append({
                    'component': component['label'],
                    'attribute': attr_name,
                    'old_value': str(old_value),
                    'new_value': str(new_value),
                    'modification_type': 'manual'
                })
        else:
            modified_component['attributes'][attr_name] = {
                'uri': f"{modified_component['uri']}/{attr_name}",
                'type': attr_data.get('type', 'PhysicalAttribute'),
                'value': attr_data['value'],
                'unit': attr_data.get('unit', ''),
                'attribute_type': attr_data.get('attribute_type', 'PhysicalAttribute'),
                'category': attr_data.get('category', 'unknown')
            }

    return modified_component


def create_unmodified_component(component, namespace):
    """Create unmodified component with updated namespace."""
    original_uri_parts = component['uri'].split('/')
    component_identifier = '/'.join(original_uri_parts[-2:])

    unmodified_component = {
        'uri': f"{namespace}/{component_identifier}",
        'type': component['type'],
        'label': component['label'],
        'attributes': {},
        'nested_properties': component.get('nested_properties', {}).copy(),
        'source': 'unmodified',
        'derived_from': component['uri']
    }

    for attr_name, attr_data in component.get('attributes', {}).items():
        if attr_name in ['URI', 'label'] or not isinstance(attr_data, dict):
            continue

        unmodified_component['attributes'][attr_name] = {
            'uri': f"{unmodified_component['uri']}/{attr_name}",
            'type': attr_data.get('type', 'PhysicalAttribute'),
            'value': attr_data['value'],
            'unit': attr_data.get('unit', ''),
            'attribute_type': attr_data.get('attribute_type', 'PhysicalAttribute'),
            'category': attr_data.get('category', 'unknown')
        }

    return unmodified_component


def apply_batch_manual_modifications(baseline_data, component_modifications, new_scenario_name, namespace=None):
    """
    Apply manual modifications to multiple components at once.

    Args:
        baseline_data: The baseline scenario data
        component_modifications: Dict mapping component URIs to their modifications
        new_scenario_name: Name for the new scenario
        namespace: Baseline namespace (defaults to ``DEFAULT_BASELINE_NAMESPACE``)

    Returns:
        Modified scenario data structure
    """
    baseline_components = baseline_data['components']
    all_components = []
    modification_id = str(uuid.uuid4())[:8]

    if namespace is None:
        namespace = DEFAULT_BASELINE_NAMESPACE

    modification_log = []
    total_modifications = 0

    for component in baseline_components:
        if component['uri'] in component_modifications:
            modifications = component_modifications[component['uri']]
            total_modifications += len(modifications)

            modified_component = create_manually_modified_component(
                component,
                modifications,
                modification_id,
                namespace,
                modification_log
            )
            all_components.append(modified_component)
        else:
            unmodified_component = create_unmodified_component(
                component,
                namespace
            )
            all_components.append(unmodified_component)

    return {
        'scenario_name': new_scenario_name,
        'components': all_components,
        'component_links': baseline_data.get('component_links', []),
        'modification_type': 'manual_batch',
        'modification_id': modification_id,
        'type': 'manual_modification',
        'modified_count': total_modifications,
        'modified_components': len(component_modifications),
        'modification_log': modification_log,
        'namespace': namespace,
        'manual_modifications': component_modifications
    }


def validate_modification_value(old_value, new_value, category):
    """Validate that a modification value is appropriate for the attribute category."""
    if category in ['physical', 'cost', 'geospatial']:
        try:
            float(new_value)
            return True, None
        except (ValueError, TypeError):
            return False, f"Value must be numeric for {category} attributes"

    return True, None


def calculate_modification_impact(old_value, new_value, unit=''):
    """Calculate the impact of a modification."""
    try:
        old_float = float(old_value)
        new_float = float(new_value)

        absolute_change = new_float - old_float
        percent_change = ((new_float - old_float) / old_float * 100) if old_float != 0 else 0

        return {
            'old_value': old_float,
            'new_value': new_float,
            'absolute_change': absolute_change,
            'percent_change': percent_change,
            'unit': unit,
            'is_numeric': True
        }
    except (ValueError, TypeError):
        return {
            'old_value': str(old_value),
            'new_value': str(new_value),
            'is_numeric': False
        }
