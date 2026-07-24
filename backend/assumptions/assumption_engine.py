# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/assumptions/assumption_engine.py
"""
Streamlined assumption engine
Applies assumptions to baseline scenarios to create modified scenarios
"""
import uuid
import json

DEFAULT_BASELINE_NAMESPACE = 'https://digicities.info/proj/REFORMERS'


def apply_single_assumption(baseline_data, assumption, new_scenario_name, namespace=None):
    """Apply single assumption to create new scenario"""
    baseline_components = baseline_data['components']
    all_components = []
    assumption_id = str(uuid.uuid4())[:8]

    if namespace is None:
        namespace = DEFAULT_BASELINE_NAMESPACE

    modified_count = 0
    modification_log = []
    target_components = [comp for comp in baseline_components
                         if comp['type'] == assumption['target_component']]

    # Process all components
    for component in baseline_components:
        if component['type'] == assumption['target_component']:
            # Create modified component
            original_uri_parts = component['uri'].split('/')
            component_identifier = '/'.join(original_uri_parts[-2:])

            modified_component = {
                'uri': f"{namespace}/{component_identifier}_modified_{assumption_id}",
                'type': component['type'],
                'label': f"{component['label']} (Modified)",
                'attributes': {},
                'nested_properties': component.get('nested_properties', {}).copy(),
                'source': 'modified',
                'modification_id': assumption_id,
                'derived_from': component['uri']
            }

            # Apply modification
            result = apply_modification_to_component(
                component, modified_component, assumption
            )

            if result['success']:
                modified_count += 1
                modification_log.append(result['modification_detail'])

            all_components.append(modified_component)
        else:
            # Include unmodified components
            unmodified_component = create_unmodified_component(
                component, namespace
            )
            all_components.append(unmodified_component)

    return {
        'scenario_name': new_scenario_name,
        'components': all_components,
        'component_links': baseline_data.get('component_links', []),
        'assumption': assumption,
        'assumption_id': assumption_id,
        'type': 'single',
        'modified_count': modified_count,
        'modification_log': modification_log,
        'namespace': namespace,
        'based_on': baseline_data.get('scenario_uri'),
        'service': baseline_data.get('service'),
        'workspace': baseline_data.get('workspace')
    }


def apply_series_assumption(baseline_data, assumption, base_scenario_name, namespace=None):
    """Apply series assumption to create multiple scenarios"""
    timesteps = json.loads(assumption['assumption_timesteps'])
    modifier_values = json.loads(assumption['modifier_value_series'])

    if namespace is None:
        namespace = DEFAULT_BASELINE_NAMESPACE

    scenarios = []
    baseline_components = baseline_data['components']

    for i, timestep in enumerate(timesteps):
        scenario_name = f"{base_scenario_name}_{timestep}"
        all_components = []
        assumption_id = str(uuid.uuid4())[:8]
        modified_count = 0
        modification_log = []

        for component in baseline_components:
            if component['type'] == assumption['target_component']:
                # Create modified component for this timestep
                original_uri_parts = component['uri'].split('/')
                component_identifier = '/'.join(original_uri_parts[-2:])

                modified_component = {
                    'uri': f"{namespace}/{component_identifier}_{timestep}_modified_{assumption_id}",
                    'type': component['type'],
                    'label': f"{component['label']} ({timestep})",
                    'attributes': {},
                    'nested_properties': component.get('nested_properties', {}).copy(),
                    'source': 'modified',
                    'modification_id': assumption_id,
                    'derived_from': component['uri'],
                    'timestep': timestep
                }

                # Apply cumulative modification
                result = apply_series_modification(
                    component, modified_component, assumption, i, modifier_values
                )

                if result['success']:
                    modified_count += 1
                    modification_log.append(result['modification_detail'])

                all_components.append(modified_component)
            else:
                # Include unmodified component for this timestep
                unmodified_component = create_unmodified_component_with_timestep(
                    component, namespace, timestep
                )
                all_components.append(unmodified_component)

        scenarios.append({
            'scenario_name': scenario_name,
            'timestep': timestep,
            'components': all_components,
            'component_links': baseline_data.get('component_links', []),
            'assumption': assumption,
            'assumption_id': assumption_id,
            'type': 'series_member',
            'series_index': i,
            'modified_count': modified_count,
            'modification_log': modification_log,
            'namespace': namespace,
            'based_on': baseline_data.get('scenario_uri'),
            'service': baseline_data.get('service'),
            'workspace': baseline_data.get('workspace')
        })

    return scenarios


def apply_modification_to_component(original_component, modified_component, assumption):
    """Apply modification to a single component"""
    target_attribute = assumption['target_attribute']

    # Find target attribute
    target_attr_name, attr_info = find_target_attribute(
        original_component, target_attribute
    )

    if not target_attr_name:
        # Copy all attributes unchanged
        copy_all_attributes_unchanged(original_component, modified_component)
        return {'success': False}

    # Apply modification
    try:
        old_value = float(attr_info['value'])
        modifier = assumption['modifier']
        modifier_value = float(assumption['modifier_value'])

        if modifier == '*':
            new_value = old_value * modifier_value
        elif modifier == '+':
            new_value = old_value + modifier_value
        elif modifier == '-':
            new_value = old_value - modifier_value
        elif modifier == 'set':
            new_value = modifier_value
        else:
            new_value = modifier_value

        # Create modified attribute as a thin override: a fresh URI carrying the
        # new value that supersedes the replica attribute (attr_info['uri']).
        modified_component['attributes'][target_attr_name] = {
            'uri': f"{original_component['uri']}/{target_attr_name}_{modified_component['modification_id']}",
            'original_uri': attr_info.get('uri'),
            'is_modified': True,
            'attr_class': target_attr_name,
            'type': attr_info.get('type', 'PhysicalAttribute'),
            'value': str(new_value),
            'unit': attr_info.get('unit', ''),
            'attribute_type': attr_info.get('attribute_type', 'PhysicalAttribute'),
            'category': attr_info.get('category', 'physical'),
            'currency': attr_info.get('currency')
        }

        # Copy other attributes
        copy_other_attributes_unchanged(
            original_component, modified_component, target_attr_name
        )

        return {
            'success': True,
            'modification_detail': {
                'component': original_component['label'],
                'attribute': target_attr_name,
                'old_value': old_value,
                'new_value': new_value,
                'modification_type': f"{modifier} {modifier_value}"
            }
        }

    except (ValueError, TypeError) as e:
        copy_all_attributes_unchanged(original_component, modified_component)
        return {'success': False}


