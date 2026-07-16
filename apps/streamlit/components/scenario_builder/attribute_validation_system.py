# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/attribute_validation_system.py
"""
Fixed attribute validation system that properly resolves nested attributes
FIXED: Enhanced validation now properly calls the nested attribute resolution
"""
import streamlit as st
from typing import Dict, List, Any, Optional, Tuple

# Import enhanced validation functions
try:
    from components.scenario_builder.scenario_builder_components import (
        resolve_nested_attribute_requirement,
        validate_nested_attribute_requirements
    )

    ENHANCED_VALIDATION_AVAILABLE = True
except ImportError:
    ENHANCED_VALIDATION_AVAILABLE = False


def tab_enhanced_attribute_validation():
    """Enhanced attribute validation tab without nested expanders"""
    st.subheader("🔍 Attribute Validation")

    if not st.session_state.selected_requirements:
        st.warning("Please select service requirements first")
        return

    if not st.session_state.scenario_components:
        st.info("Add components to scenario to validate their attributes")
        return

    requirements = st.session_state.selected_requirements
    required_attributes = requirements.get('required_attributes', {})

    if not required_attributes:
        st.info("No attribute requirements specified in the service definition")
        return

    # Performance optimization: compute validation results once
    validation_results = compute_all_validation_results(required_attributes)

    # Display validation summary
    display_validation_summary(validation_results)

    # Use tabs instead of expanders for component details
    display_component_validation_tabs(validation_results, required_attributes)


def compute_all_validation_results(required_attributes):
    """Compute validation results for all components at once for better performance"""
    validation_results = {}

    for component in st.session_state.scenario_components:
        comp_type = component['type']
        comp_uri = component['uri']

        if comp_type in required_attributes:
            required_attrs = required_attributes[comp_type]

            # FIXED: Use the enhanced validation that properly handles nested attributes
            missing, present, sources = validate_component_attributes_detailed_enhanced(component, required_attrs)

            # Also check for partial attributes using the enhanced method
            if ENHANCED_VALIDATION_AVAILABLE:
                missing_nested, partial_nested = validate_nested_attribute_requirements(component, required_attrs)
                # Update missing list with nested validation results
                missing = list(set(missing + missing_nested))
                # Add partial attributes to present if they have some data
                for partial_attr in partial_nested:
                    if partial_attr not in present:
                        present.append(partial_attr)
                partial = partial_nested
            else:
                partial = []

            validation_results[comp_uri] = {
                'component': component,
                'comp_type': comp_type,
                'required_attrs': required_attrs,
                'missing': missing,
                'present': present,
                'partial': partial,
                'sources': sources,
                'compliance_status': determine_compliance_status(missing, partial, required_attrs)
            }

    return validation_results


def validate_component_attributes_detailed_enhanced(component, required_attrs):
    """
    FIXED: Enhanced validation function that properly uses nested attribute resolution
    """
    missing = []
    present = []
    sources = []

    for req_attr in required_attrs:
        # CRITICAL: Use the enhanced nested attribute resolution
        if ENHANCED_VALIDATION_AVAILABLE:
            attr_value = resolve_nested_attribute_requirement(component, req_attr)

            if attr_value is not None and attr_value != "":
                present.append(req_attr)
                # Determine source of the attribute
                comp_source = component.get('source', 'unknown')
                if comp_source == 'ttl_use_case':
                    sources.append('Workspace TTL')
                elif comp_source == 'data_products':
                    dp_name = component.get('source_catalog', 'unknown')
                    sources.append(f'Data Products: {dp_name}')
                elif comp_source == 'knowledge_graph':
                    sources.append('Knowledge Graph')
                else:
                    sources.append('Unknown Source')
            else:
                missing.append(req_attr)
        else:
            # Fallback to basic validation if enhanced components not available
            missing_basic, present_basic, sources_basic = validate_component_attributes_detailed_basic(component, required_attrs)
            return missing_basic, present_basic, sources_basic

    return missing, present, sources


def validate_component_attributes_detailed(component, required_attrs):
    """
    Legacy validation function for backward compatibility
    This is kept for imports from other modules
    """
    if ENHANCED_VALIDATION_AVAILABLE:
        return validate_component_attributes_detailed_enhanced(component, required_attrs)
    else:
        return validate_component_attributes_detailed_basic(component, required_attrs)


