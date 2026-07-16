# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/scenario_builder_summary.py
"""
Updated scenario builder summary module that integrates with NextCloud workspace data
Generates TTL with enhanced workspace context and maintains compatibility
UPDATED: Added support for EventAttribute type in TTL generation
UPDATED: Disabled partial components - only complete components are included
FIXED: Enhanced nested attribute resolution for GraphDB export
FIXED: Proper DynamicAttribute and TimeSeries generation
FIXED: Dictionary hashability error in time series resources
"""
import streamlit as st
import json
from typing import Dict, List, Any, Optional
from datetime import datetime


def get_component_label_by_uri(uri):
    """Get component label by URI from NextCloud sources with enhanced TTL support"""
    try:
        from components.scenario_builder.scenario_builder_components import get_mock_components_with_instances

        # First check scenario components for URI fragment
        for component in st.session_state.get('scenario_components', []):
            if component.get('uri') == uri:
                return component.get('uri_fragment', component.get('label', uri.split('/')[-1]))

        # Check all NextCloud sources - UPDATED: Added Building support
        for component_type in ['EnergyCarrier', 'Region', 'ElectricityDemandProfile', 'SolarPotentialProfile', 'WindTurbine', 'GlobalWindAtlasSite', 'PV', 'Building', 'EnergyConsumer', 'EnergyGenerator', 'Location']:
            # Check NextCloud knowledge graph components
            components = get_mock_components_with_instances(component_type)
            for comp in components:
                if comp.get('uri') == uri:
                    return comp.get('label', uri.split('/')[-1])

            # Check NextCloud data products
            try:
                from components.scenario_builder.scenario_builder_components import get_data_product_components_by_type
                dp_components = get_data_product_components_by_type(component_type)
                for comp in dp_components:
                    if comp.get('uri') == uri:
                        return comp.get('label', uri.split('/')[-1])
            except:
                pass

            # Check workspace TTL components and return URI fragment for uniqueness
            try:
                from components.scenario_builder.scenario_builder_components import get_ttl_use_case_components_by_type
                ttl_components = get_ttl_use_case_components_by_type(component_type)
                for comp in ttl_components:
                    if comp.get('uri') == uri:
                        return comp.get('uri_fragment', uri.split('/')[-1])
            except:
                pass
    except ImportError:
        pass

    # Fallback to URI fragment
    return uri.split('/')[-1]


def get_component_type_from_uri(uri):
    """Extract component type from URI with Building support"""
    if 'EnergyCarrier' in uri:
        return 'EnergyCarrier'
    elif 'Region' in uri and 'Profile' not in uri and 'Site' not in uri:
        return 'Region'
    elif 'ElectricityDemandProfile' in uri:
        return 'ElectricityDemandProfile'
    elif 'SolarPotentialProfile' in uri:
        return 'SolarPotentialProfile'
    elif 'HeatingDemandProfile' in uri:
        return 'HeatingDemandProfile'
    elif 'WindTurbine' in uri:
        return 'WindTurbine'
    elif 'GlobalWindAtlasSite' in uri:
        return 'GlobalWindAtlasSite'
    elif 'PV' in uri:
        return 'PV'
    elif 'Building' in uri:
        return 'Building'
    elif 'EnergyConsumer' in uri:
        return 'EnergyConsumer'
    elif 'EnergyGenerator' in uri:
        return 'EnergyGenerator'
    elif 'Location' in uri:
        return 'Location'
    return 'Unknown'


def get_requirement_fulfillment_summary():
    """Get detailed summary of how each requirement has been met with enhanced NextCloud support"""
    if not st.session_state.selected_requirements:
        return []

    requirements = st.session_state.selected_requirements['component_links']
    fulfillment_summary = []

    for req in requirements:
        parts = req.split('.')
        if len(parts) >= 3:
            source_type = parts[1]
            target_type = parts[2]

            # Check if this is an automatic scenario link
            is_automatic = source_type == 'Scenario'

            if is_automatic:
                # Get automatic links for this requirement
                auto_links = [
                    link for link in st.session_state.scenario_links
                    if (link.get('link_type') == 'scenario_automatic' and
                        get_component_type_from_uri(link['target']) == target_type)
                ]

                fulfillment_summary.append({
                    'requirement': req,
                    'source_type': source_type,
                    'target_type': target_type,
                    'type': 'automatic',
                    'status': 'fulfilled' if auto_links else 'unfulfilled',
                    'count': len(auto_links),
                    'details': [
                        {
                            'source': 'Scenario',
                            'target': get_component_label_by_uri(link['target']),
                            'link_type': link['link_type']
                        }
                        for link in auto_links
                    ]
                })
            else:
                # Get manual links for this requirement
                manual_links = [
                    link for link in st.session_state.scenario_links
                    if (get_component_type_from_uri(link['source']) == source_type and
                        get_component_type_from_uri(link['target']) == target_type and
                        link.get('link_type') != 'scenario_automatic')
                ]

                fulfillment_summary.append({
                    'requirement': req,
                    'source_type': source_type,
                    'target_type': target_type,
                    'type': 'manual',
                    'status': 'fulfilled' if manual_links else 'unfulfilled',
                    'count': len(manual_links),
                    'details': [
                        {
                            'source': get_component_label_by_uri(link['source']),
                            'target': get_component_label_by_uri(link['target']),
                            'link_type': link['link_type']
                        }
                        for link in manual_links
                    ]
                })

    return fulfillment_summary


