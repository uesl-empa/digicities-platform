# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The full scenario-TTL emitter, headless (Phase 4b of the backend/UI split).

Moved verbatim from
``apps/streamlit/components/scenario_builder/scenario_builder_summary.py``:
the transformation logic is unchanged — only the inputs moved from
``st.session_state`` reads to an explicit :class:`~backend.scenario_builder.draft.ScenarioDraft`
(for :func:`generate_full_ttl`) or plain arguments (for the helpers, which
already took their data explicitly). The Streamlit module remains as a shim
that adapts session state onto these functions.

Pinned behavior (see ``tests/test_characterize_scenario_emitter.py`` and the
golden ``tests/goldens/scenario_emitter_full.ttl``) is preserved on purpose,
including the quirks:

* booleans hit the ``isinstance(value, (int, float))`` branch and are emitted
  as ``"True"^^xsd:decimal``;
* the ``dici_onto:linksInputyEntityTo`` spelling (shared with the thin builder
  in ``backend/scenario_builder/__init__.py`` and the shipped demo scenarios);
* the completeness filter is truthiness-based, so a legitimate ``0`` value
  drops a component.

Also moved here: ``resolve_nested_attribute_requirement`` (previously in
``components/scenario_builder/scenario_builder_components.py``; that module
now re-imports it from here). It is pure dict resolution and both the emitter
and the component browser depend on it, so it must be one function, not two
copies. Its dotted-path last resort delegates to the already-relocated
``display_utils.get_nested_property_from_ttl_component``.

Two seam changes, both behavior-neutral for the characterized paths:

* the old ``except ImportError`` fallbacks (for when the components module was
  not importable) are unreachable now that the resolver is module-local; the
  enhanced path — the one every real deployment and the characterization tests
  exercise — is always taken;
* ``st.error(...)`` in the resolver's catch-all became a silent
  ``return None, None, None`` (the return value is unchanged).