def validate_component_attributes_detailed_basic(component, required_attrs):
    """Basic validation function for backward compatibility"""
    missing = []
    present = []
    sources = []

    component_attributes = component.get('attributes', {})
    nested_properties = component.get('nested_properties', {})

    for req_attr in required_attrs:
        found = False

        # Check for simple attributes first
        if req_attr in component_attributes:
            attr_data = component_attributes[req_attr]
            if isinstance(attr_data, dict):
                value = attr_data.get('value')
                if value is not None and value != "":
                    present.append(req_attr)
                    sources.append(component.get('source', 'unknown'))
                    found = True
            elif attr_data is not None and attr_data != "":
                present.append(req_attr)
                sources.append(component.get('source', 'unknown'))
                found = True

        # Check for nested attributes
        if not found and '.' in req_attr:
            parts = req_attr.split('.')
            if len(parts) >= 2:
                base_attr = parts[0]
                nested_prop = '.'.join(parts[1:])

                # Check all possible variations of the base attribute in nested_properties
                component_type = component.get('type', '')
                possible_keys = [
                    base_attr,
                    f"{base_attr}Attribute",
                    f"{component_type}{base_attr}",
                    f"{component_type}{base_attr}Attribute"
                ]

                for key in possible_keys:
                    if key in nested_properties:
                        nested_data = nested_properties[key]
                        if isinstance(nested_data, dict) and nested_prop in nested_data:
                            value = nested_data[nested_prop]
                            if value is not None and value != "":
                                present.append(req_attr)
                                sources.append(component.get('source', 'unknown'))
                                found = True
                                break

                if found:
                    continue

        if not found:
            missing.append(req_attr)

    return missing, present, sources


def determine_compliance_status(missing, partial, required_attrs):
    """Determine compliance status based on missing and partial attributes"""
    if not missing and not partial:
        return 'compliant'
    elif missing and len(missing) == len(required_attrs):
        return 'missing_all'
    else:
        return 'partial'


def display_validation_summary(validation_results):
    """Display validation summary with metrics"""
    if not validation_results:
        return

    # Calculate summary statistics
    total_components = len(validation_results)
    compliant_count = sum(1 for r in validation_results.values() if r['compliance_status'] == 'compliant')
    partial_count = sum(1 for r in validation_results.values() if r['compliance_status'] == 'partial')
    missing_count = sum(1 for r in validation_results.values() if r['compliance_status'] == 'missing_all')

    st.write("### 📊 Validation Summary")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Components", total_components)

    with col2:
        st.metric("✅ Compliant", compliant_count)

    with col3:
        st.metric("⚠️ Partially Compliant", partial_count)

    with col4:
        st.metric("❌ Missing Attributes", missing_count)

    # Show overall compliance percentage
    if total_components > 0:
        compliance_percentage = (compliant_count / total_components) * 100
        st.progress(compliance_percentage / 100)
        st.caption(f"Overall compliance: {compliance_percentage:.1f}%")

    st.markdown("---")


def display_component_validation_tabs(validation_results, required_attributes):
    """Display component validation using tabs instead of nested expanders"""
    if not validation_results:
        return

    # Group components by compliance status
    compliant_components = []
    partial_components = []
    missing_components = []

    for result in validation_results.values():
        if result['compliance_status'] == 'compliant':
            compliant_components.append(result)
        elif result['compliance_status'] == 'partial':
            partial_components.append(result)
        else:
            missing_components.append(result)

    # Create tabs for different compliance levels
    tabs = []
    tab_labels = []

    if compliant_components:
        tab_labels.append(f"✅ Compliant ({len(compliant_components)})")
        tabs.append(compliant_components)

    if partial_components:
        tab_labels.append(f"⚠️ Partial ({len(partial_components)})")
        tabs.append(partial_components)

    if missing_components:
        tab_labels.append(f"❌ Missing ({len(missing_components)})")
        tabs.append(missing_components)

    if not tabs:
        return

    st_tabs = st.tabs(tab_labels)

    for i, (tab_components, st_tab) in enumerate(zip(tabs, st_tabs)):
        with st_tab:
            display_component_list_validation(tab_components, required_attributes)


def display_component_list_validation(components, required_attributes):
    """Display validation results for a list of components with enhanced nested attribute debugging"""
    for result in components:
        component = result['component']
        comp_type = result['comp_type']
        missing = result['missing']
        present = result['present']
        partial = result.get('partial', [])

        # Component header
        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"**{component['label']}** ({comp_type})")
            st.caption(f"URI: `{component['uri']}`")

            # Show source information
            source_labels = {
                'technology_catalog_2025': '⚙️ Technology Catalog',
                'demand_profiles_2024': '📊 Demand Profiles',
                'geological_data_2025': '🌍 Geological Data',
                'ttl_use_case': '📄 Workspace TTL',
                'data_products': '📊 Data Products',
                'knowledge_graph': '🏛️ Knowledge Graph'
            }
            source_label = source_labels.get(component.get('source', 'unknown'), f"❓ {component.get('source', 'unknown')}")
            st.caption(f"Source: {source_label}")

        with col2:
            # Compliance badge
            if not missing and not partial:
                st.success("✅ Fully Compliant")
            elif missing:
                st.error(f"❌ {len(missing)} Missing")
            else:
                st.warning("⚠️ Partially Compliant")

        # ENHANCED: Debug nested attribute resolution for missing attributes
        if missing:
            st.write("**❌ Missing Attributes:**")
            for missing_attr in missing:
                st.write(f"• `{missing_attr}`")

                # DEBUGGING: Show what's actually in the component for nested attributes
                if '.' in missing_attr and ENHANCED_VALIDATION_AVAILABLE:
                    # Try to resolve and show debug info
                    debug_nested_attribute_for_validation(component, missing_attr)

                # Show guidance for missing attribute
                guidance = get_attribute_guidance(comp_type, missing_attr, component.get('source', 'unknown'))
                if guidance:
                    st.info(f"💡 {guidance}")

        # Attribute details
        if present:
            st.write("**✅ Present Attributes:**")
            st.write(", ".join(present))

        if partial:
            st.write("**⚠️ Partially Satisfied:**")
            st.write(", ".join(partial))

        st.markdown("---")