def resolve_enhanced_attribute_value(component, req_attr):
    """
    FIXED: Properly resolve attribute values and include nested properties for TTL generation
    """
    try:
        # Validate inputs
        if not component or not req_attr:
            return None, None, None

        if not isinstance(component, dict):
            return None, None, None

        from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement

        # Handle nested attribute requirements like Power.hasHistoricTimeSeriesReference
        if '.' in req_attr:
            nested_value = resolve_nested_attribute_requirement(component, req_attr)
            if nested_value:
                parts = req_attr.split('.')
                base_attr_name = parts[0]

                # Get the base attribute data and merge with nested properties
                component_type = component.get('type', '')
                possible_base_keys = [
                    base_attr_name,
                    f"{base_attr_name}Attribute",
                    f"{component_type}{base_attr_name}",
                    f"{component_type}{base_attr_name}Attribute"
                ]

                # Start with base attribute data
                attr_data = {}
                component_attributes = component.get('attributes', {})

                for key in possible_base_keys:
                    if key in component_attributes and isinstance(component_attributes[key], dict):
                        attr_data = component_attributes[key].copy()
                        break

                # CRITICAL: Merge nested properties into attribute data
                nested_props = component.get('nested_properties', {})
                for key in possible_base_keys:
                    if key in nested_props and isinstance(nested_props[key], dict):
                        # Safely merge nested properties
                        for nested_key, nested_val in nested_props[key].items():
                            if isinstance(nested_key, str):  # Ensure key is hashable
                                attr_data[nested_key] = nested_val
                        break

                # Ensure this is marked as DynamicAttribute if it has time series properties
                if any('TimeSeries' in str(k) for k in attr_data.keys() if isinstance(k, str)):
                    attr_data['attribute_type'] = 'DynamicAttribute'

                attr_data['value'] = nested_value
                attr_data['unit'] = attr_data.get('unit', 'text')

                return nested_value, attr_data.get('unit', 'text'), attr_data
            else:
                return None, None, None

        # Handle simple attributes - get base attribute and merge nested properties
        component_attributes = component.get('attributes', {})

        if req_attr in component_attributes:
            attr_data = component_attributes[req_attr]
            if isinstance(attr_data, dict):
                attr_data = attr_data.copy()

                # CRITICAL: For any attribute, check if it has nested properties and merge them
                nested_props = component.get('nested_properties', {})
                component_type = component.get('type', '')

                possible_keys = [
                    req_attr,
                    f"{req_attr}Attribute",
                    f"{component_type}{req_attr}",
                    f"{component_type}{req_attr}Attribute"
                ]

                for key in possible_keys:
                    if key in nested_props and isinstance(nested_props[key], dict):
                        # Safely merge nested properties
                        for nested_key, nested_val in nested_props[key].items():
                            if isinstance(nested_key, str):  # Ensure key is hashable
                                attr_data[nested_key] = nested_val
                        break

                # Ensure this is marked as DynamicAttribute if it has time series properties
                if any('TimeSeries' in str(k) for k in attr_data.keys() if isinstance(k, str)):
                    attr_data['attribute_type'] = 'DynamicAttribute'

                # Return appropriate value based on attribute type
                if attr_data.get('attribute_type') == 'CategoricalAttribute':
                    category_value = attr_data.get('category_value', attr_data.get('value'))
                    return category_value, attr_data.get('unit', 'category'), attr_data
                elif attr_data.get('attribute_type') == 'EventAttribute':
                    temporal_value = attr_data.get('temporal_value', attr_data.get('value'))
                    return temporal_value, attr_data.get('unit', 'temporal'), attr_data
                else:
                    return attr_data.get('value'), attr_data.get('unit'), attr_data

        # ENHANCED: Try comprehensive case variations and patterns
        component_type = component.get('type', '')

        # Generate all possible variations of the attribute name
        attr_variations = [
            req_attr,
            req_attr.lower(),
            req_attr.replace('_', ''),
            req_attr.replace('_', ' ').title().replace(' ', ''),
            req_attr.replace('_', '').lower(),
            f"{component_type}{req_attr}",
            f"{component_type}{req_attr}Attribute",
            f"{req_attr}Attribute",
            f"{component_type.lower()}{req_attr.lower()}",
            f"{component_type.lower()}{req_attr.lower()}attribute"
        ]

        # Remove duplicates while preserving order
        seen = set()
        attr_variations = [x for x in attr_variations if not (x in seen or seen.add(x))]

        # Try each variation
        for variation in attr_variations:
            if variation in component_attributes:
                attr_data = component_attributes[variation]
                if isinstance(attr_data, dict):
                    attr_data = attr_data.copy()

                    # CRITICAL: For any attribute, check if it has nested properties and merge them
                    nested_props = component.get('nested_properties', {})

                    possible_keys = [
                        variation,
                        f"{variation}Attribute",
                        f"{component_type}{variation}",
                        f"{component_type}{variation}Attribute"
                    ]

                    for key in possible_keys:
                        if key in nested_props and isinstance(nested_props[key], dict):
                            # Safely merge nested properties
                            for nested_key, nested_val in nested_props[key].items():
                                if isinstance(nested_key, str):  # Ensure key is hashable
                                    attr_data[nested_key] = nested_val
                            break

                    # Ensure this is marked as DynamicAttribute if it has time series properties
                    if any('TimeSeries' in str(k) for k in attr_data.keys() if isinstance(k, str)):
                        attr_data['attribute_type'] = 'DynamicAttribute'

                    # Return appropriate value based on attribute type
                    if attr_data.get('attribute_type') == 'CategoricalAttribute':
                        category_value = attr_data.get('category_value', attr_data.get('value'))
                        return category_value, attr_data.get('unit', 'category'), attr_data
                    elif attr_data.get('attribute_type') == 'EventAttribute':
                        temporal_value = attr_data.get('temporal_value', attr_data.get('value'))
                        return temporal_value, attr_data.get('unit', 'temporal'), attr_data
                    else:
                        return attr_data.get('value'), attr_data.get('unit'), attr_data
                else:
                    # Simple value
                    return attr_data, 'dimensionless', {'value': attr_data, 'unit': 'dimensionless'}

    except ImportError:
        # Fallback to basic resolution if enhanced components not available
        component_attributes = component.get('attributes', {})

        # Handle nested attribute requirements
        if '.' in req_attr:
            # Try to resolve manually for nested properties using the fallback method
            parts = req_attr.split('.')
            component_type = component.get('type', '')

            # Remove component type if it matches
            if len(parts) > 2 and parts[0] == component_type:
                parts = parts[1:]

            if len(parts) >= 2:
                attr_name = parts[0]
                nested_prop = '.'.join(parts[1:])

                # Check nested_properties with comprehensive key matching
                nested_props = component.get('nested_properties', {})

                # Generate all possible keys for nested properties
                possible_keys = [
                    attr_name,
                    f"{attr_name}Attribute",
                    f"{component_type}{attr_name}",
                    f"{component_type}{attr_name}Attribute",
                    attr_name.lower(),
                    f"{attr_name.lower()}attribute",
                    f"{component_type.lower()}{attr_name.lower()}",
                    f"{component_type.lower()}{attr_name.lower()}attribute"
                ]

                # Remove duplicates while preserving order
                seen = set()
                possible_keys = [x for x in possible_keys if not (x in seen or seen.add(x))]

                for key in possible_keys:
                    if key in nested_props and isinstance(nested_props[key], dict):
                        nested_data = nested_props[key]

                        # Try exact match for nested property
                        if nested_prop in nested_data:
                            value = nested_data[nested_prop]

                            # Create enhanced attribute data for DynamicAttribute
                            enhanced_attr_data = {
                                'value': value,
                                'unit': 'text',
                                'attribute_type': 'DynamicAttribute'
                            }

                            # Add all nested properties for proper TTL generation
                            for nested_key, nested_val in nested_data.items():
                                if isinstance(nested_key, str):  # Ensure key is hashable
                                    enhanced_attr_data[nested_key] = nested_val

                            return value, 'text', enhanced_attr_data

                        # Try variations of nested property
                        nested_variations = [
                            nested_prop,
                            nested_prop.lower(),
                            nested_prop.replace('has', ''),
                            nested_prop.replace('has', '').lower(),
                            nested_prop.replace('Reference', 'Ref'),
                            nested_prop.replace('TimeSeries', 'TS')
                        ]

                        for nested_var in nested_variations:
                            if nested_var in nested_data:
                                value = nested_data[nested_var]

                                # Create enhanced attribute data for DynamicAttribute
                                enhanced_attr_data = {
                                    'value': value,
                                    'unit': 'text',
                                    'attribute_type': 'DynamicAttribute'
                                }

                                # Add all nested properties for proper TTL generation
                                for nested_key, nested_val in nested_data.items():
                                    if isinstance(nested_key, str):  # Ensure key is hashable
                                        enhanced_attr_data[nested_key] = nested_val

                                return value, 'text', enhanced_attr_data

            return None, None, None

        # Simple attribute lookup for fallback
        if req_attr in component_attributes:
            attr_data = component_attributes[req_attr]
            if isinstance(attr_data, dict):
                # For categorical attributes, ensure we return the string value
                if attr_data.get('attribute_type') == 'CategoricalAttribute' or attr_data.get('data_type') == 'categorical':
                    category_value = attr_data.get('category_value', attr_data.get('value'))
                    return category_value, attr_data.get('unit', 'category'), attr_data
                # For EventAttribute, return the temporal value
                elif attr_data.get('attribute_type') == 'EventAttribute' or attr_data.get('data_type') == 'temporal':
                    temporal_value = attr_data.get('temporal_value', attr_data.get('value'))
                    return temporal_value, attr_data.get('unit', 'temporal'), attr_data
                else:
                    return attr_data.get('value'), attr_data.get('unit'), attr_data

    except Exception as e:
        # Log the error but don't crash
        st.error(f"Error resolving attribute {req_attr}: {str(e)}")
        return None, None, None

    return None, None, None


def map_unit_to_uri(unit_str):
    """Map unit strings to QUDT URIs with enhanced unit support including temporal"""
    unit_mapping = {
        'MW': '<http://qudt.org/vocab/unit/MegaW>',
        'kW': '<http://qudt.org/vocab/unit/KiloW>',
        'kWh': '<http://qudt.org/vocab/unit/KiloW-HR>',
        'm': '<http://qudt.org/vocab/unit/M>',
        'm/s': '<http://qudt.org/vocab/unit/M-PER-SEC>',
        'W/m²': '<http://qudt.org/vocab/unit/W-PER-M2>',
        '%': '<http://qudt.org/vocab/unit/PERCENT>',
        'CHF/kWh': '<http://qudt.org/vocab/unit/KiloW-HR>',
        'EUR/kWh': '<http://qudt.org/vocab/unit/KiloW-HR>',
        'EUR/MW': '<http://qudt.org/vocab/unit/MegaW>',
        'kg CO2/kWh': '<http://qudt.org/vocab/unit/KiloGM-PER-KiloW-HR>',
        'MWh/year': '<http://qudt.org/vocab/unit/MegaW-HR-PER-YR>',
        'km²': '<http://qudt.org/vocab/unit/KiloM2>',
        'km': '<http://qudt.org/vocab/unit/KiloM>',
        '°': '<http://qudt.org/vocab/unit/DEG>',
        '°C': '<http://qudt.org/vocab/unit/DEG_C>',
        'Hz': '<http://qudt.org/vocab/unit/HZ>',
        'bar': '<http://qudt.org/vocab/unit/BAR>',
        'kg': '<http://qudt.org/vocab/unit/KiloGM>',
        'kg/h': '<http://qudt.org/vocab/unit/KiloGM-PER-HR>',
        'kg/day': '<http://qudt.org/vocab/unit/KiloGM-PER-DAY>',
        'uri': '<http://qudt.org/vocab/unit/UNITLESS>',
        'text': '<http://qudt.org/vocab/unit/UNITLESS>',
        'category': '<http://qudt.org/vocab/unit/UNITLESS>',
        'temporal': '<http://qudt.org/vocab/unit/UNITLESS>',
        'dimensionless': '<http://qudt.org/vocab/unit/UNITLESS>'
    }
    return unit_mapping.get(unit_str, f'<http://qudt.org/vocab/unit/{unit_str.replace("/", "-PER-").replace("²", "2").replace(" ", "-")}>')


