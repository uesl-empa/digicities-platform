# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/scenario_builder_components.py
"""
Complete Scenario Builder Components with GraphDB Export Loader
Includes all three loading modes: Direct, Export, and TTL
FIXED: Enhanced nested attribute resolution for GraphDB export patterns
"""
import streamlit as st
import json
import time
import tempfile
import os
import hashlib
import urllib.parse
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# The legacy GraphDB export loader has been retired — components load through the
# unified bulk-semantic loader (graphdb_component_loader). Flag kept False so any
# stray reference degrades gracefully.
EXPORT_LOADER_AVAILABLE = False

# Try to import GraphDB direct loader
try:
    from components.scenario_builder.graphdb_component_loader import (
        get_scenario_components,
        get_available_component_types,
        show_loader_status,
        clear_loader_cache
    )

    GRAPHDB_LOADER_AVAILABLE = True
except ImportError:
    GRAPHDB_LOADER_AVAILABLE = False

# Pure display helpers (no loader dependency).
from components.scenario_builder.component_display_utils import (
    get_uri_fragment,
    format_ttl_component_for_display,
    get_nested_property_from_ttl_component,
)

# The Data Products feature still loads TTL data products through this loader;
# imported here only to clear its cache on refresh.
try:
    from components.scenario_builder.ttl_use_case_loader import get_workspace_ttl_loader

    TTL_LOADER_AVAILABLE = True
except ImportError:
    TTL_LOADER_AVAILABLE = False

# Try to import data loaders
try:
    from components.data_loaders import nextcloud_data_loader

    DATA_LOADER_AVAILABLE = True
except ImportError:
    DATA_LOADER_AVAILABLE = False

# Try to import GraphDB client for export functionality
try:
    from components.graphdb import get_or_refresh_graphdb_client

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False


# ============================================================================
# PERFORMANCE OPTIMIZATION: Cached component loading
# ============================================================================

@st.cache_data(ttl=600, show_spinner=False)  # Cache for 10 minutes
def load_components_cached(component_type: str, mode: str = 'direct',
                           enabled_data_products: tuple = ()) -> tuple:
    """
    CACHED component loading - only loads when inputs change.
    Returns (kg_components, dp_components)

    The knowledge graph is the sole source of truth. Components come from the
    unified bulk-semantic loader (subClassOf*/subPropertyOf*); the legacy export
    and TTL paths are retired. ``mode`` is kept only for cache-key/back-compat.
    """
    # Load from the knowledge graph (single source of truth).
    kg_components = []
    try:
        if GRAPHDB_LOADER_AVAILABLE:
            raw_components = get_scenario_components(component_type)
            for comp in raw_components:
                comp.setdefault('source', 'knowledge_graph')
            kg_components = raw_components
    except Exception:
        pass

    # Load from data products
    dp_components = []
    if enabled_data_products:
        try:
            from components.scenario_builder.data_products_tab import get_enabled_data_products
            data_products = get_enabled_data_products()

            for product_key in enabled_data_products:
                if product_key in data_products:
                    product_data = data_products[product_key]
                    if "components" in product_data and component_type in product_data["components"]:
                        # FIXED: Create a copy of each component and set source fields
                        # This prevents modifying cached objects and ensures proper source tracking
                        for comp in product_data["components"][component_type]:
                            comp_copy = comp.copy()
                            comp_copy['source'] = 'data_products'
                            comp_copy['source_catalog'] = product_key
                            dp_components.append(comp_copy)
        except Exception:
            pass

    return kg_components, dp_components


def show_export_loader_controls():
    """Show the component source status. The knowledge graph is the only source.

    Delegates to show_loader_status, which renders the caption, a single Refresh
    button, and the connection status (avoids a duplicate Refresh button here).
    """
    st.markdown("### 📊 Component Source")

    if GRAPHDB_LOADER_AVAILABLE:
        show_loader_status()
    else:
        st.error("No component loader available")


def get_components_by_type_unified(component_type):
    """Components of a type from the knowledge graph (sole source of truth)."""
    if GRAPHDB_LOADER_AVAILABLE:
        try:
            return get_scenario_components(component_type)
        except Exception as e:
            st.warning(f"Component load failed: {e}")
    return []