def debug_nested_attribute_for_validation(component, missing_attr):
    """Debug helper to show why a nested attribute is marked as missing"""
    if not ('.' in missing_attr):
        return

    parts = missing_attr.split('.')
    if len(parts) >= 2:
        base_attr = parts[0]
        nested_prop = '.'.join(parts[1:])

        # Check what's available in nested_properties
        nested_props = component.get('nested_properties', {})
        component_type = component.get('type', '')

        # Show debug info in a compact way
        debug_info = []

        # Check all possible keys
        possible_keys = [
            base_attr,
            f"{base_attr}Attribute",
            f"{component_type}{base_attr}",
            f"{component_type}{base_attr}Attribute"
        ]

        found_keys = []
        for key in possible_keys:
            if key in nested_props:
                found_keys.append(key)
                nested_data = nested_props[key]
                if isinstance(nested_data, dict):
                    if nested_prop in nested_data:
                        debug_info.append(f"✅ Found {nested_prop} in {key}: {nested_data[nested_prop]}")
                    else:
                        available_props = list(nested_data.keys())
                        debug_info.append(f"❌ {key} exists but missing {nested_prop}. Available: {available_props}")

        if not found_keys:
            debug_info.append(f"❌ No base attribute found for {base_attr}. Available nested_properties keys: {list(nested_props.keys())}")

        if debug_info:
            with st.expander(f"🔍 Debug: {missing_attr}", expanded=False):
                for info in debug_info:
                    st.caption(info)


def get_attribute_guidance(comp_type, missing_attr, source):
    """Get guidance for missing attributes based on component type and source"""
    guidance_map = {
        'EnergyConsumer': {
            'Power': "Add the energy consumer's power consumption data. Check time series files.",
            'Power.hasHistoricTimeSeriesReference': "Add historic time series reference for power consumption. This should point to a CSV file with historic power data.",
            'URI': "Component URI should be automatically generated.",
            'label': "Component label should be set from the component name."
        },
        'EnergyGenerator': {
            'Power': "Add the energy generator's power production data. Check time series files.",
            'Power.hasHistoricTimeSeriesReference': "Add historic time series reference for power production. This should point to a CSV file with historic power data.",
            'URI': "Component URI should be automatically generated.",
            'label': "Component label should be set from the component name."
        },
        'WindTurbine': {
            'RatedPower': "Add the turbine's rated power capacity in MW. Check manufacturer specifications.",
            'HubHeight': "Specify the hub height in meters. This is crucial for wind resource calculations.",
            'CAPEX': "Include capital expenditure costs. Check recent market data or manufacturer quotes.",
            'OPEX': "Add operational expenditure costs per year or per MW.",
            'PowerProduction': "This requires time series data. Upload power production profiles or connect to time series database.",
            'PowerProduction.hasFutureTimeSeries': "Link to future power production time series data in your workspace TTL files."
        },
        'PV': {
            'RatedPower': "Add the PV system's rated power capacity in kW or MW.",
            'Efficiency': "Specify panel efficiency as a percentage (typically 15-22% for modern panels).",
            'CAPEX': "Include system capital costs including panels, inverters, and installation.",
            'CellType': "Specify cell technology (e.g., Monocrystalline, Polycrystalline, Thin-film)."
        },
        'GlobalWindAtlasSite': {
            'Roughness': "Add surface roughness length in meters (typically 0.01-1.0 for different terrains).",
            'Latitude': "Specify site latitude in decimal degrees.",
            'Longitude': "Specify site longitude in decimal degrees.",
            'WindSpeed': "Add reference wind speed data at hub height."
        },
        'EnergyCarrier': {
            'EnergyCost': "Specify energy cost per unit (e.g., EUR/kWh for electricity).",
            'CarbonIntensity': "Add carbon intensity in kgCO2/kWh or similar units."
        }
    }

    source_guidance = {
        'ttl_use_case': "Add this attribute to your workspace TTL file with appropriate QUDT units and values.",
        'data_products': "Check if this attribute is available in other data product catalogs you can enable.",
        'technology_catalog_2025': "This attribute should be available in the technology catalog. Contact data provider if missing.",
        'demand_profiles_2024': "This attribute should be in the demand profiles catalog. Verify catalog completeness.",
        'geological_data_2025': "Geographic data should include this attribute. Check data coverage for your region.",
        'knowledge_graph': "This attribute should be in your knowledge graph. Check the Triplestore export or TTL files."
    }

    # Get specific guidance for attribute
    comp_guidance = guidance_map.get(comp_type, {})
    attr_guidance = comp_guidance.get(missing_attr, "")

    if attr_guidance:
        return attr_guidance

    # Special guidance for nested attributes
    if '.' in missing_attr:
        parts = missing_attr.split('.')
        if len(parts) >= 2:
            base_attr = parts[0]
            nested_prop = parts[1]

            if 'TimeSeriesReference' in nested_prop:
                return f"Add a time series reference for {base_attr}. This should be a string pointing to your time series data file (e.g., 'power_data.csv')."
            elif 'TimeSeries' in nested_prop:
                return f"Add a time series URI for {base_attr}. This should point to your time series data resource."

    # Get general source guidance
    return source_guidance.get(source, f"Ensure this attribute is available in your {source} data source.")


