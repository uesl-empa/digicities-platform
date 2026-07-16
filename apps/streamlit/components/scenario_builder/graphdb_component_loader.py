# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/graphdb_component_loader.py
"""
GraphDB Component Loader for Scenario Builder - FIXED VERSION
- Fixed SPARQL UNION syntax error
- Added user choice for data source (GraphDB vs TTL)
"""
import streamlit as st
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
from datetime import datetime

from backend.graphdb import queries as gdb_queries
from backend.graphdb.queries.components import ATTRIBUTE_KIND_CLASSES

# Attribute kind classes, for the rare fallback when the ontology kind lookup
# can't run (the primary path resolves kinds semantically via subClassOf*).
_KIND_CLASS_NAMES = set(ATTRIBUTE_KIND_CLASSES)

# Import GraphDB client
try:
    from components.graphdb import GraphDBClient, get_or_refresh_graphdb_client

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False


class GraphDBComponentLoader:
    """Load components from the workspace knowledge graph.

    The graph is the sole source of truth. The whole workspace is pulled in a
    fixed number of bulk, semantic SPARQL queries (subClassOf*/subPropertyOf*)
    and served from a per-type in-memory index — no per-instance round-trips and
    no TTL files.
    """

    def __init__(self, workspace_id: str = None):
        """Initialize loader with workspace context.

        The knowledge graph is the sole source of truth: this loader pulls the
        whole workspace in a fixed number of bulk SPARQL queries (independent of
        instance count) and serves a per-type index from memory. No TTL files.
        """
        self.workspace_id = workspace_id or st.session_state.get('current_workspace', {}).get('id')
        self.client = None
        self._index = None  # {component_type_local: [component_dict, ...]}
        self._attr_kind_cache = None  # {attribute_uri: kind class local name}
        self._cache_timestamp = None
        self._cache_ttl = 300  # 5 minutes cache

        if GRAPHDB_AVAILABLE and self.workspace_id:
            try:
                self.client = get_or_refresh_graphdb_client(self.workspace_id)
            except Exception as e:
                st.warning(f"Triplestore connection failed: {e}")
                self.client = None

    def is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if not self._cache_timestamp:
            return False

        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self._cache_ttl

    def clear_cache(self):
        """Clear all caches"""
        self._index = None
        self._attr_kind_cache = None
        self._cache_timestamp = None

    def _get_attribute_kind_map(self) -> Dict[str, str]:
        """{attribute_uri: kind class local name} resolved semantically via the
        ontology hierarchy (rdfs:subClassOf* onto a kind class), so an attribute's
        editor kind is determined by the ontology rather than by matching class
        names. Cached per loader; empty dict if unavailable."""
        if self._attr_kind_cache is not None:
            return self._attr_kind_cache
        mapping: Dict[str, str] = {}
        if self.client is not None:
            try:
                df = gdb_queries.get_attribute_kinds(self.client)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        mapping[str(row['attribute'])] = self._extract_fragment(str(row['kind']))
            except Exception as e:
                st.warning(f"Could not resolve attribute kinds from the ontology: {e}")
        self._attr_kind_cache = mapping
        return mapping

    def get_component_types(self) -> List[str]:
        """Component types that have instances (most specific / leaf types)."""
        return sorted(self._build_index().keys())

    def get_components_by_type(self, component_type: str) -> List[Dict]:
        """All components of a specific type, from the bulk-loaded index."""
        return self._build_index().get(component_type, [])

    def _build_index(self) -> Dict[str, List[Dict]]:
        """Load the whole workspace in a fixed number of bulk SPARQL queries and
        build a {component_type: [component_dict]} index. Cached for cache_ttl.

        Queries (all semantic, independent of instance count):
          - get_all_component_instances     instances + most specific type + label
          - get_all_attribute_values        every (instance, attribute, prop, value)
          - get_all_instance_direct_properties  annotation-style direct properties
          - get_attribute_kinds (via _get_attribute_kind_map)  editor kind per attribute
        """
        if self._index is not None and self.is_cache_valid():
            return self._index

        index: Dict[str, List[Dict]] = {}
        if not self.client:
            self._index = index
            return index

        try:
            instances_df = gdb_queries.get_all_component_instances(self.client)
            values_df = gdb_queries.get_all_attribute_values(self.client)
            direct_df = gdb_queries.get_all_instance_direct_properties(self.client)
            kind_map = self._get_attribute_kind_map()
        except Exception as e:
            st.warning(f"Error loading components from the knowledge graph: {e}")
            self._index = index
            return index

        # Group attribute values / direct properties by instance once.
        values_by_instance = {}
        if values_df is not None and not values_df.empty:
            for instance_uri, sub in values_df.groupby('instance'):
                values_by_instance[instance_uri] = sub
        direct_by_instance = {}
        if direct_df is not None and not direct_df.empty:
            for instance_uri, sub in direct_df.groupby('instance'):
                direct_by_instance[instance_uri] = sub

        if instances_df is not None and not instances_df.empty:
            for _, row in instances_df.iterrows():
                instance_uri = row['instance']
                component_type = self._extract_type_name(str(row['type']))
                label = row['label'] if isinstance(row.get('label'), str) and row['label'] \
                    else self._extract_fragment(instance_uri)
                component = self._build_component(
                    instance_uri, label, component_type,
                    values_by_instance.get(instance_uri),
                    direct_by_instance.get(instance_uri),
                    kind_map,
                )
                index.setdefault(component_type, []).append(component)

        # Stable display order within each type.
        for comps in index.values():
            comps.sort(key=lambda c: c.get('label') or c.get('uri', ''))

        self._index = index
        self._cache_timestamp = datetime.now()
        return index

    def _build_component(self, instance_uri: str, label: str, component_type: str,
                         attr_rows, direct_rows, kind_map: Dict[str, str]) -> Dict:
        """Assemble one component dict from the pre-fetched bulk rows. Same shape
        the per-instance path used (uri/label/type/attributes/nested_properties),
        reusing _process_attribute_data / _extract_nested_properties for values."""
        attributes: Dict[str, Any] = {}
        nested_properties: Dict[str, Any] = {}

        if attr_rows is not None and not attr_rows.empty:
            for attr_uri in attr_rows['attribute'].dropna().unique():
                attr_data = attr_rows[attr_rows['attribute'] == attr_uri]
                attr_name = self._extract_fragment(attr_uri)
                attr_dict = self._process_attribute_data(attr_data, kind_map.get(str(attr_uri)))
                if attr_dict:
                    attributes[attr_name] = attr_dict
                    nested = self._extract_nested_properties(attr_data)
                    if nested:
                        nested_properties[attr_name] = nested

        if direct_rows is not None and not direct_rows.empty:
            for _, row in direct_rows.iterrows():
                prop_name = self._extract_property_name(row['property'])
                # label is exposed top-level; keep only free-text annotations here.
                if prop_name in ['comment', 'description']:
                    attributes[prop_name] = {
                        'value': row['value'],
                        'unit': 'text',
                        'attribute_type': 'annotation',
                        'category': 'annotation',
                    }

        return {
            'uri': instance_uri,
            'label': label,
            'uri_fragment': self._extract_fragment(instance_uri),
            'type': component_type,
            'source': 'knowledge_graph',
            'workspace_id': self.workspace_id,
            'attributes': attributes,
            'nested_properties': nested_properties,
        }

    def _process_attribute_data(self, attr_data: pd.DataFrame,
                                attr_kind: Optional[str] = None) -> Optional[Dict]:
        """Process attribute data from query results.

        ``attr_kind`` is the attribute's kind class (e.g. ``PhysicalAttribute``)
        resolved semantically via the ontology hierarchy. When provided it sets the
        type/category directly; otherwise we fall back to reading an asserted kind
        class off the rdf:type rows.
        """
        attr_dict = {
            'attribute_type': 'unknown',
            'category': 'unknown'
        }

        if attr_kind:
            attr_dict['attribute_type'] = attr_kind
            attr_dict['category'] = self._get_attribute_category(attr_kind)

        # The attribute's own class local name (= last URI segment), to exclude
        # when reading a categorical value off the rdf:type rows.
        _DICI = "https://digicities.info/ontology#"
        attr_local = ""
        if attr_data is not None and not attr_data.empty and 'attribute' in attr_data.columns:
            attr_local = self._extract_fragment(str(attr_data['attribute'].iloc[0]))

        # Extract attribute properties
        for _, row in attr_data.iterrows():
            prop_name = self._extract_property_name(row['property'])
            value = row['value']

            if prop_name == 'type':
                # Fallback only — used when the ontology kind wasn't resolved.
                if not attr_kind:
                    type_name = self._extract_type_name(value)
                    if type_name in _KIND_CLASS_NAMES:
                        attr_dict['attribute_type'] = type_name
                        attr_dict['category'] = self._get_attribute_category(type_name)
                # A categorical value is a dici_onto rdf:type that isn't the
                # attribute's own class or a structural *Attribute class (and, via
                # the namespace check, not the inferred rdfs:Resource/owl:Thing).
                vstr = str(value)
                if vstr.startswith(_DICI) and 'category_value' not in attr_dict:
                    local = vstr[len(_DICI):]
                    if local != attr_local and not local.endswith('Attribute'):
                        attr_dict['category_value'] = local
            elif prop_name == 'value':
                attr_dict['value'] = self._parse_value(value)
            elif prop_name == 'hasAttributeValue':
                attr_dict['value'] = self._parse_value(value)
            elif prop_name == 'unit':
                attr_dict['unit'] = self._extract_unit(value)
            elif prop_name == 'currency':
                attr_dict['currency'] = self._extract_currency(value)
            elif prop_name == 'hasTemporalValue':
                attr_dict['temporal_value'] = value
                attr_dict['value'] = value
                attr_dict['data_type'] = 'temporal'
            elif prop_name == 'hasTemporalPrecision':
                attr_dict['temporal_precision'] = self._extract_fragment(value)
            elif prop_name in ['hasHistoricTimeSeriesReference', 'hasLiveTimeSeriesReference',
                               'hasFutureTimeSeriesReference', 'hasTimeSeriesReference']:
                attr_dict['time_series_reference'] = value
                ts_type = prop_name.replace('has', '').replace('TimeSeriesReference', '')
                attr_dict['time_series_type'] = ts_type.lower()
            elif prop_name == 'hasDataPoints':
                attr_dict['data_points'] = value
                attr_dict['data_type'] = 'curve'
            elif prop_name == 'source':
                attr_dict['datasource'] = value

        # A categorical attribute's value is its category (an rdf:type), not a
        # literal — surface it as the value so the attribute isn't dropped below.
        if attr_dict.get('category') == 'categorical' and 'value' not in attr_dict \
                and 'category_value' in attr_dict:
            attr_dict['value'] = attr_dict['category_value']

        # Set default unit if not present
        if 'value' in attr_dict and 'unit' not in attr_dict:
            if attr_dict.get('category') == 'categorical':
                attr_dict['unit'] = 'category'
            elif attr_dict.get('data_type') == 'temporal':
                attr_dict['unit'] = 'temporal'
            elif attr_dict.get('data_type') == 'curve':
                attr_dict['unit'] = 'data_points'
            else:
                attr_dict['unit'] = 'dimensionless'

        return attr_dict if 'value' in attr_dict or 'temporal_value' in attr_dict or 'data_points' in attr_dict else None

    def _extract_nested_properties(self, attr_data: pd.DataFrame) -> Dict:
        """Extract nested properties like time series references"""
        nested = {}

        for _, row in attr_data.iterrows():
            prop_name = self._extract_property_name(row['property'])

            # Time series related properties
            if 'TimeSeries' in prop_name and 'Reference' not in prop_name:
                nested[prop_name] = row['value']

        return nested

    def _get_attribute_category(self, attr_type: str) -> str:
        """Map attribute type to category"""
        category_mapping = {
            'PhysicalAttribute': 'physical',
            'SimpleCostAttribute': 'cost',
            'UnitBasedCostAttribute': 'cost',
            'CategoricalAttribute': 'categorical',
            'DynamicAttribute': 'dynamic',
            'CurveAttribute': 'curve',
            'GeospatialAttribute': 'geospatial',
            'EventAttribute': 'temporal',
            'SimpleValueAttribute': 'simple',
            'CustomPhysicalRatioAttribute': 'ratio',
            'ResourceAttribute': 'resource'
        }

        return category_mapping.get(attr_type, 'unknown')

    def _extract_fragment(self, uri: str) -> str:
        """Extract the last part of a URI"""
        if '#' in uri:
            return uri.split('#')[-1]
        elif '/' in uri:
            return uri.split('/')[-1]
        return uri

    def _extract_type_name(self, uri: str) -> str:
        """Extract type name from URI"""
        fragment = self._extract_fragment(uri)
        if fragment.startswith('https://') or fragment.startswith('http://'):
            return self._extract_fragment(fragment)
        return fragment

    def _extract_property_name(self, uri: str) -> str:
        """Extract property name from URI"""
        if '#' in uri:
            return uri.split('#')[-1]
        elif '/' in uri:
            return uri.split('/')[-1]
        return uri

    def _extract_unit(self, unit_uri: str) -> str:
        """Extract unit from URI"""
        if '/unit/' in unit_uri:
            return unit_uri.split('/unit/')[-1]
        return self._extract_fragment(unit_uri)

    def _extract_currency(self, currency_uri: str) -> str:
        """Extract currency from URI"""
        if '/currency/' in currency_uri:
            return currency_uri.split('/currency/')[-1]
        return self._extract_fragment(currency_uri)

    def _parse_value(self, value: Any) -> Any:
        """Parse value to appropriate type"""
        if isinstance(value, str):
            # Try to parse as number
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value
        return value

    def get_status(self) -> Dict[str, Any]:
        """Get loader status information"""
        index = self._index if self._index is not None else {}
        status = {
            'mode': 'Knowledge Graph',
            'selected_source': 'GraphDB',
            'workspace_id': self.workspace_id,
            'cache_valid': self.is_cache_valid(),
            'cached_types': len(index),
        }

        if self.client:
            status['graphdb_connected'] = True
            try:
                # Test query to verify connection
                test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
                result = self.client.sparql_api_query(test_query, out_format="response")
                status['graphdb_responsive'] = result is not None and result.status_code == 200
            except Exception:
                status['graphdb_responsive'] = False
        else:
            status['graphdb_connected'] = False
            status['graphdb_responsive'] = False

        return status


