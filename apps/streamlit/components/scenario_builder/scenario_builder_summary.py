# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/scenario_builder_summary.py
"""Scenario Builder summary tab — UI shell over the backend emitter.

The full scenario-TTL emitter moved to ``backend/scenario_builder/emitter.py``
(Phase 4b of the backend/UI split); its input contract is
``backend.scenario_builder.draft.ScenarioDraft``. What stays here is exactly
the Streamlit wiring:

* the ``render``/``show`` functions and the session-state assembly, unchanged;
* pure emitter helpers re-exported under their old names (same objects, so
  every existing import keeps working);
* session-state adapters with the OLD signatures — ``generate_full_ttl()``,
  ``get_filtered_components_for_ttl()``, ``get_filtered_links_for_ttl(comps)``,
  ``validate_enhanced_component_attributes()`` — that read the same session
  keys as before and hand a draft/explicit args to the backend;
* the upload buttons' session lookups and st.success/st.error around the
  headless mechanics in ``backend.scenario_builder.publish``.

Behavior (including the pinned quirks: booleans as ``xsd:decimal``, the
``linksInputyEntityTo`` spelling, the truthiness completeness filter) is
unchanged — see ``tests/test_characterize_scenario_emitter.py``.
"""
import streamlit as st
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from backend.scenario_builder.draft import ScenarioDraft
from backend.scenario_builder import emitter as _emitter
from backend.scenario_builder.publish import (
    push_scenario_to_graph,
    save_scenario_to_workspace,
)

# Pure helpers, re-exported verbatim from the backend emitter (same objects).
from backend.scenario_builder.emitter import (  # noqa: F401
    generate_basic_attribute_declaration,
    generate_enhanced_attribute_declaration,
    generate_enhanced_attribute_declaration_with_nested_properties,
    generate_time_series_resources,
    get_xsd_datatype_for_temporal_precision,
    map_unit_to_uri,
    resolve_enhanced_attribute_value,
)


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


def generate_full_ttl():
    """Generate complete TTL from session state via the backend emitter.

    Session reads are exactly the old ones (scenario_name, current_workspace,
    selected_requirements, ttl_specificity, required_attributes,
    scenario_components, scenario_links) — assembled into a ScenarioDraft.
    """
    # Preserve the old default-setting side effect on session state.
    if 'ttl_specificity' not in st.session_state:
        st.session_state.ttl_specificity = 'High'

    draft = ScenarioDraft.from_session_state(st.session_state)
    return _emitter.generate_full_ttl(draft)


def validate_enhanced_component_attributes():
    """Enhanced validation that handles nested property requirements including EventAttribute"""
    return _emitter.validate_enhanced_component_attributes(
        st.session_state.scenario_components,
        st.session_state.get('required_attributes', {}))


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
    return _emitter.get_filtered_components_for_ttl(
        st.session_state.scenario_components,
        st.session_state.get('required_attributes', {}))


# Function to filter links based on included components
def get_filtered_links_for_ttl(filtered_components):
    """Get links filtered to only include those between included components"""
    return _emitter.get_filtered_links_for_ttl(
        st.session_state.scenario_links, filtered_components)


# Function to validate only filtered components
def validate_enhanced_component_attributes_filtered(filtered_components):
    """Enhanced validation for filtered (complete) components only"""
    return _emitter.validate_enhanced_component_attributes_filtered(
        filtered_components, st.session_state.get('required_attributes', {}))


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
            save_scenario_to_workspace(ctx.storage, ttl_content, filename)
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
                save_scenario_to_workspace(storage, ttl_content, filename)
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

        ok, status, response = push_scenario_to_graph(client, ttl_content)
        if ok:
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
