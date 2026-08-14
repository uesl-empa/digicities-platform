# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Enhanced Component Explorer for the Digicities Platform - FIXED VERSION
Explores actual component instances and their various attribute types
Including support for SimpleValue and CustomPhysicalRatio attributes
FIXED: Proper namespace handling for any custom URI patterns
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import ast
import json
import math
import re
from typing import Dict, List, Any, Optional, Tuple

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    from_clause,
)
from backend.graphdb import queries as gdb_queries


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

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


def get_component_sources(client, component_type_label: str) -> Dict[str, Dict[str, Any]]:
    """Provenance per instance URI: where the record came from, and where any
    individual attribute came from when that differs.

    Shape: ``{instance_uri: {'instance': [ref, ...], 'attributes': {attr: [ref, ...]}}}``
    where each ref is ``{uri, label, type, url, date, comment}``. Empty when the
    graph carries no provenance, which is the normal case for a replica built
    before sources were recorded — the UI simply has nothing to show.
    """
    df = gdb_queries.get_component_sources(client, component_type_label)

    def cell(row, key: str) -> str:
        # An unbound OPTIONAL comes back as NaN, which is TRUTHY — `or` fallbacks
        # would silently keep it and render "nan" in the UI.
        val = row.get(key)
        return '' if val is None or pd.isna(val) else str(val)

    sources: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        instance = cell(row, 'instance')
        if not instance:
            continue
        ref = {
            'uri': cell(row, 'source'),
            # A Reference with no label still has a readable id in its URI.
            'label': cell(row, 'sourceLabel') or extract_uri_fragment(cell(row, 'source')),
            'type': cell(row, 'sourceType'),
            'url': cell(row, 'sourceUrl'),
            'date': cell(row, 'sourceDate'),
            'comment': cell(row, 'sourceComment'),
        }
        entry = sources.setdefault(instance, {'instance': [], 'attributes': {}})
        if cell(row, 'scope') == 'attribute':
            attr = cell(row, 'attributeName') or '?'
            bucket = entry['attributes'].setdefault(attr, [])
        else:
            bucket = entry['instance']
        if not any(r['uri'] == ref['uri'] for r in bucket):
            bucket.append(ref)
    return sources


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


# =============================================================================
# DATA PROCESSING FUNCTIONS - FIXED
# =============================================================================

def extract_uri_fragment(uri: str) -> str:
    """Extract the last part of a URI - FIXED for any namespace pattern"""
    if not uri:
        return ''

    # Handle URIs with fragment identifiers (#)
    if '#' in uri:
        fragment = uri.split('#')[-1]
        return fragment if fragment else uri.split('/')[-1]

    # Handle URIs with path segments (/)
    elif '/' in uri:
        path_part = uri.split('/')[-1]
        return path_part if path_part else uri

    # Return as-is if no separators found
    else:
        return uri


def extract_property_name(property_uri: str) -> str:
    """Extract property name from URI - ENHANCED"""
    if not property_uri:
        return ''

    # Common namespace patterns
    namespaces = [
        'https://digicities.info/ontology#',
        'http://qudt.org/schema/qudt/',
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'http://www.w3.org/2000/01/rdf-schema#',
        'http://purl.org/dc/terms/'
    ]

    # Try exact namespace matches first
    for ns in namespaces:
        if property_uri.startswith(ns):
            return property_uri[len(ns):]

    # Fallback to generic fragment extraction
    return extract_uri_fragment(property_uri)


def extract_readable_instance_name(uri: str) -> str:
    """Extract a readable name from instance URIs - handles any namespace pattern"""
    if not uri:
        return ''

    # Extract the local part after # or /
    local_part = extract_uri_fragment(uri)

    # If it's just a simple identifier, return it
    if local_part and len(local_part) <= 20 and not '/' in local_part:
        return local_part

    # For longer URIs, try to extract meaningful parts
    # Split on common separators and take the last meaningful part
    parts = re.split(r'[/#]', uri)
    meaningful_parts = [part for part in parts if part and len(part) > 0]

    if meaningful_parts:
        return meaningful_parts[-1]

    return uri


def clean_unit(unit_value: str) -> str:
    """A displayable unit string, or '' when there is no unit.

    ``unit:None``, the bare QUDT namespace and friends are absences dressed up as
    units (backend.units explains where each comes from); rendering one as an axis
    label shows the user something that isn't true.
    """
    from backend.units import is_missing_unit
    if is_missing_unit(unit_value):
        return ''
    text = map_unit_uri_to_string(str(unit_value).strip())
    # A bare IRI that mapped to nothing still leaves the local name to show.
    if text.startswith('http'):
        text = text.rstrip('/').rsplit('/', 1)[-1]
    return '' if is_missing_unit(text) else text


def curve_axis_units(props: Dict) -> Tuple[str, str]:
    """(x_unit, y_unit) for a curve, preferring the string labels over the IRIs.

    Both are optional and independently so: the Replica Builder writes only the
    IRIs, the Excel ingestion writes both, and a dimensionless axis (a thrust
    coefficient) legitimately has neither.
    """
    x = clean_unit(props.get('xUnitLabel', '')) or clean_unit(props.get('xUnit', ''))
    y = clean_unit(props.get('yUnitLabel', '')) or clean_unit(props.get('yUnit', ''))
    return x, y