@st.dialog("Component Attributes")
def show_component_attributes_dialog(component):
    """Show component attributes in a dialog"""
    st.write(f"### {component['label']}")
    st.caption(f"Type: {component.get('type', 'Unknown')}")
    st.caption(f"URI: `{component['uri']}`")

    if 'source' in component:
        source_labels = {
            'technology_catalog_2025': '⚙️ Technology Catalog 2025',
            'demand_profiles_2024': '📊 Building Demand Profiles 2024',
            'geological_data_2025': '🌍 Swiss Geological Data 2025',
            'ttl_use_case': '📄 TTL Use Case',
            'knowledge_graph': '🔗 Knowledge Graph',
            'data_products': '📊 Data Products'
        }
        source_label = source_labels.get(component['source'], f"❓ {component['source']}")
        st.caption(f"Source: {source_label}")

        if component['source'] in ['ttl_use_case', 'knowledge_graph'] and component.get('workspace_id'):
            current_workspace = st.session_state.get('current_workspace')
            workspace_name = current_workspace['name'] if current_workspace else component['workspace_id']
            st.caption(f"Workspace: {workspace_name}")

    st.markdown("---")
    display_simple_component_attributes(component)

    if component.get('time_series_file'):
        st.markdown("---")
        st.write("**📊 Time Series Data:**")
        st.caption(f"File: `{component['time_series_file']}`")

    if component.get('nested_properties'):
        st.markdown("---")
        st.write("**🔗 Nested Properties:**")
        display_nested_properties_simple(component['nested_properties'])

    if st.button("Close", type="primary"):
        st.rerun()


def display_simple_component_attributes(component):
    """Display component attributes in simplified format"""
    if 'attributes' not in component or not component['attributes']:
        st.info("No attributes available for this component")
        return

    st.write("**Component Attributes:**")

    attributes_data = []
    for attr_name, attr_data in component['attributes'].items():
        if isinstance(attr_data, dict) and attr_data.get('category') == 'system':
            continue

        if isinstance(attr_data, dict) and ('value' in attr_data or 'temporal_value' in attr_data):
            value = attr_data.get('value', attr_data.get('temporal_value'))
            unit = attr_data.get('unit', 'dimensionless')
            attr_type = attr_data.get('attribute_type', 'unknown')

            # Format value based on type
            if attr_data.get('attribute_type') == 'DynamicAttribute':
                formatted_value = "📊 Dynamic data"
                if attr_data.get('time_series_reference'):
                    formatted_value = f"📊 {attr_data['time_series_reference']}"
            elif attr_data.get('attribute_type') == 'CategoricalAttribute':
                category_value = attr_data.get('category_value', value)
                formatted_value = f"🏷️ {category_value}"
            elif attr_data.get('attribute_type') == 'EventAttribute':
                temporal_value = attr_data.get('temporal_value', value)
                temporal_precision = attr_data.get('temporal_precision', 'Unknown')
                formatted_value = f"📅 {temporal_value}"
                if temporal_precision != 'Unknown':
                    formatted_value += f" ({temporal_precision})"
            elif isinstance(value, float):
                formatted_value = f"{value:,.2f}"
            elif isinstance(value, int):
                formatted_value = f"{value:,}"
            else:
                formatted_value = str(value)

            # Format unit
            currency = attr_data.get('currency')
            if currency:
                if unit != 'dimensionless' and unit != currency:
                    formatted_unit = f"{currency}/{unit}"
                else:
                    formatted_unit = currency
            elif unit in ['category', 'data_points', 'temporal']:
                formatted_unit = unit
            elif unit == 'dimensionless':
                formatted_unit = "—"
            else:
                formatted_unit = unit

            attributes_data.append({
                "Attribute": attr_name.replace('_', ' ').title(),
                "Value": formatted_value,
                "Unit": formatted_unit,
                "Type": attr_type
            })

    if attributes_data:
        st.dataframe(attributes_data, use_container_width=True, hide_index=True)


def display_nested_properties_simple(nested_properties):
    """Display nested properties"""
    for attr_name, properties in nested_properties.items():
        st.write(f"**🔗 {attr_name}:**")
        for prop_name, prop_value in properties.items():
            if 'TimeSeries' in prop_name:
                st.code(f"{prop_name}: {prop_value}")
            else:
                st.write(f"  • {prop_name}: {prop_value}")


def get_data_product_components_by_type(component_type):
    """Get components from legacy data products"""
    if not DATA_LOADER_AVAILABLE:
        return []

    if 'enabled_data_products' not in st.session_state:
        return []

    cache_key = f"dp_components_{component_type}_{hash(str(sorted(st.session_state.enabled_data_products)))}"

    if cache_key in st.session_state:
        return st.session_state[cache_key]

    components = []
    try:
        data_products = nextcloud_data_loader.get_data_product_catalogs()

        for product_key in st.session_state.enabled_data_products:
            if product_key in data_products:
                product_data = data_products[product_key]
                if "components" in product_data and component_type in product_data["components"]:
                    for comp in product_data["components"][component_type]:
                        comp['source'] = 'data_products'
                        comp['source_catalog'] = product_key
                    components.extend(product_data["components"][component_type])
    except Exception as e:
        st.warning(f"Error loading data products for {component_type}: {e}")

    st.session_state[cache_key] = components
    return components


def get_ttl_use_case_components_by_type(component_type):
    """Wrapper for unified loader"""
    return get_components_by_type_unified(component_type)


def is_component_in_scenario(component_uri):
    """Check if component is already in scenario"""
    return any(comp['uri'] == component_uri for comp in st.session_state.scenario_components)