# Global functions for integration
def get_graphdb_component_loader() -> Optional[GraphDBComponentLoader]:
    """Get GraphDB component loader for current workspace"""
    current_workspace = st.session_state.get('current_workspace')
    if not current_workspace:
        return None

    workspace_id = current_workspace['id']

    # Don't cache the loader - recreate it to respect user preference changes
    return GraphDBComponentLoader(workspace_id)


def get_scenario_components(component_type: str) -> List[Dict]:
    """Components of a type from the knowledge graph (sole source of truth)."""
    loader = get_graphdb_component_loader()
    return loader.get_components_by_type(component_type) if loader else []


def get_available_component_types() -> List[str]:
    """Component types that have instances, from the knowledge graph."""
    loader = get_graphdb_component_loader()
    return loader.get_component_types() if loader else []


def show_loader_status():
    """Display loader status. The knowledge graph is the only component source."""
    col1, col2 = st.columns([3, 1])

    with col1:
        st.caption("Components are loaded from the workspace knowledge graph.")
    with col2:
        if st.button("🔄 Refresh", help="Clear cache and reload"):
            clear_loader_cache()
            st.rerun()

    loader = get_graphdb_component_loader()
    if not loader:
        st.warning("⚠️ No component loader available")
        return

    status = loader.get_status()
    if status.get('graphdb_responsive'):
        st.success(f"✅ Connected to the knowledge graph ({status['workspace_id']})")
    else:
        st.warning("⚠️ Knowledge graph not responding, check the connection")

    # Show cache info
    if status['cached_types'] > 0:
        st.caption(f"📦 {status['cached_types']} component types cached")


def clear_loader_cache():
    """Clear cached component data so the next load re-queries the graph."""
    keys_to_remove = [
        key for key in list(st.session_state.keys())
        if any(key.startswith(prefix) for prefix in [
            'graphdb_loader_', 'dp_components_', 'component_label_',
        ])
    ]
    for key in keys_to_remove:
        del st.session_state[key]
    # The Streamlit-level @st.cache_data wrapper in scenario_builder_components
    # holds the actual component lists; clear it too.
    try:
        st.cache_data.clear()
    except Exception:
        pass