def generate_enhanced_attribute_declaration(ttl_lines, attr_uri, attr_name_clean, attr_data, attr_value, attr_unit, scenario_uri, component_source):
    """Generate enhanced attribute declaration with NextCloud source tracking including EventAttribute support"""
    if not attr_data or not isinstance(attr_data, dict):
        # Fallback to basic declaration
        generate_basic_attribute_declaration(ttl_lines, attr_uri, attr_name_clean, attr_value, attr_unit, scenario_uri, component_source)
        return

    attribute_type = attr_data.get('attribute_type', 'PhysicalAttribute')

    # FIXED: Handle DynamicAttribute with time series references properly
    if attribute_type == 'DynamicAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:DynamicAttribute ;"
        ])

        # Add time series URI if available
        if 'hasHistoricTimeSeries' in attr_data:
            ts_uri = attr_data['hasHistoricTimeSeries']
            ttl_lines.append(f"    dici_onto:hasHistoricTimeSeries <{ts_uri}> ;")
        elif 'hasLiveTimeSeries' in attr_data:
            ts_uri = attr_data['hasLiveTimeSeries']
            ttl_lines.append(f"    dici_onto:hasLiveTimeSeries <{ts_uri}> ;")
        elif 'hasFutureTimeSeries' in attr_data:
            ts_uri = attr_data['hasFutureTimeSeries']
            ttl_lines.append(f"    dici_onto:hasFutureTimeSeries <{ts_uri}> ;")

        # Add time series reference if available
        if 'hasHistoricTimeSeriesReference' in attr_data:
            ts_ref = attr_data['hasHistoricTimeSeriesReference']
            ttl_lines.append(f"    dici_onto:hasHistoricTimeSeriesReference \"{ts_ref}\"^^xsd:string ;")
        elif 'hasLiveTimeSeriesReference' in attr_data:
            ts_ref = attr_data['hasLiveTimeSeriesReference']
            ttl_lines.append(f"    dici_onto:hasLiveTimeSeriesReference \"{ts_ref}\"^^xsd:string ;")
        elif 'hasFutureTimeSeriesReference' in attr_data:
            ts_ref = attr_data['hasFutureTimeSeriesReference']
            ttl_lines.append(f"    dici_onto:hasFutureTimeSeriesReference \"{ts_ref}\"^^xsd:string ;")

    elif attribute_type == 'SimpleCostAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:SimpleCostAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        # Add currency for cost attributes
        currency = attr_data.get('currency', 'CHF')
        ttl_lines.append(f'    dici_onto:currency cur:{currency} ;')

    elif attribute_type == 'UnitBasedCostAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:UnitBasedCostAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        if attr_unit and attr_unit != 'file':
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

        # Add currency for cost attributes
        currency = attr_data.get('currency', 'CHF')
        ttl_lines.append(f'    dici_onto:currency cur:{currency} ;')

    elif attribute_type == 'CategoricalAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:CategoricalAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        # For categorical attributes, add the category type as a second type
        category_value = attr_data.get('category_value', attr_value)
        if category_value and isinstance(category_value, str):
            # Clean the category value to make it a valid URI part
            clean_category = category_value.replace(' ', '').replace('-', '').replace('_', '')
            ttl_lines.append(f'    a dici_onto:{clean_category} ;')

    elif attribute_type == 'GeospatialAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:GeospatialAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        if attr_unit and attr_unit != 'file':
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    # NEW: Handle EventAttribute
    elif attribute_type == 'EventAttribute':
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:EventAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        # Add temporal value with appropriate XSD datatype
        temporal_value = attr_data.get('temporal_value', attr_value)
        temporal_precision = attr_data.get('temporal_precision', 'Unknown')

        # Determine XSD datatype based on temporal precision
        xsd_datatype = get_xsd_datatype_for_temporal_precision(temporal_precision, temporal_value)
        ttl_lines.append(f'    dici_onto:hasTemporalValue "{temporal_value}"^^{xsd_datatype} ;')

        # Add temporal precision if available
        if temporal_precision != 'Unknown':
            ttl_lines.append(f'    dici_onto:hasTemporalPrecision dici_onto:{temporal_precision} ;')

    else:  # PhysicalAttribute or fallback
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:PhysicalAttribute ;",
            f"    dici_onto:sourceType \"{component_source}\" ;"
        ])

        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        if attr_unit and attr_unit != 'file':
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    # Close attribute declaration with enhanced metadata
    ttl_lines.extend([
        f'    dici_onto:usedInScenario <{scenario_uri}> .',
        ""
    ])


def get_xsd_datatype_for_temporal_precision(temporal_precision, temporal_value):
    """Determine appropriate XSD datatype based on temporal precision and value format"""
    # Map temporal precision to XSD datatypes
    precision_mapping = {
        'Year': 'xsd:gYear',
        'YearMonth': 'xsd:gYearMonth',
        'Date': 'xsd:date',
        'DateTime': 'xsd:dateTime',
        'Time': 'xsd:time'
    }

    # Return mapped datatype or fallback based on value format
    if temporal_precision in precision_mapping:
        return precision_mapping[temporal_precision]

    # Fallback: try to infer from value format
    if isinstance(temporal_value, str):
        temporal_str = str(temporal_value).strip()

        # Check for year only (4 digits)
        if len(temporal_str) == 4 and temporal_str.isdigit():
            return 'xsd:gYear'
        # Check for year-month format (YYYY-MM)
        elif len(temporal_str) == 7 and temporal_str.count('-') == 1:
            return 'xsd:gYearMonth'
        # Check for date format (YYYY-MM-DD)
        elif len(temporal_str) == 10 and temporal_str.count('-') == 2:
            return 'xsd:date'
        # Check for datetime format (contains T or space and time)
        elif 'T' in temporal_str or (':' in temporal_str and len(temporal_str) > 10):
            return 'xsd:dateTime'

    # Final fallback
    return 'xsd:string'


def generate_basic_attribute_declaration(ttl_lines, attr_uri, attr_name_clean, attr_value, attr_unit, scenario_uri, component_source):
    """Generate basic attribute declaration as fallback with source tracking"""
    ttl_lines.extend([
        f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
        f"    dici_onto:sourceType \"{component_source}\" ;"
    ])

    # Handle different value types
    if isinstance(attr_value, (int, float)):
        ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
    else:
        ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

    if attr_unit and attr_unit != 'file':
        unit_uri = map_unit_to_uri(attr_unit)
        ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    ttl_lines.extend([
        f'    dici_onto:usedInScenario <{scenario_uri}> .',
        ""
    ])


def generate_time_series_resources(ttl_lines, components, scenario_uri):
    """
    FIXED: Generate TimeSeries resource declarations without dictionary hashing error
    """
    # Use a dictionary to track time series resources by URI to avoid duplicates
    time_series_resources = {}

    for component in components:
        nested_props = component.get('nested_properties', {})

        for attr_name, props in nested_props.items():
            if isinstance(props, dict):
                # Check for time series URIs
                for prop_name, prop_value in props.items():
                    if ('TimeSeries' in prop_name and
                            'Reference' not in prop_name and
                            prop_value and
                            str(prop_value).startswith('http')):

                        # Store time series resource info using URI as key
                        if prop_value not in time_series_resources:
                            time_series_resources[prop_value] = {
                                'uri': prop_value,
                                'properties': {}
                            }

                        # Merge properties for this time series resource
                        time_series_resources[prop_value]['properties'].update(props)

    # Generate TimeSeries resources
    if time_series_resources:
        ttl_lines.extend([
            "# Time Series Resources",
            ""
        ])

        for ts_info in time_series_resources.values():
            ts_uri = ts_info['uri']
            props = ts_info['properties']

            ttl_lines.extend([
                f"<{ts_uri}> a dici_onto:TimeSeries ;"
            ])

            # Add storedAt and hasFileName if reference is available
            reference = None
            unit = None

            for prop_name, prop_value in props.items():
                if 'Reference' in prop_name and prop_value:
                    reference = prop_value
                elif (prop_name.endswith('_unit') or prop_name == 'unit') and prop_value:
                    unit = prop_value

            if reference:
                ttl_lines.extend([
                    f'    dici_onto:storedAt "{reference}"^^xsd:string ;',
                    f'    dici_onto:hasFileName "{reference}"^^xsd:string ;'
                ])

            # Add unit if available
            if unit:
                unit_uri = map_unit_to_uri(unit)
                ttl_lines.append(f'    qudt:unit {unit_uri} ;')

            ttl_lines.extend([
                f'    dici_onto:usedInScenario <{scenario_uri}> .',
                ""
            ])


# Complete fix for scenario_builder_summary.py
# Replace the entire generate_full_ttl() function and add the new helper function