def add_component_to_scenario(component, component_type):
    """Add component to scenario"""
    if is_component_in_scenario(component['uri']):
        return False

    base_uri = component['uri']
    existing_count = sum(1 for comp in st.session_state.scenario_components
                         if comp.get('base_uri', comp['uri']) == base_uri)

    if existing_count > 0:
        unique_uri = f"{base_uri}_instance_{existing_count + 1}"
        unique_label = f"{component.get('uri_fragment', component['label'])} (Instance {existing_count + 1})"
    else:
        unique_uri = base_uri
        unique_label = component.get('uri_fragment', component['label'])

    attributes = component.get('attributes', {}).copy()

    attributes['URI'] = {
        'value': unique_uri,
        'unit': 'uri',
        'attribute_type': 'system',
        'category': 'system'
    }

    attributes['label'] = {
        'value': unique_label,
        'unit': 'text',
        'attribute_type': 'system',
        'category': 'system'
    }

    component_data = {
        'uri': unique_uri,
        'base_uri': base_uri,
        'label': unique_label,
        'type': component_type,
        'source': component.get('source', 'unknown'),
        'workspace_id': component.get('workspace_id'),
        'source_catalog': component.get('source_catalog'),
        'attributes': attributes,
        'nested_properties': component.get('nested_properties', {}),
        'instance_declaration': component.get('instance_declaration', ''),
        'time_series_file': component.get('time_series_file', None),
        'original_component': component,
        'uri_fragment': component.get('uri_fragment', unique_label)
    }

    st.session_state.scenario_components.append(component_data)
    create_automatic_scenario_link(component_data)
    # REMOVED: clear_all_component_caches() - too aggressive, kills performance!

    return True


def remove_component_from_scenario(component_uri):
    """Remove component from scenario"""
    removed = None
    new_components = []

    for comp in st.session_state.scenario_components:
        if comp['uri'] == component_uri:
            removed = comp
        else:
            new_components.append(comp)

    st.session_state.scenario_components = new_components

    if removed:
        st.session_state.scenario_links = [
            link for link in st.session_state.scenario_links
            if link.get('source') != component_uri and link.get('target') != component_uri
        ]

    # REMOVED: clear_all_component_caches() - too aggressive, kills performance!
    return removed is not None


def create_automatic_scenario_link(component):
    """Create automatic scenario link"""
    scenario_link = {
        'source': 'scenario',
        'target': component['uri'],
        'link_type': 'scenario_automatic',
        'pattern': f"CL.Scenario.{component['type']}"
    }

    existing = any(
        link.get('pattern') == scenario_link['pattern'] and link['target'] == scenario_link['target']
        for link in st.session_state.scenario_links
    )

    if not existing:
        st.session_state.scenario_links.append(scenario_link)


