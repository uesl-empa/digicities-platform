# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Resource Analyzer Module
File: components/data_products/resource_analyzer.py

Handles analysis and visualization of resource files from data products.
Supports CSV timeseries, GeoJSON visualization, and raw data viewing.
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
import json
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import io

# Import data loader for resource loading
from .data_loader import DataProductLoader


class ResourceAnalyzer:
    """Analyzes and visualizes data product resource files"""

    def __init__(self, product: Dict):
        """Initialize with a data product"""
        self.product = product
        self.loader = DataProductLoader()

    def analyze_all_resources(self) -> None:
        """Main interface for analyzing all resources in a data product"""
        st.markdown(f"### 📁 Resource Analysis: {self.product['name']}")

        # Get all resource files from the data product
        resources = self.product.get('resources', [])

        if not resources:
            st.info("No resource files found in this data product")

            # Debug information
            with st.expander("🔍 Debug Information", expanded=False):
                st.write("**Data Product Structure:**")
                st.write(f"- Name: {self.product.get('name')}")
                st.write(f"- Type: {self.product.get('type')}")
                st.write(f"- Resource Path: {self.product.get('resource_path')}")
                st.write(f"- Resources in product: {len(resources)}")

                # Check if components have resource references
                components = self.product.get('components', {})
                resource_refs = []
                for comp_type, comp_list in components.items():
                    for comp in comp_list:
                        attrs = comp.get('attributes', {})
                        for attr_name, attr_data in attrs.items():
                            if isinstance(attr_data, dict) and attr_data.get('resource_reference'):
                                resource_refs.append(attr_data.get('resource_reference'))

                if resource_refs:
                    st.write(f"**Resource references found in components:** {resource_refs}")
                else:
                    st.write("**No resource references found in component attributes**")

            return

        # Group resources by type
        resource_types = self._group_resources_by_type(resources)

        # Display resource summary
        self._display_resource_summary(resource_types)

        # Resource selection and analysis
        self._render_resource_selection_interface(resources)

    def _group_resources_by_type(self, resources: List[Dict]) -> Dict[str, List[Dict]]:
        """Group resources by file type"""
        grouped = {}

        for resource in resources:
            file_type = resource.get('type', 'unknown')
            if file_type not in grouped:
                grouped[file_type] = []
            grouped[file_type].append(resource)

        return grouped

    def _display_resource_summary(self, resource_types: Dict[str, List[Dict]]) -> None:
        """Display summary of available resource types"""
        st.markdown("#### 📊 Resource Summary")

        cols = st.columns(min(len(resource_types), 4))

        for i, (file_type, resources) in enumerate(resource_types.items()):
            with cols[i % len(cols)]:
                # Choose appropriate emoji and color based on file type
                type_info = self._get_type_info(file_type)
                st.metric(
                    f"{type_info['emoji']} {file_type.upper()}",
                    len(resources),
                    help=f"{file_type} files"
                )

    def _get_type_info(self, file_type: str) -> Dict[str, str]:
        """Get display information for file types"""
        type_mapping = {
            'csv': {'emoji': '📊', 'description': 'Tabular data'},
            'geojson': {'emoji': '🗺️', 'description': 'Geographic data'},
            'json': {'emoji': '📄', 'description': 'Structured data'},
            'epw': {'emoji': '🌤️', 'description': 'Weather data'},
            'txt': {'emoji': '📝', 'description': 'Text data'},
            'xml': {'emoji': '🏷️', 'description': 'XML data'},
            'unknown': {'emoji': '❓', 'description': 'Unknown format'}
        }
        return type_mapping.get(file_type, type_mapping['unknown'])

    def _render_resource_selection_interface(self, resources: List[Dict]) -> None:
        """Render the resource selection and analysis interface"""
        st.markdown("#### 🔍 Resource Analysis")

        # Resource selector
        col1, col2 = st.columns([2, 1])

        with col1:
            resource_options = []
            for i, resource in enumerate(resources):
                type_info = self._get_type_info(resource.get('type', 'unknown'))
                size_mb = resource.get('size', 0) / (1024 * 1024) if resource.get('size') else 0
                resource_options.append(
                    f"{type_info['emoji']} {resource['name']} ({resource['type']}) - {size_mb:.2f} MB"
                )

            selected_idx = st.selectbox(
                "Select Resource to Analyze:",
                range(len(resources)),
                format_func=lambda x: resource_options[x],
                key="resource_analyzer_selector"
            )

        with col2:
            analysis_mode = st.radio(
                "Analysis Mode:",
                ["Auto", "Raw Data", "Visualization"],
                horizontal=True,
                help="Auto: Automatic analysis based on file type"
            )

        if selected_idx is not None:
            selected_resource = resources[selected_idx]
            st.markdown("---")

            # Display resource info
            self._display_resource_info(selected_resource)

            # Analyze the selected resource
            self._analyze_single_resource(selected_resource, analysis_mode)

    def _display_resource_info(self, resource: Dict) -> None:
        """Display information about a selected resource"""
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.info(f"**File:** {resource['name']}")
        with col2:
            st.info(f"**Type:** {resource['type'].upper()}")
        with col3:
            size_mb = resource.get('size', 0) / (1024 * 1024) if resource.get('size') else 0
            st.info(f"**Size:** {size_mb:.2f} MB")
        with col4:
            modified = resource.get('last_modified', 'Unknown')
            if modified and modified != 'Unknown':
                try:
                    # Try to parse and format the date
                    dt = datetime.fromisoformat(modified.replace('Z', '+00:00'))
                    formatted_date = dt.strftime('%Y-%m-%d')
                    st.info(f"**Modified:** {formatted_date}")
                except:
                    st.info(f"**Modified:** {modified[:10]}")
            else:
                st.info("**Modified:** Unknown")

    def _analyze_single_resource(self, resource: Dict, analysis_mode: str) -> None:
        """Analyze a single resource file"""
        resource_name = resource['name']
        file_type = resource.get('type', 'unknown')

        try:
            # Load the resource data
            with st.spinner(f"Loading {resource_name}..."):
                data = self.loader.load_resource_file(self.product, resource_name)

            if data is None:
                st.error(f"Could not load resource: {resource_name}")
                return

            st.success(f"Successfully loaded {resource_name}")

            # Analyze based on mode and file type
            if analysis_mode == "Raw Data":
                self._display_raw_data(data, resource)
            elif analysis_mode == "Visualization":
                self._display_visualization(data, resource)
            else:  # Auto mode
                self._auto_analyze_resource(data, resource)

        except Exception as e:
            st.error(f"Error analyzing resource {resource_name}: {str(e)}")

    def _auto_analyze_resource(self, data: Any, resource: Dict) -> None:
        """Automatically analyze resource based on its type and content"""
        file_type = resource.get('type', 'unknown')

        if file_type == 'csv' and isinstance(data, pd.DataFrame):
            self._analyze_csv_data(data, resource)
        elif file_type in ['geojson', 'json'] and isinstance(data, dict):
            self._analyze_geojson_data(data, resource)
        elif file_type == 'epw' and isinstance(data, str):
            self._analyze_epw_data(data, resource)
        else:
            # Default to raw data view
            self._display_raw_data(data, resource)

    def _analyze_csv_data(self, df: pd.DataFrame, resource: Dict) -> None:
        """Analyze CSV data with automatic timeseries detection"""
        st.markdown(f"### 📊 CSV Analysis: {resource['name']}")

        # Basic info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Rows", len(df))
        with col2:
            st.metric("Columns", len(df.columns))
        with col3:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            st.metric("Numeric Columns", len(numeric_cols))
        with col4:
            missing_values = df.isnull().sum().sum()
            st.metric("Missing Values", missing_values)

        # Data preview
        st.markdown("#### 📋 Data Preview")
        st.dataframe(df.head(10), use_container_width=True)

        # Column analysis
        st.markdown("#### 📈 Column Analysis")
        col_analysis = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            unique_vals = df[col].nunique()
            null_count = df[col].isnull().sum()

            col_analysis.append({
                'Column': col,
                'Type': dtype,
                'Unique Values': unique_vals,
                'Null Count': null_count,
                'Sample Values': str(df[col].dropna().head(3).tolist())[:50] + "..."
            })

        col_df = pd.DataFrame(col_analysis)
        st.dataframe(col_df, use_container_width=True, hide_index=True)

        # Detect and plot timeseries
        self._detect_and_plot_timeseries(df, resource)

        # Download option
        self._add_download_option(df, resource)

    def _detect_and_plot_timeseries(self, df: pd.DataFrame, resource: Dict) -> None:
        """Detect timeseries columns and create visualizations"""
        st.markdown("#### 📈 Timeseries Visualization")

        # Try to detect datetime columns
        datetime_cols = []
        for col in df.columns:
            if df[col].dtype == 'object':
                # Try to parse as datetime
                try:
                    pd.to_datetime(df[col].head(10))
                    datetime_cols.append(col)
                except:
                    pass
            elif 'datetime' in str(df[col].dtype):
                datetime_cols.append(col)

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if datetime_cols and numeric_cols:
            col1, col2 = st.columns(2)

            with col1:
                selected_time_col = st.selectbox(
                    "Time Column:",
                    datetime_cols,
                    key=f"time_col_{resource['name']}"
                )

            with col2:
                selected_value_cols = st.multiselect(
                    "Value Columns:",
                    numeric_cols,
                    default=numeric_cols[:3],  # Default to first 3 numeric columns
                    key=f"value_cols_{resource['name']}"
                )

            if selected_time_col and selected_value_cols:
                try:
                    # Convert time column to datetime
                    df_plot = df.copy()
                    df_plot[selected_time_col] = pd.to_datetime(df_plot[selected_time_col])

                    # Create the plot
                    fig = go.Figure()

                    for col in selected_value_cols:
                        fig.add_trace(go.Scatter(
                            x=df_plot[selected_time_col],
                            y=df_plot[col],
                            mode='lines',
                            name=col,
                            line=dict(width=2)
                        ))

                    fig.update_layout(
                        title=f"Timeseries: {resource['name']}",
                        xaxis_title=selected_time_col,
                        yaxis_title="Value",
                        hovermode='x unified',
                        height=500
                    )

                    # Add range slider
                    fig.update_layout(xaxis=dict(rangeslider=dict(visible=True)))

                    st.plotly_chart(fig, use_container_width=True)

                    # Statistics
                    st.markdown("#### 📊 Timeseries Statistics")
                    stats_data = []
                    for col in selected_value_cols:
                        stats_data.append({
                            'Column': col,
                            'Min': f"{df[col].min():.3f}",
                            'Max': f"{df[col].max():.3f}",
                            'Mean': f"{df[col].mean():.3f}",
                            'Std': f"{df[col].std():.3f}",
                            'Data Points': len(df[col].dropna())
                        })

                    stats_df = pd.DataFrame(stats_data)
                    st.dataframe(stats_df, use_container_width=True, hide_index=True)

                except Exception as e:
                    st.warning(f"Could not create timeseries plot: {e}")
        else:
            if not datetime_cols:
                st.info("No datetime columns detected for timeseries visualization")
            if not numeric_cols:
                st.info("No numeric columns found for plotting")

    def _analyze_geojson_data(self, data: Dict, resource: Dict) -> None:
        """Analyze GeoJSON data and create map visualization"""
        st.markdown(f"### 🗺️ GeoJSON Analysis: {resource['name']}")

        # Basic GeoJSON info
        geom_type = data.get('type', 'Unknown')
        st.info(f"**GeoJSON Type:** {geom_type}")

        if geom_type == 'FeatureCollection':
            features = data.get('features', [])
            st.info(f"**Features:** {len(features)}")

            if features:
                # Analyze feature properties
                st.markdown("#### 📊 Feature Analysis")

                # Get all unique properties
                all_props = set()
                for feature in features:
                    props = feature.get('properties', {})
                    all_props.update(props.keys())

                if all_props:
                    st.write(f"**Available Properties:** {', '.join(sorted(all_props))}")

                    # Show first few features
                    st.markdown("#### 📋 Sample Features")
                    sample_features = []
                    for i, feature in enumerate(features[:5]):
                        props = feature.get('properties', {})
                        geom = feature.get('geometry', {})
                        sample_features.append({
                            'Feature': i + 1,
                            'Geometry Type': geom.get('type', 'Unknown'),
                            'Properties': str(props)[:100] + "..." if len(str(props)) > 100 else str(props)
                        })

                    sample_df = pd.DataFrame(sample_features)
                    st.dataframe(sample_df, use_container_width=True, hide_index=True)

                # Create map visualization
                self._create_geojson_map(data, resource)

        elif geom_type in ['Point', 'LineString', 'Polygon']:
            # Single geometry
            coords = data.get('coordinates', [])
            st.info(f"**Coordinates:** {len(coords)} points")

            # Create simple map for single geometry
            self._create_simple_geometry_map(data, resource)

        # Raw JSON view
        with st.expander("🔍 Raw GeoJSON Data", expanded=False):
            st.json(data)

    def _create_geojson_map(self, geojson_data: Dict, resource: Dict) -> None:
        """Create an interactive map from GeoJSON data"""
        st.markdown("#### 🗺️ Interactive Map")

        try:
            # Extract coordinates to center the map
            features = geojson_data.get('features', [])
            if not features:
                st.warning("No features found in GeoJSON")
                return

            # Calculate center point
            all_coords = []
            for feature in features:
                geom = feature.get('geometry', {})
                coords = geom.get('coordinates', [])

                if geom.get('type') == 'Point':
                    all_coords.append(coords)
                elif geom.get('type') in ['LineString', 'MultiPoint']:
                    all_coords.extend(coords)
                elif geom.get('type') in ['Polygon', 'MultiLineString']:
                    for coord_group in coords:
                        all_coords.extend(coord_group)

            if all_coords:
                # Calculate bounds
                lons = [coord[0] for coord in all_coords if len(coord) >= 2]
                lats = [coord[1] for coord in all_coords if len(coord) >= 2]

                if lons and lats:
                    center_lat = sum(lats) / len(lats)
                    center_lon = sum(lons) / len(lons)

                    # Create plotly map
                    fig = px.choropleth_mapbox(
                        geojson=geojson_data,
                        locations=[i for i in range(len(features))],
                        mapbox_style="open-street-map",
                        center={"lat": center_lat, "lon": center_lon},
                        zoom=10,
                        height=500,
                        title=f"Map: {resource['name']}"
                    )

                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Could not extract valid coordinates from GeoJSON")
            else:
                st.warning("No coordinates found in GeoJSON features")

        except Exception as e:
            st.error(f"Error creating map: {e}")
            st.info("Displaying raw GeoJSON data instead")

    def _create_simple_geometry_map(self, geom_data: Dict, resource: Dict) -> None:
        """Create a simple map for single geometry"""
        st.markdown("#### 🗺️ Geometry Map")

        try:
            coords = geom_data.get('coordinates', [])
            geom_type = geom_data.get('type', 'Unknown')

            if geom_type == 'Point' and len(coords) >= 2:
                lon, lat = coords[0], coords[1]

                fig = px.scatter_mapbox(
                    lat=[lat],
                    lon=[lon],
                    zoom=10,
                    height=400,
                    mapbox_style="open-street-map",
                    title=f"{geom_type}: {resource['name']}"
                )

                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(f"Map visualization not implemented for {geom_type}")

        except Exception as e:
            st.error(f"Error creating geometry map: {e}")

    def _analyze_epw_data(self, data: str, resource: Dict) -> None:
        """Analyze EPW weather data files"""
        st.markdown(f"### 🌤️ EPW Weather Data: {resource['name']}")

        lines = data.split('\n')
        st.info(f"**Total Lines:** {len(lines)}")

        # Show first few lines
        st.markdown("#### 📋 File Header")
        header_lines = lines[:10]
        for i, line in enumerate(header_lines):
            if line.strip():
                st.code(f"Line {i+1}: {line[:100]}{'...' if len(line) > 100 else ''}")

        # Try to parse weather data
        st.markdown("#### 🌡️ Weather Data Preview")

        # EPW files typically have weather data starting from line 8
        if len(lines) > 10:
            try:
                # Try to parse a few data lines
                data_lines = []
                for line in lines[8:13]:  # Sample a few data lines
                    if ',' in line and len(line.split(',')) > 10:
                        parts = line.split(',')
                        data_lines.append({
                            'Month': parts[1] if len(parts) > 1 else '',
                            'Day': parts[2] if len(parts) > 2 else '',
                            'Hour': parts[3] if len(parts) > 3 else '',
                            'Temperature': parts[6] if len(parts) > 6 else '',
                            'Humidity': parts[8] if len(parts) > 8 else '',
                            'Solar': parts[13] if len(parts) > 13 else ''
                        })

                if data_lines:
                    weather_df = pd.DataFrame(data_lines)
                    st.dataframe(weather_df, use_container_width=True, hide_index=True)
                else:
                    st.info("Could not parse weather data format")

            except Exception as e:
                st.warning(f"Error parsing EPW data: {e}")

        # Raw data option
        with st.expander("📄 Raw EPW Content (first 1000 characters)", expanded=False):
            st.text(data[:1000] + "..." if len(data) > 1000 else data)

    def _display_raw_data(self, data: Any, resource: Dict) -> None:
        """Display raw data regardless of type"""
        st.markdown(f"### 📄 Raw Data: {resource['name']}")

        if isinstance(data, pd.DataFrame):
            st.markdown("#### 📊 DataFrame")
            st.dataframe(data, use_container_width=True)
            self._add_download_option(data, resource)

        elif isinstance(data, dict):
            st.markdown("#### 📋 JSON/Dictionary")
            st.json(data)

        elif isinstance(data, str):
            st.markdown("#### 📝 Text Content")
            # Show first 2000 characters
            if len(data) > 2000:
                st.text_area(
                    "Content (first 2000 characters):",
                    data[:2000] + "\n\n... (truncated)",
                    height=300
                )
                st.info(f"Full content is {len(data)} characters long")
            else:
                st.text_area("Content:", data, height=300)
        else:
            st.markdown("#### ❓ Unknown Data Type")
            st.write(f"Data type: {type(data)}")
            st.write(str(data)[:500] + "..." if len(str(data)) > 500 else str(data))

    def _display_visualization(self, data: Any, resource: Dict) -> None:
        """Force visualization mode for data"""
        st.markdown(f"### 📊 Forced Visualization: {resource['name']}")

        if isinstance(data, pd.DataFrame):
            # Show basic plots for DataFrame
            numeric_cols = data.select_dtypes(include=[np.number]).columns

            if len(numeric_cols) > 0:
                st.markdown("#### 📈 Numeric Column Distributions")

                for col in numeric_cols[:3]:  # Limit to first 3 columns
                    fig = px.histogram(data, x=col, title=f"Distribution of {col}")
                    st.plotly_chart(fig, use_container_width=True)

                if len(numeric_cols) > 1:
                    st.markdown("#### 📊 Correlation Matrix")
                    corr_matrix = data[numeric_cols].corr()
                    fig = px.imshow(
                        corr_matrix,
                        title="Correlation Matrix",
                        aspect="auto"
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No numeric columns found for visualization")

        elif isinstance(data, dict):
            # Try to visualize as GeoJSON if possible
            if data.get('type') in ['FeatureCollection', 'Point', 'LineString', 'Polygon']:
                self._analyze_geojson_data(data, resource)
            else:
                st.info("Dictionary data - showing raw JSON")
                st.json(data)
        else:
            st.info("Cannot create visualization for this data type")
            self._display_raw_data(data, resource)

    def _add_download_option(self, data: pd.DataFrame, resource: Dict) -> None:
        """Add download option for DataFrame"""
        st.markdown("#### 📥 Download")

        col1, col2 = st.columns(2)

        with col1:
            csv = data.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"{resource['name']}_analyzed.csv",
                mime="text/csv"
            )

        with col2:
            json_data = data.to_json(orient='records')
            st.download_button(
                label="📥 Download as JSON",
                data=json_data,
                file_name=f"{resource['name']}_analyzed.json",
                mime="application/json"
            )