def generate_full_ttl():
    """Generate complete TTL with enhanced NextCloud workspace context and FIXED nested attribute handling"""
    scenario_name = st.session_state.scenario_name

    # Always filter to complete components only
    components = get_filtered_components_for_ttl()
    links = get_filtered_links_for_ttl(components)

    required_attributes = st.session_state.get('required_attributes', {})

    # Create safe scenario URI with enhanced workspace context
    current_workspace = st.session_state.get('current_workspace')
    workspace_id = current_workspace['id'] if current_workspace else 'default_workspace'
    workspace_name = current_workspace['name'] if current_workspace else 'Default Workspace'

    safe_scenario_name = scenario_name.replace(" ", "_").replace("/", "_")
    scenario_uri = f'https://digicities.info/proj/{workspace_id}/{safe_scenario_name}'

    ttl_lines = [
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix cur: <http://qudt.org/vocab/currency/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        f"# Scenario declaration for workspace: {workspace_name}",
        f"# Generated from NextCloud workspace: {workspace_id}",
        f'<{scenario_uri}> a dici_onto:Scenario ;',
        f'    rdfs:label "{scenario_name}" ;',
        f'    dcterms:description "Scenario built in workspace {workspace_name}" ;',
    ]
    # Record which service template this scenario was built to satisfy, so it can
    # be matched to that service later (e.g. the API submission convert tab only
    # offers scenarios built for the chosen service).
    service_name = (st.session_state.get('selected_requirements') or {}).get('service_name')
    if service_name:
        ttl_lines.append(f'    dici_onto:builtForService "{service_name}" ;')
    ttl_lines.append(f'    dici_onto:createdInWorkspace "{workspace_id}" .')
    ttl_lines.append("")

    # Get object property specificity preference
    if 'ttl_specificity' not in st.session_state:
        st.session_state.ttl_specificity = 'High'

    specificity = st.session_state.ttl_specificity

    # Add component instance declarations with FIXED nested attribute handling
    if components:
        ttl_lines.extend([
            "# Component instance declarations with NextCloud source tracking",
            ""
        ])

        for component in components:
            component_uri = component['uri']
            component_type = component['type']
            component_source = component.get('source', 'unknown')
            workspace_id_comp = component.get('workspace_id', workspace_id)

            # Start component declaration with enhanced metadata
            ttl_lines.append(f"<{component_uri}> a dici_onto:{component_type} ;")
            ttl_lines.append(f'    rdfs:label "{component["label"]}" ;')

            # Add source tracking metadata
            ttl_lines.append(f'    dici_onto:sourceType "{component_source}" ;')
            if component_source == 'ttl_use_case' and workspace_id_comp:
                ttl_lines.append(f'    dici_onto:sourceWorkspace "{workspace_id_comp}" ;')
            elif component_source == 'data_products' and component.get('source_catalog'):
                ttl_lines.append(f'    dici_onto:sourceCatalog "{component["source_catalog"]}" ;')

            # FIXED: Process required attributes with proper nested handling
            required_attrs = required_attributes.get(component_type, [])

            # Separate base attributes from nested properties
            base_attributes = {}
            nested_properties = {}

            for req_attr in required_attrs:
                if req_attr in ['URI', 'label']:
                    continue

                if '.' in req_attr:
                    # This is a nested property requirement like ElectricityDemandProfile.hasHistoricTimeSeriesReference
                    parts = req_attr.split('.')

                    # Remove component type if it matches the first part
                    if len(parts) > 2 and parts[0] == component_type:
                        parts = parts[1:]

                    if len(parts) >= 2:
                        base_attr_name = parts[0]  # e.g., ElectricityDemandProfile
                        nested_prop_name = '.'.join(parts[1:])  # e.g., hasHistoricTimeSeriesReference

                        # Track that we need this base attribute
                        if base_attr_name not in base_attributes:
                            base_attributes[base_attr_name] = []

                        # Track the nested property for this base attribute
                        if base_attr_name not in nested_properties:
                            nested_properties[base_attr_name] = []
                        nested_properties[base_attr_name].append(nested_prop_name)
                else:
                    # Simple attribute
                    if req_attr not in base_attributes:
                        base_attributes[req_attr] = []

            # Generate component-level property declarations ONLY for base attributes
            for base_attr in base_attributes.keys():
                # Check if we have this base attribute
                attr_value, attr_unit, attr_data = resolve_enhanced_attribute_value(component, base_attr)

                if attr_value is not None:
                    # Create attribute URI and declaration based on specificity level
                    attr_name_clean = base_attr.replace('_', '').replace(' ', '').replace('.', '')
                    attr_uri = f"{component_uri}/{attr_name_clean}"

                    # Generate property based on specificity level - ONLY for base attributes
                    if specificity == 'Low':
                        property_name = "hasAttribute"
                    elif specificity == 'Medium':
                        property_name = f"has{attr_name_clean}Attribute"
                    else:  # High specificity
                        property_name = f"has{component_type}{attr_name_clean}Attribute"

                    ttl_lines.append(f"    dici_onto:{property_name} <{attr_uri}> ;")

            # Close component declaration
            ttl_lines.append(f'    dici_onto:usedInScenario <{scenario_uri}> .')
            ttl_lines.append("")

            # FIXED: Generate attribute declarations with proper nested properties
            for base_attr in base_attributes.keys():
                # Resolve the base attribute
                attr_value, attr_unit, attr_data = resolve_enhanced_attribute_value(component, base_attr)

                if attr_value is not None:
                    attr_name_clean = base_attr.replace('_', '').replace(' ', '').replace('.', '')
                    attr_uri = f"{component_uri}/{attr_name_clean}"

                    # Generate enhanced attribute declaration with nested properties
                    generate_enhanced_attribute_declaration_with_nested_properties(
                        ttl_lines, attr_uri, attr_name_clean, attr_data, attr_value, attr_unit,
                        scenario_uri, component_source, component, base_attr,
                        nested_properties.get(base_attr, [])
                    )

    # Generate TimeSeries resources (unchanged)
    generate_time_series_resources(ttl_lines, components, scenario_uri)

    # Add scenario to component links and manual links (unchanged)
    scenario_links = [link for link in links if link.get('link_type') == 'scenario_automatic']
    if scenario_links:
        ttl_lines.extend([
            f"# Scenario component links (automatic) for workspace: {workspace_name}"
        ])

        link_counter = 1
        for link in scenario_links:
            link_uri = f"{scenario_uri}/ComponentLink_{link_counter}"
            ttl_lines.extend([
                f"<{link_uri}> a dici_onto:ComponentLink ;",
                f"    dici_onto:hasInputEntity <{scenario_uri}> ;",
                f"    dici_onto:linksInputyEntityTo <{link['target']}> ;",
                f"    dici_onto:linkType \"scenario_automatic\" ;",
                f"    dici_onto:usedInScenario <{scenario_uri}> .",
                ""
            ])
            link_counter += 1

    # Add manual component relationships
    manual_links = [link for link in links if link.get('link_type') != 'scenario_automatic']
    if manual_links:
        ttl_lines.extend([
            "# Component relationships (manual)"
        ])

        relationship_counter = 1
        for link in manual_links:
            link_uri = f"{scenario_uri}/RelationshipLink_{relationship_counter}"
            ttl_lines.extend([
                f"<{link_uri}> a dici_onto:ComponentLink ;",
                f"    dici_onto:hasInputEntity <{link['source']}> ;",
                f"    dici_onto:linksInputyEntityTo <{link['target']}> ;",
                f"    dici_onto:linkType \"{link.get('link_type', 'manual')}\" ;",
                f"    dici_onto:usedInScenario <{scenario_uri}> .",
                ""
            ])
            relationship_counter += 1

    return "\n".join(ttl_lines)


def generate_enhanced_attribute_declaration_with_nested_properties(ttl_lines, attr_uri, attr_name_clean, attr_data, attr_value, attr_unit, scenario_uri, component_source, component, base_attr_name, nested_prop_names):
    """
    FIXED: Generate enhanced attribute declaration with proper nested properties handling
    """
    if not attr_data or not isinstance(attr_data, dict):
        # Fallback to basic declaration
        generate_basic_attribute_declaration(ttl_lines, attr_uri, attr_name_clean, attr_value, attr_unit, scenario_uri, component_source)
        return

    attribute_type = attr_data.get('attribute_type', 'PhysicalAttribute')

    # Start attribute declaration
    ttl_lines.append(f"<{attr_uri}> a dici_onto:{attr_name_clean} ;")

    # Add attribute type
    if attribute_type == 'DynamicAttribute':
        ttl_lines.append(f"    a dici_onto:DynamicAttribute ;")
    elif attribute_type == 'SimpleCostAttribute':
        ttl_lines.append(f"    a dici_onto:SimpleCostAttribute ;")
    elif attribute_type == 'UnitBasedCostAttribute':
        ttl_lines.append(f"    a dici_onto:UnitBasedCostAttribute ;")
    elif attribute_type == 'CategoricalAttribute':
        ttl_lines.append(f"    a dici_onto:CategoricalAttribute ;")
        # For categorical attributes, add the category type as a second type
        category_value = attr_data.get('category_value', attr_value)
        if category_value and isinstance(category_value, str):
            clean_category = category_value.replace(' ', '').replace('-', '').replace('_', '')
            ttl_lines.append(f'    a dici_onto:{clean_category} ;')
    elif attribute_type == 'GeospatialAttribute':
        ttl_lines.append(f"    a dici_onto:GeospatialAttribute ;")
    elif attribute_type == 'EventAttribute':
        ttl_lines.append(f"    a dici_onto:EventAttribute ;")
    else:  # PhysicalAttribute or fallback
        ttl_lines.append(f"    a dici_onto:PhysicalAttribute ;")

    # FIXED: Add nested properties by resolving them from the component
    for nested_prop_name in nested_prop_names:
        full_nested_path = f"{base_attr_name}.{nested_prop_name}"

        # Resolve the nested property value using the enhanced resolution
        nested_value, _, _ = resolve_enhanced_attribute_value(component, full_nested_path)

        if nested_value is not None:
            # Determine the property name and value format
            if 'TimeSeriesReference' in nested_prop_name:
                # Time series reference - string value
                ttl_lines.append(f'    dici_onto:{nested_prop_name} "{nested_value}"^^xsd:string ;')
            elif 'TimeSeries' in nested_prop_name and 'Reference' not in nested_prop_name:
                # Time series URI - URI reference
                ttl_lines.append(f'    dici_onto:{nested_prop_name} <{nested_value}> ;')
            elif nested_prop_name in ['cost', 'unit']:
                # Handle cost and unit properties
                if nested_prop_name == 'cost':
                    if isinstance(nested_value, (int, float)):
                        ttl_lines.append(f'    dici_onto:cost "{nested_value}"^^xsd:decimal ;')
                    else:
                        ttl_lines.append(f'    dici_onto:cost "{nested_value}"^^xsd:string ;')
                elif nested_prop_name == 'unit':
                    unit_uri = map_unit_to_uri(str(nested_value))
                    ttl_lines.append(f'    qudt:unit {unit_uri} ;')
            else:
                # Generic property - determine format based on value
                if isinstance(nested_value, (int, float)):
                    ttl_lines.append(f'    dici_onto:{nested_prop_name} "{nested_value}"^^xsd:decimal ;')
                elif str(nested_value).startswith('http'):
                    ttl_lines.append(f'    dici_onto:{nested_prop_name} <{nested_value}> ;')
                else:
                    ttl_lines.append(f'    dici_onto:{nested_prop_name} "{nested_value}"^^xsd:string ;')

    # Handle attribute-specific properties (value, unit, currency, etc.)
    if attribute_type == 'DynamicAttribute':
        # For DynamicAttribute, unit is required
        if attr_unit and attr_unit not in ['file', 'text']:
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    elif attribute_type in ['SimpleCostAttribute', 'UnitBasedCostAttribute']:
        # Add value
        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        # Add unit for UnitBasedCostAttribute
        if attribute_type == 'UnitBasedCostAttribute' and attr_unit and attr_unit != 'file':
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

        # Add currency for cost attributes
        currency = attr_data.get('currency', 'CHF')
        ttl_lines.append(f'    dici_onto:currency cur:{currency} ;')

    elif attribute_type == 'EventAttribute':
        # Add temporal value with appropriate XSD datatype
        temporal_value = attr_data.get('temporal_value', attr_value)
        temporal_precision = attr_data.get('temporal_precision', 'Unknown')

        xsd_datatype = get_xsd_datatype_for_temporal_precision(temporal_precision, temporal_value)
        ttl_lines.append(f'    dici_onto:hasTemporalValue "{temporal_value}"^^{xsd_datatype} ;')

        if temporal_precision != 'Unknown':
            ttl_lines.append(f'    dici_onto:hasTemporalPrecision dici_onto:{temporal_precision} ;')

    elif attribute_type not in ['CategoricalAttribute']:  # Skip value for categorical
        # Add value for other attribute types
        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:string ;')

        # Add unit if available and not a file reference
        if attr_unit and attr_unit not in ['file', 'text', 'category', 'temporal']:
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    # Add source tracking
    ttl_lines.append(f'    dici_onto:sourceType "{component_source}" ;')

    # Close attribute declaration
    ttl_lines.extend([
        f'    dici_onto:usedInScenario <{scenario_uri}> .',
        ""
    ])