@st.fragment
def display_component_type_section_no_form(comp_type):
    """Display components with checkboxes (FRAGMENT - no full rerun!)"""
    # Get current state for cache key
    mode = 'graph'  # knowledge graph is the sole source
    enabled_dps = tuple(st.session_state.get('enabled_ttl_data_products', []))

    # OPTIMIZED: Load components with caching
    kg_components, dp_components = load_components_cached(comp_type, mode, enabled_dps)

    kg_source = "Knowledge Graph"

    all_components = dp_components + kg_components

    # Display data products
    if dp_components:
        st.write("**Available from Data Products:**")
        for comp in dp_components:
            # FIXED: Include source in key to avoid duplicates
            checkbox_key = f"select_dp_{comp_type}_{comp['uri']}"
            is_in_scenario = is_component_in_scenario(comp['uri'])

            # Initialize with current scenario state only once
            if checkbox_key not in st.session_state.component_selections:
                st.session_state.component_selections[checkbox_key] = is_in_scenario

            col1, col2, col3 = st.columns([0.5, 3.5, 1])

            with col1:
                # Checkbox manages its own state - no writing on change
                selected = st.checkbox(
                    label="Select",
                    value=st.session_state.component_selections[checkbox_key],
                    key=checkbox_key,
                    label_visibility="collapsed"
                )
                # Update selections dict (doesn't trigger rerun)
                st.session_state.component_selections[checkbox_key] = selected

            with col2:
                source_badge = '📊 DP'
                display_label = comp.get('uri_fragment', comp['label'])
                status = " ✅" if is_in_scenario else ""
                st.write(f"{source_badge} **{display_label}**{status}")

                if comp.get('source_catalog'):
                    st.caption(f"Catalog: {comp['source_catalog']}")
                st.caption(f"URI: `{comp['uri']}`")
                show_component_attribute_summary_simple(comp)

            with col3:
                if comp.get('attributes'):
                    st.caption("👁️ Has attributes")

        if kg_components:
            st.markdown("---")

    # Display knowledge graph components
    if kg_components:
        current_workspace = st.session_state.get('current_workspace')
        workspace_name = current_workspace['name'] if current_workspace else 'Current Workspace'
        st.write(f"**Available from {workspace_name} {kg_source}:**")

        for comp in kg_components:
            # FIXED: Include source in key to avoid duplicates
            checkbox_key = f"select_kg_{comp_type}_{comp['uri']}"
            is_in_scenario = is_component_in_scenario(comp['uri'])

            # Initialize with current scenario state only once
            if checkbox_key not in st.session_state.component_selections:
                st.session_state.component_selections[checkbox_key] = is_in_scenario

            col1, col2, col3 = st.columns([0.5, 3.5, 1])

            with col1:
                # Checkbox manages its own state - no writing on change
                selected = st.checkbox(
                    label="Select",
                    value=st.session_state.component_selections[checkbox_key],
                    key=checkbox_key,
                    label_visibility="collapsed"
                )
                # Update selections dict (doesn't trigger rerun)
                st.session_state.component_selections[checkbox_key] = selected

            with col2:
                if comp.get('source') == 'knowledge_graph':
                    source_badge = '🔗 KG'
                else:
                    source_badge = '📄 TTL'

                display_label = comp.get('uri_fragment', comp['label'])
                status = " ✅" if is_in_scenario else ""
                st.write(f"{source_badge} **{display_label}**{status}")

                if comp.get('workspace_id'):
                    st.caption(f"Workspace: {workspace_name}")
                st.caption(f"URI: `{comp['uri']}`")
                show_component_attribute_summary_simple(comp)

            with col3:
                if comp.get('attributes'):
                    st.caption("👁️ Has attributes")

    # View attributes
    if all_components:
        with st.expander("🔍 View Component Attributes", expanded=False):
            for idx, comp in enumerate(all_components):
                col1, col2 = st.columns([3, 1])
                with col1:
                    source_badge = '📊 DP' if comp in dp_components else ('🔗 KG' if comp.get('source') == 'knowledge_graph' else '📄 TTL')
                    display_label = comp.get('uri_fragment', comp['label'])
                    st.write(f"{source_badge} **{display_label}**")
                with col2:
                    if comp.get('attributes'):
                        uri_hash = hashlib.md5(comp['uri'].encode()).hexdigest()[:8]
                        source_prefix = 'dp' if comp in dp_components else 'kg'
                        if st.button("👁️ View", key=f"view_noform_{comp_type}_{source_prefix}_{idx}_{uri_hash}"):
                            show_component_attributes_dialog(comp)

    # Show summary
    if all_components:
        in_scenario_count = sum(1 for comp in all_components if is_component_in_scenario(comp['uri']))

        # Count selected (checking both dp and kg keys)
        selected_count = 0
        for comp in dp_components:
            if st.session_state.component_selections.get(f"select_dp_{comp_type}_{comp['uri']}", False):
                selected_count += 1
        for comp in kg_components:
            if st.session_state.component_selections.get(f"select_kg_{comp_type}_{comp['uri']}", False):
                selected_count += 1

        st.info(f"📊 In scenario: {in_scenario_count} | Selected: {selected_count} | Total: {len(all_components)}")

    if not dp_components and not kg_components:
        st.info(f"No {comp_type} components available.")


def apply_all_component_changes(component_types: List[str]):
    """Apply all checkbox selections across all component types"""
    added_count = 0
    removed_count = 0

    # Optional debug mode - can be enabled in session state for troubleshooting
    debug_mode = st.session_state.get('component_debug_mode', False)
    debug_log = []

    with st.spinner("Applying changes across all component types..."):
        for comp_type in component_types:
            # Get components for this type
            mode = 'graph'  # knowledge graph is the sole source
            enabled_dps = tuple(st.session_state.get('enabled_ttl_data_products', []))
            kg_components, dp_components = load_components_cached(comp_type, mode, enabled_dps)

            if debug_mode:
                debug_log.append(f"Processing {comp_type}: {len(dp_components)} DP, {len(kg_components)} KG components")

            # Process DP components
            for comp in dp_components:
                checkbox_key = f"select_dp_{comp_type}_{comp['uri']}"
                is_selected = st.session_state.component_selections.get(checkbox_key, False)
                is_in_scenario = is_component_in_scenario(comp['uri'])

                if debug_mode and is_selected:
                    debug_log.append(f"  DP {comp['uri']}: selected={is_selected}, in_scenario={is_in_scenario}, source={comp.get('source', 'MISSING')}")

                if is_selected and not is_in_scenario:
                    if add_component_to_scenario(comp, comp_type):
                        added_count += 1
                        if debug_mode:
                            debug_log.append(f"    ✅ Added DP component: {comp.get('label', comp['uri'])}")
                elif not is_selected and is_in_scenario:
                    if remove_component_from_scenario(comp['uri']):
                        removed_count += 1

            # Process KG components
            for comp in kg_components:
                checkbox_key = f"select_kg_{comp_type}_{comp['uri']}"
                is_selected = st.session_state.component_selections.get(checkbox_key, False)
                is_in_scenario = is_component_in_scenario(comp['uri'])

                if debug_mode and is_selected:
                    debug_log.append(f"  KG {comp['uri']}: selected={is_selected}, in_scenario={is_in_scenario}, source={comp.get('source', 'MISSING')}")

                if is_selected and not is_in_scenario:
                    if add_component_to_scenario(comp, comp_type):
                        added_count += 1
                        if debug_mode:
                            debug_log.append(f"    ✅ Added KG component: {comp.get('label', comp['uri'])}")
                elif not is_selected and is_in_scenario:
                    if remove_component_from_scenario(comp['uri']):
                        removed_count += 1

    # Show debug log if enabled
    if debug_mode and debug_log:
        with st.expander("🐛 Debug Log", expanded=True):
            for line in debug_log:
                st.text(line)

    if added_count or removed_count:
        st.success(f"✅ Added {added_count} | ❌ Removed {removed_count} components")
        st.rerun()
    else:
        st.info("No changes to apply")