"""
from __future__ import annotations

from backend.scenario_builder import scenario_uri_for
from backend.scenario_builder.display_utils import get_nested_property_from_ttl_component
from backend.scenario_builder.draft import ScenarioDraft


def resolve_nested_attribute_requirement(component, requirement_path):
    """
    ENHANCED: Resolve nested attribute requirements with comprehensive handling of GraphDB export patterns
    Handles patterns like:
    - Power.hasHistoricTimeSeriesReference
    - EnergyConsumer.Power.hasHistoricTimeSeriesReference
    - All possible inheritance combinations from GraphDB export
    """
    if not requirement_path or not component:
        return None

    # If no dots, it's a simple attribute
    if '.' not in requirement_path:
        attr_data = component.get('attributes', {}).get(requirement_path)
        if isinstance(attr_data, dict):
            if attr_data.get('attribute_type') == 'CategoricalAttribute':
                return attr_data.get('category_value', attr_data.get('value'))
            elif attr_data.get('attribute_type') == 'EventAttribute':
                return attr_data.get('temporal_value', attr_data.get('value'))
            else:
                return attr_data.get('value')
        return attr_data

    # Parse the requirement path
    parts = requirement_path.split('.')
    component_type = component.get('type', '')

    # Remove component type if it matches the first part
    if len(parts) > 2 and parts[0] == component_type:
        parts = parts[1:]  # Remove the component type prefix

    # Now we should have something like ['Power', 'hasHistoricTimeSeriesReference']
    if len(parts) >= 2:
        attribute_name = parts[0]
        nested_property = '.'.join(parts[1:])  # Handle deeper nesting

        # CRITICAL: Create comprehensive list of possible keys
        possible_keys = [
            # Base attribute name
            attribute_name,
            # With Attribute suffix
            f"{attribute_name}Attribute",
            # With component type prefix
            f"{component_type}{attribute_name}",
            # With component type and Attribute suffix
            f"{component_type}{attribute_name}Attribute",
            # Lowercase variations
            attribute_name.lower(),
            f"{attribute_name.lower()}attribute",
            f"{component_type.lower()}{attribute_name.lower()}",
            f"{component_type.lower()}{attribute_name.lower()}attribute",
            # Title case variations
            attribute_name.title(),
            f"{attribute_name.title()}Attribute",
            f"{component_type.title()}{attribute_name.title()}",
            f"{component_type.title()}{attribute_name.title()}Attribute"
        ]

        # Remove duplicates while preserving order
        seen = set()
        possible_keys = [x for x in possible_keys if not (x in seen or seen.add(x))]

        # Check nested_properties first (most likely location for GraphDB export)
        nested_props = component.get('nested_properties', {})
        for key in possible_keys:
            if key in nested_props:
                nested_data = nested_props[key]
                if isinstance(nested_data, dict):
                    # Direct check for the nested property
                    if nested_property in nested_data:
                        return nested_data[nested_property]

                    # Check for variations of the nested property name
                    nested_variations = [
                        nested_property,
                        nested_property.lower(),
                        nested_property.replace('has', ''),  # Remove 'has' prefix
                        nested_property.replace('has', '').lower(),
                        nested_property.replace('TimeSeries', 'TimesSeries'),  # Common typo
                        nested_property.replace('Reference', 'Ref'),  # Shortened form
                    ]

                    for nested_var in nested_variations:
                        if nested_var in nested_data:
                            return nested_data[nested_var]

        # Check attributes for nested properties stored directly
        attributes = component.get('attributes', {})
        for key in possible_keys:
            if key in attributes:
                attr_data = attributes[key]
                if isinstance(attr_data, dict):
                    # Direct check for the nested property
                    if nested_property in attr_data:
                        return attr_data[nested_property]

                    # Special handling for time series references that might be stored differently
                    if 'TimeSeriesReference' in nested_property:
                        # Check for common alternative storage keys
                        alt_keys = [
                            'time_series_reference',
                            'timeSeriesReference',
                            'hasTimeSeriesReference',
                            'reference',
                            'file_reference',
                            'data_reference'
                        ]
                        for alt_key in alt_keys:
                            if alt_key in attr_data:
                                return attr_data[alt_key]

        # ENHANCED: Try direct path resolution for deeper nesting
        # This handles cases where the full path might be stored as a flattened key
        flattened_keys = [
            requirement_path,  # Original path
            requirement_path.replace('.', ''),  # No dots
            requirement_path.replace('.', '_'),  # Underscores
            requirement_path.replace(f"{component_type}.", ''),  # Remove component prefix
            '.'.join(parts),  # Reconstructed without component type
        ]

        # Check both nested_properties and attributes for flattened keys
        for flattened_key in flattened_keys:
            # Check nested_properties
            if flattened_key in nested_props:
                result = nested_props[flattened_key]
                if result:
                    return result

            # Check attributes
            if flattened_key in attributes:
                attr_data = attributes[flattened_key]
                if isinstance(attr_data, dict):
                    return attr_data.get('value')
                return attr_data

    # Final fallback: progressive resolution for complex paths
    if len(parts) > 2:
        current = component
        for i, part in enumerate(parts):
            if i == 0:
                # Look for the base attribute in both attributes and nested_properties
                current = None

                # Try all possible key variations
                for key_candidate in possible_keys:
                    # Check attributes first
                    if key_candidate in component.get('attributes', {}):
                        current = component['attributes'][key_candidate]
                        break
                    # Then check nested_properties
                    if key_candidate in component.get('nested_properties', {}):
                        current = component['nested_properties'][key_candidate]
                        break

                if current is None:
                    return None
            else:
                if isinstance(current, dict):
                    # Try the exact part name and variations
                    if part in current:
                        current = current[part]
                    else:
                        # Try variations
                        found = False
                        for variation in [part, part.lower(), part.replace('has', ''), part.replace('Reference', 'Ref')]:
                            if variation in current:
                                current = current[variation]
                                found = True
                                break
                        if not found:
                            return None
                else:
                    return None

        return current if current is not None else None

    # Dotted Attribute.nestedProp fallback (pure helper).
    if component.get('source') in ['ttl_use_case', 'knowledge_graph']:
        try:
            return get_nested_property_from_ttl_component(component, requirement_path)
        except Exception:
            pass

    return None


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

    except Exception:
        # Never crash TTL generation on a malformed attribute; the old module
        # surfaced this via st.error, the return contract is unchanged.
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


def _string_literal(value) -> str:
    """A safe Turtle string token for attribute values.

    Simple one-line values keep the plain quoting the goldens pin; a value
    carrying newlines or quotes (curve data points, free text) becomes an
    escaped triple-quoted literal — it used to be emitted inside bare quotes,
    which is invalid Turtle and broke re-parsing the emitted scenario.
    """
    s = str(value)
    if '\n' in s or '"' in s or '\\' in s:
        s = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"""{s}"""'
    return f'"{s}"'


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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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
        ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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


def generate_full_ttl(draft: ScenarioDraft) -> str:
    """Generate complete TTL with enhanced workspace context and FIXED nested attribute handling.

    Headless port of the Streamlit ``generate_full_ttl()``: every
    ``st.session_state`` read became a :class:`ScenarioDraft` field, the
    transformation is otherwise verbatim.
    """
    scenario_name = draft.scenario_name

    # Always filter to complete components only
    components = get_filtered_components_for_ttl(draft.components, draft.required_attributes)
    links = get_filtered_links_for_ttl(draft.links, components)

    required_attributes = draft.required_attributes or {}

    # Create safe scenario URI with enhanced workspace context
    workspace_id = draft.workspace_id or 'default_workspace'
    workspace_name = draft.workspace_name or 'Default Workspace'

    scenario_uri = scenario_uri_for(workspace_id, scenario_name)

    description = draft.description or f"Scenario built in workspace {workspace_name}"

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
        f'    dcterms:description "{description}" ;',
    ]
    # Record which service template this scenario was built to satisfy, so it can
    # be matched to that service later (e.g. the API submission convert tab only
    # offers scenarios built for the chosen service).
    service_name = draft.service_name
    if service_name:
        ttl_lines.append(f'    dici_onto:builtForService "{service_name}" ;')
    ttl_lines.append(f'    dici_onto:createdInWorkspace "{workspace_id}" .')
    ttl_lines.append("")

    # Get object property specificity preference
    specificity = draft.ttl_specificity or 'High'

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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

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


def validate_enhanced_component_attributes(components, required_attributes):
    """Enhanced validation that handles nested property requirements including EventAttribute"""
    missing_attributes = []
    required_attributes = required_attributes or {}

    for component in components:
        comp_type = component['type']
        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            for req_attr in required_attrs:
                try:
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })
                except Exception:
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


# Function to filter components based on completeness (always enabled now)
def get_filtered_components_for_ttl(components, required_attributes):
    """Get components filtered to include only complete components with all required attributes"""
    # UPDATED: Always filter out incomplete components - no option to include partial
    filtered_components = []
    required_attributes = required_attributes or {}

    for component in components:
        comp_type = component['type']
        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            # Check if component has all required attributes
            missing_count = 0
            for req_attr in required_attrs:
                try:
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_count += 1
                except Exception:
                    missing_count += 1

            # Only include component if it has all required attributes
            if missing_count == 0:
                filtered_components.append(component)
        else:
            # Include components with no requirements
            filtered_components.append(component)

    return filtered_components


# Function to filter links based on included components
def get_filtered_links_for_ttl(links, filtered_components):
    """Get links filtered to only include those between included components"""
    # UPDATED: Always filter links - no option for partial components

    # Create set of included component URIs for efficient lookup
    included_component_uris = {comp['uri'] for comp in filtered_components}
    # Also include 'scenario' as a valid source for automatic links
    included_component_uris.add('scenario')

    # Filter links to only include those where both source and target are in included components
    filtered_links = []

    for link in links:
        source_uri = link.get('source')
        target_uri = link.get('target')

        # Include link only if both source and target are in the filtered component set
        if source_uri in included_component_uris and target_uri in included_component_uris:
            filtered_links.append(link)

    return filtered_links


# Function to validate only filtered components
def validate_enhanced_component_attributes_filtered(filtered_components, required_attributes):
    """Enhanced validation for filtered (complete) components only"""
    missing_attributes = []
    required_attributes = required_attributes or {}

    for component in filtered_components:
        comp_type = component['type']
        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            for req_attr in required_attrs:
                try:
                    attr_value = resolve_nested_attribute_requirement(component, req_attr)
                    if not attr_value:
                        missing_attributes.append({
                            'component': component['label'],
                            'type': comp_type,
                            'missing_attribute': req_attr
                        })
                except Exception:
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


__all__ = [
    "resolve_nested_attribute_requirement",
    "resolve_enhanced_attribute_value",
    "map_unit_to_uri",
    "generate_enhanced_attribute_declaration",
    "generate_enhanced_attribute_declaration_with_nested_properties",
    "generate_basic_attribute_declaration",
    "get_xsd_datatype_for_temporal_precision",
    "generate_time_series_resources",
    "generate_full_ttl",
    "get_filtered_components_for_ttl",
    "get_filtered_links_for_ttl",
    "validate_enhanced_component_attributes",
    "validate_enhanced_component_attributes_filtered",
]