def validate_enhanced_component_attributes():
    """Enhanced validation that handles nested property requirements including EventAttribute"""
    missing_attributes = []

    for component in st.session_state.scenario_components:
        comp_type = component['type']
        if comp_type in st.session_state.get('required_attributes', {}):
            required_attrs = st.session_state.required_attributes[comp_type]

            for req_attr in required_attrs:
                try:
                    from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })
                except:
                    # Fallback to simple validation
                    component_attrs = set(component.get('attributes', {}).keys())

                    # Convert attribute names to match common patterns
                    attr_variations = [
                        req_attr,
                        req_attr.lower(),
                        req_attr.replace('_', ''),
                        req_attr.replace('_', ' ').title().replace(' ', ''),
                        req_attr.replace('_', '').lower()
                    ]

                    if not any(attr.lower() in [v.lower() for v in attr_variations] for attr in component_attrs):
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })

    return missing_attributes


def export_debug_component_data():
    """
    Export comprehensive debug data about all components for troubleshooting
    """
    debug_data = {
        'export_timestamp': datetime.now().isoformat(),
        'scenario_name': st.session_state.get('scenario_name', 'Unknown'),
        'workspace_info': st.session_state.get('current_workspace', {}),
        'total_components': len(st.session_state.get('scenario_components', [])),
        'selected_requirements': st.session_state.get('selected_requirements', {}),
        'required_attributes': st.session_state.get('required_attributes', {}),
        'components': []
    }

    # Export each component with full detail
    for i, component in enumerate(st.session_state.get('scenario_components', [])):
        try:
            # Create a deep copy to avoid modifying original
            comp_debug = {
                'index': i,
                'uri': component.get('uri', 'NO_URI'),
                'label': component.get('label', 'NO_LABEL'),
                'type': component.get('type', 'NO_TYPE'),
                'source': component.get('source', 'NO_SOURCE'),
                'workspace_id': component.get('workspace_id', 'NO_WORKSPACE_ID'),
                'source_catalog': component.get('source_catalog', 'NO_SOURCE_CATALOG'),
                'uri_fragment': component.get('uri_fragment', 'NO_URI_FRAGMENT'),
                'base_uri': component.get('base_uri', 'NO_BASE_URI'),
                'attributes': {},
                'nested_properties': {},
                'attribute_keys': [],
                'nested_property_keys': [],
                'attribute_analysis': {},
                'error_info': None
            }

            # Analyze attributes
            attributes = component.get('attributes', {})
            comp_debug['attribute_keys'] = list(attributes.keys())

            for attr_name, attr_data in attributes.items():
                try:
                    if isinstance(attr_data, dict):
                        comp_debug['attributes'][attr_name] = {
                            'value': attr_data.get('value', 'NO_VALUE'),
                            'unit': attr_data.get('unit', 'NO_UNIT'),
                            'attribute_type': attr_data.get('attribute_type', 'NO_ATTR_TYPE'),
                            'category': attr_data.get('category', 'NO_CATEGORY'),
                            'data_type': attr_data.get('data_type', 'NO_DATA_TYPE'),
                            'all_keys': list(attr_data.keys()),
                            'data_structure': str(type(attr_data)),
                            'has_time_series_props': any('TimeSeries' in k for k in attr_data.keys())
                        }
                    else:
                        comp_debug['attributes'][attr_name] = {
                            'raw_value': str(attr_data),
                            'value_type': str(type(attr_data)),
                            'is_dict': False
                        }
                except Exception as attr_error:
                    comp_debug['attributes'][attr_name] = {
                        'error': str(attr_error),
                        'error_type': str(type(attr_error))
                    }

            # Analyze nested_properties
            nested_props = component.get('nested_properties', {})
            comp_debug['nested_property_keys'] = list(nested_props.keys())

            for nested_name, nested_data in nested_props.items():
                try:
                    if isinstance(nested_data, dict):
                        comp_debug['nested_properties'][nested_name] = {
                            'all_keys': list(nested_data.keys()),
                            'data_structure': str(type(nested_data)),
                            'properties': {}
                        }

                        for prop_name, prop_value in nested_data.items():
                            comp_debug['nested_properties'][nested_name]['properties'][prop_name] = {
                                'value': str(prop_value),
                                'value_type': str(type(prop_value)),
                                'is_time_series_related': 'TimeSeries' in prop_name
                            }
                    else:
                        comp_debug['nested_properties'][nested_name] = {
                            'raw_value': str(nested_data),
                            'value_type': str(type(nested_data)),
                            'is_dict': False
                        }
                except Exception as nested_error:
                    comp_debug['nested_properties'][nested_name] = {
                        'error': str(nested_error),
                        'error_type': str(type(nested_error))
                    }

            # Test attribute resolution for required attributes
            comp_type = component.get('type')
            if comp_type in debug_data['required_attributes']:
                required_attrs = debug_data['required_attributes'][comp_type]
                comp_debug['attribute_analysis'] = {}

                for req_attr in required_attrs:
                    try:
                        # Test the enhanced resolution
                        from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement
                        resolved_value = resolve_nested_attribute_requirement(component, req_attr)

                        comp_debug['attribute_analysis'][req_attr] = {
                            'resolved_value': str(resolved_value) if resolved_value is not None else 'NULL',
                            'resolution_success': resolved_value is not None,
                            'is_nested': '.' in req_attr,
                            'resolution_method': 'enhanced'
                        }

                        # Also test the TTL resolution
                        try:
                            attr_value, attr_unit, attr_data = resolve_enhanced_attribute_value(component, req_attr)
                            comp_debug['attribute_analysis'][req_attr].update({
                                'ttl_value': str(attr_value) if attr_value is not None else 'NULL',
                                'ttl_unit': str(attr_unit) if attr_unit is not None else 'NULL',
                                'ttl_data_keys': list(attr_data.keys()) if isinstance(attr_data, dict) else 'NOT_DICT',
                                'ttl_attr_type': attr_data.get('attribute_type') if isinstance(attr_data, dict) else 'UNKNOWN',
                                'ttl_resolution_success': attr_value is not None
                            })
                        except Exception as ttl_error:
                            comp_debug['attribute_analysis'][req_attr]['ttl_error'] = str(ttl_error)

                    except Exception as resolve_error:
                        comp_debug['attribute_analysis'][req_attr] = {
                            'resolution_error': str(resolve_error),
                            'resolution_method': 'failed'
                        }

            debug_data['components'].append(comp_debug)

        except Exception as comp_error:
            # If component processing fails, still include what we can
            error_comp = {
                'index': i,
                'component_error': str(comp_error),
                'error_type': str(type(comp_error)),
                'raw_component_keys': list(component.keys()) if hasattr(component, 'keys') else 'NOT_DICT',
                'component_type': str(type(component))
            }
            debug_data['components'].append(error_comp)

    # Generate the debug report
    debug_json = json.dumps(debug_data, indent=2, ensure_ascii=False)

    # Create downloadable file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scenario_debug_{timestamp}.json"

    st.download_button(
        label="Download Debug Data",
        data=debug_json,
        file_name=filename,
        mime="application/json",
        help="Download comprehensive debug data for troubleshooting TTL generation issues"
    )

    # Also show summary in the UI
    st.write("### Debug Data Summary")
    st.write(f"**Total Components:** {debug_data['total_components']}")
    st.write(f"**Workspace:** {debug_data.get('workspace_info', {}).get('name', 'Unknown')}")
    st.write(f"**Required Attribute Types:** {list(debug_data['required_attributes'].keys())}")

    # Show component overview
    if debug_data['components']:
        st.write("**Component Overview:**")
        for comp in debug_data['components'][:5]:  # Show first 5
            if 'uri' in comp:
                st.write(f"• {comp['type']}: {comp['label']} ({len(comp.get('attribute_keys', []))} attrs, {len(comp.get('nested_property_keys', []))} nested)")
            else:
                st.write(f"• ERROR COMPONENT: {comp.get('component_error', 'Unknown error')}")

        if len(debug_data['components']) > 5:
            st.write(f"... and {len(debug_data['components']) - 5} more components")

    return debug_data