def select_all_components(component_types: List[str]):
    """Select all available components across all types"""
    for comp_type in component_types:
        mode = 'graph'  # knowledge graph is the sole source
        enabled_dps = tuple(st.session_state.get('enabled_ttl_data_products', []))
        kg_components, dp_components = load_components_cached(comp_type, mode, enabled_dps)

        for comp in dp_components:
            checkbox_key = f"select_dp_{comp_type}_{comp['uri']}"
            st.session_state.component_selections[checkbox_key] = True

        for comp in kg_components:
            checkbox_key = f"select_kg_{comp_type}_{comp['uri']}"
            st.session_state.component_selections[checkbox_key] = True


def deselect_all_components(component_types: List[str]):
    """Deselect all components across all types"""
    for comp_type in component_types:
        mode = 'graph'  # knowledge graph is the sole source
        enabled_dps = tuple(st.session_state.get('enabled_ttl_data_products', []))
        kg_components, dp_components = load_components_cached(comp_type, mode, enabled_dps)

        for comp in dp_components:
            checkbox_key = f"select_dp_{comp_type}_{comp['uri']}"
            st.session_state.component_selections[checkbox_key] = False

        for comp in kg_components:
            checkbox_key = f"select_kg_{comp_type}_{comp['uri']}"
            st.session_state.component_selections[checkbox_key] = False


