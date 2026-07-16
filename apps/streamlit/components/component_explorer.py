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


def parse_curve_data(curve_data_str: str) -> List[Tuple[float, float]]:
    """Parse curve data from string format to list of points"""
    if not curve_data_str:
        return []

    try:
        cleaned = re.sub(r'\s+', ' ', curve_data_str.strip())

        if cleaned.startswith('[') and cleaned.endswith(']'):
            try:
                points = ast.literal_eval(cleaned)
                if isinstance(points, list) and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in points):
                    return [(float(p[0]), float(p[1])) for p in points]
            except:
                pass

        try:
            points = json.loads(cleaned)
            if isinstance(points, list) and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in points):
                return [(float(p[0]), float(p[1])) for p in points]
        except:
            pass

        point_pattern = r'\[\s*([0-9.-]+)\s*,\s*([0-9.-]+)\s*\]'
        matches = re.findall(point_pattern, cleaned)
        if matches:
            return [(float(x), float(y)) for x, y in matches]

    except Exception as e:
        print(f"Error parsing curve data: {e}")

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
        """Process CurveAttribute with data points"""
        props = attr_data.get('properties', {})
        data_points = props.get('hasDataPoints', '')
        x_unit = props.get('xUnit', '')
        y_unit = props.get('yUnit', '')

        if data_points:
            x_unit_str = map_unit_uri_to_string(x_unit) if x_unit else ''
            y_unit_str = map_unit_uri_to_string(y_unit) if y_unit else ''

            try:
                points = parse_curve_data(data_points)
                if points:
                    return f"Curve ({len(points)} points): {y_unit_str} vs {x_unit_str}"
            except:
                pass

            return f"Curve Data: {y_unit_str} vs {x_unit_str}"
        return None

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

def visualize_curve(df: pd.DataFrame, instance_id: str, curve_column: str):
    """Enhanced curve visualization with better parsing and display"""
    try:
        if instance_id not in df.index:
            st.error(f"Instance {instance_id} not found in data")
            return

        curve_data_str = df.loc[instance_id, curve_column]

        if pd.isna(curve_data_str) or curve_data_str == '':
            st.error("No curve data available for this instance")
            return

        curve_data = parse_curve_data(str(curve_data_str))

        if not curve_data:
            st.error("Could not parse curve data")
            st.text("Raw data:")
            st.code(str(curve_data_str)[:500])
            return

        x_values = [point[0] for point in curve_data]
        y_values = [point[1] for point in curve_data]

        fig, ax = plt.subplots(figsize=(12, 8))
        ax.plot(x_values, y_values, 'o-', linewidth=2, markersize=4, color='#1f77b4')

        ax.set_title(f"Curve Data: {curve_column} for {instance_id}", fontsize=14, fontweight='bold')

        if 'vs' in curve_column.lower():
            parts = curve_column.split('vs')
            if len(parts) == 2:
                y_label = parts[0].strip()
                x_label = parts[1].strip()
                ax.set_xlabel(x_label, fontsize=12)
                ax.set_ylabel(y_label, fontsize=12)
            else:
                ax.set_xlabel("X Values", fontsize=12)
                ax.set_ylabel("Y Values", fontsize=12)
        else:
            ax.set_xlabel("X Values", fontsize=12)
            ax.set_ylabel("Y Values", fontsize=12)

        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=10)

        ax.text(0.02, 0.98, f'Points: {len(curve_data)}', transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.tight_layout()
        st.pyplot(fig)

        with st.expander("📊 Curve Statistics"):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Data Points", len(curve_data))
            with col2:
                st.metric("X Range", f"{min(x_values):.2f} - {max(x_values):.2f}")
            with col3:
                st.metric("Y Range", f"{min(y_values):.2f} - {max(y_values):.2f}")
            with col4:
                y_mean = np.mean(y_values)
                st.metric("Y Mean", f"{y_mean:.2f}")

    except Exception as e:
        st.error(f"Error visualizing curve: {str(e)}")


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

    curve_cols = [col for col in filtered_df.columns
                 if any(curve_name in col.lower() for curve_name in ['curve', 'profile', 'datapoints'])]

    show_curves = st.checkbox("Show curve data in table", value=False)

    if not show_curves and curve_cols:
        table_df = filtered_df.drop(columns=curve_cols)
        st.info(f"Hiding {len(curve_cols)} curve data columns. Enable 'Show curve data' to display them.")
    else:
        table_df = filtered_df

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True
    )

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

    # Curve visualization
    if curve_cols:
        with st.expander("📈 Curve Visualization", expanded=False):
            st.subheader("Visualize Curve Data")

            instance_options = filtered_df.index.tolist()
            if not instance_options:
                st.warning("No instances available to visualize")
                return

            selected_instance = st.selectbox(
                "Select Instance",
                instance_options,
                key="viz_instance_selector"
            )

            selected_curve = st.selectbox(
                "Select Curve",
                curve_cols,
                key="viz_curve_selector"
            )

            if st.button("📊 Generate Visualization"):
                with st.spinner("Generating curve visualization..."):
                    visualize_curve(filtered_df, selected_instance, selected_curve)


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