def add_debug_export_to_ttl_tab():
    """
    Add debug export functionality to the TTL tab
    """
    st.write("### Debug Tools")

    col1, col2 = st.columns([1, 3])

    with col1:
        if st.button("Export Debug Data", type="secondary"):
            try:
                export_debug_component_data()
            except Exception as debug_error:
                st.error(f"Debug export failed: {str(debug_error)}")
                st.code(str(debug_error))

    with col2:
        st.caption("Export all component data for debugging TTL generation issues. This creates a comprehensive JSON file with all attributes, nested properties, and resolution test results.")


def tab_summary_ttl():
    """Tab 3: Summary and TTL generation with enhanced NextCloud workspace integration"""
    st.subheader("📊 Scenario Summary & TTL")

    if not st.session_state.scenario_components:
        st.warning("Please add components in Tab 1 first")
        return

    # Show workspace context
    current_workspace = st.session_state.get('current_workspace')
    if current_workspace:
        st.info(f"📁 **Workspace Context:** {current_workspace['name']} (ID: {current_workspace['id']})")

    scenario_name = st.session_state.scenario_name

    # View toggle
    view_mode = st.radio(
        "Select View:",
        ["📊 Requirements Summary", "📄 TTL Output"],
        horizontal=True,
        key="summary_view_toggle"
    )

    if view_mode == "📊 Requirements Summary":
        show_enhanced_requirements_summary()
    else:
        show_enhanced_ttl_output()


def show_enhanced_requirements_summary():
    """Show detailed requirements fulfillment summary with enhanced NextCloud workspace support"""
    st.write("### Enhanced Requirements Fulfillment Analysis")

    # Show workspace context for components
    current_workspace = st.session_state.get('current_workspace')
    if current_workspace:
        st.caption(f"Components loaded from workspace: {current_workspace['name']}")

    # Get fulfillment summary
    fulfillment = get_requirement_fulfillment_summary()

    if not fulfillment:
        st.info("No requirements to analyze")
        return

    # Overall statistics
    total_reqs = len(fulfillment)
    fulfilled_reqs = len([req for req in fulfillment if req['status'] == 'fulfilled'])
    completion_pct = int((fulfilled_reqs / total_reqs * 100)) if total_reqs > 0 else 0

    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Requirements", total_reqs)
    with col2:
        st.metric("Fulfilled", fulfilled_reqs)
    with col3:
        st.metric("Unfulfilled", total_reqs - fulfilled_reqs)
    with col4:
        st.metric("Completion", f"{completion_pct}%")

    # Progress bar
    st.progress(completion_pct / 100)

    # Enhanced detailed breakdown with NextCloud source tracking
    st.write("### Detailed Requirement Analysis")

    for i, req in enumerate(fulfillment):
        status_icon = "✅" if req['status'] == 'fulfilled' else "❌"
        requirement_type = "📄 Automatic" if req['type'] == 'automatic' else "🔗 Manual"

        with st.expander(f"{status_icon} {requirement_type} | {req['requirement']} ({req['count']} links)", expanded=False):
            col1, col2 = st.columns([1, 2])

            with col1:
                st.write("**Requirement Details:**")
                st.write(f"• **Pattern:** `{req['requirement']}`")
                st.write(f"• **Source Type:** {req['source_type']}")
                st.write(f"• **Target Type:** {req['target_type']}")
                st.write(f"• **Type:** {req['type'].title()}")
                st.write(f"• **Status:** {req['status'].title()}")
                st.write(f"• **Links Created:** {req['count']}")

            with col2:
                if req['details']:
                    st.write("**Created Links:**")
                    for detail in req['details']:
                        link_type_badge = "📄" if detail['link_type'] == 'scenario_automatic' else "🔗"
                        st.write(f"{link_type_badge} **{detail['source']}** → **{detail['target']}**")
                        st.caption(f"Link Type: {detail['link_type']}")
                else:
                    st.info("No links created for this requirement yet")

                    # Suggest what to do with workspace context
                    if req['type'] == 'automatic':
                        st.caption(f"💡 Add {req['target_type']} components from workspace TTL or data products in Tab 1")
                    else:
                        st.caption(f"💡 Create links between {req['source_type']} and {req['target_type']} components in Tab 2")

    # Enhanced component summary with NextCloud source breakdown
    show_enhanced_component_summary()


def show_enhanced_component_summary():
    """Show enhanced component summary with NextCloud source analysis including EventAttribute support"""
    st.write("### Enhanced Component Summary with NextCloud Sources")

    # Group components by type and source
    components_by_type = {}
    source_breakdown = {}

    for comp in st.session_state.scenario_components:
        comp_type = comp['type']
        comp_source = comp.get('source', 'unknown')

        if comp_type not in components_by_type:
            components_by_type[comp_type] = []
        components_by_type[comp_type].append(comp)

        if comp_source not in source_breakdown:
            source_breakdown[comp_source] = 0
        source_breakdown[comp_source] += 1

    # Show source breakdown
    st.write("**NextCloud Source Breakdown:**")
    source_labels = {
        'ttl_use_case': '📄 Workspace TTL Files',
        'data_products': '📊 NextCloud Data Products',
        'knowledge_graph': '🏛️ NextCloud Knowledge Graph'
    }

    if source_breakdown:
        cols = st.columns(len(source_breakdown))
        for i, (source, count) in enumerate(source_breakdown.items()):
            with cols[i]:
                label = source_labels.get(source, f'❓ {source}')
                st.metric(label, count)

    # Show components by type with enhanced source info
    for comp_type, components in components_by_type.items():
        with st.expander(f"🔧 {comp_type} ({len(components)} components)", expanded=False):
            for comp in components:
                source_badge = {
                    'ttl_use_case': '📄',
                    'data_products': '📊',
                    'knowledge_graph': '🏛️'
                }.get(comp.get('source', 'unknown'), '❓')

                st.write(f"{source_badge} **{comp['label']}**")
                st.caption(f"URI: `{comp['uri']}`")

                # Show source-specific context
                if comp.get('source') == 'ttl_use_case' and comp.get('workspace_id'):
                    current_workspace = st.session_state.get('current_workspace')
                    workspace_name = current_workspace['name'] if current_workspace else comp['workspace_id']
                    st.caption(f"Source: Workspace TTL ({workspace_name})")
                elif comp.get('source') == 'data_products' and comp.get('source_catalog'):
                    st.caption(f"Source: Data Products ({comp['source_catalog']})")
                elif comp.get('source') == 'knowledge_graph':
                    st.caption(f"Source: NextCloud Knowledge Graph")

                # Show enhanced attribute summary by category
                show_component_attribute_breakdown(comp)


def show_component_attribute_breakdown(component):
    """Show breakdown of component attributes by category with source tracking including EventAttribute support"""
    attributes = component.get('attributes', {})
    if not attributes:
        return

    # Count attributes by category
    category_counts = {}
    has_temporal = False  # NEW: Track temporal/event attributes

    for attr_name, attr_data in attributes.items():
        if isinstance(attr_data, dict) and attr_data.get('category'):
            category = attr_data['category']
            if category != 'system':  # Skip system attributes
                category_counts[category] = category_counts.get(category, 0) + 1

                # NEW: Check for temporal/event attributes
                if (category == 'temporal' or
                        attr_data.get('attribute_type') == 'EventAttribute' or
                        attr_data.get('data_type') == 'temporal'):
                    has_temporal = True

    if category_counts:
        category_labels = {
            'physical': '⚙️',
            'cost': '💰',
            'geospatial': '🌍',
            'dynamic': '📊',
            'curve': '📈',
            'categorical': '🏷️',
            'temporal': '📅'  # NEW: Added temporal category
        }

        breakdown_parts = []
        for category, count in category_counts.items():
            emoji = category_labels.get(category, '📋')
            breakdown_parts.append(f"{emoji}{count}")

        if breakdown_parts:
            # NEW: Add temporal indicator if present
            temporal_indicator = " 📅" if has_temporal else ""
            st.caption(f"  Attributes: {' | '.join(breakdown_parts)}{temporal_indicator}")