def display_component_type_section_optimized(comp_type):
    """Display components for selection - FULLY CACHED for speed"""
    # Get current state for cache key
    mode = 'graph'  # knowledge graph is the sole source
    enabled_dps = tuple(st.session_state.get('enabled_ttl_data_products', []))

    # OPTIMIZED: Load components with caching - only reloads when inputs change!
    kg_components, dp_components = load_components_cached(comp_type, mode, enabled_dps)

    kg_source = "Knowledge Graph"

    available_components = []
    all_components = dp_components + kg_components

    with st.form(f"component_selection_form_{comp_type}"):
        if dp_components:
            st.write("**Available from Data Products:**")
            dp_selections = {}

            for comp in dp_components:
                checkbox_key = f"form_dp_{comp_type}_{comp['uri']}"
                is_in_scenario = is_component_in_scenario(comp['uri'])

                col1, col2, col3 = st.columns([0.5, 3.5, 1])

                with col1:
                    dp_selections[comp['uri']] = st.checkbox(
                        label="Select",
                        value=is_in_scenario,
                        key=checkbox_key,
                        label_visibility="collapsed"
                    )

                with col2:
                    source_badge = '📊 DP'
                    display_label = comp.get('uri_fragment', comp['label'])
                    status = " ✅" if is_in_scenario else ""
                    st.write(f"{source_badge} **{display_label}**{status}")

                    if comp.get('source_catalog'):
                        st.caption(f"Catalog: {comp['source_catalog']}")
                    st.caption(f"URI: `{comp['uri']}`")
                    show_component_attribute_summary_simple(comp)

                with col3:
                    if comp.get('attributes'):
                        st.caption("👁️ Has attributes")

                available_components.append((comp, 'dp', dp_selections))

            if kg_components:
                st.markdown("---")

        kg_selections = {}
        if kg_components:
            current_workspace = st.session_state.get('current_workspace')
            workspace_name = current_workspace['name'] if current_workspace else 'Current Workspace'
            st.write(f"**Available from {workspace_name} {kg_source}:**")

            for comp in kg_components:
                checkbox_key = f"form_kg_{comp_type}_{comp['uri']}"
                is_in_scenario = is_component_in_scenario(comp['uri'])

                col1, col2, col3 = st.columns([0.5, 3.5, 1])

                with col1:
                    kg_selections[comp['uri']] = st.checkbox(
                        label="Select",
                        value=is_in_scenario,
                        key=checkbox_key,
                        label_visibility="collapsed"
                    )

                with col2:
                    if comp.get('source') == 'knowledge_graph':
                        source_badge = '🔗 KG'
                    else:
                        source_badge = '📄 TTL'

                    display_label = comp.get('uri_fragment', comp['label'])
                    status = " ✅" if is_in_scenario else ""
                    st.write(f"{source_badge} **{display_label}**{status}")

                    if comp.get('workspace_id'):
                        st.caption(f"Workspace: {workspace_name}")
                    st.caption(f"URI: `{comp['uri']}`")
                    show_component_attribute_summary_simple(comp)

                with col3:
                    if comp.get('attributes'):
                        st.caption("👁️ Has attributes")

                available_components.append((comp, 'kg', kg_selections))

        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            select_all = st.form_submit_button("✅ Select All", type="secondary")

        with col2:
            deselect_all = st.form_submit_button("❌ Deselect All", type="secondary")

        with col3:
            apply_changes = st.form_submit_button("🔄 Apply Changes", type="primary")

        # Process with batching to avoid GraphDB overload
        if select_all or deselect_all or apply_changes:
            if select_all:
                added = 0
                for comp, source, _ in available_components:
                    if not is_component_in_scenario(comp['uri']):
                        if add_component_to_scenario(comp, comp_type):
                            added += 1
                if added > 0:
                    st.success(f"✅ Added {added} {comp_type} components")
                st.rerun()

            elif deselect_all:
                removed = 0
                for comp, source, _ in available_components:
                    if is_component_in_scenario(comp['uri']):
                        if remove_component_from_scenario(comp['uri']):
                            removed += 1
                if removed > 0:
                    st.success(f"❌ Removed {removed} {comp_type} components")
                st.rerun()

            elif apply_changes:
                selected_components = []
                deselected_components = []

                for comp, source, selections in available_components:
                    if source == 'dp' and comp['uri'] in dp_selections:
                        if dp_selections[comp['uri']] and not is_component_in_scenario(comp['uri']):
                            selected_components.append(comp)
                        elif not dp_selections[comp['uri']] and is_component_in_scenario(comp['uri']):
                            deselected_components.append(comp)
                    elif source == 'kg' and comp['uri'] in kg_selections:
                        if kg_selections[comp['uri']] and not is_component_in_scenario(comp['uri']):
                            selected_components.append(comp)
                        elif not kg_selections[comp['uri']] and is_component_in_scenario(comp['uri']):
                            deselected_components.append(comp)

                # Process changes - OPTIMIZED: no delays needed
                added_count = 0
                removed_count = 0

                if selected_components:
                    for comp in selected_components:
                        if add_component_to_scenario(comp, comp_type):
                            added_count += 1

                for comp in deselected_components:
                    if remove_component_from_scenario(comp['uri']):
                        removed_count += 1

                if added_count or removed_count:
                    st.success(f"✅ Added {added_count} | ❌ Removed {removed_count}")
                    st.rerun()
                else:
                    st.info("No changes to apply")

    # View attributes outside form
    if all_components:
        with st.expander("🔍 View Component Attributes", expanded=False):
            for idx, comp in enumerate(all_components):
                col1, col2 = st.columns([3, 1])
                with col1:
                    source_badge = '📊 DP' if comp in dp_components else ('🔗 KG' if comp.get('source') == 'knowledge_graph' else '📄 TTL')
                    display_label = comp.get('uri_fragment', comp['label'])
                    st.write(f"{source_badge} **{display_label}**")
                with col2:
                    if comp.get('attributes'):
                        # Use index + hash to ensure unique keys
                        uri_hash = hashlib.md5(comp['uri'].encode()).hexdigest()[:8]
                        source_prefix = 'dp' if comp in dp_components else 'kg'
                        if st.button("👁️ View", key=f"view_{comp_type}_{source_prefix}_{idx}_{uri_hash}"):
                            show_component_attributes_dialog(comp)

    if available_components:
        in_scenario_count = sum(1 for comp, _, _ in available_components if is_component_in_scenario(comp['uri']))
        st.info(f"📊 {in_scenario_count} of {len(available_components)} components in scenario")

    if not dp_components and not kg_components:
        st.info(f"No {comp_type} components available.")


