# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/assumptions/assumption_types.py
"""
Predefined assumption types with enhanced attribute category support
Simplified and streamlined for integration
"""


def create_predefined_assumptions():
    """Create predefined assumption templates"""
    return [
        # PHYSICAL ATTRIBUTES
        {
            'id': 'increase_wind_power_50pc',
            'name': 'Increase Wind Turbine Power by 50%',
            'description': 'Increases rated power of all wind turbines by 50%',
            'target_component': 'WindTurbine',
            'target_attribute': 'RatedPower',
            'attribute_category': 'physical',
            'modifier': '*',
            'modifier_value': '1.5',
            'population_influenced': '1.0',
            'type': 'single',
            'expected_unit': 'MW'
        },
        {
            'id': 'double_hub_height',
            'name': 'Double Hub Height',
            'description': 'Doubles the hub height of wind turbines',
            'target_component': 'WindTurbine',
            'target_attribute': 'HubHeight',
            'attribute_category': 'physical',
            'modifier': '*',
            'modifier_value': '2.0',
            'population_influenced': '1.0',
            'type': 'single',
            'expected_unit': 'm'
        },

        # COST ATTRIBUTES
        {
            'id': 'reduce_wind_capex_30pc',
            'name': 'Reduce Wind Turbine CAPEX by 30%',
            'description': 'Reduces capital expenditure for wind turbines',
            'target_component': 'WindTurbine',
            'target_attribute': 'CAPEX',
            'attribute_category': 'cost',
            'modifier': '*',
            'modifier_value': '0.7',
            'population_influenced': '1.0',
            'type': 'single',
            'expected_unit': 'CHF',
            'expected_currency': 'CHF'
        },

        # SERIES ASSUMPTIONS
        {
            'id': 'wind_power_growth_series',
            'name': 'Wind Power Growth Series',
            'description': 'Gradual wind power capacity increase over time',
            'target_component': 'WindTurbine',
            'target_attribute': 'RatedPower',
            'attribute_category': 'physical',
            'modifier': '*',
            'modifier_value_series': '[1.05, 1.05, 1.05]',
            'population_influenced': '[1.0, 1.0, 1.0]',
            'assumption_timesteps': '[2030, 2040, 2050]',
            'type': 'series',
            'expected_unit': 'MW'
        },
        {
            'id': 'cost_reduction_learning_curve',
            'name': 'Technology Cost Learning Curve',
            'description': 'Progressive cost reductions due to learning effects',
            'target_component': 'WindTurbine',
            'target_attribute': 'CAPEX',
            'attribute_category': 'cost',
            'modifier': '*',
            'modifier_value_series': '[0.95, 0.90, 0.85]',
            'population_influenced': '[1.0, 1.0, 1.0]',
            'assumption_timesteps': '[2030, 2035, 2040]',
            'type': 'series',
            'expected_unit': 'CHF',
            'expected_currency': 'CHF'
        },
    ]


def validate_assumption_compatibility(assumption, baseline_components):
    """Check if assumption is compatible with baseline components"""
    target_component_type = assumption['target_component']
    target_attribute = assumption['target_attribute']

    # Find matching components
    matching_components = [
        comp for comp in baseline_components
        if comp['type'] == target_component_type
    ]

    if not matching_components:
        return False, f"No {target_component_type} components found in baseline"

    # Check if components have the target attribute
    components_with_attribute = []

    for comp in matching_components:
        attributes = comp.get('attributes', {})

        # Flexible attribute matching
        for attr_name in attributes.keys():
            if is_attribute_match(attr_name, target_attribute):
                components_with_attribute.append(comp)
                break

    if not components_with_attribute:
        return False, f"No {target_component_type} components have {target_attribute} attribute"

    return True, f"Compatible with {len(components_with_attribute)} components"


def is_attribute_match(attr_name, target_attribute):
    """Flexible attribute name matching"""
    import re

    # Exact match
    if attr_name == target_attribute:
        return True

    # Case insensitive
    if attr_name.lower() == target_attribute.lower():
        return True

    # Remove underscores and spaces
    attr_clean = re.sub(r'[_\s]+', '', attr_name.lower())
    target_clean = re.sub(r'[_\s]+', '', target_attribute.lower())

    if attr_clean == target_clean:
        return True

    # Partial match
    if target_clean in attr_clean or attr_clean in target_clean:
        return True

    return False


def get_assumption_impact_preview(assumption, baseline_components):
    """Get preview of assumption impact"""
    target_component_type = assumption['target_component']
    target_attribute = assumption['target_attribute']

    affected_components = []

    for comp in baseline_components:
        if comp['type'] == target_component_type:
            # Find matching attribute
            for attr_name, attr_info in comp.get('attributes', {}).items():
                if is_attribute_match(attr_name, target_attribute):
                    impact = calculate_impact(assumption, attr_info, comp['label'])
                    if impact:
                        affected_components.append(impact)
                    break

    return affected_components


def calculate_impact(assumption, attr_info, component_label):
    """Calculate impact of assumption on attribute"""
    try:
        if not isinstance(attr_info, dict):
            return None

        current_value = attr_info.get('value')
        if current_value is None:
            return None

        # Handle series assumptions
        if assumption.get('type') == 'series':
            import json
            modifier_values = json.loads(assumption['modifier_value_series'])
            modifier_value = float(modifier_values[0]) if modifier_values else 1.0
        else:
            modifier_value = float(assumption['modifier_value'])

        modifier = assumption['modifier']
        old_value = float(current_value)

        # Calculate new value
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

        change_percent = ((new_value - old_value) / old_value * 100) if old_value != 0 else 0

        return {
            'component': component_label,
            'attribute': assumption['target_attribute'],
            'current_value': old_value,
            'new_value': new_value,
            'change_percent': change_percent,
            'unit': attr_info.get('unit', '')
        }

    except (ValueError, TypeError):
        return None


def get_supported_attribute_categories():
    """Get list of supported attribute categories"""
    return ['physical', 'cost', 'geospatial', 'curve', 'categorical', 'dynamic']


def get_supported_component_types():
    """Get list of supported component types"""
    assumptions = create_predefined_assumptions()
    component_types = set(a['target_component'] for a in assumptions)
    return sorted(list(component_types))