def map_unit_uri_to_string(unit_uri: str) -> str:
    """Map QUDT unit URIs to readable strings, including custom ratios - ENHANCED"""
    if not unit_uri:
        return ''

    # Check if it's a custom ratio format (e.g., "KiloGM/KiloW")
    if '/' in unit_uri and not unit_uri.startswith('http'):
        return unit_uri

    # Check for -PER- format (e.g., "KiloGM-PER-KiloW")
    if '-PER-' in unit_uri:
        return unit_uri.replace('-PER-', '/')

    # Standard unit mappings
    unit_mapping = {
        'http://qudt.org/vocab/unit/MegaW': 'MW',
        'http://qudt.org/vocab/unit/KiloW': 'kW',
        'http://qudt.org/vocab/unit/W': 'W',
        'http://qudt.org/vocab/unit/M': 'm',
        'http://qudt.org/vocab/unit/DEG': '°',
        'http://qudt.org/vocab/unit/M-PER-SEC': 'm/s',
        'http://qudt.org/vocab/unit/N': 'N',
        'http://qudt.org/vocab/unit/ONE': '',
        'http://qudt.org/vocab/unit/W-M2': 'W/m²',
        'http://qudt.org/vocab/unit/W-HR': 'Wh',
        'http://qudt.org/vocab/unit/KiloW-HR': 'kWh',
        'http://qudt.org/vocab/unit/kWh': 'kWh',  # Added common variant
        'http://qudt.org/vocab/unit/KiloGM': 'kg',
        'http://qudt.org/vocab/unit/KiloGM-PER-KiloW': 'kg/kW',
    }

    # Exact match
    if unit_uri in unit_mapping:
        return unit_mapping[unit_uri]

    # Handle unit: prefix
    if unit_uri.startswith('unit:'):
        local_unit = unit_uri.replace('unit:', '')
        if '-PER-' in local_unit:
            return local_unit.replace('-PER-', '/')
        # Try to match with full URI
        for full_uri, symbol in unit_mapping.items():
            if full_uri.endswith(local_unit):
                return symbol

    # Extract fragment as fallback
    return extract_uri_fragment(unit_uri)


def map_currency_uri_to_string(currency_uri: str) -> str:
    """Map currency URIs to readable strings"""
    if not currency_uri:
        return ''

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

    if currency_uri in currency_mapping:
        return currency_mapping[currency_uri]

    return extract_uri_fragment(currency_uri)


# Hidden column prefix carrying a curve's parsed points + units next to its
# human-readable summary. Underscore-prefixed columns are filtered out of the
# table by get_visible_columns.
CURVE_META_PREFIX = '_curve__'

# A number as any writer or hand-authored file can spell it: sign, decimals,
# leading dot, exponent. The old pattern was `[0-9.-]+`, which silently dropped
# negatives written as `- 5`, `+1.2`, and anything in scientific notation.
_NUM = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
_PAIR_BRACKET = re.compile(r'\[\s*(%s)\s*[,;]\s*(%s)\s*\]' % (_NUM, _NUM))
_PAIR_PAREN = re.compile(r'\(\s*(%s)\s*[,;]\s*(%s)\s*\)' % (_NUM, _NUM))

# hasDataPoints sometimes holds a pointer to an external file instead of points.
_RESOURCE_HINT = re.compile(r'resources/|\.csv|\.json|\.parquet', re.I)


def curve_data_is_reference(curve_data_str: str) -> bool:
    """True when the literal points at an external file rather than holding points."""
    s = (curve_data_str or '').strip()
    return bool(s) and '[' not in s and '(' not in s and bool(_RESOURCE_HINT.search(s))


def parse_curve_data(curve_data_str: str) -> List[Tuple[float, float]]:
    """Parse a ``hasDataPoints`` literal into [(x, y), …].

    The platform emits several mutually incompatible shapes and none of them is
    validated on write, so every one has to be tried:

    * ``[  0.0,  1.0]`` newline-separated with NO commas between pairs — what the
      Excel→TTL ingestion produces, and NOT valid JSON despite the declared range
    * ``[0.0, 1.0],`` comma-separated — the Replica Builder UI, valid JSON
    * ``(0.10, 2.5),`` Python tuples — hand-authored files and the tutorial data
    * ``[(0,0);(1,10)]`` semicolon-separated — the authoring format users type
    * an external file reference (see ``curve_data_is_reference``)

    Non-finite and unparseable entries are dropped rather than raising, so one bad
    pair cannot cost the whole curve.
    """
    if not curve_data_str:
        return []

    def _finite(pairs):
        out = []
        for x, y in pairs:
            try:
                fx, fy = float(x), float(y)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fx) and math.isfinite(fy):
                out.append((fx, fy))
        return out

    try:
        cleaned = re.sub(r'\s+', ' ', str(curve_data_str).strip())
        if not cleaned or cleaned in ('[', '[]', '[ ]'):
            return []

        # Structured parsers first — they preserve pairing exactly.
        for loader in (json.loads, ast.literal_eval):
            try:
                points = loader(cleaned)
            except Exception:
                continue
            if isinstance(points, (list, tuple)):
                pairs = [(p[0], p[1]) for p in points
                         if isinstance(p, (list, tuple)) and len(p) >= 2]
                if pairs:
                    return _finite(pairs)

        # Regex fallbacks: the comma-less and paren forms are not loadable.
        for pattern in (_PAIR_BRACKET, _PAIR_PAREN):
            matches = pattern.findall(cleaned)
            if matches:
                return _finite(matches)

    except Exception as e:                      # never let the table/plot die on data
        print(f"[component_explorer] error parsing curve data: {e}")

    return []