def apply_series_modification(original_component, modified_component, assumption, series_index, modifier_values):
    """Apply cumulative series modification"""
    target_attribute = assumption['target_attribute']

    target_attr_name, attr_info = find_target_attribute(
        original_component, target_attribute
    )

    if not target_attr_name:
        copy_all_attributes_unchanged(original_component, modified_component)
        return {'success': False}

    try:
        old_value = float(attr_info['value'])
        modifier = assumption['modifier']

        # Apply cumulative modifications
        new_value = old_value
        for j in range(series_index + 1):
            if j < len(modifier_values):
                modifier_value = float(modifier_values[j])
                if modifier == '*':
                    new_value = new_value * modifier_value
                elif modifier == '+':
                    new_value = new_value + modifier_value
                elif modifier == '-':
                    new_value = new_value - modifier_value

        # Create modified attribute as a thin override (see apply_modification_to_component).
        modified_component['attributes'][target_attr_name] = {
            'uri': f"{original_component['uri']}/{target_attr_name}_{modified_component['modification_id']}",
            'original_uri': attr_info.get('uri'),
            'is_modified': True,
            'attr_class': target_attr_name,
            'type': attr_info.get('type', 'PhysicalAttribute'),
            'value': str(new_value),
            'unit': attr_info.get('unit', ''),
            'attribute_type': attr_info.get('attribute_type', 'PhysicalAttribute'),
            'category': attr_info.get('category', 'physical'),
            'currency': attr_info.get('currency')
        }

        # Copy other attributes
        copy_other_attributes_unchanged(
            original_component, modified_component, target_attr_name
        )

        return {
            'success': True,
            'modification_detail': {
                'component': original_component['label'],
                'attribute': target_attr_name,
                'old_value': old_value,
                'new_value': new_value,
                'series_index': series_index
            }
        }

    except (ValueError, TypeError):
        copy_all_attributes_unchanged(original_component, modified_component)
        return {'success': False}


def find_target_attribute(component, target_attribute):
    """Find target attribute with flexible matching"""
    import re

    attributes = component.get('attributes', {})

    for attr_name, attr_info in attributes.items():
        # Exact match
        if attr_name == target_attribute:
            return attr_name, attr_info

        # Case insensitive
        if attr_name.lower() == target_attribute.lower():
            return attr_name, attr_info

        # Remove underscores
        attr_clean = re.sub(r'[_\s]+', '', attr_name.lower())
        target_clean = re.sub(r'[_\s]+', '', target_attribute.lower())

        if attr_clean == target_clean:
            return attr_name, attr_info

    return None, None


def copy_all_attributes_unchanged(original_component, modified_component):
    """Record all attributes as unchanged (they inherit from the replica)."""
    for attr_name, attr_info in original_component.get('attributes', {}).items():
        modified_component['attributes'][attr_name] = {
            'uri': attr_info.get('uri'),
            'original_uri': attr_info.get('uri'),
            'is_modified': False,
            'type': attr_info.get('type', 'PhysicalAttribute'),
            'value': attr_info.get('value'),
            'unit': attr_info.get('unit', ''),
            'attribute_type': attr_info.get('attribute_type', 'PhysicalAttribute'),
            'category': attr_info.get('category', 'unknown')
        }


def copy_other_attributes_unchanged(original_component, modified_component, modified_attr_name):
    """Record all attributes except the modified one as unchanged."""
    for attr_name, attr_info in original_component.get('attributes', {}).items():
        if attr_name != modified_attr_name:
            modified_component['attributes'][attr_name] = {
                'uri': attr_info.get('uri'),
                'original_uri': attr_info.get('uri'),
                'is_modified': False,
                'type': attr_info.get('type', 'PhysicalAttribute'),
                'value': attr_info.get('value'),
                'unit': attr_info.get('unit', ''),
                'attribute_type': attr_info.get('attribute_type', 'PhysicalAttribute'),
                'category': attr_info.get('category', 'unknown')
            }


def create_unmodified_component(component, namespace):
    """Create unmodified component with updated namespace"""
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

    copy_all_attributes_unchanged(component, unmodified_component)

    return unmodified_component


def create_unmodified_component_with_timestep(component, namespace, timestep):
    """Create unmodified component for series with timestep"""
    original_uri_parts = component['uri'].split('/')
    component_identifier = '/'.join(original_uri_parts[-2:])

    unmodified_component = {
        'uri': f"{namespace}/{component_identifier}_{timestep}",
        'type': component['type'],
        'label': f"{component['label']} ({timestep})",
        'attributes': {},
        'nested_properties': component.get('nested_properties', {}).copy(),
        'source': 'unmodified',
        'derived_from': component['uri'],
        'timestep': timestep
    }

    copy_all_attributes_unchanged(component, unmodified_component)

    return unmodified_component

