# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_service_guide.py
"""
Service Guide for Replica Builder
Lists service requirement YAMLs (workspace + global) and displays their content.
Discovery/reading is shared via components.service_catalog.
"""
import streamlit as st
import yaml
from typing import Dict, List, Any, Optional

from components.service_catalog import services_by_name, read_service_text


def load_service_yaml_files():
    """Available services keyed by name — workspace `services/` + global library."""
    return services_by_name()


def parse_service_yaml(yaml_content: Dict[str, Any]) -> Dict[str, Any]:
    """Parse service YAML to extract components, attributes, and links in a user-friendly format"""
    result = {
        'components': {},  # {component_type: [list of attributes]}
        'links': set()  # Use set for unique links
    }

    def extract_component_type(uri_value: str) -> Optional[str]:
        """Extract component type from URI pattern like 'Location.URI' -> 'Location'"""
        if isinstance(uri_value, str) and '.' in uri_value:
            comp_type = uri_value.split('.')[0]
            # Exclude Scenario from components
            if comp_type != 'Scenario':
                return comp_type
        return None

    def extract_attribute_name(attr_value: str) -> Optional[str]:
        """Extract attribute name from pattern, handling nested properties
        Examples:
        - 'Location.WeatherEPW' -> 'WeatherEPW'
        - 'EnergyGenerator.Power.hasHistoricTimeSeriesReference' -> 'Power.hasHistoricTimeSeriesReference'
        """
        if isinstance(attr_value, str) and '.' in attr_value:
            parts = attr_value.split('.')
            if len(parts) >= 2:
                # Return everything after the component type (first part)
                return '.'.join(parts[1:])
        return None

    def parse_component_block(block: Dict[str, Any], parent_key: str = None):
        """Recursively parse a component block"""
        if not isinstance(block, dict):
            return

        # Check if this block has a URI field (indicates it's a component)
        # Can be either 'uri' or 'name' field
        uri_field = block.get('uri') or block.get('name')
        if uri_field:
            component_type = extract_component_type(uri_field)
            if component_type:
                if component_type not in result['components']:
                    result['components'][component_type] = []

                # Extract attributes from this component
                for key, value in block.items():
                    if key in ['uri', 'name', 'link', 'template']:
                        continue

                    # Check if value is a component.attribute pattern
                    if isinstance(value, str):
                        attr_name = extract_attribute_name(value)
                        if attr_name and attr_name not in result['components'][component_type]:
                            result['components'][component_type].append(attr_name)
                    elif isinstance(value, dict):
                        # Recursively parse nested structures
                        parse_component_block(value, key)

        # Check for links
        if 'link' in block:
            link_value = block['link']
            if isinstance(link_value, str) and link_value.strip():  # Only add non-empty links
                result['links'].add(link_value)

        # Check for template blocks (common in service YAMLs)
        if 'template' in block:
            parse_component_block(block['template'], parent_key)

        # Recursively process nested dictionaries
        for key, value in block.items():
            if key not in ['uri', 'name', 'link', 'template'] and isinstance(value, dict):
                parse_component_block(value, key)

    # Start parsing from scenario_data
    scenario_data = yaml_content.get('scenario_data', {})
    parse_component_block(scenario_data)

    # Convert links set to sorted list
    result['links'] = sorted(list(result['links']))

    return result


def show_service_guide_expander():
    """Display service guide in an expander - shows raw YAML and parsed view"""

    with st.expander("📋 Service Guide - View Service Requirements", expanded=False):
        st.write("Select a service to view its requirements for building your digital replica.")

        yaml_files = load_service_yaml_files()

        if not yaml_files:
            st.info("No service requirement YAMLs found. Add one to the workspace `services/` folder (or NextCloud `global/services/`).")
            st.caption("The Scenario Builder's \"Save to Workspace\" writes service definitions here.")
            return

        service_names = ["-- Select a Service --"] + sorted(list(yaml_files.keys()))
        selected_service = st.selectbox(
            "Available Services",
            service_names,
            key="replica_service_selector"
        )

        if selected_service == "-- Select a Service --":
            st.info("👆 Select a service to view its requirements")
            return

        service_ref = yaml_files[selected_service]

        st.markdown("---")
        st.subheader(f"📦 {selected_service}")
        st.caption(f"Source: `{service_ref.ref}` ({service_ref.source})")

        # Get the YAML content (workspace storage or global library)
        try:
            yaml_text = read_service_text(service_ref)
            if not yaml_text:
                st.error("Could not load YAML content")
                return

            # Parse YAML
            yaml_content = yaml.safe_load(yaml_text)

            # Radio buttons for view selection
            view_mode = st.radio(
                "Display Mode",
                ["Requirements", "Raw YAML"],
                horizontal=True,
                key="service_view_mode"
            )

            st.markdown("---")

            if view_mode == "Raw YAML":
                # Show raw YAML
                st.code(yaml_text, language='yaml', line_numbers=True)
            else:
                # Show parsed user-friendly view
                parsed = parse_service_yaml(yaml_content)

                if parsed['components']:
                    st.write("### 🔧 Required Components and Attributes")

                    for comp_type, attributes in sorted(parsed['components'].items()):
                        if attributes:
                            # Display as horizontal comma-separated list
                            attr_list = ", ".join(f"`{attr}`" for attr in sorted(attributes))
                            st.write(f"**{comp_type}:** {attr_list}")
                        else:
                            st.write(f"**{comp_type}:** No specific attributes required")
                else:
                    st.info("No components found in this service definition")

                if parsed['links']:
                    st.write("### 🔗 Required Links")
                    for link in parsed['links']:
                        if link:  # Only display non-empty links
                            st.write(f"- `{link}`")
                else:
                    st.info("No links defined in this service")

        except yaml.YAMLError as e:
            st.error(f"Error parsing YAML: {e}")
        except Exception as e:
            st.error(f"Error loading service: {e}")