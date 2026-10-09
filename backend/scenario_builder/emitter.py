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
  in ``backend/scenario_builder/__init__.py`` and the shipped demo scenarios).

One pinned quirk was deliberately UNPINNED (2026-09-24): the completeness filter
was truthiness-based, so a legitimate ``0`` value (TurbulenceIntensity 0.0,
NumberOfFloors 0) dropped its component from the scenario and converted the
payload hollow — the wind-forecasting empty-payload failure. The filter now
treats only None/empty as missing (see ``_requirement_absent``).

Also moved here: ``resolve_nested_attribute_requirement`` (previously in
``components/scenario_builder/scenario_builder_components.py``; that module
now re-imports it from here). It is pure dict resolution and both the emitter
and the component browser depend on it, so it must be one function, not two
copies. Requirement names resolve by the IRIs they name (identity, or the
property hierarchy for a nested property), never by spelling variants.

Two seam changes, both behavior-neutral for the characterized paths:

* the old ``except ImportError`` fallbacks (for when the components module was
  not importable) are unreachable now that the resolver is module-local; the
  enhanced path — the one every real deployment and the characterization tests
  exercise — is always taken;
* the resolver's catch-all is gone: a malformed component now raises
  instead of silently resolving to nothing.
"""
from __future__ import annotations

from backend.scenario_builder import scenario_uri_for
from backend.ontology_kinds import DICI, AttributeKind
from backend.scenario_builder.draft import ScenarioDraft
from backend.scenario_builder.semantics import (
    MISSING,
    TIME_SERIES_LINKS,
    TIME_SERIES_REFERENCES,
    find_property,
    first_present,
    has_time_series_data,
    is_time_series_key,
    is_time_series_reference_key,
    kind_of,
    local_key,
    is_unknown_precision,
    names_subclass_of,
    precision_term,
    stored_series_reference,
)


def _requirement_parts(component, requirement_path):
    """A dotted requirement split into ``[attribute, property, ...]``.

    A leading component type (``EnergyConsumer.Power.hasX``) is dropped when
    the component's type is that class or a class under it.
    """
    parts = requirement_path.split('.')
    if len(parts) > 2 and names_subclass_of(component.get('type'), parts[0]):
        parts = parts[1:]
    return parts


def _attribute_value(attr_data):
    """The value a requirement reads off an attribute, by its kind."""
    kind = kind_of(attr_data)
    if kind is AttributeKind.CATEGORICAL:
        return attr_data.get('category_value', attr_data.get('value'))
    if kind is AttributeKind.EVENT:
        return attr_data.get('temporal_value', attr_data.get('value'))
    return attr_data.get('value')


def resolve_nested_attribute_requirement(component, requirement_path):
    """Resolve a service requirement against a component dict.

    ``Power`` reads the attribute stored under that name. A dotted path
    (``Power.hasHistoricTimeSeriesReference``, optionally led by the
    component's class) reads a property of that attribute: the property named,
    or a subproperty of it, from the attribute's nested properties, its own
    data, or the time series reference a loader stored for it. Names match by
    the IRIs they name, never by spelling variants.
    """
    if not requirement_path or not component:
        return None

    attributes = component.get('attributes', {})
    if '.' not in requirement_path:
        attr_data = attributes.get(requirement_path)
        if isinstance(attr_data, dict):
            return _attribute_value(attr_data)
        return attr_data

    parts = _requirement_parts(component, requirement_path)
    if len(parts) < 2:
        return None
    attribute_name, props = parts[0], parts[1:]
    nested = component.get('nested_properties', {}).get(attribute_name)
    attr_data = attributes.get(attribute_name)

    if len(props) == 1:
        wanted = props[0]
        for source in (nested, attr_data):
            if isinstance(source, dict):
                value = find_property(source, wanted)
                if value is not MISSING:
                    return value
        if isinstance(attr_data, dict):
            value = stored_series_reference(attr_data, wanted)
            if value is not MISSING:
                return value
        return None

    # Deeper paths walk one property per step.
    current = nested if isinstance(nested, dict) else attr_data
    for part in props:
        if not isinstance(current, dict):
            return None
        current = find_property(current, part)
        if current is MISSING:
            return None
    return current


def _merged_attribute(component, attribute_name):
    """A copy of the named attribute's data with its nested properties merged
    in, re-typed dynamic when a time series link or reference is among them."""
    attr_data = component.get('attributes', {}).get(attribute_name)
    attr_data = dict(attr_data) if isinstance(attr_data, dict) else {}
    nested = component.get('nested_properties', {}).get(attribute_name)
    if isinstance(nested, dict):
        attr_data.update(nested)
    if has_time_series_data(attr_data.keys()):
        attr_data['attribute_type'] = AttributeKind.DYNAMIC
    return attr_data


def resolve_enhanced_attribute_value(component, req_attr):
    """``(value, unit, attribute data)`` a requirement resolves to on a
    component, or ``(None, None, None)``. The attribute data carries the
    attribute's nested properties merged in, for TTL generation."""
    if not component or not req_attr or not isinstance(component, dict):
        return None, None, None

    # Nested requirement like Power.hasHistoricTimeSeriesReference
    if '.' in req_attr:
        nested_value = resolve_nested_attribute_requirement(component, req_attr)
        if not nested_value:
            return None, None, None
        attr_data = _merged_attribute(component, _requirement_parts(component, req_attr)[0])
        attr_data['value'] = nested_value
        attr_data['unit'] = attr_data.get('unit', 'text')
        return nested_value, attr_data['unit'], attr_data

    raw = component.get('attributes', {}).get(req_attr)
    if raw is None:
        return None, None, None
    if not isinstance(raw, dict):
        # Simple value
        return raw, 'dimensionless', {'value': raw, 'unit': 'dimensionless'}

    attr_data = _merged_attribute(component, req_attr)
    kind = kind_of(attr_data)
    if kind is AttributeKind.CATEGORICAL:
        return _attribute_value(attr_data), attr_data.get('unit', 'category'), attr_data
    if kind is AttributeKind.EVENT:
        return _attribute_value(attr_data), attr_data.get('unit', 'temporal'), attr_data
    return attr_data.get('value'), attr_data.get('unit'), attr_data


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

    kind = kind_of(attr_data) or AttributeKind.PHYSICAL

    # FIXED: Handle DynamicAttribute with time series references properly
    if kind is AttributeKind.DYNAMIC:
        ttl_lines.extend([
            f"<{attr_uri}> a dici_onto:{attr_name_clean} ;",
            f"    a dici_onto:DynamicAttribute ;"
        ])

        # Add time series URI if available
        found = first_present(attr_data, TIME_SERIES_LINKS)
        if found:
            prop, ts_uri = found
            ttl_lines.append(f"    dici_onto:{local_key(prop)} <{ts_uri}> ;")

        # Add time series reference if available
        found = first_present(attr_data, TIME_SERIES_REFERENCES)
        if found:
            prop, ts_ref = found
            ttl_lines.append(f"    dici_onto:{local_key(prop)} \"{ts_ref}\"^^xsd:string ;")

    elif kind is AttributeKind.SIMPLE_COST:
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

    elif kind is AttributeKind.UNIT_BASED_COST:
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

    elif kind is AttributeKind.CATEGORICAL:
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

    elif kind is AttributeKind.GEOSPATIAL:
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
    elif kind is AttributeKind.EVENT:
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
        precision = precision_term(temporal_precision)
        if precision is not None and not is_unknown_precision(temporal_precision):
            ttl_lines.append(f'    dici_onto:hasTemporalPrecision dici_onto:{local_key(precision)} ;')

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


# XSD datatype of a temporal value, by its dici_onto:TemporalPrecision individual.
_XSD_BY_PRECISION = {
    DICI.Year: 'xsd:gYear',
    DICI.YearMonth: 'xsd:gYearMonth',
    DICI.Date: 'xsd:date',
    DICI.DateTime: 'xsd:dateTime',
}


def get_xsd_datatype_for_temporal_precision(temporal_precision, temporal_value):
    """Determine appropriate XSD datatype based on temporal precision and value format"""
    # The precision individual decides
    precision = precision_term(temporal_precision)
    if precision in _XSD_BY_PRECISION:
        return _XSD_BY_PRECISION[precision]

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
                    if (is_time_series_key(prop_name) and
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
                if is_time_series_reference_key(prop_name) and prop_value:
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
                    parts = _requirement_parts(component, req_attr)

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

    kind = kind_of(attr_data) or AttributeKind.PHYSICAL

    # Start attribute declaration
    ttl_lines.append(f"<{attr_uri}> a dici_onto:{attr_name_clean} ;")

    # Add attribute type
    if kind is AttributeKind.DYNAMIC:
        ttl_lines.append(f"    a dici_onto:DynamicAttribute ;")
    elif kind is AttributeKind.SIMPLE_COST:
        ttl_lines.append(f"    a dici_onto:SimpleCostAttribute ;")
    elif kind is AttributeKind.UNIT_BASED_COST:
        ttl_lines.append(f"    a dici_onto:UnitBasedCostAttribute ;")
    elif kind is AttributeKind.CATEGORICAL:
        ttl_lines.append(f"    a dici_onto:CategoricalAttribute ;")
        # For categorical attributes, add the category type as a second type
        category_value = attr_data.get('category_value', attr_value)
        if category_value and isinstance(category_value, str):
            clean_category = category_value.replace(' ', '').replace('-', '').replace('_', '')
            ttl_lines.append(f'    a dici_onto:{clean_category} ;')
    elif kind is AttributeKind.GEOSPATIAL:
        ttl_lines.append(f"    a dici_onto:GeospatialAttribute ;")
    elif kind is AttributeKind.EVENT:
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
            if is_time_series_reference_key(nested_prop_name):
                # Time series reference - string value
                ttl_lines.append(f'    dici_onto:{nested_prop_name} "{nested_value}"^^xsd:string ;')
            elif is_time_series_key(nested_prop_name):
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
    if kind is AttributeKind.DYNAMIC:
        # For DynamicAttribute, unit is required
        if attr_unit and attr_unit not in ['file', 'text']:
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

    elif kind in (AttributeKind.SIMPLE_COST, AttributeKind.UNIT_BASED_COST):
        # Add value
        if isinstance(attr_value, (int, float)):
            ttl_lines.append(f'    qudt:value "{attr_value}"^^xsd:decimal ;')
        else:
            ttl_lines.append(f'    qudt:value {_string_literal(attr_value)}^^xsd:string ;')

        # Add unit for UnitBasedCostAttribute
        if kind is AttributeKind.UNIT_BASED_COST and attr_unit and attr_unit != 'file':
            unit_uri = map_unit_to_uri(attr_unit)
            ttl_lines.append(f'    qudt:unit {unit_uri} ;')

        # Add currency for cost attributes
        currency = attr_data.get('currency', 'CHF')
        ttl_lines.append(f'    dici_onto:currency cur:{currency} ;')

    elif kind is AttributeKind.EVENT:
        # Add temporal value with appropriate XSD datatype
        temporal_value = attr_data.get('temporal_value', attr_value)
        temporal_precision = attr_data.get('temporal_precision', 'Unknown')

        xsd_datatype = get_xsd_datatype_for_temporal_precision(temporal_precision, temporal_value)
        ttl_lines.append(f'    dici_onto:hasTemporalValue "{temporal_value}"^^{xsd_datatype} ;')

        precision = precision_term(temporal_precision)
        if precision is not None and not is_unknown_precision(temporal_precision):
            ttl_lines.append(f'    dici_onto:hasTemporalPrecision dici_onto:{local_key(precision)} ;')

    elif kind is not AttributeKind.CATEGORICAL:  # Skip value for categorical
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


def _requirement_absent(attr_value) -> bool:
    """A required attribute is missing only when it has NO value — None, or an
    empty string/collection. A plain truthiness test wrongly counted legitimate
    zero values (TurbulenceIntensity 0.0, NumberOfFloors 0, a False flag) as
    missing, which silently dropped the whole component from the scenario and
    converted its payload block hollow."""
    if attr_value is None:
        return True
    if isinstance(attr_value, (str, list, tuple, dict, set)):
        return len(attr_value) == 0
    return False


def validate_enhanced_component_attributes(components, required_attributes):
    """Enhanced validation that handles nested property requirements including EventAttribute"""
    missing_attributes = []
    required_attributes = required_attributes or {}

    for component in components:
        comp_type = component['type']
        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            for req_attr in required_attrs:
                attr_value = resolve_nested_attribute_requirement(component, req_attr)
                if _requirement_absent(attr_value):
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
                attr_value = resolve_nested_attribute_requirement(component, req_attr)
                if _requirement_absent(attr_value):
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
                attr_value = resolve_nested_attribute_requirement(component, req_attr)
                if _requirement_absent(attr_value):
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