class AttributeProcessor:
    """Handles processing of different attribute types - ENHANCED"""

    def __init__(self):
        self.attribute_type_handlers = {
            'PhysicalAttribute': self._process_physical_attribute,
            'SimpleCostAttribute': self._process_simple_cost_attribute,
            'UnitBasedCostAttribute': self._process_unit_based_cost_attribute,
            'CategoricalAttribute': self._process_categorical_attribute,
            'CurveAttribute': self._process_curve_attribute,
            'DynamicAttribute': self._process_dynamic_attribute,
            'GeospatialAttribute': self._process_geospatial_attribute,
            'SimpleValueAttribute': self._process_simple_value_attribute,
            'CustomPhysicalRatioAttribute': self._process_custom_physical_ratio_attribute
        }

    def process_instance_attributes(self, attributes: List[Dict]) -> Dict[str, Any]:
        """Process all attributes for a single component instance"""
        processed = {}
        self.curve_meta = {}          # filled by _process_curve_attribute, per instance

        attrs_by_uri = {}
        for attr in attributes:
            attr_uri = attr.get('attribute', {}).get('value', '')
            if attr_uri:
                if attr_uri not in attrs_by_uri:
                    attrs_by_uri[attr_uri] = []
                attrs_by_uri[attr_uri].append(attr)

        for attr_uri, attr_properties in attrs_by_uri.items():
            # FIXED: Better attribute name extraction
            attr_name = self._extract_attribute_name(attr_uri)
            attr_data = self._consolidate_attribute_properties(attr_properties)

            attr_type = self._determine_attribute_type(attr_data)

            if attr_type in self.attribute_type_handlers:
                processed_value = self.attribute_type_handlers[attr_type](attr_data, attr_name)
                if processed_value is not None:
                    processed[attr_name] = processed_value
            else:
                processed[attr_name] = self._process_generic_attribute(attr_data, attr_name)

        # Carry the parsed curves alongside their summaries. The leading underscore
        # keeps these out of the table (get_visible_columns) and out of the CSV.
        for name, meta in self.curve_meta.items():
            processed[f"{CURVE_META_PREFIX}{name}"] = meta

        return processed

    def _extract_attribute_name(self, attr_uri: str) -> str:
        """Extract attribute name from URI - ENHANCED for any namespace"""
        if not attr_uri:
            return 'unknown'

        # Handle the case where attribute URI is like: instance_uri/attribute_name
        # Split by '/' and take the last part
        parts = attr_uri.split('/')
        if len(parts) >= 2:
            attr_name = parts[-1]
            # Clean up common patterns
            if attr_name and not attr_name.startswith('_'):
                return attr_name

        # Fallback to fragment extraction
        return extract_uri_fragment(attr_uri)

    def _consolidate_attribute_properties(self, attr_properties: List[Dict]) -> Dict[str, Any]:
        """Consolidate all properties for a single attribute"""
        consolidated = {
            'properties': {},
            'types': set(),       # local names (used for primary-type detection)
            'type_uris': set()    # full type IRIs (needed to filter by namespace)
        }

        for prop in attr_properties:
            prop_uri = prop.get('property', {}).get('value', '')
            prop_value = prop.get('value', {}).get('value', '')
            prop_name = extract_property_name(prop_uri)

            if prop_name:
                if prop_name == 'type' or 'type' in prop_uri.lower():
                    type_name = extract_uri_fragment(prop_value)
                    consolidated['types'].add(type_name)
                    consolidated['type_uris'].add(prop_value)
                else:
                    consolidated['properties'][prop_name] = prop_value

        return consolidated

    def _determine_attribute_type(self, attr_data: Dict) -> str:
        """Determine the primary attribute type from RDF types"""
        types = attr_data.get('types', set())

        priority_types = [
            'CurveAttribute',
            'DynamicAttribute',
            'CustomPhysicalRatioAttribute',
            'SimpleValueAttribute',
            'UnitBasedCostAttribute',
            'SimpleCostAttribute',
            'GeospatialAttribute',
            'PhysicalAttribute',
            'CategoricalAttribute'
        ]

        for priority_type in priority_types:
            if priority_type in types:
                return priority_type

        return 'unknown'

    def _process_physical_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process PhysicalAttribute with value and unit"""
        props = attr_data.get('properties', {})
        value = props.get('value', '')
        unit = props.get('unit', '')

        if value:
            unit_str = map_unit_uri_to_string(unit) if unit else ''
            return f"{value} {unit_str}".strip()
        return None

    def _process_simple_value_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process SimpleValueAttribute - just a value with no units"""
        props = attr_data.get('properties', {})

        # Look for hasAttributeValue first (the standard property for SimpleValue)
        value = props.get('hasAttributeValue', '')

        # Fallback to 'value' if hasAttributeValue not found
        if not value:
            value = props.get('value', '')

        if value:
            return str(value)
        return None

    def _process_custom_physical_ratio_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process CustomPhysicalRatioAttribute with custom unit ratios"""
        props = attr_data.get('properties', {})
        value = props.get('value', '')
        unit = props.get('unit', '')

        if value:
            if unit:
                unit_str = map_unit_uri_to_string(unit)
                return f"{value} {unit_str}".strip()
            else:
                return str(value)
        return None

    def _process_simple_cost_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process SimpleCostAttribute with value and currency"""
        props = attr_data.get('properties', {})
        value = props.get('value', '')
        currency = props.get('currency', '')

        if value:
            currency_str = map_currency_uri_to_string(currency) if currency else ''
            return f"{value} {currency_str}".strip()
        return None

    def _process_unit_based_cost_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process UnitBasedCostAttribute with value, unit, and currency"""
        props = attr_data.get('properties', {})
        value = props.get('value', '')
        unit = props.get('unit', '')
        currency = props.get('currency', '')

        if value:
            unit_str = map_unit_uri_to_string(unit) if unit else ''
            currency_str = map_currency_uri_to_string(currency) if currency else ''
            return f"{value} {currency_str}/{unit_str}".strip()
        return None

    def _process_categorical_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process CategoricalAttribute -> the chosen category value.

        The value is encoded as an rdf:type of the attribute node, e.g.
        ``<.../BuildingType> a dici_onto:MFH``. The node also carries structural
        types (its own class, CategoricalAttribute, the *Attribute hierarchy) and,
        once RDFS/OWL inference is materialised, rdfs:Resource / owl:Thing. So pick
        the dici_onto type that is NOT a structural attribute class or the
        attribute's own class — filtering by namespace, not just local name (the
        old local-name-only filter let rdfs:Resource through).
        """
        DICI = "https://digicities.info/ontology#"

        candidates = []
        for type_uri in attr_data.get('type_uris', set()):
            if not type_uri.startswith(DICI):
                continue  # skip rdfs:Resource, owl:Thing, owl:NamedIndividual, ...
            local = type_uri[len(DICI):]
            if local.endswith('Attribute') or local == attr_name:
                continue  # structural class or the attribute's own class
            candidates.append(local)

        if candidates:
            # Normally exactly one; sort for determinism if a value carries supers.
            return sorted(candidates)[0]

        return 'Unknown Category'

    def _process_curve_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Summarise a CurveAttribute for the table, and stash the real points.

        The table cell can only hold a short human summary, but the plot needs the
        actual series. Previously only the summary survived, so the visualiser was
        re-parsing "Curve (12 points): kW vs m/s" and could never draw anything.
        The parsed points and units go into ``self.curve_meta``, which the caller
        carries into a hidden ``_curve__<name>`` column.
        """
        props = attr_data.get('properties', {})
        data_points = props.get('hasDataPoints', '')
        if not data_points:
            return None

        x_unit, y_unit = curve_axis_units(props)
        axes = f"{y_unit or '?'} vs {x_unit or '?'}"

        if curve_data_is_reference(data_points):
            self.curve_meta[attr_name] = {
                'points': [], 'x_unit': x_unit, 'y_unit': y_unit,
                'reference': str(data_points).strip(), 'raw': str(data_points),
            }
            return f"Curve (external file): {str(data_points).strip()}"

        points = parse_curve_data(data_points)
        self.curve_meta[attr_name] = {
            'points': points, 'x_unit': x_unit, 'y_unit': y_unit,
            'reference': None, 'raw': str(data_points),
        }
        if points:
            return f"Curve ({len(points)} points): {axes}"
        # Units but nothing parseable — distinct from "no curve here at all", and
        # usually means the source cell used a shape the ingestion regex rejected.
        return f"Curve (no points parsed): {axes}"

    def _process_dynamic_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process DynamicAttribute (time series) - ENHANCED"""
        props = attr_data.get('properties', {})
        unit = props.get('unit', '')

        ts_refs = [
            ('hasLiveTimeSeriesReference', 'Live'),
            ('hasHistoricTimeSeriesReference', 'Historic'),
            ('hasFutureTimeSeriesReference', 'Future'),
            ('hasTimeSeriesReference', 'Generic')
        ]

        for ref_prop, ref_type in ts_refs:
            if ref_prop in props:
                unit_str = map_unit_uri_to_string(unit) if unit else ''
                ref_value = props[ref_prop]
                # FIXED: Better display of time series reference
                ref_display = extract_uri_fragment(str(ref_value)) if ref_value else ref_type
                return f"{ref_type} Time Series: {ref_display} ({unit_str})"

        unit_str = map_unit_uri_to_string(unit) if unit else ''
        return f"Time Series ({unit_str})"

    def _process_geospatial_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Process GeospatialAttribute (same as physical but with location context)"""
        return self._process_physical_attribute(attr_data, attr_name)

    def _process_generic_attribute(self, attr_data: Dict, attr_name: str) -> Optional[str]:
        """Generic attribute processing for unknown types"""
        props = attr_data.get('properties', {})

        # Check for various value properties
        for prop_name in ['hasAttributeValue', 'value', 'hasValue', 'val']:
            if prop_name in props:
                return str(props[prop_name])

        for prop_name, prop_value in props.items():
            if prop_value and str(prop_value).strip():
                return str(prop_value)

        return 'No Value'


def process_enhanced_component_data(component_instances: List[Dict], component_attributes: List[Dict]) -> pd.DataFrame:
    """Process component data with enhanced attribute type handling - FIXED"""
    if not component_instances:
        return pd.DataFrame()

    instances_data = {}

    for instance in component_instances:
        instance_uri = instance.get('instance', {}).get('value', '')
        instance_label = instance.get('instanceLabel', {}).get('value', '') if 'instanceLabel' in instance else ''

        if instance_uri:
            # FIXED: Better instance name extraction
            readable_name = extract_readable_instance_name(instance_uri)
            display_label = instance_label if instance_label else readable_name

            instances_data[instance_uri] = {
                'URI': instance_uri,
                'instance_id': readable_name,
                'label': display_label
            }

    attribute_processor = AttributeProcessor()

    attributes_by_instance = {}
    for attr in component_attributes:
        instance_uri = attr.get('instance', {}).get('value', '')
        if instance_uri not in attributes_by_instance:
            attributes_by_instance[instance_uri] = []
        attributes_by_instance[instance_uri].append(attr)

    for instance_uri, attrs in attributes_by_instance.items():
        if instance_uri in instances_data:
            processed_attrs = attribute_processor.process_instance_attributes(attrs)
            instances_data[instance_uri].update(processed_attrs)

    if not instances_data:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(instances_data, orient='index')
    df.reset_index(drop=True, inplace=True)

    return df


# Provenance rides on the frame the same way curve points do: a hidden column
# get_visible_columns strips, so the table and the CSV stay clean until asked for.
SOURCE_META_COLUMN = '_sources'
SOURCE_COLUMN = 'Source'


def attach_sources(df: pd.DataFrame, sources: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """Attach per-instance provenance to the frame, keyed by the instance URI.

    Adds the hidden metadata column plus a readable ``Source`` summary. Both are
    absent when nothing in the graph has provenance, so a replica built before
    sources were recorded looks exactly as it did.
    """
    if df.empty or not sources or 'URI' not in df.columns:
        return df
    df = df.copy()
    df[SOURCE_META_COLUMN] = df['URI'].map(lambda u: sources.get(u))
    df[SOURCE_COLUMN] = df[SOURCE_META_COLUMN].map(summarize_sources)
    return df


def summarize_sources(entry: Optional[Dict[str, Any]]) -> str:
    """One cell's worth: the record's own source, plus any file that supplied some of
    the row's individual values (e.g. a catalogue file whose spec was copied down).
    Named, not counted — "+1" told the reader nothing; a count only when 3+ files
    would crowd the cell. Which attributes came from where is the per-instance panel's
    job. NB the `derivedFromCatalogue` link in the table is the model-level
    counterpart: it names the catalogue INSTANCE, this column the files."""
    if not entry:
        return ''
    names = [r['label'] for r in entry.get('instance', [])]
    extra = sorted({r['label'] for refs in entry.get('attributes', {}).values() for r in refs}
                   - set(names))
    text = ', '.join(names) if names else '—'
    if extra:
        text += (f" (+ {', '.join(extra)} for some values)" if len(extra) <= 2
                 else f" (+{len(extra)} files for some values)")
    return text


def get_visible_columns(df: pd.DataFrame) -> List[str]:
    """Get columns that should be visible in the table"""
    if df.empty:
        return []

    visible_columns = []

    for col in df.columns.tolist():
        if col in ['URI', 'instance_id', 'label']:
            visible_columns.append(col)
        elif not col.startswith('_'):
            visible_columns.append(col)

    return visible_columns


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================

_PLOT_POINT_LIMIT = 5000        # above this, draw a line only and say so


def curve_columns(df: pd.DataFrame) -> List[str]:
    """Curve attribute columns, identified by the metadata the processor attached.

    Detection used to be a substring match on the column name ('curve', 'profile',
    'datapoints'), which both missed real curves named anything else (Efficiency,
    PowerOutput) and offered non-curves whose name happened to match.
    """
    if df is None or df.empty:
        return []
    return [c[len(CURVE_META_PREFIX):] for c in df.columns
            if c.startswith(CURVE_META_PREFIX)]


def _curve_meta(df: pd.DataFrame, instance_id, curve_column: str) -> Optional[Dict]:
    col = f"{CURVE_META_PREFIX}{curve_column}"
    if col not in df.columns or instance_id not in df.index:
        return None
    meta = df.loc[instance_id, col]
    return meta if isinstance(meta, dict) else None


def visualize_curve(df: pd.DataFrame, instance_id, curve_column: str):
    """Plot one instance's curve, using the points parsed at load time."""
    try:
        meta = _curve_meta(df, instance_id, curve_column)
        if meta is None:
            st.error(f"No curve data recorded for '{curve_column}' on this instance.")
            return

        if meta.get('reference'):
            st.info(f"This curve points at an external file rather than holding its "
                    f"points inline:\n\n`{meta['reference']}`\n\nNothing to plot here — "
                    f"open the data product to see the series.")
            return

        points = meta.get('points') or []
        if not points:
            st.warning("This curve has no plottable points.")
            with st.expander("Show the raw value"):
                st.code(str(meta.get('raw', ''))[:2000])
            st.caption("A curve with units but no points usually means the source cell "
                       "used a number format the ingestion didn't recognise (a space "
                       "after the comma, a negative, or scientific notation).")
            return

        # Points are stored in source order and nothing guarantees ascending x, so an
        # unsorted curve would render as a zigzag. Sort a copy for the line.
        ordered = sorted(points, key=lambda p: p[0])
        x_values = [p[0] for p in ordered]
        y_values = [p[1] for p in ordered]

        x_unit, y_unit = meta.get('x_unit', ''), meta.get('y_unit', '')
        x_label = f"X [{x_unit}]" if x_unit else "X (no unit recorded)"
        y_label = f"{curve_column} [{y_unit}]" if y_unit else f"{curve_column} (no unit recorded)"

        downsampled = len(ordered) > _PLOT_POINT_LIMIT
        if downsampled:
            step = len(ordered) // _PLOT_POINT_LIMIT + 1
            x_plot, y_plot = x_values[::step], y_values[::step]
        else:
            x_plot, y_plot = x_values, y_values

        fig, ax = plt.subplots(figsize=(12, 6))
        if len(ordered) == 1:
            ax.plot(x_plot, y_plot, 'o', markersize=10, color='#1f77b4')
        elif downsampled:
            ax.plot(x_plot, y_plot, '-', linewidth=1.5, color='#1f77b4')
        else:
            ax.plot(x_plot, y_plot, 'o-', linewidth=2, markersize=4, color='#1f77b4')

        ax.set_title(f"{curve_column} — {instance_id}", fontsize=14, fontweight='bold')
        ax.set_xlabel(x_label, fontsize=12)
        ax.set_ylabel(y_label, fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=10)

        note = f'Points: {len(ordered)}' + (f' (showing {len(x_plot)})' if downsampled else '')
        ax.text(0.02, 0.98, note, transform=ax.transAxes, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)                       # Streamlit reruns leak figures otherwise

        if len(ordered) == 1:
            st.caption("A single point — there is no curve to draw through it.")
        if not x_unit or not y_unit:
            missing = " and ".join(a for a, u in (("X", x_unit), ("Y", y_unit)) if not u)
            st.caption(f"No {missing} unit recorded for this curve. That is expected for a "
                       f"dimensionless axis (a coefficient or ratio); otherwise the unit is "
                       f"missing from the source data.")

        with st.expander("📊 Curve statistics"):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Data points", len(ordered))
            col2.metric(f"X range{f' [{x_unit}]' if x_unit else ''}",
                        f"{min(x_values):g} – {max(x_values):g}")
            col3.metric(f"Y range{f' [{y_unit}]' if y_unit else ''}",
                        f"{min(y_values):g} – {max(y_values):g}")
            col4.metric("Y mean", f"{np.mean(y_values):g}")
            st.dataframe(pd.DataFrame(ordered, columns=[x_label, y_label]),
                         use_container_width=True, height=240)

    except Exception as e:
        st.error(f"Error visualizing curve: {e}")