def show_enhanced_ttl_output():
    """Show TTL output with enhanced NextCloud workspace context and source tracking including EventAttribute support"""
    st.write("### Generated TTL File with Workspace Context")

    # Show workspace context
    current_workspace = st.session_state.get('current_workspace')
    if current_workspace:
        st.info(f"📁 TTL will include workspace metadata for: **{current_workspace['name']}**")

    # UPDATED: Scenario configuration section (removed partial components option)
    st.write("#### 🎯 Scenario Configuration")

    col1, col2 = st.columns([2, 1])

    with col1:
        # Allow renaming scenario
        new_scenario_name = st.text_input(
            "Scenario Name:",
            value=st.session_state.scenario_name,
            key="scenario_name_summary",
            help="Enter a name for your scenario"
        )

        # Update scenario name if changed
        if new_scenario_name != st.session_state.scenario_name:
            st.session_state.scenario_name = new_scenario_name

    with col2:
        # UPDATED: Information about complete components only (no checkbox)
        st.info("🎯 **Complete Components Only**\n\nOnly components with all required attributes will be included in the TTL.")

    # Object Property Specificity Selection
    st.write("#### ⚙️ Object Property Specificity")

    specificity_col1, specificity_col2 = st.columns([2, 3])

    with specificity_col1:
        specificity = st.selectbox(
            "Choose object property specificity level:",
            options=['Low', 'Medium', 'High'],
            index=2,  # Default to High
            key='ttl_specificity_selector',
            help="Controls how specific the object properties are in the generated TTL"
        )
        st.session_state.ttl_specificity = specificity

    with specificity_col2:
        # Show examples based on selection
        if specificity == 'Low':
            st.info("**Low:** `dici_onto:hasAttribute` (generic property for all attributes)")
        elif specificity == 'Medium':
            st.info("**Medium:** `dici_onto:hasHubHeightAttribute` (attribute-specific property)")
        else:  # High
            st.info("**High:** `dici_onto:hasWindTurbineHubHeightAttribute` (component+attribute specific)")

    # UPDATED: Always filter to complete components only
    filtered_components = get_filtered_components_for_ttl()
    filtered_links = get_filtered_links_for_ttl(filtered_components)

    # UPDATED: Show warning about excluded incomplete components
    total_components = len(st.session_state.scenario_components)
    total_links = len(st.session_state.scenario_links)
    filtered_component_count = len(filtered_components)
    filtered_links_count = len(filtered_links)

    excluded_components = total_components - filtered_component_count
    excluded_links = total_links - filtered_links_count

    if excluded_components > 0:
        st.warning(f"⚠️ **{excluded_components} incomplete component(s) omitted** - Only complete components with all required attributes are included in the TTL for simulation readiness.")
        if excluded_links > 0:
            st.caption(f"🔎 {excluded_links} associated links were also omitted.")

    # Generate TTL content with filtered components and links (now always filtered)
    ttl_content = generate_full_ttl()

    # Enhanced statistics with NextCloud source tracking
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Components", len(filtered_components))
    with col2:
        automatic_links = len([link for link in filtered_links if link.get('link_type') == 'scenario_automatic'])
        st.metric("Auto Links", automatic_links)
    with col3:
        manual_links = len([link for link in filtered_links if link.get('link_type') != 'scenario_automatic'])
        st.metric("Manual Links", manual_links)
    with col4:
        # Count usedInScenario statements
        used_in_scenario_count = ttl_content.count('dici_onto:usedInScenario')
        st.metric("usedInScenario", used_in_scenario_count)
    with col5:
        # Count attribute declarations
        attribute_count = ttl_content.count('dici_onto:has')
        st.metric("Attributes", attribute_count)
    with col6:
        # Count source type tracking
        source_tracking_count = ttl_content.count('dici_onto:sourceType')
        st.metric("Source Tracking", source_tracking_count)

    # Enhanced attribute validation summary with nested property support
    if st.session_state.get('required_attributes'):
        missing_attributes = validate_enhanced_component_attributes_filtered(filtered_components)
        if missing_attributes:
            with st.expander("⚠️ Missing Required Attributes in Complete Components", expanded=True):
                st.warning(f"Found {len(missing_attributes)} missing required attributes in otherwise complete components:")
                for missing in missing_attributes:
                    st.write(f"• **{missing['component']}** ({missing['type']}) missing: `{missing['missing_attribute']}`")
                    # Show if it's a nested property requirement
                    if '.' in missing['missing_attribute']:
                        st.caption(f"  This is a nested property requirement - check workspace TTL or nested_properties")
                    # Show if it might be an EventAttribute
                    elif 'Age' in missing['missing_attribute'] or 'Year' in missing['missing_attribute'] or 'Date' in missing['missing_attribute']:
                        st.caption(f"  This might be an EventAttribute - check for temporal values in workspace TTL")
        else:
            st.success("✅ All required attributes present in complete components!")

    # TTL preview and download with workspace context
    with st.expander("📄 TTL Content Preview", expanded=True):
        # Show workspace and specificity impact
        if current_workspace:
            st.write(f"**Workspace:** {current_workspace['name']} | **Specificity:** {specificity}")

        # Show sample property if components exist
        if filtered_components:
            sample_lines = [line for line in ttl_content.split('\n') if 'dici_onto:has' in line and 'Attribute' in line]
            if sample_lines:
                st.code(sample_lines[0].strip(), language="turtle")
                st.caption("↑ Example of generated object property with current specificity")

        st.code(ttl_content, language="turtle")

        # Action buttons for download and upload
        scenario_name = st.session_state.scenario_name
        workspace_suffix = f"_{current_workspace['id']}" if current_workspace else ""
        filename = f"{scenario_name.replace(' ', '_')}{workspace_suffix}_{specificity.lower()}_specificity.ttl"

        col1, col2, col3 = st.columns(3)

        with col1:
            st.download_button(
                "💾 Download TTL File",
                ttl_content,
                file_name=filename,
                mime="text/turtle",
                key="download_ttl",
                type="primary"
            )

        with col2:
            # Save the scenario TTL into the workspace scenarios/ folder.
            if st.button("☁️ Save to Workspace", key="upload_ttl", type="secondary"):
                upload_scenario_to_workspace(ttl_content, filename)

        with col3:
            # Push the scenario into the <scenarios> named graph (and persist the
            # file so it survives a workspace reopen).
            if st.button("📊 Upload to Graph", key="upload_ttl_graph", type="secondary"):
                upload_scenario_to_graph(ttl_content, filename)

        st.caption(
            "💾 Download saves locally · ☁️ saves the TTL to the workspace `scenarios/` "
            "folder · 📊 loads it into the `<scenarios>` named graph"
        )

    # Add debug export functionality
    add_debug_export_to_ttl_tab()

    # Enhanced TTL Features Summary with NextCloud integration
    st.write("### Enhanced TTL Features with NextCloud Integration")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**✅ Standard Features:**")
        st.write("• Scenario declaration with type and label")
        st.write("• All component instance declarations")
        st.write("• Component links typed as `dici_onto:ComponentLink`")
        st.write("• Automatic scenario-to-component links")
        st.write("• Manual component-to-component relationships")
        st.write("• Enhanced attribute type declarations")
        st.write("• Nested property resolution")
        st.write("• Categorical attribute support")
        st.write("• **EventAttribute support with temporal values**")

    with col2:
        st.write("**🚀 NextCloud Integration Features:**")
        st.write("• **Workspace context tracking** in scenario URI")
        st.write("• **Source type metadata** for all components")
        st.write("• **Workspace ID** tracking for TTL components")
        st.write("• **Catalog references** for data product components")
        st.write("• **Enhanced time series** with source tracking")
        st.write("• **Cross-workspace compatibility**")
        st.write("• **Source-aware attribute declarations**")
        st.write("• Configurable object property specificity")
        st.write("• **Workspace upload to graph/scenarios**")
        st.write("• **🎯 Complete components only** - simulation-ready TTL")

    # Show enhanced service requirements with workspace context
    show_enhanced_service_requirements_summary()


# Function to filter components based on completeness (always enabled now)
def get_filtered_components_for_ttl():
    """Get components filtered to include only complete components with all required attributes"""
    # UPDATED: Always filter out incomplete components - no option to include partial
    filtered_components = []
    required_attributes = st.session_state.get('required_attributes', {})

    for component in st.session_state.scenario_components:
        comp_type = component['type']
        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            # Check if component has all required attributes
            missing_count = 0
            for req_attr in required_attrs:
                try:
                    from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_count += 1
                except:
                    missing_count += 1

            # Only include component if it has all required attributes
            if missing_count == 0:
                filtered_components.append(component)
        else:
            # Include components with no requirements
            filtered_components.append(component)

    return filtered_components


# Function to filter links based on included components
def get_filtered_links_for_ttl(filtered_components):
    """Get links filtered to only include those between included components"""
    # UPDATED: Always filter links - no option for partial components

    # Create set of included component URIs for efficient lookup
    included_component_uris = {comp['uri'] for comp in filtered_components}
    # Also include 'scenario' as a valid source for automatic links
    included_component_uris.add('scenario')

    # Filter links to only include those where both source and target are in included components
    filtered_links = []

    for link in st.session_state.scenario_links:
        source_uri = link.get('source')
        target_uri = link.get('target')

        # Include link only if both source and target are in the filtered component set
        if source_uri in included_component_uris and target_uri in included_component_uris:
            filtered_links.append(link)

    return filtered_links


# Function to validate only filtered components
def validate_enhanced_component_attributes_filtered(filtered_components):
    """Enhanced validation for filtered (complete) components only"""
    missing_attributes = []

    for component in filtered_components:
        comp_type = component['type']
        if comp_type in st.session_state.get('required_attributes', {}):
            required_attrs = st.session_state.required_attributes[comp_type]

            for req_attr in required_attrs:
                try:
                    from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })
                except:
                    # Fallback to simple validation
                    component_attrs = set(component.get('attributes', {}).keys())

                    # Convert attribute names to match common patterns
                    attr_variations = [
                        req_attr,
                        req_attr.lower(),
                        req_attr.replace('_', ''),
                        req_attr.replace('_', ' ').title().replace(' ', ''),
                        req_attr.replace('_', '').lower()
                    ]

                    if not any(attr.lower() in [v.lower() for v in attr_variations] for attr in component_attrs):
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })

    return missing_attributes


