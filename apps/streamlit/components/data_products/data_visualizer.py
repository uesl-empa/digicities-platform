# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Data Visualizer Module
File: components/data_products/data_visualizer.py

Handles all visualization types: timeseries, geospatial, curves, and static data.
Enhanced with comprehensive attributes display functionality.
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Import data loader for resource loading
from .data_loader import DataProductLoader


class DataVisualizer:
    """Handles visualization of different data types"""

    def __init__(self, product: Dict):
        """Initialize with a data product"""
        self.product = product
        self.loader = DataProductLoader()

    def visualize_component(self, component: Dict) -> None:
        """Main visualization method for a component"""
        viz_data, viz_type = self.get_visualization_data(component)

        # Create tabs for different views
        tab1, tab2 = st.tabs(["📊 Visualization", "📋 Attributes"])

        with tab1:
            if viz_type == "static":
                self.display_static_data(viz_data, component)
            elif viz_type == "geospatial":
                self.display_geospatial_data(viz_data, component)
            elif viz_type == "timeseries":
                self.display_timeseries_data(viz_data, component)
            elif viz_type == "curve":
                self.display_curve_data(viz_data, component)
            else:
                st.warning(f"Unknown visualization type: {viz_type}")

        with tab2:
            self.display_component_attributes(component)

    def display_component_attributes(self, component: Dict) -> None:
        """Display all attributes of a component in a detailed view"""
        st.markdown(f"### 📋 All Attributes: {component.get('label', 'Unknown')}")

        attributes = component.get('attributes', {})

        if not attributes:
            st.info("No attributes found for this component")
            return

        # Component metadata
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**Component Type:** {component.get('type', 'Unknown')}")
        with col2:
            st.info(f"**Total Attributes:** {len(attributes)}")
        with col3:
            resource_count = sum(1 for attr in attributes.values()
                               if isinstance(attr, dict) and attr.get('resource_reference'))
            st.info(f"**With Resources:** {resource_count}")

        # Group attributes by category
        categories = {}
        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                category = attr_data.get('category', 'unknown')
                if category not in categories:
                    categories[category] = []
                categories[category].append((attr_name, attr_data))

        # Display attributes by category
        for category, attrs in categories.items():
            if category != 'unknown' or len(categories) == 1:
                # Create expander for each category
                with st.expander(f"📁 {category.title()} Attributes ({len(attrs)})", expanded=True):
                    self._display_attribute_category(attrs, category)

        # Raw JSON view option
        with st.expander("🔍 Raw Attribute Data (JSON)", expanded=False):
            st.json(attributes)

    def _display_attribute_category(self, attrs: List[tuple], category: str) -> None:
        """Display attributes in a specific category"""
        attr_data = []

        for attr_name, attr_info in attrs:
            # Format the attribute information
            row = {
                'Attribute': attr_name.replace('_', ' ').title(),
                'Value': self._format_attribute_value(attr_info),
                'Unit': attr_info.get('unit', ''),
                'Type': attr_info.get('attribute_type', 'unknown'),
                'Resource': '📁' if attr_info.get('resource_reference') else '',
                'URI': attr_info.get('uri', '')
            }

            # Add category-specific information
            if category == 'cost':
                if attr_info.get('currency'):
                    row['Currency'] = attr_info.get('currency')
            elif category == 'dynamic':
                if attr_info.get('time_series_type'):
                    row['Series Type'] = attr_info.get('time_series_type')
            elif category == 'geospatial':
                # Already shown in Value/Unit
                pass
            elif category == 'curve':
                if attr_info.get('x_unit'):
                    row['X Unit'] = attr_info.get('x_unit')
                if attr_info.get('y_unit'):
                    row['Y Unit'] = attr_info.get('y_unit')
            elif category == 'temporal':
                if attr_info.get('temporal_precision'):
                    row['Precision'] = attr_info.get('temporal_precision')

            attr_data.append(row)

        if attr_data:
            # Convert to DataFrame for better display
            df = pd.DataFrame(attr_data)

            # Remove empty columns
            df = df.loc[:, (df != '').any(axis=0)]

            # Display the table
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Show resource details if any
            resources = [(name, info) for name, info in attrs
                        if isinstance(info, dict) and info.get('resource_reference')]

            if resources:
                st.markdown("**📁 Resource References:**")
                for attr_name, attr_info in resources:
                    resource_ref = attr_info.get('resource_reference')
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.caption(f"• **{attr_name}**: `{resource_ref}`")

                    with col2:
                        # Try to determine file type and show load button
                        if resource_ref.endswith('.csv'):
                            if st.button(f"📊 Load CSV", key=f"load_{attr_name}", help=f"Load {resource_ref}"):
                                self._load_and_display_resource(attr_info, attr_name)
                        elif resource_ref.endswith(('.json', '.geojson')):
                            if st.button(f"🗺️ Load GeoJSON", key=f"load_{attr_name}", help=f"Load {resource_ref}"):
                                self._load_and_display_resource(attr_info, attr_name)

    def _format_attribute_value(self, attr_info: Dict) -> str:
        """Format attribute value for display with enhanced formatting"""
        value = attr_info.get('value', 'N/A')

        # Handle different value types
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            else:
                return f"{value:.3f}"
        elif isinstance(value, str):
            # Handle special cases
            if value.startswith('Time series:'):
                return f"🔗 {value}"
            elif 'resources/' in value:
                return f"📁 {value}"
            elif len(value) > 60:
                return value[:57] + "..."
            return value
        elif value is None or value == 'N/A':
            return '—'
        else:
            return str(value)

    def _load_and_display_resource(self, attr_info: Dict, attr_name: str) -> None:
        """Load and display a resource file"""
        resource_ref = attr_info.get('resource_reference')
        if not resource_ref:
            st.error("No resource reference found")
            return

        try:
            # Load the resource using the data loader
            resource_data = self.loader.load_resource_file(self.product, resource_ref)

            if resource_data is None:
                st.error(f"Could not load resource: {resource_ref}")
                return

            st.success(f"Loaded resource: {resource_ref}")

            if isinstance(resource_data, pd.DataFrame):
                st.markdown(f"**📊 CSV Data Preview ({len(resource_data)} rows)**")
                st.dataframe(resource_data.head(10), use_container_width=True)

                # Show download option
                csv = resource_data.to_csv(index=False)
                st.download_button(
                    label="📥 Download Full CSV",
                    data=csv,
                    file_name=f"{attr_name}_{resource_ref.split('/')[-1]}",
                    mime="text/csv"
                )

            elif isinstance(resource_data, dict):
                st.markdown(f"**🗺️ GeoJSON Data**")
                st.json(resource_data)

            else:
                st.markdown(f"**📄 Resource Content**")
                st.text(str(resource_data)[:1000] + "..." if len(str(resource_data)) > 1000 else str(resource_data))

        except Exception as e:
            st.error(f"Error loading resource: {e}")

    def get_visualization_data(self, component: Dict) -> Tuple[Any, str]:
        """Determine visualization type and extract data"""
        # Check for different data types
        if self._has_geospatial_data(component):
            return self._extract_geospatial_data(component), "geospatial"
        elif self._has_timeseries_data(component):
            return self._extract_timeseries_data(component), "timeseries"
        elif self._has_curve_data(component):
            return self._extract_curve_data(component), "curve"
        else:
            return self._extract_static_data(component), "static"

    def _has_geospatial_data(self, component: Dict) -> bool:
        """Check if component has geospatial attributes"""
        geo_indicators = ['latitude', 'longitude', 'geometry', 'coordinates', 'elevation', 'location']
        attributes = component.get('attributes', {})

        for attr_name, attr_data in attributes.items():
            if any(indicator in attr_name.lower() for indicator in geo_indicators):
                return True
            if isinstance(attr_data, dict) and attr_data.get('category') == 'geospatial':
                return True

        return False

    def _has_timeseries_data(self, component: Dict) -> bool:
        """Check if component has time series data"""
        attributes = component.get('attributes', {})

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                if attr_data.get('category') == 'dynamic':
                    return True
                if attr_data.get('time_series_reference'):
                    return True
                if attr_data.get('resource_reference'):
                    ref = attr_data['resource_reference']
                    if 'timeseries' in ref.lower() or '.csv' in ref:
                        return True

        return False

    def _has_curve_data(self, component: Dict) -> bool:
        """Check if component has curve data"""
        attributes = component.get('attributes', {})

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict) and attr_data.get('data_type') == 'curve':
                return True

        return False

    def _extract_geospatial_data(self, component: Dict) -> Optional[Dict]:
        """Extract geospatial data"""
        attributes = component.get('attributes', {})

        # Look for lat/lon
        lat = None
        lon = None

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                if 'latitude' in attr_name.lower() or 'lat' in attr_name.lower():
                    lat = attr_data.get('value')
                elif 'longitude' in attr_name.lower() or 'lon' in attr_name.lower():
                    lon = attr_data.get('value')

        if lat and lon:
            return {
                'type': 'Point',
                'coordinates': [float(lon), float(lat)],
                'properties': {
                    'name': component.get('label', 'Unknown'),
                    'uri': component.get('uri', ''),
                    'attributes': attributes,
                    'component_type': component.get('type', 'Unknown')
                }
            }

        # Check for geojson resource
        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict) and attr_data.get('resource_reference'):
                if '.geojson' in attr_data['resource_reference']:
                    geojson_data = self.loader.load_resource_file(
                        self.product,
                        attr_data['resource_reference']
                    )
                    if geojson_data:
                        return geojson_data

        return None

    def _extract_timeseries_data(self, component: Dict) -> pd.DataFrame:
        """Extract time series data"""
        attributes = component.get('attributes', {})

        # Look for time series resource references
        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                resource_ref = attr_data.get('resource_reference') or attr_data.get('time_series_reference', '')

                if resource_ref:
                    # Load the time series file
                    ts_data = self.loader.load_resource_file(self.product, resource_ref)
                    if isinstance(ts_data, pd.DataFrame):
                        return ts_data

        # Generate mock data if no resource found
        return self._create_mock_timeseries(component)

    def _extract_curve_data(self, component: Dict) -> Optional[pd.DataFrame]:
        """Extract curve data"""
        attributes = component.get('attributes', {})

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict) and attr_data.get('data_type') == 'curve':
                resource_ref = attr_data.get('resource_reference') or attr_data.get('data_points', '')

                if resource_ref:
                    # Load the curve data file
                    curve_data = self.loader.load_resource_file(self.product, resource_ref)
                    if isinstance(curve_data, pd.DataFrame):
                        return curve_data

        return None

    def _extract_static_data(self, component: Dict) -> pd.DataFrame:
        """Extract static attributes as tabular data"""
        attributes = component.get('attributes', {})
        data = []

        for attr_name, attr_data in attributes.items():
            if isinstance(attr_data, dict):
                row = {
                    'Attribute': attr_name.replace('_', ' ').title(),
                    'Value': attr_data.get('value', 'N/A'),
                    'Unit': attr_data.get('unit', ''),
                    'Type': attr_data.get('attribute_type', 'unknown'),
                    'Category': attr_data.get('category', 'unknown')
                }
                data.append(row)

        return pd.DataFrame(data) if data else None

    def _create_mock_timeseries(self, component: Dict) -> pd.DataFrame:
        """Create mock time series data for demonstration"""
        start_date = datetime.now() - timedelta(days=7)
        dates = [start_date + timedelta(hours=i) for i in range(168)]

        component_type = component.get('type', '').lower()

        if 'solar' in component_type or 'pv' in component_type:
            # Solar pattern: daily cycles
            values = [max(0, 500 + 400 * np.sin((i % 24) * np.pi / 12) + np.random.normal(0, 50))
                      for i in range(168)]
        elif 'wind' in component_type:
            # Wind pattern: more random
            values = [max(0, 300 + np.random.normal(0, 150)) for _ in range(168)]
        else:
            # Generic pattern
            values = [100 + 50 * np.sin(i * 2 * np.pi / 24) + np.random.normal(0, 20)
                      for i in range(168)]

        return pd.DataFrame({
            'timestamp': dates,
            'value': values,
            'component': component.get('label', 'Unknown')
        })

    def display_static_data(self, df: pd.DataFrame, component: Dict) -> None:
        """Display static component data in tabular format"""
        st.markdown(f"### 📊 Static Data: {component.get('label', 'Unknown')}")

        col1, col2 = st.columns([2, 1])

        with col1:
            if df is not None and not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No attribute data available")

        with col2:
            st.info(f"**Component Type:** {component.get('type', 'Unknown')}")

            if df is not None and not df.empty:
                # Count by category
                if 'Category' in df.columns:
                    category_counts = df['Category'].value_counts()
                    for category, count in category_counts.items():
                        if category != 'unknown':
                            st.metric(f"{category.title()} Attrs", count)

    def display_geospatial_data(self, geometry_data: Dict, component: Dict) -> None:
        """Display geospatial data on a map"""
        st.markdown(f"### 🗺️ Geospatial Data: {component.get('label', 'Unknown')}")

        if geometry_data and geometry_data.get('type') == 'Point':
            lon, lat = geometry_data['coordinates']

            # Create plotly map
            fig = px.scatter_mapbox(
                lat=[lat],
                lon=[lon],
                hover_name=[component.get('label', 'Unknown')],
                zoom=8,
                height=500,
                title=f"Location: {component.get('label', 'Unknown')}"
            )
            fig.update_layout(mapbox_style="open-street-map")
            fig.update_layout(margin={"r": 0, "t": 30, "l": 0, "b": 0})

            col1, col2 = st.columns([3, 1])

            with col1:
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                st.info(f"**Coordinates:**\nLat: {lat:.6f}\nLon: {lon:.6f}")
                st.info(f"**Component Type:** {component.get('type', 'Unknown')}")

                # Show other geo attributes
                attributes = component.get('attributes', {})
                for attr_name, attr_data in attributes.items():
                    if isinstance(attr_data, dict):
                        if 'elevation' in attr_name.lower():
                            value = attr_data.get('value', 'N/A')
                            unit = attr_data.get('unit', '')
                            st.metric("Elevation", f"{value} {unit}")
        else:
            st.warning("No valid geospatial data found")

    def display_timeseries_data(self, df: pd.DataFrame, component: Dict) -> None:
        """Display time series data with interactive plots"""
        st.markdown(f"### 📈 Time Series Data: {component.get('label', 'Unknown')}")

        if df is not None and not df.empty:
            # Ensure proper columns
            if 'timestamp' in df.columns and 'value' in df.columns:
                # Create interactive plot
                fig = px.line(
                    df,
                    x='timestamp',
                    y='value',
                    title=f"Time Series: {component.get('label', 'Unknown')}",
                    labels={'value': 'Value', 'timestamp': 'Time'}
                )

                # Add range slider
                fig.update_xaxes(rangeslider_visible=True)

                st.plotly_chart(fig, use_container_width=True)

                # Show statistics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Min", f"{df['value'].min():.2f}")
                with col2:
                    st.metric("Max", f"{df['value'].max():.2f}")
                with col3:
                    st.metric("Mean", f"{df['value'].mean():.2f}")
                with col4:
                    st.metric("Points", len(df))

                # Data download option
                with st.expander("📊 View Raw Data"):
                    st.dataframe(df, use_container_width=True)

                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name=f"{component.get('label', 'data')}_timeseries.csv",
                        mime="text/csv"
                    )
            else:
                st.warning("Time series data missing required columns (timestamp, value)")
        else:
            st.info("No time series data available")

    def display_curve_data(self, df: pd.DataFrame, component: Dict) -> None:
        """Display curve data"""
        st.markdown(f"### 📉 Curve Data: {component.get('label', 'Unknown')}")

        if df is not None and not df.empty:
            # Try to identify x and y columns
            if len(df.columns) >= 2:
                x_col = df.columns[0]
                y_col = df.columns[1]

                # Create interactive plot
                fig = px.line(
                    df,
                    x=x_col,
                    y=y_col,
                    title=f"Curve: {component.get('label', 'Unknown')}",
                    markers=True
                )

                st.plotly_chart(fig, use_container_width=True)

                # Show statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Data Points", len(df))
                with col2:
                    st.metric(f"Min {y_col}", f"{df[y_col].min():.2f}")
                with col3:
                    st.metric(f"Max {y_col}", f"{df[y_col].max():.2f}")

                # Show data points
                with st.expander("📊 Data Points", expanded=False):
                    st.dataframe(df, use_container_width=True)
            else:
                st.warning("Insufficient data for curve visualization")
        else:
            st.info("No curve data available")