# How a Reference's recorded location is resolved to something viewable. Each entry
# is (predicate, opener) and they are tried in order, so a new kind of source is a
# new opener rather than a change to the viewer. `hasReferenceType` on the Reference
# says which kind it is; the openers below decide whether they can actually fetch it.
# Extensions we will not print into the page — a spreadsheet or an archive rendered
# as text is noise. They are offered for download instead.
_BINARY_SUFFIXES = ('.xlsx', '.xlsm', '.xls', '.zip', '.parquet', '.png', '.jpg', '.pdf')

# Where a bare relative path might live inside a workspace. The recorded location is
# relative to whatever produced it, so try the canonical data directories too.
_WORKSPACE_PREFIXES = ('', 'ingestion/input/', 'ingestion/output/', 'private_data_products/',
                       'timeseries/', 'docs/')


def _resolve_workspace_file(ref: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """A path inside the current workspace's storage -> (path, text), or None."""
    path = (ref.get('url') or '').strip()
    if not path or path.startswith(('http://', 'https://')):
        return None
    storage = getattr(st.session_state.get('workspace_context'), 'storage', None)
    if storage is None:
        return None
    for prefix in _WORKSPACE_PREFIXES:
        candidate = f"{prefix}{path}"
        try:
            if not storage.exists(candidate) or storage.isdir(candidate):
                continue
            if candidate.lower().endswith(_BINARY_SUFFIXES):
                return candidate, ''          # found, but not printable
            return candidate, storage.read_text(candidate)
        except Exception:
            continue
    return None


SOURCE_OPENERS = (_resolve_workspace_file,)


def open_source(ref: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """First opener that can fetch this source's content, else None."""
    for opener in SOURCE_OPENERS:
        try:
            found = opener(ref)
        except Exception:
            found = None
        if found:
            return found
    return None


def _render_source(ref: Dict[str, Any], key: str):
    """One source: what it is, where it is, and its content if we can reach it."""
    bits = [f"**{ref['label']}**"]
    if ref.get('type'):
        bits.append(f"`{ref['type']}`")
    st.markdown(' · '.join(bits))
    if ref.get('url'):
        st.caption(f"📍 {ref['url']}")
    if ref.get('date'):
        st.caption(f"🗓 accessed {ref['date']}")
    if ref.get('comment'):
        st.caption(ref['comment'])

    if st.button("📄 View source data", key=f"view_source_{key}"):
        found = open_source(ref)
        if found and found[1]:
            name, text = found
            st.caption(f"`{name}`")
            st.code(text[:20000], language=None)
            if len(text) > 20000:
                st.caption(f"…truncated, {len(text):,} characters in total")
        elif found:
            st.info(f"`{found[0]}` is in this workspace but isn't a text file — open it "
                    f"from the workspace rather than here.")
        else:
            # Not a failure: an onboarded working folder or an external dataset is
            # not in the workspace, so the recorded location is all there is.
            st.info(f"This source isn't stored in the workspace, so there's nothing to "
                    f"open here. It is recorded as **{ref.get('type') or 'a source'}** at "
                    f"`{ref.get('url') or ref['label']}`.")


def display_source_data(df: pd.DataFrame, filtered_df: pd.DataFrame):
    """Per-instance provenance: where the record came from, and where any single
    value came from when that differs from the record."""
    with st.expander("🔎 Data sources", expanded=False):
        options = [i for i in filtered_df.index.tolist()
                   if isinstance(df.loc[i, SOURCE_META_COLUMN], dict)]
        if not options:
            st.info("None of the instances shown record a source.")
            return

        def _label(idx):
            for col in ('instance_id', 'label'):
                if col in df.columns and isinstance(df.loc[idx, col], str) and df.loc[idx, col]:
                    return df.loc[idx, col]
            return str(idx)

        selected = st.selectbox("Instance", options, format_func=_label,
                                key="source_instance_selector")
        entry = df.loc[selected, SOURCE_META_COLUMN]

        st.markdown("**This record came from**")
        if entry.get('instance'):
            for n, ref in enumerate(entry['instance']):
                _render_source(ref, f"{selected}_inst_{n}")
        else:
            st.caption("No source recorded for the record as a whole.")

        if entry.get('attributes'):
            st.markdown("**Individual values that came from somewhere else**")
            st.caption("An attribute appears here when its own source differs from the "
                       "record's — for example a specification copied down from a "
                       "catalogue entry held in another file.")
            rows = [{'Attribute': attr,
                     'Source': ', '.join(r['label'] for r in refs),
                     'Location': ', '.join(r['url'] for r in refs if r.get('url'))}
                    for attr, refs in sorted(entry['attributes'].items())]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def display_data_table(df: pd.DataFrame, component_type: str):
    """Enhanced data table display with better attribute handling"""
    if df.empty:
        st.info(f"No data found for {component_type}")
        return

    visible_columns = get_visible_columns(df)
    display_df = df[visible_columns] if visible_columns else df

    # Search functionality
    search_term = st.text_input("🔍 Search in table:", "")

    if search_term:
        mask = display_df.astype(str).apply(lambda x: x.str.contains(search_term, case=False)).any(axis=1)
        filtered_df = display_df[mask]
    else:
        filtered_df = display_df

    st.write(f"📊 Showing {len(filtered_df)} instances of {component_type}")

    # Identified from the attached metadata, not from the column name.
    curve_cols = [c for c in curve_columns(df) if c in filtered_df.columns]
    has_sources = SOURCE_META_COLUMN in df.columns

    toggles = st.columns(2)
    show_curves = toggles[0].checkbox("Show curve data in table", value=False)
    show_sources = toggles[1].checkbox(
        "Show data sources", value=False, disabled=not has_sources,
        help="Where each instance came from — the file, data product or dataset it was "
             "read from. Off by default so the table stays about the data itself."
        if has_sources else
        "This replica records no sources. They are written when a workspace is "
        "populated by the onboarding agent, or when a workbook cites its Reference sheet.")

    table_df = filtered_df
    if not show_curves and curve_cols:
        table_df = table_df.drop(columns=curve_cols)
        st.info(f"Hiding {len(curve_cols)} curve data columns. Enable 'Show curve data' to display them.")
    if not show_sources and SOURCE_COLUMN in table_df.columns:
        table_df = table_df.drop(columns=[SOURCE_COLUMN])

    table_event = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"explorer_table_{component_type}",
    )

    # Inspect the selected instance in the Query Manager. The selection is
    # positional within table_df; the URI lives in the full df's hidden columns,
    # reachable because every derived frame shares the original index.
    selected_rows = getattr(getattr(table_event, "selection", None), "rows", None) or []
    if selected_rows and "URI" in df.columns:
        row_idx = table_df.index[selected_rows[0]]
        uri = df.loc[row_idx, "URI"]
        label = next((df.loc[row_idx, c] for c in ("instance_id", "label")
                      if c in df.columns and isinstance(df.loc[row_idx, c], str)
                      and df.loc[row_idx, c]), None)
        if isinstance(uri, str) and uri:
            display = label or uri.rsplit("/", 1)[-1]
            if st.button(f"🔍 Inspect '{display}' in the Query Manager",
                         help="Open the Query Manager with recommended queries "
                              "about this instance — its links, attributes, class "
                              "relatives, catalogue derivation and data sources."):
                st.session_state.inspected_instance = {
                    "uri": uri, "label": display, "component_type": component_type,
                }
                st.session_state.pending_module_switch = "Query Manager"
                # Arrive with the overview query already in the editor.
                try:
                    from backend.graphdb.queries import recommended_queries
                    st.session_state.pending_query_text = \
                        recommended_queries(uri)[0]["sparql"]
                except Exception:
                    pass
                st.rerun()

    # Download functionality
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"{component_type}_data_{timestamp}.csv",
        mime="text/csv",
        key='download_button'
    )

    # Where the data came from
    if has_sources and show_sources:
        display_source_data(df, filtered_df)

    # Curve visualization
    if curve_cols:
        with st.expander("📈 Curve Visualization", expanded=False):
            st.subheader("Visualize Curve Data")

            instance_options = filtered_df.index.tolist()
            if not instance_options:
                st.warning("No instances available to visualize")
                return

            # The index is positional after reset_index, so show the instance's name
            # and map back — a list of integers told the user nothing.
            def _instance_label(idx):
                for col in ('instance_id', 'label'):
                    if col in df.columns:
                        val = df.loc[idx, col]
                        if isinstance(val, str) and val:
                            return f"{val}"
                return str(idx)

            selected_instance = st.selectbox(
                "Select Instance",
                instance_options,
                format_func=_instance_label,
                key="viz_instance_selector"
            )

            selected_curve = st.selectbox(
                "Select Curve",
                curve_cols,
                key="viz_curve_selector"
            )

            # `df`, not `filtered_df`: the parsed points live in hidden columns that
            # get_visible_columns strips out of the display frame.
            if st.button("📊 Generate Visualization"):
                with st.spinner("Generating curve visualization..."):
                    visualize_curve(df, selected_instance, selected_curve)