# Function to upload scenario to workspace
def upload_scenario_to_workspace(ttl_content: str, filename: str):
    """Save scenario TTL to the active workspace's scenarios/ folder via
    WorkspaceStorage (works for both local and NextCloud-backed workspaces)."""
    try:
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            st.error("No workspace selected")
            return

        # Save through the workspace storage abstraction, which handles both
        # local and NextCloud-backed workspaces (no direct NextCloud client).
        ctx = st.session_state.get("workspace_context")
        if ctx is None:
            st.error("No active workspace storage; cannot save the scenario.")
            return

        try:
            ctx.storage.write_text(f"scenarios/{filename}", ttl_content)
        except Exception as storage_err:
            st.error(f"❌ Failed to save scenario to the workspace: {storage_err}")
            return

        st.success("✅ Scenario saved to workspace!")
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📁 **Path:** `{ctx.id}/scenarios/{filename}`")
        with col2:
            st.info(f"📏 **Size:** {len(ttl_content):,} bytes | ⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}")

    except Exception as upload_error:
        st.error(f"❌ Failed to save scenario: {upload_error}")


def upload_scenario_to_graph(ttl_content: str, filename: str):
    """Load the scenario into the workspace's ``<scenarios>`` named graph.

    Appends to the graph (each scenario is uniquely URI'd) via the
    backend-agnostic client, and also persists the TTL to the workspace
    ``scenarios/`` folder — provisioning rebuilds ``<scenarios>`` from those files
    on workspace reopen, so a graph-only upload would otherwise be lost.
    """
    try:
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            st.error("No workspace selected")
            return

        # Persist the file first so the scenario survives a workspace reopen.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is not None:
            try:
                storage.write_text(f"scenarios/{filename}", ttl_content)
            except Exception as storage_err:
                st.warning(f"Uploaded to the graph but could not save the workspace file "
                           f"(it may not survive a reopen): {storage_err}")

        # Push into the <scenarios> named graph (append; backend-agnostic client).
        from components.graphdb import get_or_refresh_graphdb_client
        from backend.graphdb.graphs import SCENARIOS_GRAPH

        client = get_or_refresh_graphdb_client(current_workspace['id'])
        if not client:
            st.error("Could not connect to the knowledge graph")
            return

        response = client.upload_ttl(
            ttl_str=ttl_content, graph_name=SCENARIOS_GRAPH, replace_existing=False
        )
        status = getattr(response, "status_code", None)
        if status is None or status in (200, 201, 204):
            st.success("✅ Scenario loaded into the `<scenarios>` named graph!")
            st.info(f"📊 **Graph:** `{SCENARIOS_GRAPH}` | ⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}")
        else:
            st.error(f"❌ Graph upload failed (HTTP {status}): {getattr(response, 'text', '')[:200]}")

    except Exception as graph_error:
        st.error(f"❌ Failed to upload scenario to the graph: {graph_error}")


def show_enhanced_service_requirements_summary():
    """Show enhanced service requirements summary with NextCloud workspace context including EventAttribute support"""
    if not st.session_state.get('required_attributes'):
        return

    st.write("### Enhanced Service Requirements Summary")
    required_attrs = st.session_state.required_attributes

    current_workspace = st.session_state.get('current_workspace')
    if current_workspace:
        st.caption(f"Requirements validation for workspace: {current_workspace['name']}")

    for comp_type, attributes in required_attrs.items():
        components_of_type = [c for c in st.session_state.scenario_components if c['type'] == comp_type]
        if components_of_type:
            with st.expander(f"🔧 {comp_type} Components ({len(components_of_type)})", expanded=False):
                # Separate simple and nested attributes
                simple_attrs = [attr for attr in attributes if '.' not in attr]
                nested_attrs = [attr for attr in attributes if '.' in attr]

                if simple_attrs:
                    st.write(f"**Simple Attributes:** {', '.join(simple_attrs)}")

                if nested_attrs:
                    st.write(f"**Nested Properties:** {', '.join(nested_attrs)}")

                # Show TTL property examples based on current specificity
                specificity = st.session_state.get('ttl_specificity', 'High')
                st.write(f"**Object Properties (with {specificity} specificity):**")

                sample_attrs = (simple_attrs + nested_attrs)[:3]  # Show first 3 as examples
                for attr in sample_attrs:
                    attr_clean = attr.split('.')[-1] if '.' in attr else attr
                    attr_clean = attr_clean.replace('_', '').replace(' ', '')

                    if specificity == 'Low':
                        prop_example = "hasAttribute"
                    elif specificity == 'Medium':
                        prop_example = f"has{attr_clean}Attribute"
                    else:  # High
                        prop_example = f"has{comp_type}{attr_clean}Attribute"

                    nested_indicator = " (nested)" if '.' in attr else ""
                    st.caption(f"• `dici_onto:{prop_example}`{nested_indicator}")

                if len(attributes) > 3:
                    st.caption(f"... and {len(attributes) - 3} more")

                # Enhanced component status with NextCloud source context
                st.write("**Enhanced Component Status with Sources:**")
                for comp in components_of_type:
                    comp_attrs = comp.get('attributes', {})
                    source_badge = {
                        'ttl_use_case': '📄',
                        'data_products': '📊',
                        'knowledge_graph': '🏛️'
                    }.get(comp.get('source', 'unknown'), '❓')

                    st.write(f"{source_badge} **{comp.get('uri_fragment', comp['label'])}**")

                    for req_attr in attributes:
                        # Use enhanced nested attribute resolution
                        try:
                            from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement
                            attr_value = resolve_nested_attribute_requirement(comp, req_attr)
                            has_attr = attr_value is not None

                            # For categorical attributes, show the actual category value
                            if has_attr and req_attr in comp_attrs:
                                attr_data = comp_attrs[req_attr]
                                if isinstance(attr_data, dict):
                                    if attr_data.get('attribute_type') == 'CategoricalAttribute' or attr_data.get('data_type') == 'categorical':
                                        category_value = attr_data.get('category_value', attr_value)
                                        status = f"✅ ({category_value})"
                                    # For EventAttribute, show temporal value and precision
                                    elif attr_data.get('attribute_type') == 'EventAttribute' or attr_data.get('data_type') == 'temporal':
                                        temporal_value = attr_data.get('temporal_value', attr_value)
                                        temporal_precision = attr_data.get('temporal_precision')
                                        if temporal_precision:
                                            status = f"✅ 📅 ({temporal_value}, {temporal_precision})"
                                        else:
                                            status = f"✅ 📅 ({temporal_value})"
                                    else:
                                        status = "✅"
                                else:
                                    status = "✅"
                            else:
                                status = "✅" if has_attr else "❌"
                        except:
                            # Fallback to simple check
                            has_attr = any(
                                attr_name.lower() == req_attr.lower() or
                                attr_name.replace('_', '').lower() == req_attr.replace('_', '').lower()
                                for attr_name in comp_attrs.keys()
                            )
                            status = "✅" if has_attr else "❌"

                        nested_indicator = " (nested)" if '.' in req_attr else ""
                        # Add temporal indicator for potential EventAttribute
                        if 'Age' in req_attr or 'Year' in req_attr or 'Date' in req_attr:
                            temporal_indicator = " 📅"
                        else:
                            temporal_indicator = ""
                        st.caption(f"    {status} {req_attr}{nested_indicator}{temporal_indicator}")

    # Enhanced file statistics with workspace context
    ttl_content = generate_full_ttl()  # Generate content for stats
    lines_count = len(ttl_content.split('\n'))
    char_count = len(ttl_content)
    specificity = st.session_state.get('ttl_specificity', 'High')

    # Count NextCloud features
    source_tracking_count = ttl_content.count('dici_onto:sourceType')
    workspace_refs = ttl_content.count('createdInWorkspace')
    # Count EventAttribute features
    event_attr_count = ttl_content.count('dici_onto:EventAttribute')
    temporal_value_count = ttl_content.count('dici_onto:hasTemporalValue')

    workspace_name = current_workspace['name'] if current_workspace else 'Unknown'

    # Enhanced info with EventAttribute stats
    info_parts = [
        f"**Enhanced File Stats:** {lines_count} lines, {char_count} chars",
        f"**Workspace:** {workspace_name}",
        f"**Specificity:** {specificity}",
        f"**Source Tracking:** {source_tracking_count}",
        f"**Workspace Refs:** {workspace_refs}"
    ]

    # Add EventAttribute stats if present
    if event_attr_count > 0:
        info_parts.append(f"**EventAttributes:** {event_attr_count}")
    if temporal_value_count > 0:
        info_parts.append(f"**Temporal Values:** {temporal_value_count}")

    st.info(" | ".join(info_parts))

    # Enhanced validation status with workspace context
    filtered_components = get_filtered_components_for_ttl()
    if filtered_components and st.session_state.scenario_links:
        if st.session_state.get('required_attributes'):
            missing_attributes = validate_enhanced_component_attributes_filtered(filtered_components)
            if not missing_attributes:
                # Enhanced success message with EventAttribute support
                success_msg = f"✅ Enhanced TTL ready with {specificity} specificity, full NextCloud workspace integration"
                if event_attr_count > 0:
                    success_msg += f", and {event_attr_count} EventAttribute(s)"
                success_msg += ", and all required attributes in complete components!"
                st.success(success_msg)
            else:
                st.warning("⚠️ Enhanced TTL generated but some complete components are missing required attributes")
        else:
            success_msg = f"✅ Enhanced TTL ready with {specificity} specificity and full NextCloud workspace integration!"
            if event_attr_count > 0:
                success_msg = success_msg[:-1] + f" including {event_attr_count} EventAttribute(s)!"
            st.success(success_msg)
    else:
        st.warning("⚠️ Add components and links to generate a complete enhanced TTL file")