def render_resources_tab():
    """Render the resources analysis tab"""
    st.subheader("📁 Resource File Analysis")

    # Check if data products are loaded
    if not st.session_state.loaded_data_products:
        st.info("📦 No data products loaded. Please load data products first.")
        return

    # Data product selector - same as Explorer and Analytics tabs
    col1, col2 = st.columns([3, 1])

    with col1:
        product_options = {}
        for key, product in st.session_state.loaded_data_products.items():
            badge = "🌍" if product['type'] == 'global' else "🔒"
            resource_count = len(product.get('resources', []))
            display_name = f"{badge} {product['name']} ({resource_count} resources)"
            product_options[display_name] = key

        selected_display = st.selectbox(
            "Select Data Product to Analyze:",
            options=list(product_options.keys()),
            key="resources_product_selector"
        )

        if selected_display:
            selected_key = product_options[selected_display]
            st.session_state.selected_data_product = selected_key

    with col2:
        if st.button("🔄 Refresh Resources", use_container_width=True):
            st.rerun()

    # Check if a product is selected
    if not st.session_state.selected_data_product:
        st.info("🔍 Please select a data product to analyze resources.")
        return

    product = st.session_state.loaded_data_products[st.session_state.selected_data_product]

    st.write(f"**Analyzing Resources from:** {product['name']} ({product['type'].title()})")

    # Initialize analyzer
    analyzer = ResourceAnalyzer(product)

    # Analyze all resources
    analyzer.analyze_all_resources()