# =============================================================================
# DEBUG FUNCTIONS - ADDED
# =============================================================================

def debug_component_structure(client):
    """Debug query to understand the component structure"""
    query = f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

    SELECT DISTINCT ?instance ?type ?label ?hasAttribute
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance a ?type .
      ?type rdfs:subClassOf* dici_onto:Component .
      OPTIONAL {{ ?instance rdfs:label ?label }}
      OPTIONAL {{
        ?instance ?attrPredicate ?hasAttribute .
        ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      }}
    }}
    ORDER BY ?type ?instance
    LIMIT 50
    """

    try:
        result = client.sparql_api_query(query, out_format="df")
        if result is not None and not result.empty:
            st.write("### 🔧 Component Structure Debug")
            st.dataframe(result)

            # Show summary
            types_count = result['type'].nunique() if 'type' in result.columns else 0
            instances_count = result['instance'].nunique() if 'instance' in result.columns else 0
            st.write(f"**Found:** {types_count} component types, {instances_count} instances")

        return result
    except Exception as e:
        st.error(f"Debug query failed: {e}")
        return None


def debug_attribute_structure(client, component_type_label: str):
    """Debug query to understand attribute structure for a specific component type"""
    query = f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT DISTINCT ?instance ?attribute ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
      ?instance ?attrPredicate ?attribute .
      ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?attribute ?property ?value .
    }}
    ORDER BY ?instance ?attribute ?property
    LIMIT 100
    """

    try:
        result = client.sparql_api_query(query, out_format="df")
        if result is not None and not result.empty:
            st.write(f"### 🔧 Attribute Structure Debug for {component_type_label}")
            st.dataframe(result)

            # Show summary
            instances_count = result['instance'].nunique() if 'instance' in result.columns else 0
            attributes_count = result['attribute'].nunique() if 'attribute' in result.columns else 0
            st.write(f"**Found:** {instances_count} instances, {attributes_count} attributes")

        return result
    except Exception as e:
        st.error(f"Debug query failed: {e}")
        return None