def tab_add_components():
    """Main tab for adding components to scenario"""
    st.subheader("📦 Add Components to Scenario")

    if not st.session_state.selected_requirements:
        st.warning("Please select service requirements first")
        return

    requirements = st.session_state.selected_requirements

    st.session_state.scenario_name = st.text_input(
        "Scenario Name:",
        value=st.session_state.scenario_name,
        key="scenario_name_tab1"
    )

    # Show export loader controls
    show_export_loader_controls()

    st.write("**Required Component Types:**")

    component_types = requirements.get('all_required_component_types', [])

    if not component_types:
        component_types = set()
        for link in requirements['component_links']:
            parts = link.split('.')
            if len(parts) >= 3:
                component_types.add(parts[1])
                component_types.add(parts[2])
        component_types.discard('Scenario')
        component_types = sorted(list(component_types))

    # Initialize session state for component selections if not exists
    if 'component_selections' not in st.session_state:
        st.session_state.component_selections = {}

    # Display all component type tabs
    if len(component_types) > 1:
        component_tabs = st.tabs([f"🔧 {comp_type}" for comp_type in component_types])
        for i, comp_type in enumerate(component_types):
            with component_tabs[i]:
                display_component_type_section_no_form(comp_type)
    else:
        if component_types:
            display_component_type_section_no_form(component_types[0])

    # GLOBAL APPLY CHANGES SECTION - applies to ALL component types
    st.markdown("---")
    st.markdown("### 🚀 Apply Changes to Scenario")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("✅ Apply All Changes", type="primary", use_container_width=True):
            apply_all_component_changes(component_types)

    with col2:
        if st.button("🔄 Select All", type="secondary", use_container_width=True):
            select_all_components(component_types)
            st.rerun()

    with col3:
        if st.button("❌ Deselect All", type="secondary", use_container_width=True):
            deselect_all_components(component_types)
            st.rerun()

    with col4:
        if st.button("🗑️ Clear Selections", type="secondary", use_container_width=True):
            st.session_state.component_selections = {}
            st.rerun()

    # Debug toggle for troubleshooting
    with st.expander("🐛 Debug Options", expanded=False):
        debug_enabled = st.checkbox(
            "Enable debug logging for component additions",
            value=st.session_state.get('component_debug_mode', False),
            help="Shows detailed information about which components are being processed when Apply All Changes is clicked"
        )
        st.session_state.component_debug_mode = debug_enabled

        if debug_enabled:
            st.info("Debug mode enabled. Detailed logs will appear when you click 'Apply All Changes'.")

    display_scenario_summary()


def display_scenario_summary():
    """Display scenario summary"""
    if not st.session_state.scenario_components:
        return

    st.markdown("---")
    st.subheader("📊 Scenario Summary")

    source_counts = {}
    attribute_compliance = {'compliant': 0, 'partial': 0, 'missing': 0}

    for comp in st.session_state.scenario_components:
        source = comp.get('source', 'unknown')
        source_counts[source] = source_counts.get(source, 0) + 1

        comp_type = comp['type']
        if comp_type in st.session_state.get('required_attributes', {}):
            required_attrs = st.session_state.required_attributes[comp_type]
            missing_count = sum(1 for req_attr in required_attrs
                                if not resolve_nested_attribute_requirement(comp, req_attr))

            if missing_count == 0:
                attribute_compliance['compliant'] += 1
            elif missing_count < len(required_attrs):
                attribute_compliance['partial'] += 1
            else:
                attribute_compliance['missing'] += 1

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Total Components", len(st.session_state.scenario_components))

        source_labels = {
            'technology_catalog_2025': '⚙️ Technology Catalog',
            'demand_profiles_2024': '📊 Demand Profiles',
            'geological_data_2025': '🌍 Geological Data',
            'ttl_use_case': '📄 Workspace TTL',
            'knowledge_graph': '🔗 Knowledge Graph',
            'data_products': '📊 Data Products'
        }

        for source, count in source_counts.items():
            label = source_labels.get(source, f'❓ {source}')
            st.write(f"• {label}: {count}")

    with col2:
        total_components = sum(attribute_compliance.values())
        if total_components > 0:
            st.write("**Attribute Compliance:**")
            if attribute_compliance['compliant'] > 0:
                st.metric("✅ Compliant", attribute_compliance['compliant'])
            if attribute_compliance['partial'] > 0:
                st.metric("⚠️ Partial", attribute_compliance['partial'])
            if attribute_compliance['missing'] > 0:
                st.metric("❌ Missing", attribute_compliance['missing'])


# Moved to the backend emitter (Phase 4b): pure dict resolution shared by the
# TTL emitter and this component browser. Re-imported so every existing
# ``from components.scenario_builder.scenario_builder_components import
# resolve_nested_attribute_requirement`` call site keeps working unchanged.
from backend.scenario_builder.emitter import resolve_nested_attribute_requirement  # noqa: E402,F401


def validate_nested_attribute_requirements(component, required_attrs):
    """
    Validate nested attribute requirements for a component
    Returns (missing, partial) lists
    """
    missing = []
    partial = []

    for req_attr in required_attrs:
        # Use the resolve_nested_attribute_requirement function to check if value exists
        value = resolve_nested_attribute_requirement(component, req_attr)

        if value is None or value == "":
            # Check if it's a nested requirement
            if '.' in req_attr:
                # For nested requirements, check if we have the base attribute at least
                parts = req_attr.split('.')
                base_attr = parts[0]

                # Check in attributes first
                component_attrs = component.get('attributes', {})
                has_base = False

                # Check various possible keys for the base attribute
                possible_base_keys = [
                    base_attr,
                    f"{component.get('type', '')}{base_attr}",
                    f"{base_attr}Attribute",
                    f"{component.get('type', '')}{base_attr}Attribute"
                ]

                for key in possible_base_keys:
                    if key in component_attrs:
                        has_base = True
                        break

                # Also check in nested_properties
                if not has_base and base_attr in component.get('nested_properties', {}):
                    has_base = True

                if has_base:
                    partial.append(req_attr)  # We have the attribute but not the nested property
                else:
                    missing.append(req_attr)  # We don't even have the base attribute
            else:
                missing.append(req_attr)

    return missing, partial


