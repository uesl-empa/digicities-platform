# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Data Explorer Module
File: components/data_products/data_explorer.py

Handles exploration of data products, components, and their attributes.
"""

import streamlit as st
from typing import Dict, List, Optional, Any
import pandas as pd


class DataProductExplorer:
    """Explorer for data products and their components"""

    def __init__(self):
        """Initialize explorer"""
        self.current_product = None
        self.current_component = None

    def explore_data_product(self, product: Dict) -> None:
        """Main exploration interface for a data product"""
        st.subheader(f"📦 Data Product: {product['name']}")

        # Product metadata
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            badge = "🌍" if product['type'] == 'global' else "🔒"
            st.info(f"**Type:** {badge} {product['type'].title()}")
        with col2:
            st.info(f"**Components:** {product.get('component_count', 0)}")
        with col3:
            st.info(f"**Types:** {len(product.get('component_types', []))}")
        with col4:
            if product.get('resources'):
                st.info(f"**Resources:** {len(product.get('resources', {}))}")

        # Component type breakdown
        if product.get('components'):
            st.markdown("### Component Types")
            self._display_component_types(product['components'])

            st.markdown("### Component Explorer")
            selected_component = self._component_selector(product['components'])

            if selected_component:
                self._display_component_details(selected_component)

    def _display_component_types(self, components: Dict[str, List]) -> None:
        """Display component type statistics"""
        type_data = []
        for comp_type, comp_list in components.items():
            type_data.append({
                'Type': comp_type,
                'Count': len(comp_list),
                'Has Resources': sum(1 for c in comp_list if c.get('resources')),
                'Attributes': sum(len(c.get('attributes', {})) for c in comp_list) // len(comp_list) if comp_list else 0
            })

        if type_data:
            df = pd.DataFrame(type_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

    def _component_selector(self, components: Dict[str, List]) -> Optional[Dict]:
        """Component selection interface"""
        # Flatten components for selection
        all_components = []
        for comp_type, comp_list in components.items():
            for component in comp_list:
                all_components.append(component)

        if not all_components:
            st.warning("No components found in this data product")
            return None

        # Component filter
        col1, col2 = st.columns([2, 1])

        with col1:
            # Create selection options
            options = []
            for i, comp in enumerate(all_components):
                label = comp.get('label', 'Unknown')
                comp_type = comp.get('type', 'Unknown')
                has_resources = "📁" if comp.get('resources') else ""
                options.append(f"{has_resources} {label} ({comp_type})")

            selected_idx = st.selectbox(
                "Select Component:",
                range(len(options)),
                format_func=lambda x: options[x],
                key="component_selector"
            )

        with col2:
            # Filter by type
            comp_types = list(components.keys())
            filter_type = st.selectbox(
                "Filter by Type:",
                ["All"] + comp_types,
                key="component_type_filter"
            )

        if selected_idx is not None:
            return all_components[selected_idx]

        return None

    def _display_component_details(self, component: Dict) -> None:
        """Display detailed component information"""
        st.markdown("---")
        st.markdown(f"### Component: {component.get('label', 'Unknown')}")

        # Component info tabs - simplified
        tab1, tab2 = st.tabs(["📋 Attributes", "🔗 Metadata"])

        with tab1:
            self._display_attributes(component.get('attributes', {}))

        with tab2:
            self._display_metadata(component)

    def _display_attributes(self, attributes: Dict) -> None:
        """Display component attributes"""
        if not attributes:
            st.info("No attributes found for this component")
            return

        # Group attributes by category
        categories = {}
        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                category = attr_data.get('category', 'unknown')
                if category not in categories:
                    categories[category] = []
                categories[category].append((attr_name, attr_data))

        # Display by category
        for category, attrs in categories.items():
            if category != 'unknown':
                st.write(f"**{category.title()} Attributes**")

            attr_data = []
            for attr_name, attr_info in attrs:
                row = {
                    'Name': attr_name.replace('_', ' ').title(),
                    'Value': self._format_attribute_value(attr_info),
                    'Unit': attr_info.get('unit', ''),
                    'Type': attr_info.get('attribute_type', 'unknown')
                }

                # Add resource indicator
                if attr_info.get('resource_reference'):
                    row['Resource'] = '📁'
                else:
                    row['Resource'] = ''

                attr_data.append(row)

            if attr_data:
                df = pd.DataFrame(attr_data)
                st.dataframe(df, use_container_width=True, hide_index=True)

    def _format_attribute_value(self, attr_info: Dict) -> str:
        """Format attribute value for display"""
        value = attr_info.get('value', 'N/A')

        # Handle different value types
        if isinstance(value, float):
            # Format numbers nicely
            if value.is_integer():
                return str(int(value))
            else:
                return f"{value:.2f}"
        elif isinstance(value, str):
            # Truncate long strings
            if len(value) > 50:
                return value[:47] + "..."
            return value
        else:
            return str(value)

    def _display_resources(self, resources: Dict) -> None:
        """Display component resources"""
        if not resources:
            st.info("No resources found for this component")

            # Debug information to help troubleshoot
            with st.expander("🔍 Debug: Resource Linking", expanded=False):
                st.write("**Component Resource Debug:**")
                st.write(f"- Resources dict: {resources}")
                st.write("- This means no resource references were found in component attributes")
                st.write("- Check if component attributes have 'resource_reference' fields")
            return

        st.write(f"**Found {len(resources)} resource(s)**")

        for res_name, res_filename in resources.items():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.write(f"**{res_name}:** `{res_filename}`")

            with col2:
                # Determine file type from filename
                if '.csv' in res_filename:
                    file_type = "CSV"
                elif '.json' in res_filename or '.geojson' in res_filename:
                    file_type = "JSON"
                elif '.epw' in res_filename:
                    file_type = "EPW"
                else:
                    file_type = "File"

                st.caption(f"Type: {file_type}")

    def _display_metadata(self, component: Dict) -> None:
        """Display component metadata"""
        metadata = {
            'URI': component.get('uri', 'N/A'),
            'Label': component.get('label', 'N/A'),
            'Type': component.get('type', 'N/A'),
            'Attribute Count': len(component.get('attributes', {})),
            'Resource Count': len(component.get('resources', {}))
        }

        for key, value in metadata.items():
            st.write(f"**{key}:** {value}")

    def get_visualization_type(self, component: Dict) -> str:
        """Determine visualization type for component"""
        attributes = component.get('attributes', {})

        # Check for different data types
        has_geo = False
        has_timeseries = False
        has_curve = False

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                category = attr_data.get('category', '')

                if category == 'geospatial' or 'latitude' in attr_name.lower() or 'longitude' in attr_name.lower():
                    has_geo = True
                elif category == 'dynamic' or attr_data.get('time_series_reference'):
                    has_timeseries = True
                elif category == 'curve' or attr_data.get('data_type') == 'curve':
                    has_curve = True

        # Return primary visualization type
        if has_geo:
            return 'geospatial'
        elif has_timeseries:
            return 'timeseries'
        elif has_curve:
            return 'curve'
        else:
            return 'static'


def render_explorer_tab():
    """Render the explorer tab"""
    st.subheader("🔍 Data Product Explorer")

    # Check if data products are loaded
    if not st.session_state.loaded_data_products:
        st.info("📦 No data products loaded. Please load data products first.")
        return

    # Product selector
    col1, col2 = st.columns([3, 1])

    with col1:
        product_options = {}
        for key, product in st.session_state.loaded_data_products.items():
            badge = "🌍" if product['type'] == 'global' else "🔒"
            display_name = f"{badge} {product['name']} ({product.get('component_count', 0)} components)"
            product_options[display_name] = key

        selected_display = st.selectbox(
            "Select Data Product to Explore:",
            options=list(product_options.keys()),
            key="explorer_product_selector"
        )

        if selected_display:
            selected_key = product_options[selected_display]
            st.session_state.selected_data_product = selected_key

    with col2:
        view_mode = st.radio(
            "View Mode:",
            ["Summary", "Detailed"],
            horizontal=True
        )

    # Display selected product
    if st.session_state.selected_data_product:
        product = st.session_state.loaded_data_products[st.session_state.selected_data_product]

        if view_mode == "Summary":
            display_product_summary(product)
        else:
            explorer = DataProductExplorer()
            explorer.explore_data_product(product)


def display_product_summary(product: Dict):
    """Display summary view of a data product"""
    st.markdown("---")
    st.markdown(f"### 📊 Summary: {product['name']}")

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Components", product.get('component_count', 0))

    with col2:
        st.metric("Component Types", len(product.get('component_types', [])))

    with col3:
        total_attrs = 0
        if product.get('components'):
            for comp_type, comp_list in product['components'].items():
                for comp in comp_list:
                    total_attrs += len(comp.get('attributes', {}))
        st.metric("Total Attributes", total_attrs)

    with col4:
        total_resources = 0
        if product.get('components'):
            for comp_type, comp_list in product['components'].items():
                for comp in comp_list:
                    total_resources += len(comp.get('resources', {}))
        st.metric("Total Resources", total_resources)

    # Component types pie chart
    if product.get('components'):
        st.markdown("### Component Distribution")

        import plotly.express as px

        type_counts = {comp_type: len(comp_list)
                       for comp_type, comp_list in product['components'].items()}

        if type_counts:
            df = pd.DataFrame(list(type_counts.items()), columns=['Type', 'Count'])
            fig = px.pie(df, values='Count', names='Type',
                         title=f"Component Types in {product['name']}")
            st.plotly_chart(fig, use_container_width=True)

    # Attribute categories
    st.markdown("### Attribute Categories")

    category_counts = {}
    if product.get('components'):
        for comp_type, comp_list in product['components'].items():
            for comp in comp_list:
                for attr_name, attr_data in comp.get('attributes', {}).items():
                    if isinstance(attr_data, dict):
                        category = attr_data.get('category', 'unknown')
                        category_counts[category] = category_counts.get(category, 0) + 1

    if category_counts:
        df = pd.DataFrame(list(category_counts.items()), columns=['Category', 'Count'])
        df = df.sort_values('Count', ascending=False)
        st.bar_chart(df.set_index('Category'))

    # Quick component list
    with st.expander("📋 Component List", expanded=False):
        if product.get('components'):
            for comp_type, comp_list in product['components'].items():
                st.write(f"**{comp_type}** ({len(comp_list)} components)")
                for comp in comp_list[:5]:  # Show first 5
                    label = comp.get('label', 'Unknown')
                    attrs = len(comp.get('attributes', {}))
                    resources = "📁" if comp.get('resources') else ""
                    st.caption(f"  • {resources} {label} ({attrs} attributes)")
                if len(comp_list) > 5:
                    st.caption(f"  ... and {len(comp_list) - 5} more")