# =============================================================================
# MAIN COMPONENT EXPLORER FUNCTION - ENHANCED
# =============================================================================

def component_explorer(client):
    """Enhanced Component Explorer main function - FIXED VERSION"""
    st.header("🔍 Digital Replica Explorer")
    st.write("Browse and visualize component instances and their attribute values from your Digital Replica")

    if not client:
        st.error("❌ No Triplestore client available")
        return

    # Debug section - ENHANCED
    with st.expander("🛠 Debug Information", expanded=False):
        st.markdown("**Triplestore Client Status:**")
        if client:
            st.success(f"✅ Connected to repository: {getattr(client, 'selected_repo', 'Unknown')}")
            st.write(f"**Base URL:** {getattr(client, 'base_url', 'Unknown')}")
            st.write(f"**Auth Mode:** {getattr(client, 'auth_mode', 'Unknown')}")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔧 Test Connection"):
                try:
                    test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
                    result = client.sparql_api_query(test_query, out_format="response")
                    if result and result.status_code == 200:
                        st.success("✅ Connection test successful")
                    else:
                        st.error("❌ Connection test failed")
                except Exception as e:
                    st.error(f"❌ Connection test failed: {str(e)}")

        with col2:
            if st.button("🔍 Debug Component Structure"):
                debug_component_structure(client)

    # Get component types and create dropdown
    with st.spinner("Loading component types with instances..."):
        try:
            component_types_df = get_component_types_with_instances(client)

            if component_types_df.empty:
                st.warning("⚠️ No component types with instances found in the knowledge graph")
                st.info("💡 This could mean:")
                st.markdown("- No component instances are loaded in this repository")
                st.markdown("- The ontology structure is different than expected")
                st.markdown("- The component instances are not properly typed")

                if st.button("🔧 Debug All Types"):
                    debug_query = """
                    SELECT DISTINCT ?type (COUNT(?instance) as ?count) WHERE {
                        ?instance a ?type .
                    }
                    GROUP BY ?type
                    ORDER BY DESC(?count)
                    LIMIT 20
                    """
                    try:
                        debug_result = client.sparql_api_query(debug_query, out_format="df")
                        if debug_result is not None and not debug_result.empty:
                            st.write("**Found these types in the knowledge graph:**")
                            st.dataframe(debug_result)
                        else:
                            st.write("No types found in the knowledge graph")
                    except Exception as e:
                        st.error(f"Debug query failed: {e}")
                return

            st.success(f"✅ Found {len(component_types_df)} component types with instances")

            # Component selection
            def format_component_option(idx):
                row = component_types_df.iloc[idx]
                return f"{row['componentName']} ({row['instanceCount']} instances)"

            selected_idx = st.selectbox(
                "Select a Component Type:",
                options=range(len(component_types_df)),
                format_func=format_component_option,
                key='component_selector'
            )

            selected_component = component_types_df.iloc[selected_idx]['componentName']
            instance_count = component_types_df.iloc[selected_idx]['instanceCount']

        except Exception as e:
            st.error(f"❌ Error loading component types: {str(e)}")
            import traceback
            with st.expander("🔍 Error Details"):
                st.code(traceback.format_exc())
            return

    # Main content area
    if selected_component:
        st.markdown(f"### 📊 Data for: **{selected_component}**")
        st.caption(f"Found {instance_count} instances of this component type")

        # Add debug option for this specific component type
        if st.button(f"🔧 Debug {selected_component} Attributes"):
            debug_attribute_structure(client, selected_component)

        with st.spinner(f"Loading {selected_component} data..."):
            try:
                component_instances, component_attributes = get_component_data_unified(client, selected_component)

                if component_instances and component_attributes:
                    df = process_enhanced_component_data(component_instances, component_attributes)
                    # Provenance is a separate, optional query: a replica with no
                    # sources recorded must look exactly as it did before.
                    df = attach_sources(df, get_component_sources(client, selected_component))

                    if not df.empty:
                        # FIXED: Better indexing for display
                        if 'instance_id' in df.columns:
                            df.index = df['instance_id']
                        elif 'URI' in df.columns:
                            df.index = df['URI'].apply(lambda x: extract_readable_instance_name(x) if x else '')

                        display_data_table(df, selected_component)
                    else:
                        st.error("❌ Failed to process component data into table format")
                        st.info("💡 Try using the debug options above to understand the data structure")

                elif component_instances and not component_attributes:
                    st.warning(f"Found {len(component_instances)} instances but no attributes")
                    st.info("This might mean the instances don't have linked attributes or use a different attribute pattern")

                    # Show the instances we found
                    if st.checkbox("Show found instances"):
                        instances_df = pd.DataFrame([
                            {
                                'URI': inst.get('instance', {}).get('value', ''),
                                'Instance ID': extract_readable_instance_name(inst.get('instance', {}).get('value', '')),
                                'Label': inst.get('instanceLabel', {}).get('value', '') if 'instanceLabel' in inst else ''
                            }
                            for inst in component_instances
                        ])
                        st.dataframe(instances_df)

                else:
                    st.error(f"❌ No data found for {selected_component}")

            except Exception as e:
                st.error(f"❌ Error loading component data: {str(e)}")
                import traceback
                with st.expander("🔍 Error Details"):
                    st.code(traceback.format_exc())

        # Footer information
        with st.expander("ℹ️ About Enhanced Component Explorer"):
            st.markdown("""
            **Enhanced Component Explorer** explores actual component instances and their attributes from your knowledge graph.
            
            **FIXED Features:**
            - **Universal Namespace Support**: Works with any URI namespace pattern (e.g., `http://ait.ac.at/NMS_Enkplatz#`)
            - **Smart URI Processing**: Automatically extracts meaningful names from any URI format
            - **Generic Component Detection**: Finds any component type without hard-coding names
            - **Enhanced Debugging**: Built-in tools to understand your data structure
            
            **Supported Attribute Types:**
            - **Physical Attributes**: Value + unit (e.g., "67.0 Wh")
            - **Cost Attributes**: Value + currency (e.g., "40.0 CHF")
            - **Unit-Based Cost**: Value + unit + currency (e.g., "3.0 CHF/kWh")
            - **Categorical**: Category values (e.g., "Crystalline")
            - **Curve Data**: X/Y data points for plotting
            - **Dynamic/Time Series**: Live, historic, or future data references
            - **Geospatial**: Location-based attributes
            - **SimpleValue**: Basic value without units (e.g., "4.0")
            - **CustomPhysicalRatio**: Custom unit ratios (e.g., "5.0 kg/kW")
            
            **How it works:**
            1. Automatically discovers all component types in your knowledge graph
            2. Extracts readable names from any URI format
            3. Processes attributes based on their semantic types
            4. Displays data in an intuitive table format
            """)