def render_analytics_tab():
    """Render the analytics/visualization tab"""
    st.subheader("📊 Data Analytics & Visualization")

    # Check if data products are loaded
    if not st.session_state.loaded_data_products:
        st.info("📦 No data products loaded. Please load data products first.")
        return

    # Data product selector - same as Explorer tab
    col1, col2 = st.columns([3, 1])

    with col1:
        product_options = {}
        for key, product in st.session_state.loaded_data_products.items():
            badge = "🌍" if product['type'] == 'global' else "🔒"
            display_name = f"{badge} {product['name']} ({product.get('component_count', 0)} components)"
            product_options[display_name] = key

        selected_display = st.selectbox(
            "Select Data Product to Analyze:",
            options=list(product_options.keys()),
            key="analytics_product_selector"
        )

        if selected_display:
            selected_key = product_options[selected_display]
            st.session_state.selected_data_product = selected_key

    with col2:
        # View mode selection
        view_mode = st.radio(
            "Focus on:",
            ["Visualization", "Attributes"],
            horizontal=True,
            key="analytics_focus_mode"
        )

    # Check if a product is selected
    if not st.session_state.selected_data_product:
        st.info("🔍 Please select a data product to analyze.")
        return

    product = st.session_state.loaded_data_products[st.session_state.selected_data_product]

    st.write(f"**Analyzing:** {product['name']} ({product['type'].title()})")

    # Component filter and selection
    st.markdown("### Select Component to Analyze")

    # Get all components
    all_components = []
    for comp_type, comp_list in product.get('components', {}).items():
        for component in comp_list:
            all_components.append(component)

    if not all_components:
        st.warning("No components found in selected data product")
        return

    # Visualization type filter
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        # Component selector with visualization indicators
        visualizer = DataVisualizer(product)

        options = []
        viz_types = []
        for i, comp in enumerate(all_components):
            _, viz_type = visualizer.get_visualization_data(comp)
            viz_types.append(viz_type)

            label = comp.get('label', 'Unknown')
            comp_type = comp.get('type', 'Unknown')

            # Add visualization type emoji
            viz_emoji = {
                "static": "📊",
                "geospatial": "🗺️",
                "timeseries": "📈",
                "curve": "📉"
            }.get(viz_type, "❓")

            has_resources = "📁" if comp.get('resources') else ""
            attr_count = len(comp.get('attributes', {}))
            options.append(f"{viz_emoji} {has_resources} {label} ({comp_type}) - {attr_count} attrs")

        selected_idx = st.selectbox(
            "Select Component:",
            range(len(options)),
            format_func=lambda x: options[x],
            key="analytics_component_selector"
        )

    with col2:
        # Filter by visualization type
        unique_viz_types = list(set(viz_types))
        viz_filter = st.selectbox(
            "Filter by Viz Type:",
            ["All"] + unique_viz_types,
            key="viz_type_filter"
        )

    with col3:
        # View mode selection
        analysis_view_mode = st.radio(
            "Focus on:",
            ["Visualization", "Attributes"],
            horizontal=True,
            key="analytics_analysis_view_mode"
        )

    # Display visualization
    if selected_idx is not None:
        component = all_components[selected_idx]
        viz_type = viz_types[selected_idx]

        if viz_filter == "All" or viz_type == viz_filter:
            st.markdown("---")

            # Component info header
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.info(f"**Component:** {component.get('label', 'Unknown')}")
            with col2:
                st.info(f"**Type:** {component.get('type', 'Unknown')}")
            with col3:
                st.info(f"**Viz Type:** {viz_type.title()}")
            with col4:
                attr_count = len(component.get('attributes', {}))
                st.info(f"**Attributes:** {attr_count}")

            # Show visualization or attributes based on view mode
            if analysis_view_mode == "Attributes":
                visualizer.display_component_attributes(component)
            else:
                # Visualize the component
                visualizer.visualize_component(component)

            # Navigation buttons
            col1, col2, col3 = st.columns([1, 1, 1])

            with col1:
                if selected_idx > 0:
                    if st.button("⬅️ Previous", use_container_width=True):
                        st.session_state.analytics_component_selector = selected_idx - 1
                        st.rerun()

            with col2:
                if st.button("🔄 Refresh", use_container_width=True):
                    st.rerun()

            with col3:
                if selected_idx < len(all_components) - 1:
                    if st.button("➡️ Next", use_container_width=True):
                        st.session_state.analytics_component_selector = selected_idx + 1
                        st.rerun()

        else:
            st.info(f"Component has visualization type '{viz_type}' but filter is set to '{viz_filter}'")

    # Summary statistics
    with st.expander("📊 Analytics Summary", expanded=False):
        viz_type_counts = {}
        for vt in viz_types:
            viz_type_counts[vt] = viz_type_counts.get(vt, 0) + 1

        st.write("**Visualization Type Distribution:**")
        for vt, count in viz_type_counts.items():
            st.write(f"- {vt.title()}: {count} components")

        # Resource statistics
        resource_count = sum(1 for comp in all_components if comp.get('resources'))
        st.write(f"\n**Components with Resources:** {resource_count}/{len(all_components)}")

        # Attribute statistics
        total_attrs = sum(len(comp.get('attributes', {})) for comp in all_components)
        avg_attrs = total_attrs / len(all_components) if all_components else 0
        st.write(f"**Average Attributes per Component:** {avg_attrs:.1f}")