def get_component_attribute_sources(component, attributes):
    """Get attribute sources for validation reporting"""
    sources = {}

    for attr in attributes:
        if ENHANCED_VALIDATION_AVAILABLE:
            # Use the enhanced resolution to check if attribute exists
            attr_value = resolve_nested_attribute_requirement(component, attr)
            if attr_value:
                sources[attr] = component.get('source', 'unknown')
        else:
            # Fallback to basic checking
            if attr in component.get('attributes', {}):
                attr_data = component['attributes'][attr]
                if isinstance(attr_data, dict):
                    source = attr_data.get('source', component.get('source', 'unknown'))
                    sources[attr] = source
                else:
                    sources[attr] = component.get('source', 'unknown')

    return sources


def display_attribute_requirements_summary(required_attributes):
    """Display summary of all attribute requirements"""
    st.write("### 📋 Required Attributes Summary")

    for comp_type, attrs in required_attributes.items():
        st.write(f"**{comp_type}** ({len(attrs)} attributes required):")

        # Group attributes by complexity
        simple_attrs = [attr for attr in attrs if '.' not in attr]
        nested_attrs = [attr for attr in attrs if '.' in attr]

        if simple_attrs:
            st.write("Simple attributes: " + ", ".join(f"`{attr}`" for attr in simple_attrs))

        if nested_attrs:
            st.write("Nested properties: " + ", ".join(f"`{attr}`" for attr in nested_attrs))

        st.write("")


def export_validation_report():
    """Export validation results as a downloadable report"""
    if not st.session_state.scenario_components or not st.session_state.selected_requirements:
        st.warning("No components or requirements to export")
        return

    required_attributes = st.session_state.selected_requirements.get('required_attributes', {})
    validation_results = compute_all_validation_results(required_attributes)

    # Create report content
    report_lines = []
    report_lines.append("# Attribute Validation Report")
    report_lines.append(f"Scenario: {st.session_state.scenario_name}")
    report_lines.append(f"Generated: {st.session_state.get('current_timestamp', 'Unknown')}")
    report_lines.append("")

    # Summary
    total = len(validation_results)
    compliant = sum(1 for r in validation_results.values() if r['compliance_status'] == 'compliant')
    report_lines.append(f"## Summary")
    report_lines.append(f"- Total components: {total}")
    report_lines.append(f"- Fully compliant: {compliant}")
    report_lines.append(f"- Compliance rate: {(compliant / total * 100):.1f}%" if total > 0 else "- Compliance rate: 0%")
    report_lines.append("")

    # Component details
    report_lines.append("## Component Details")
    for result in validation_results.values():
        component = result['component']
        report_lines.append(f"### {component['label']} ({component['type']})")
        report_lines.append(f"URI: {component['uri']}")
        report_lines.append(f"Source: {component.get('source', 'unknown')}")

        if result['present']:
            report_lines.append(f"✅ Present: {', '.join(result['present'])}")

        if result['missing']:
            report_lines.append(f"❌ Missing: {', '.join(result['missing'])}")

        if result.get('partial'):
            report_lines.append(f"⚠️ Partial: {', '.join(result['partial'])}")

        report_lines.append("")

    report_content = "\n".join(report_lines)

    st.download_button(
        label="📄 Download Validation Report",
        data=report_content,
        file_name=f"validation_report_{st.session_state.scenario_name.replace(' ', '_')}.md",
        mime="text/markdown"
    )