def show_component_attribute_summary_simple(comp):
    """Show simplified attribute summary"""
    if not comp.get('attributes'):
        return

    category_counts = {}
    has_temporal = False

    for attr_name, attr_data in comp['attributes'].items():
        if isinstance(attr_data, dict) and attr_data.get('category'):
            category = attr_data['category']
            if category != 'system':
                category_counts[category] = category_counts.get(category, 0) + 1

                if category == 'temporal' or attr_data.get('attribute_type') == 'EventAttribute':
                    has_temporal = True

    if category_counts:
        total_attrs = sum(category_counts.values())
        category_summary = ', '.join(f'{cat}:{count}' for cat, count in category_counts.items())
        temporal_indicator = " 📅" if has_temporal else ""
        st.caption(f"Attributes: {total_attrs} ({category_summary}){temporal_indicator}")


def get_component_label_by_uri(uri):
    """Get component label by URI"""
    for component in st.session_state.get('scenario_components', []):
        if component.get('uri') == uri:
            return component.get('uri_fragment', component.get('label', get_uri_fragment(uri)))

    cache_key = f"component_label_{uri}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    label = get_uri_fragment(uri)
    st.session_state[cache_key] = label
    return label


def debug_nested_attribute_resolution(component, requirement_path):
    """
    Debug function to understand how nested attributes are stored and resolved
    """
    print(f"\n=== DEBUGGING NESTED ATTRIBUTE RESOLUTION ===")
    print(f"Component: {component.get('label', 'Unknown')}")
    print(f"Component Type: {component.get('type', 'Unknown')}")
    print(f"Requirement Path: {requirement_path}")
    print(f"Source: {component.get('source', 'Unknown')}")

    # Show what's in attributes
    print(f"\n--- ATTRIBUTES KEYS ---")
    attributes = component.get('attributes', {})
    for key in sorted(attributes.keys()):
        attr_data = attributes[key]
        if isinstance(attr_data, dict):
            attr_type = attr_data.get('attribute_type', 'Unknown')
            has_value = 'value' in attr_data
            print(f"  {key}: {attr_type} (has_value: {has_value})")
        else:
            print(f"  {key}: {type(attr_data).__name__} = {attr_data}")

    # Show what's in nested_properties
    print(f"\n--- NESTED_PROPERTIES KEYS ---")
    nested_props = component.get('nested_properties', {})
    for key in sorted(nested_props.keys()):
        nested_data = nested_props[key]
        if isinstance(nested_data, dict):
            print(f"  {key}:")
            for sub_key, sub_value in nested_data.items():
                print(f"    {sub_key}: {sub_value}")
        else:
            print(f"  {key}: {nested_data}")

    # Parse requirement path
    parts = requirement_path.split('.')
    component_type = component.get('type', '')

    print(f"\n--- REQUIREMENT ANALYSIS ---")
    print(f"Parts: {parts}")
    print(f"Component Type: {component_type}")

    # Remove component type if it matches
    if len(parts) > 2 and parts[0] == component_type:
        parts = parts[1:]
        print(f"Parts after removing component type: {parts}")

    if len(parts) >= 2:
        attribute_name = parts[0]
        nested_property = '.'.join(parts[1:])
        print(f"Base Attribute: {attribute_name}")
        print(f"Nested Property: {nested_property}")

        # Generate possible keys
        possible_keys = [
            attribute_name,
            f"{attribute_name}Attribute",
            f"{component_type}{attribute_name}",
            f"{component_type}{attribute_name}Attribute",
        ]

        print(f"\n--- POSSIBLE KEYS TO CHECK ---")
        for key in possible_keys:
            print(f"  {key}")

            # Check in nested_properties
            if key in nested_props:
                print(f"    Found in nested_properties!")
                nested_data = nested_props[key]
                if isinstance(nested_data, dict):
                    if nested_property in nested_data:
                        print(f"    Contains {nested_property}: {nested_data[nested_property]}")
                    else:
                        print(f"    Does NOT contain {nested_property}")
                        print(f"    Available keys: {list(nested_data.keys())}")
            else:
                print(f"    Not found in nested_properties")

            # Check in attributes
            if key in attributes:
                print(f"    Found in attributes!")
                attr_data = attributes[key]
                if isinstance(attr_data, dict):
                    if nested_property in attr_data:
                        print(f"    Contains {nested_property}: {attr_data[nested_property]}")
                    else:
                        print(f"    Does NOT contain {nested_property}")
                        print(f"    Available keys: {list(attr_data.keys())}")
            else:
                print(f"    Not found in attributes")

    # Try the actual resolution
    print(f"\n--- RESOLUTION ATTEMPT ---")
    try:
        result = resolve_nested_attribute_requirement(component, requirement_path)
        print(f"Result: {result}")
        print(f"Result type: {type(result)}")
    except Exception as e:
        print(f"Error during resolution: {e}")

    print(f"=== END DEBUG ===\n")

    return None