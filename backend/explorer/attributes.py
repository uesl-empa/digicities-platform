# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Attribute rows into the explorer's display table.

``AttributeProcessor`` knows every attribute shape the platform writes
(physical values with units, costs, categoricals carried as rdf:types, curves,
time-series references) and turns each into a short human-readable cell.
``process_enhanced_component_data`` assembles those cells into one DataFrame
row per instance; parsed curve points ride along in hidden ``_curve__``
columns that ``get_visible_columns`` keeps out of the table and the CSV.
"""

import ast
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.explorer.units import (
    curve_axis_units,
    map_currency_uri_to_string,
    map_unit_uri_to_string,
)
from backend.explorer.uris import (
    extract_property_name,
    extract_readable_instance_name,
    extract_uri_fragment,
)

# Hidden column prefix carrying a curve's parsed points + units next to its
# human-readable summary. Underscore-prefixed columns are filtered out of the
# table by get_visible_columns.
CURVE_META_PREFIX = '_curve__'
SERIES_META_PREFIX = '_series__'

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
        self.series_meta = {}         # filled by _process_dynamic_attribute, per instance

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
        for name, meta in self.series_meta.items():
            processed[f"{SERIES_META_PREFIX}{name}"] = meta

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
                # Stash the reference so the UI can open/plot the data, the
                # same way curve points ride alongside their summary.
                self.series_meta[attr_name] = {
                    'kind': ref_type,
                    'reference': str(ref_value),
                    'unit': unit_str or None,
                }
                # FIXED: Better display of time series reference
                ref_display = extract_uri_fragment(str(ref_value)) if ref_value else ref_type
                if unit_str:
                    return f"{ref_type} Time Series: {ref_display} ({unit_str})"
                return f"{ref_type} Time Series: {ref_display}"

        # No reference means no data for this instance — the cell stays blank,
        # like any other attribute the instance doesn't carry.
        return None

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


_TIME_SERIES_REFS = (
    'hasHistoricTimeSeriesReference',
    'hasLiveTimeSeriesReference',
    'hasFutureTimeSeriesReference',
    'hasTimeSeriesReference',
)

_VALUE_PROPS = ('value', 'hasAttributeValue', 'hasDataPath', 'hasValue', 'hasCurveData')


def structured_instance_attributes(component_attributes: List[Dict]) -> Dict[str, Dict[str, Dict]]:
    """Per-instance attributes in the Scenario Builder / emitter shape.

    The table view (``process_enhanced_component_data``) flattens each attribute
    to a display string; the emitter's requirement resolver
    (``resolve_nested_attribute_requirement``) instead needs
    ``attributes[name] = {value, attribute_type, category_value, temporal_value}``
    plus ``nested_properties[name] = {hasHistoricTimeSeriesReference: ..., ...}``.
    This reuses the same grouping/typing pipeline to produce that shape, keyed
    by instance URI.
    """
    by_instance: Dict[str, List[Dict]] = {}
    for attr in component_attributes or []:
        uri = attr.get('instance', {}).get('value', '')
        if uri:
            by_instance.setdefault(uri, []).append(attr)

    processor = AttributeProcessor()
    out: Dict[str, Dict[str, Dict]] = {}
    for instance_uri, attrs in by_instance.items():
        attributes: Dict[str, Dict] = {}
        nested: Dict[str, Dict] = {}

        attrs_by_uri: Dict[str, List[Dict]] = {}
        for attr in attrs:
            attr_uri = attr.get('attribute', {}).get('value', '')
            if attr_uri:
                attrs_by_uri.setdefault(attr_uri, []).append(attr)

        for attr_uri, attr_properties in attrs_by_uri.items():
            name = processor._extract_attribute_name(attr_uri)
            data = processor._consolidate_attribute_properties(attr_properties)
            props = data.get('properties', {})
            types = data.get('types', set())
            attr_type = processor._determine_attribute_type(data)

            entry: Dict[str, object] = {}
            for value_prop in _VALUE_PROPS:
                if props.get(value_prop) not in (None, ''):
                    entry['value'] = props[value_prop]
                    break
            if 'EventAttribute' in types:
                entry['attribute_type'] = 'EventAttribute'
                if props.get('hasTemporalValue') not in (None, ''):
                    entry['temporal_value'] = props['hasTemporalValue']
                    entry.setdefault('value', props['hasTemporalValue'])
            elif attr_type == 'CategoricalAttribute':
                entry['attribute_type'] = attr_type
                category = processor._process_categorical_attribute(data, name)
                if category and category != 'Unknown Category':
                    entry['category_value'] = category
                    entry.setdefault('value', category)
            elif attr_type != 'unknown':
                entry['attribute_type'] = attr_type

            ts = {ref: props[ref] for ref in _TIME_SERIES_REFS
                  if props.get(ref) not in (None, '')}
            if ts:
                nested[name] = ts
                # A time-series attribute is "present" even without a scalar.
                entry.setdefault('value', next(iter(ts.values())))

            if entry:
                attributes[name] = entry

        out[instance_uri] = {'attributes': attributes, 'nested_properties': nested}
    return out
