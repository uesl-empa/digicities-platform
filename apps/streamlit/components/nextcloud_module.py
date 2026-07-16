# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional, List, Dict, Any
import os
import json
from io import BytesIO
from datetime import datetime

# Import the standalone client
from components.nextcloud_client import NextcloudClient, create_client_from_env
import requests
import base64

# Try to import folium at module level
try:
    import folium
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


def nextcloud_module(workspace: Dict[str, Any]):
    """
    Streamlined Nextcloud module for file operations and timeseries visualization.

    Args:
        workspace: Workspace configuration dictionary
    """
    # Custom CSS for better styling (removed the green header CSS)
    st.markdown("""
    <style>
    .file-card {
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: all 0.2s ease;
    }
    .file-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    .metric-card {
        background: white;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
    """, unsafe_allow_html=True)

    workspace_id = workspace.get("id")
    workspace_name = workspace.get("name", "Unknown")

    if not workspace_id:
        st.error("❌ Workspace ID not found")
        return

    st.title(f"📊 Data Viewer and Uploader")
    st.markdown("Explore the cloud storage")

    # Initialize client with error handling
    try:
        if "nextcloud_client" not in st.session_state or st.session_state.get("current_workspace_id") != workspace_id:
            st.session_state.nextcloud_client = create_client_from_env(workspace_id)
            st.session_state.current_workspace_id = workspace_id

        client = st.session_state.nextcloud_client
    except Exception as e:
        st.error(f"❌ Failed to initialize Nextcloud client: {e}")
        st.info("💡 Make sure NEXTCLOUD_BASIC_USERNAME and NEXTCLOUD_BASIC_PASSWORD are set in your environment")
        return

    # Create tabs for different operations (simplified)
    tab1, tab2 = st.tabs([
        "📁 File Browser",
        "⬆️ File Management"
    ])

    with tab1:
        _enhanced_file_browser_tab(client, workspace)

    with tab2:
        _file_management_tab(client, workspace)


def _enhanced_file_browser_tab(client: NextcloudClient, workspace: Dict[str, Any]):
    """Enhanced file browser with folder structure for timeseries and geospatial data."""
    st.subheader("📁 File Browser & Preview")

    # Quick refresh button
    if st.button("🔄 Refresh Files", use_container_width=True):
        if "file_list" in st.session_state:
            del st.session_state["file_list"]
        if "timeseries_files" in st.session_state:
            del st.session_state["timeseries_files"]
        if "geospatial_files" in st.session_state:
            del st.session_state["geospatial_files"]
        if "selected_file_for_viewing" in st.session_state:
            del st.session_state["selected_file_for_viewing"]
        st.rerun()

    # Load files from different folders
    try:
        # Get root files
        if "file_list" not in st.session_state:
            with st.spinner("Loading root files..."):
                st.session_state.file_list = client.list_files()

        # Get timeseries files using proper subfolder listing
        if "timeseries_files" not in st.session_state:
            with st.spinner("Loading timeseries files..."):
                st.session_state.timeseries_files = _list_files_in_subfolder(client, "timeseries")

        # Get geospatial files using proper subfolder listing
        if "geospatial_files" not in st.session_state:
            with st.spinner("Loading geospatial files..."):
                st.session_state.geospatial_files = _list_files_in_subfolder(client, "geospatial")

        root_files = st.session_state.file_list
        timeseries_files = st.session_state.timeseries_files
        geospatial_files = st.session_state.geospatial_files

        # Display folder statistics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📈 Timeseries Files", len(timeseries_files))
        with col2:
            st.metric("🗺️ Geospatial Files", len(geospatial_files))
        with col3:
            st.metric("📄 Root Files", len(root_files))

        # Show files by folder
        if timeseries_files:
            st.markdown("### 📈 Timeseries Folder")
            _display_folder_files(client, timeseries_files, "timeseries")

        if geospatial_files:
            st.markdown("### 🗺️ Geospatial Folder")
            _display_folder_files(client, geospatial_files, "geospatial")

        if root_files:
            st.markdown("### 📄 Root Files")
            _display_folder_files(client, root_files, "root")

        if not timeseries_files and not geospatial_files and not root_files:
            _show_upload_prompt()

        # Full-width data viewer section
        st.markdown("---")
        _display_data_viewer(client)

    except Exception as e:
        st.error(f"❌ Failed to load files: {e}")
        import traceback
        st.code(traceback.format_exc())


def _list_files_in_subfolder(client: NextcloudClient, subfolder: str) -> List[Dict]:
    """
    List files in a specific subfolder using the correct Nextcloud WebDAV path.
    Based on the working download script pattern.
    """
    try:
        # Get credentials and workspace info
        username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
        password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
        base_url = os.getenv("NEXTCLOUD_BASE_URL")

        if not username or not password or not base_url:
            return []

        # Build the subfolder URL using the same pattern as the working download script
        workspace_id = client.workspace_id
        folder_url = f"{base_url}/remote.php/dav/files/{username}/{workspace_id}/{subfolder}/"

        # Setup auth headers
        auth_header = "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
        headers = {
            "Authorization": auth_header,
            "Depth": "1",
            "Content-Type": "application/xml"
        }

        # PROPFIND request to list files
        xml_body = """<?xml version="1.0"?>
        <d:propfind xmlns:d="DAV:">
            <d:prop>
                <d:displayname/>
                <d:getcontentlength/>
                <d:getlastmodified/>
                <d:getcontenttype/>
            </d:prop>
        </d:propfind>
        """

        response = requests.request("PROPFIND", folder_url, headers=headers, data=xml_body)

        if response.status_code == 404:
            # Subfolder doesn't exist
            return []

        response.raise_for_status()

        # Parse XML response
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.content)
        ns = {"d": "DAV:"}
        files = []

        for resp in root.findall("d:response", ns):
            href = resp.find("d:href", ns)
            if href is None:
                continue

            name = href.text.split("/")[-1]
            if not name or name.endswith("/"):  # Skip folders
                continue

            # Extract file properties
            props = resp.find("d:propstat/d:prop", ns)
            size_elem = props.find("d:getcontentlength", ns) if props is not None else None
            modified_elem = props.find("d:getlastmodified", ns) if props is not None else None
            content_type_elem = props.find("d:getcontenttype", ns) if props is not None else None

            files.append({
                "name": f"{subfolder}/{name}",  # Keep full path for downloads
                "display_name": name,  # Clean name for display
                "size": int(size_elem.text) if size_elem is not None and size_elem.text else 0,
                "last_modified": modified_elem.text if modified_elem is not None else None,
                "content_type": content_type_elem.text if content_type_elem is not None else None
            })

        return files

    except Exception as e:
        st.error(f"❌ Failed to list files in {subfolder}: {e}")
        return []


def _advanced_analytics_tab(client: NextcloudClient, workspace: Dict[str, Any]):
    """Advanced data analytics and visualization tab."""
    st.subheader("📊 Data Analytics & Visualization")

    # Get CSV files for analysis
    try:
        csv_files = client.get_csv_files()

        if not csv_files:
            st.info("📊 No CSV files found for analysis")
            return

        # Analytics dashboard layout
        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("### 🎛️ Analysis Controls")

            selected_csv = st.selectbox(
                "📁 Select Data File:",
                options=csv_files,
                help="Choose a CSV file for analysis"
            )

            if selected_csv:
                # Analysis options
                with st.expander("⚙️ Analysis Options", expanded=True):
                    timestamp_col = st.text_input(
                        "Timestamp column:",
                        value="timestamp",
                        help="Column containing timestamps"
                    )

                    auto_parse = st.checkbox(
                        "Auto-parse timestamps",
                        value=True,
                        help="Automatically detect timestamp format"
                    )

                    sample_size = st.slider(
                        "Sample size (rows):",
                        min_value=100,
                        max_value=10000,
                        value=1000,
                        help="Number of rows to analyze"
                    )

                if st.button("🚀 Analyze Data", use_container_width=True):
                    _perform_advanced_analysis(client, selected_csv, timestamp_col, auto_parse, sample_size)

        with col2:
            st.markdown("### 📈 Analysis Results")
            if 'analysis_results' in st.session_state:
                _display_analysis_results(st.session_state.analysis_results)
            else:
                st.info("Select a CSV file and click 'Analyze Data' to see results here.")

    except Exception as e:
        st.error(f"❌ Failed to load analytics: {e}")


def _file_management_tab(client: NextcloudClient, workspace: Dict[str, Any]):
    """File management operations tab with folder-specific uploads."""
    st.subheader("⬆️ File Management Operations")

    # Upload section with folder selection
    st.markdown("### ⬆️ Upload Files")

    # Choose upload destination
    upload_folder = st.selectbox(
        "Upload to folder:",
        ["timeseries", "geospatial", "root"],
        help="Choose where to upload your files"
    )

    uploaded_files = st.file_uploader(
        "Choose files to upload:",
        accept_multiple_files=True,
        help="Select one or more files to upload to the workspace"
    )

    if uploaded_files:
        st.write(f"**Ready to upload {len(uploaded_files)} files to {upload_folder} folder:**")
        for file in uploaded_files:
            st.write(f"• {file.name}")

        if st.button("⬆️ Upload All Files", use_container_width=True):
            _upload_files_to_folder(client, uploaded_files, upload_folder)


def _workspace_tools_tab(client: NextcloudClient, workspace: Dict[str, Any]):
    """Workspace tools and utilities tab."""
    st.subheader("🔧 Workspace Tools & Utilities")
    st.info("Basic workspace tools available here")


# ==================== HELPER FUNCTIONS ====================

def _apply_file_filters(files: List[Dict], filter_type: str, sort_by: str) -> List[Dict]:
    """Apply filters and sorting to file list."""
    filtered = files.copy()

    # Apply type filter
    if filter_type == "CSV Files":
        filtered = [f for f in filtered if f['name'].lower().endswith('.csv')]
    elif filter_type == "Images":
        filtered = [f for f in filtered if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp'))]
    elif filter_type == "Documents":
        filtered = [f for f in filtered if f['name'].lower().endswith(('.pdf', '.doc', '.docx', '.txt', '.md'))]

    # Apply sorting
    if sort_by == "Name":
        filtered.sort(key=lambda x: x['name'].lower())
    elif sort_by == "Size":
        filtered.sort(key=lambda x: x.get('size', 0), reverse=True)
    elif sort_by == "Date":
        filtered.sort(key=lambda x: x.get('last_modified', ''), reverse=True)

    return filtered


def _display_file_stats(files: List[Dict]) -> None:
    """Display file statistics."""
    total_files = len(files)
    total_size = sum(f.get('size', 0) for f in files) / 1024 / 1024
    csv_files = len([f for f in files if f['name'].lower().endswith('.csv')])

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("📁 Files", total_files)
    with col2:
        st.metric("📏 Total Size", f"{total_size:.1f} MB")
    with col3:
        st.metric("📊 CSV Files", csv_files)


def _display_folder_files(client: NextcloudClient, files: List[Dict], folder_type: str) -> None:
    """Display files from a specific folder."""
    if not files:
        return

    # Show files in a clean list format
    for file_info in files:
        filename = file_info['name']
        # Use display_name if available, otherwise clean the filename
        if 'display_name' in file_info:
            display_name = file_info['display_name']
        elif folder_type != "root":
            display_name = filename.replace(f"{folder_type}/", "")
        else:
            display_name = filename

        file_size = file_info.get('size', 0) / 1024

        # Create a nice file row
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

        with col1:
            # File icon based on type
            if display_name.lower().endswith('.csv'):
                icon = "📊"
            elif display_name.lower().endswith(('.geojson', '.json')):
                icon = "🗺️"
            elif display_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                icon = "🖼️"
            else:
                icon = "📄"

            st.write(f"{icon} **{display_name}**")

        with col2:
            st.write(f"{file_size:.1f} KB")

        with col3:
            if st.button("📈", key=f"view_{filename}", help="View Data"):
                st.session_state.selected_file_for_viewing = {
                    'filename': filename,
                    'display_name': display_name,
                    'folder_type': folder_type
                }
                # Don't use st.rerun() - just update session state

        with col4:
            if st.button("📥", key=f"download_{filename}", help="Download"):
                _download_file(client, filename)


def _show_upload_prompt() -> None:
    """Show upload prompt when no files exist."""
    st.info("This workspace doesn't contain any files yet. Use the File Management tab to upload files!")


def _perform_advanced_analysis(client: NextcloudClient, filename: str, timestamp_col: str, auto_parse: bool, sample_size: int) -> None:
    """Perform advanced data analysis."""
    try:
        with st.spinner(f"Analyzing {filename}..."):
            if auto_parse:
                df = client.read_timeseries_csv(filename, timestamp_col=timestamp_col)
            else:
                df = client.read_csv(filename)

            # Limit sample size
            if len(df) > sample_size:
                df = df.head(sample_size)
                st.info(f"Analysis limited to first {sample_size} rows")

            # Perform analysis
            analysis_results = {
                'filename': filename,
                'dataframe': df,
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'dtypes': df.dtypes.to_dict(),
                'missing_values': df.isnull().sum().to_dict(),
                'numeric_summary': df.describe().to_dict() if len(df.select_dtypes(include=['number']).columns) > 0 else {},
                'timestamp': datetime.now()
            }

            st.session_state.analysis_results = analysis_results
            st.success(f"✅ Analysis complete for {filename}")

    except Exception as e:
        st.error(f"❌ Analysis failed: {e}")


def _display_analysis_results(results: Dict) -> None:
    """Display analysis results."""
    df = results['dataframe']

    st.markdown(f"**📊 Analysis Results for:** `{results['filename']}`")

    # Basic info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📋 Rows", results['shape'][0])
    with col2:
        st.metric("📊 Columns", results['shape'][1])
    with col3:
        missing_total = sum(results['missing_values'].values())
        st.metric("❓ Missing Values", missing_total)

    # Data preview
    with st.expander("🔍 Data Preview", expanded=True):
        st.dataframe(df.head(10), use_container_width=True)

    # Numeric columns analysis
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    if numeric_cols:
        with st.expander("📈 Numeric Analysis", expanded=True):
            selected_numeric = st.multiselect("Select columns to visualize:", numeric_cols, default=numeric_cols[:3])

            if selected_numeric:
                if hasattr(df.index, 'dtype') and 'datetime' in str(df.index.dtype):
                    # Time series plot
                    fig = make_subplots(rows=len(selected_numeric), cols=1, subplot_titles=selected_numeric, shared_xaxes=True)

                    for i, col in enumerate(selected_numeric):
                        fig.add_trace(
                            go.Scatter(x=df.index, y=df[col], name=col, mode='lines'),
                            row=i + 1, col=1
                        )

                    fig.update_layout(height=200 * len(selected_numeric), title="Time Series Analysis")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    # Regular plots
                    for col in selected_numeric:
                        fig = px.histogram(df, x=col, title=f"Distribution of {col}")
                        st.plotly_chart(fig, use_container_width=True)


def _upload_files_to_folder(client: NextcloudClient, files: List, folder: str) -> None:
    """Upload files to a specific folder."""
    success_count = 0

    for file in files:
        try:
            # Determine file path based on folder
            if folder == "root":
                file_path = file.name
            else:
                file_path = f"{folder}/{file.name}"

            client.upload_file(file_path, file.getvalue())
            success_count += 1
            st.success(f"✅ {file.name}: Uploaded to {folder}")
        except Exception as e:
            st.error(f"❌ {file.name}: Upload failed - {e}")

    # Clear cache
    if "file_list" in st.session_state:
        del st.session_state["file_list"]

    st.info(f"📊 Upload Summary: {success_count}/{len(files)} files uploaded to {folder}")


def _upload_files_with_progress(client: NextcloudClient, files: List) -> None:
    """Upload files with progress tracking."""
    success_count = 0

    for file in files:
        try:
            client.upload_file(file.name, file.getvalue())
            success_count += 1
            st.success(f"✅ {file.name}: Uploaded successfully")
        except Exception as e:
            st.error(f"❌ {file.name}: Upload failed - {e}")

    # Clear cache
    if "file_list" in st.session_state:
        del st.session_state["file_list"]

    st.info(f"📊 Upload Summary: {success_count}/{len(files)} files uploaded successfully")


def _download_file(client: NextcloudClient, filename: str) -> None:
    """Handle file download."""
    try:
        content = client.download_file(filename)
        st.download_button(
            label=f"💾 Download {filename}",
            data=content,
            file_name=filename,
            mime="application/octet-stream",
            use_container_width=True
        )
        st.success(f"✅ {filename} ready for download")
    except Exception as e:
        st.error(f"❌ Failed to download {filename}: {e}")


def _display_data_viewer(client: NextcloudClient) -> None:
    """Display full-width data viewer for selected files."""
    if "selected_file_for_viewing" not in st.session_state:
        st.markdown("""
        ### 📊 Data Viewer
        *Click the 📈 button next to any file to view it here*

        - **CSV files** → Interactive charts and graphs
        - **GeoJSON files** → Interactive maps
        - **Other files** → Text preview
        """)
        return

    file_info = st.session_state.selected_file_for_viewing
    filename = file_info['filename']
    display_name = file_info['display_name']
    folder_type = file_info['folder_type']

    # Header for data viewer
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"### 📊 Data Viewer: {display_name}")
    with col2:
        if st.button("❌ Close Viewer", key="close_viewer"):
            del st.session_state.selected_file_for_viewing
            st.rerun()

    # Display content based on file type
    try:
        if display_name.lower().endswith('.csv'):
            _display_csv_chart(client, filename, display_name)
        elif display_name.lower().endswith(('.geojson', '.json')):
            _display_geojson_map(client, filename, display_name)
        else:
            _display_text_content(client, filename, display_name)

    except Exception as e:
        st.error(f"❌ Failed to display {display_name}: {e}")


def _display_csv_chart(client: NextcloudClient, filename: str, display_name: str) -> None:
    """Display CSV file as interactive charts with enhanced timeseries support."""
    try:
        # Load CSV data
        df = client.read_csv(filename)

        st.write(f"**File:** {display_name}")
        st.write(f"**Shape:** {df.shape[0]} rows × {df.shape[1]} columns")

        # Show data preview
        with st.expander("📋 Data Preview", expanded=False):
            st.dataframe(df.head(20), use_container_width=True)

        # Show full raw data option
        with st.expander("📄 Raw Data", expanded=False):
            st.dataframe(df, use_container_width=True)

            # Option to download as CSV
            csv_data = df.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv_data,
                file_name=f"processed_{display_name}",
                mime="text/csv"
            )

        # Get numeric columns for plotting
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        if not numeric_cols:
            st.warning("No numeric columns found for plotting")
            return

        # Enhanced plotting section for timeseries
        st.markdown("### 📈 Data Visualization")

        # Auto-detect timestamp columns
        timestamp_cols = []
        for col in df.columns:
            if any(keyword in col.lower() for keyword in ['time', 'date', 'timestamp']):
                timestamp_cols.append(col)
            # Also check if column contains datetime-like data
            elif df[col].dtype == 'object':
                try:
                    pd.to_datetime(df[col].head(5))
                    timestamp_cols.append(col)
                except:
                    pass

        # Smart default settings for timeseries
        default_chart_type = "Line Plot" if timestamp_cols else "Bar Chart"

        # Plotting controls
        col1, col2, col3 = st.columns(3)

        with col1:
            chart_type = st.selectbox(
                "Chart Type:",
                ["Line Plot", "Bar Chart", "Scatter Plot", "Area Chart", "Box Plot", "Histogram"],
                index=0 if timestamp_cols else 1,
                key="chart_type"
            )

        with col2:
            y_columns = st.multiselect(
                "Y Column(s):",
                numeric_cols,
                default=numeric_cols[:3] if len(numeric_cols) >= 3 else numeric_cols,
                key="y_columns"
            )

        with col3:
            # X column selection with smart defaults for timeseries
            x_options = ["Index"] + list(df.columns)
            default_x_index = 0

            if timestamp_cols:
                default_x_index = x_options.index(timestamp_cols[0]) if timestamp_cols[0] in x_options else 0

            x_column = st.selectbox(
                "X Column:",
                x_options,
                index=default_x_index,
                key="x_column"
            )

        if not y_columns:
            st.info("Please select at least one Y column to plot")
            return

        # Prepare data for plotting
        if x_column == "Index":
            x_data = df.index
            x_title = "Index"
        else:
            x_data = df[x_column]
            x_title = x_column

            # Try to convert to datetime if it looks like timestamps
            if x_column in timestamp_cols:
                try:
                    x_data = pd.to_datetime(x_data)
                    x_title = f"{x_column} (Time)"
                except:
                    pass

        # Create the main plot
        if chart_type in ["Line Plot", "Area Chart", "Scatter Plot"] and len(y_columns) == 1:
            # Single column plots
            y_col = y_columns[0]
            y_data = df[y_col]

            if chart_type == "Line Plot":
                fig = px.line(x=x_data, y=y_data, title=f"{y_col} over {x_title}")
            elif chart_type == "Scatter Plot":
                fig = px.scatter(x=x_data, y=y_data, title=f"{y_col} vs {x_title}")
            elif chart_type == "Area Chart":
                fig = px.area(x=x_data, y=y_data, title=f"{y_col} over {x_title}")

        elif chart_type == "Bar Chart":
            # For bar charts, limit data points if too many
            plot_df = df.copy()
            if len(plot_df) > 50:
                plot_df = plot_df.head(50)
                st.info("Bar chart limited to first 50 rows for readability")

            if len(y_columns) == 1:
                if x_column == "Index":
                    fig = px.bar(y=plot_df[y_columns[0]], title=f"{y_columns[0]} by Index")
                else:
                    fig = px.bar(plot_df, x=x_column, y=y_columns[0], title=f"{y_columns[0]} by {x_title}")
            else:
                # Multiple columns
                fig = px.bar(plot_df, x=x_column if x_column != "Index" else None,
                             y=y_columns, title=f"Multiple Columns by {x_title}", barmode='group')

        elif chart_type == "Box Plot":
            # Box plot for distribution analysis
            if len(y_columns) == 1:
                fig = px.box(y=df[y_columns[0]], title=f"Distribution of {y_columns[0]}")
            else:
                # Multiple box plots
                melted_df = df[y_columns].melt(var_name='Column', value_name='Value')
                fig = px.box(melted_df, x='Column', y='Value', title="Distribution Comparison")

        elif chart_type == "Histogram":
            # Histogram for single column
            if len(y_columns) == 1:
                fig = px.histogram(df, x=y_columns[0], title=f"Histogram of {y_columns[0]}")
            else:
                # Multiple histograms
                fig = px.histogram(df, x=y_columns, title="Multiple Histograms", barmode='overlay', opacity=0.7)

        else:
            # Multi-line plot for multiple columns
            fig = go.Figure()
            for y_col in y_columns:
                if chart_type == "Line Plot":
                    fig.add_trace(go.Scatter(x=x_data, y=df[y_col], mode='lines', name=y_col))
                elif chart_type == "Scatter Plot":
                    fig.add_trace(go.Scatter(x=x_data, y=df[y_col], mode='markers', name=y_col))
                elif chart_type == "Area Chart":
                    fig.add_trace(go.Scatter(x=x_data, y=df[y_col], fill='tonexty', name=y_col))

            fig.update_layout(
                title=f"Multiple Columns: {chart_type}",
                xaxis_title=x_title,
                yaxis_title="Values"
            )

        # Update layout and display
        if 'fig' in locals():
            fig.update_layout(
                height=500,
                xaxis_title=x_title,
                yaxis_title="Values" if len(y_columns) > 1 else y_columns[0]
            )
            st.plotly_chart(fig, use_container_width=True)

        # Statistical summary for selected columns
        if st.checkbox("📊 Show Statistical Summary"):
            st.markdown("#### Statistical Summary")
            summary_df = df[y_columns].describe()
            st.dataframe(summary_df, use_container_width=True)

            # Correlation matrix if multiple columns
            if len(y_columns) > 1:
                st.markdown("#### Correlation Matrix")
                corr_matrix = df[y_columns].corr()

                fig_corr = px.imshow(
                    corr_matrix,
                    text_auto=True,
                    aspect="auto",
                    title="Correlation Matrix",
                    color_continuous_scale="RdBu_r"
                )
                st.plotly_chart(fig_corr, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Failed to create chart: {e}")
        # Fallback to showing raw data
        st.dataframe(df, use_container_width=True)


def _display_geojson_map(client: NextcloudClient, filename: str, display_name: str) -> None:
    """Display GeoJSON file as interactive map with coordinate transformation."""
    try:
        # Load GeoJSON data
        content = client.download_text_file(filename)
        geojson_data = json.loads(content)

        st.write(f"**File:** {display_name}")
        st.write(f"**Type:** {geojson_data.get('type', 'Unknown')}")

        # Check and handle coordinate system
        original_crs = _get_crs_from_geojson(geojson_data)
        st.write(f"**Coordinate System:** {original_crs}")

        # Transform coordinates if needed
        transformed_geojson, transform_info = _transform_geojson_coordinates(geojson_data)

        if transform_info['transformed']:
            st.success(f"✅ Coordinates transformed from {transform_info['from_crs']} to WGS84")
        elif transform_info['warning']:
            st.warning(f"⚠️ {transform_info['warning']}")

        # Feature info and preview sections
        if transformed_geojson.get('type') == 'FeatureCollection':
            features = transformed_geojson.get('features', [])
            st.write(f"**Features:** {len(features)}")

            # Data preview section
            with st.expander("📋 Data Preview", expanded=False):
                if features:
                    # Show first few features in a table-like format
                    preview_data = []
                    for i, feature in enumerate(features[:10]):  # Show first 10 features
                        properties = feature.get('properties', {})
                        geometry = feature.get('geometry', {})

                        # Create a row for this feature
                        row = {
                            'Feature_ID': i + 1,
                            'Geometry_Type': geometry.get('type', 'Unknown')
                        }

                        # Add all properties as columns
                        for key, value in properties.items():
                            row[key] = value

                        preview_data.append(row)

                    if preview_data:
                        preview_df = pd.DataFrame(preview_data)
                        st.dataframe(preview_df, use_container_width=True)

                        if len(features) > 10:
                            st.info(f"Showing first 10 features of {len(features)} total features")
                else:
                    st.info("No features to preview")

            # Raw data section
            with st.expander("📄 Raw GeoJSON Data", expanded=False):
                st.json(geojson_data)

                # Option to download as GeoJSON
                geojson_str = json.dumps(geojson_data, indent=2)
                st.download_button(
                    label="📥 Download as GeoJSON",
                    data=geojson_str,
                    file_name=f"processed_{display_name}",
                    mime="application/json"
                )

                # Show transformed coordinates option if transformation occurred
                if transform_info['transformed']:
                    st.markdown("**Download Transformed Version:**")
                    transformed_str = json.dumps(transformed_geojson, indent=2)
                    st.download_button(
                        label="📥 Download Transformed GeoJSON (WGS84)",
                        data=transformed_str,
                        file_name=f"transformed_{display_name}",
                        mime="application/json"
                    )

            # Properties analysis
            if features and features[0].get('properties'):
                with st.expander("🏷️ Properties Analysis", expanded=False):
                    # Collect all unique properties across features
                    all_properties = set()
                    property_examples = {}

                    for feature in features:
                        props = feature.get('properties', {})
                        for key, value in props.items():
                            all_properties.add(key)
                            if key not in property_examples:
                                property_examples[key] = []
                            if len(property_examples[key]) < 3:  # Keep first 3 examples
                                property_examples[key].append(str(value))

                    # Display properties summary
                    st.write(f"**Total Properties Found:** {len(all_properties)}")

                    props_data = []
                    for prop in sorted(all_properties):
                        examples = ", ".join(property_examples[prop])
                        props_data.append({
                            'Property': prop,
                            'Examples': examples,
                            'Count': len([f for f in features if prop in f.get('properties', {})])
                        })

                    if props_data:
                        props_df = pd.DataFrame(props_data)
                        st.dataframe(props_df, use_container_width=True)

        elif transformed_geojson.get('type') == 'Feature':
            # Single feature
            properties = transformed_geojson.get('properties', {})
            geometry = transformed_geojson.get('geometry', {})

            with st.expander("📋 Feature Data", expanded=False):
                st.write(f"**Geometry Type:** {geometry.get('type', 'Unknown')}")

                if properties:
                    st.write("**Properties:**")
                    props_df = pd.DataFrame([
                        {'Property': k, 'Value': str(v)}
                        for k, v in properties.items()
                    ])
                    st.dataframe(props_df, use_container_width=True)

            # Raw data section for single feature
            with st.expander("📄 Raw GeoJSON Data", expanded=False):
                st.json(geojson_data)

                geojson_str = json.dumps(geojson_data, indent=2)
                st.download_button(
                    label="📥 Download as GeoJSON",
                    data=geojson_str,
                    file_name=f"processed_{display_name}",
                    mime="application/json"
                )

        # Map visualization section
        st.markdown("### 🗺️ Interactive Map")

        if not FOLIUM_AVAILABLE:
            st.warning("📍 Map display requires: pip install folium streamlit-folium")
            st.json(transformed_geojson)
            return

        # Create map
        center_lat, center_lon = 46.8182, 8.2275  # Switzerland default

        # Try to get bounds from transformed data
        bounds = _get_geojson_bounds(transformed_geojson)
        if bounds:
            center_lat = (bounds[1] + bounds[3]) / 2
            center_lon = (bounds[0] + bounds[2]) / 2

        # Create the map
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=10,
            tiles="OpenStreetMap"
        )

        # Add features with custom icons based on properties
        if transformed_geojson.get('type') == 'FeatureCollection':
            features = transformed_geojson.get('features', [])
            for feature in features:
                _add_feature_to_map(m, feature, display_name)
        elif transformed_geojson.get('type') == 'Feature':
            _add_feature_to_map(m, transformed_geojson, display_name)
        else:
            # Direct geometry - add as basic GeoJSON
            folium.GeoJson(
                transformed_geojson,
                style_function=lambda x: {
                    'fillColor': '#3388ff',
                    'color': '#3388ff',
                    'weight': 2,
                    'fillOpacity': 0.6,
                }
            ).add_to(m)

        # Fit to bounds if available
        if bounds:
            m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

        # Display the map (full width)
        map_data = st_folium(m, width=None, height=600, returned_objects=["last_object_clicked"])

        # Show clicked feature info
        if map_data and map_data.get('last_object_clicked'):
            st.markdown("#### 📍 Selected Feature")
            clicked_data = map_data['last_object_clicked']
            st.json(clicked_data)

    except json.JSONDecodeError:
        st.error("❌ Invalid JSON format")
    except Exception as e:
        st.error(f"❌ Failed to display map: {e}")


def _add_feature_to_map(map_obj, feature: dict, display_name: str) -> None:
    """Add a single feature to the map with appropriate icon and popup."""
    try:
        geometry = feature.get('geometry', {})
        properties = feature.get('properties', {})

        # Determine icon and color based on properties
        icon_info = _get_feature_icon(properties)

        if geometry.get('type') == 'Point':
            coordinates = geometry.get('coordinates', [])
            if len(coordinates) >= 2:
                # Create popup content
                popup_content = f"<b>{display_name}</b><br>"
                for key, value in properties.items():
                    popup_content += f"<b>{key}:</b> {value}<br>"

                # Add marker with icon
                folium.Marker(
                    location=[coordinates[1], coordinates[0]],  # lat, lon
                    popup=folium.Popup(popup_content, max_width=300),
                    tooltip=properties.get('class', properties.get('type', 'Feature')),
                    icon=folium.Icon(
                        color=icon_info['color'],
                        icon=icon_info['icon'],
                        prefix=icon_info['prefix']
                    )
                ).add_to(map_obj)
        else:
            # For non-point geometries, use GeoJSON
            folium.GeoJson(
                feature,
                style_function=lambda x: {
                    'fillColor': icon_info['color'],
                    'color': icon_info['color'],
                    'weight': 2,
                    'fillOpacity': 0.6,
                },
                popup=folium.Popup(f"<b>{display_name}</b>", max_width=300)
            ).add_to(map_obj)

    except Exception as e:
        # Fallback to basic GeoJSON if custom icon fails
        folium.GeoJson(
            feature,
            style_function=lambda x: {
                'fillColor': '#3388ff',
                'color': '#3388ff',
                'weight': 2,
                'fillOpacity': 0.6,
            }
        ).add_to(map_obj)


def _get_feature_icon(properties: dict) -> dict:
    """
    Determine appropriate icon for a feature based on its properties.

    Returns dict with 'color', 'icon', and 'prefix' keys.
    """
    # Default icon for any point
    icon_info = {
        'color': 'blue',
        'icon': 'map-marker',
        'prefix': 'fa'
    }

    # Get class or type from properties
    feature_class = properties.get('class', '').lower()
    feature_type = properties.get('type', '').lower()

    # Icon mapping based on common energy system components
    icon_mapping = {
        # Water/Hydro related
        'reservoir': {'color': 'blue', 'icon': 'tint', 'prefix': 'fa'},
        'dam': {'color': 'blue', 'icon': 'tint', 'prefix': 'fa'},
        'lake': {'color': 'blue', 'icon': 'tint', 'prefix': 'fa'},
        'water': {'color': 'blue', 'icon': 'tint', 'prefix': 'fa'},

        # Energy generation
        'turbine': {'color': 'green', 'icon': 'cog', 'prefix': 'fa'},
        'generator': {'color': 'green', 'icon': 'flash', 'prefix': 'fa'},
        'powerplant': {'color': 'red', 'icon': 'industry', 'prefix': 'fa'},
        'power_plant': {'color': 'red', 'icon': 'industry', 'prefix': 'fa'},

        # Solar
        'solar': {'color': 'orange', 'icon': 'sun-o', 'prefix': 'fa'},
        'photovoltaic': {'color': 'orange', 'icon': 'sun-o', 'prefix': 'fa'},
        'pv': {'color': 'orange', 'icon': 'sun-o', 'prefix': 'fa'},

        # Wind
        'wind': {'color': 'lightblue', 'icon': 'certificate', 'prefix': 'fa'},
        'windturbine': {'color': 'lightblue', 'icon': 'certificate', 'prefix': 'fa'},

        # Network/Grid
        'substation': {'color': 'purple', 'icon': 'flash', 'prefix': 'fa'},
        'transformer': {'color': 'purple', 'icon': 'flash', 'prefix': 'fa'},
        'line': {'color': 'gray', 'icon': 'minus', 'prefix': 'fa'},
        'cable': {'color': 'gray', 'icon': 'minus', 'prefix': 'fa'},

        # Buildings
        'building': {'color': 'darkred', 'icon': 'home', 'prefix': 'fa'},
        'house': {'color': 'darkred', 'icon': 'home', 'prefix': 'fa'},
        'facility': {'color': 'darkred', 'icon': 'building', 'prefix': 'fa'},

        # Nodes/Points (keep these as alternatives but default to map-marker)
        'node': {'color': 'black', 'icon': 'circle', 'prefix': 'fa'},
        'point': {'color': 'blue', 'icon': 'map-marker', 'prefix': 'fa'},
        'location': {'color': 'blue', 'icon': 'map-marker', 'prefix': 'fa'},
    }

    # Check both class and type fields
    for key_term in [feature_class, feature_type]:
        if key_term in icon_mapping:
            return icon_mapping[key_term]

        # Check if any mapping key is contained in the property value
        for map_key, map_icon in icon_mapping.items():
            if map_key in key_term:
                return map_icon

    # If no specific icon found, return default blue map marker
    return icon_info


def _get_crs_from_geojson(geojson_data: dict) -> str:
    """Extract CRS information from GeoJSON."""
    if 'crs' in geojson_data:
        crs_info = geojson_data['crs']
        if 'properties' in crs_info and 'name' in crs_info['properties']:
            crs_name = crs_info['properties']['name']

            # Extract EPSG code if present
            if 'EPSG::' in crs_name:
                epsg_code = crs_name.split('EPSG::')[-1]
                return f"EPSG:{epsg_code}"

            return crs_name

    return "WGS84 (assumed)"


def _transform_geojson_coordinates(geojson_data: dict) -> tuple:
    """
    Transform GeoJSON coordinates to WGS84 if needed.

    Returns:
        (transformed_geojson, transform_info)
    """
    # Supported coordinate systems
    SUPPORTED_CRS = {
        'EPSG:2056': {  # Swiss LV95
            'name': 'Swiss LV95',
            'transform_func': _transform_swiss_lv95_to_wgs84
        },
        'EPSG:31287': {  # Austrian MGI
            'name': 'Austrian MGI / Austria Lambert',
            'transform_func': _transform_austrian_mgi_to_wgs84
        },
        'EPSG:3416': {  # Austrian MGI M28
            'name': 'Austrian MGI M28',
            'transform_func': _transform_austrian_mgi_to_wgs84
        },
        'EPSG:4326': {  # WGS84 - no transformation needed
            'name': 'WGS84',
            'transform_func': None
        }
    }

    # Get CRS from GeoJSON
    crs = _get_crs_from_geojson(geojson_data)

    transform_info = {
        'transformed': False,
        'from_crs': crs,
        'to_crs': 'WGS84',
        'warning': None
    }

    # Check if transformation is needed
    if crs == "WGS84 (assumed)" or crs == "EPSG:4326":
        return geojson_data, transform_info

    # Check if CRS is supported
    if crs not in SUPPORTED_CRS:
        transform_info['warning'] = f"Unsupported coordinate system: {crs}. Displaying as-is (may not show correctly on map)"
        return geojson_data, transform_info

    # Get transformation function
    transform_func = SUPPORTED_CRS[crs]['transform_func']
    if transform_func is None:  # Already WGS84
        return geojson_data, transform_info

    # Transform the coordinates
    try:
        transformed_geojson = _apply_coordinate_transformation(geojson_data, transform_func)
        transform_info['transformed'] = True
        return transformed_geojson, transform_info
    except Exception as e:
        transform_info['warning'] = f"Coordinate transformation failed: {str(e)}"
        return geojson_data, transform_info


def _apply_coordinate_transformation(geojson_data: dict, transform_func) -> dict:
    """Apply coordinate transformation to all coordinates in GeoJSON."""
    import copy
    transformed_data = copy.deepcopy(geojson_data)

    def transform_coordinates(coords):
        """Recursively transform coordinates."""
        if isinstance(coords[0], (int, float)):
            # This is a coordinate pair [x, y]
            return list(transform_func(coords[0], coords[1]))
        else:
            # This is a nested coordinate array
            return [transform_coordinates(coord) for coord in coords]

    def process_geometry(geometry):
        """Process geometry coordinates."""
        if 'coordinates' in geometry:
            geometry['coordinates'] = transform_coordinates(geometry['coordinates'])

    # Process different GeoJSON types
    if transformed_data.get('type') == 'FeatureCollection':
        for feature in transformed_data.get('features', []):
            if 'geometry' in feature and feature['geometry']:
                process_geometry(feature['geometry'])
    elif transformed_data.get('type') == 'Feature':
        if 'geometry' in transformed_data and transformed_data['geometry']:
            process_geometry(transformed_data['geometry'])
    else:
        # Direct geometry
        process_geometry(transformed_data)

    # Update CRS to WGS84
    transformed_data['crs'] = {
        "type": "name",
        "properties": {
            "name": "urn:ogc:def:crs:EPSG::4326"
        }
    }

    return transformed_data


def _transform_swiss_lv95_to_wgs84(x: float, y: float) -> tuple:
    """
    Transform Swiss LV95 (EPSG:2056) coordinates to WGS84.

    Uses the official Swisstopo transformation formulas.
    """
    # Official Swisstopo approximate transformation LV95 -> WGS84
    # Convert LV95 to auxiliary values
    y_aux = (x - 2600000) / 1000000
    x_aux = (y - 1200000) / 1000000

    # Calculate longitude (lambda) in decimal degrees
    lon = 2.6779094 + 4.728982 * y_aux + 0.791484 * y_aux * x_aux + 0.1306 * y_aux * x_aux ** 2 - 0.0436 * y_aux ** 3

    # Calculate latitude (phi) in decimal degrees
    lat = 16.9023892 + 3.238272 * x_aux - 0.270978 * y_aux ** 2 - 0.002528 * x_aux ** 2 - 0.0447 * y_aux ** 2 * x_aux - 0.0140 * x_aux ** 3

    # Convert from arc seconds to degrees
    lon = lon * 100 / 36
    lat = lat * 100 / 36

    return (lon, lat)


def _transform_austrian_mgi_to_wgs84(x: float, y: float) -> tuple:
    """
    Transform Austrian MGI coordinates to WGS84.

    This is a simplified transformation for Austrian coordinate systems.
    For production use, consider using pyproj library for exact transformations.
    """
    # Simplified transformation for Austrian MGI to WGS84
    # This is an approximation - for exact results use pyproj

    # Basic parameters for Austria (simplified)
    # These are rough approximations for demonstration

    # If coordinates are in the expected range for Austrian systems
    if 400000 <= x <= 900000 and 5000000 <= y <= 5500000:
        # Assume UTM-like system
        # Very rough conversion (should use proper projection libraries)
        lon = (x - 500000) / 111320 + 13.0  # Rough approximation
        lat = y / 111320 - 45.0  # Rough approximation
    else:
        # Try different approach for other Austrian systems
        lon = x / 100000 + 10.0  # Very rough approximation
        lat = y / 100000 + 45.0  # Very rough approximation

    return (lon, lat)


def _display_text_content(client: NextcloudClient, filename: str, display_name: str) -> None:
    """Display text content for other file types."""
    try:
        content = client.download_text_file(filename)

        st.write(f"**File:** {display_name}")
        st.write(f"**Size:** {len(content)} characters")

        # Show content in a text area
        st.text_area(
            "File Content:",
            content,
            height=400,
            key="text_content"
        )

    except Exception as e:
        st.error(f"❌ Failed to display text content: {e}")
    """View GeoJSON file on an interactive map."""
    try:
        with st.spinner(f"Loading {display_name} on map..."):
            # Download and parse GeoJSON
            content = client.download_text_file(filename)
            geojson_data = json.loads(content)

            # Create expandable map section
            with st.expander(f"🗺️ Map View: {display_name}", expanded=True):

                # Basic GeoJSON info
                geojson_type = geojson_data.get('type', 'Unknown')
                st.write(f"**Type:** {geojson_type}")

                # Try to use folium for map display
                try:
                    import folium
                    from streamlit_folium import st_folium

                    # Create map centered on Switzerland (default)
                    center_lat, center_lon = 46.8182, 8.2275

                    # Try to find bounds of the GeoJSON to center the map
                    bounds = _get_geojson_bounds(geojson_data)
                    if bounds:
                        center_lat = (bounds[1] + bounds[3]) / 2  # Average of min and max lat
                        center_lon = (bounds[0] + bounds[2]) / 2  # Average of min and max lon

                    # Create the map
                    m = folium.Map(
                        location=[center_lat, center_lon],
                        zoom_start=10,
                        tiles="OpenStreetMap"
                    )

                    # Add GeoJSON to map
                    folium.GeoJson(
                        geojson_data,
                        style_function=lambda x: {
                            'fillColor': 'blue',
                            'color': 'blue',
                            'weight': 2,
                            'fillOpacity': 0.6,
                        },
                        popup=folium.Popup(f"<b>{display_name}</b>", max_width=300)
                    ).add_to(m)

                    # Fit map to bounds if available
                    if bounds:
                        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

                    # Display the map
                    st_folium(m, width=700, height=400)

                except ImportError:
                    # Fallback: show GeoJSON as text if folium not available
                    st.warning("📍 Map display requires folium and streamlit-folium packages")
                    st.write("**GeoJSON Content Preview:**")
                    st.json(geojson_data)

                # Show feature count if it's a FeatureCollection
                if geojson_type == 'FeatureCollection':
                    features = geojson_data.get('features', [])
                    st.write(f"**Features:** {len(features)}")

                    # Show first few feature properties
                    if features and features[0].get('properties'):
                        st.write("**Sample Properties:**")
                        sample_props = features[0]['properties']
                        for key, value in list(sample_props.items())[:5]:  # Show first 5 properties
                            st.write(f"• **{key}:** {value}")
                        if len(sample_props) > 5:
                            st.write(f"... and {len(sample_props) - 5} more properties")

    except json.JSONDecodeError:
        st.error(f"❌ Invalid JSON in file: {display_name}")
    except Exception as e:
        st.error(f"❌ Failed to display map for {display_name}: {e}")


def _preview_file(client: NextcloudClient, filename: str) -> None:
    """Preview file content."""
    try:
        if filename.lower().endswith('.csv'):
            df = client.read_csv(filename)
            with st.expander(f"📊 CSV Preview: {filename}", expanded=True):
                st.dataframe(df.head(20), use_container_width=True)
        elif filename.lower().endswith(('.geojson', '.json')):
            content = client.download_text_file(filename)
            geojson_data = json.loads(content)
            with st.expander(f"🗺️ GeoJSON Preview: {filename}", expanded=True):
                st.write(f"**Type:** {geojson_data.get('type', 'Unknown')}")
                if geojson_data.get('type') == 'FeatureCollection':
                    features = geojson_data.get('features', [])
                    st.write(f"**Features:** {len(features)}")
                st.json(geojson_data)
        else:
            content = client.download_text_file(filename)
            with st.expander(f"👁️ Text Preview: {filename}", expanded=True):
                st.text_area("File Content:", content[:1000], height=200)
    except Exception as e:
        st.error(f"❌ Failed to preview {filename}: {e}")


def _get_geojson_bounds(geojson_data: dict) -> tuple:
    """
    Calculate bounding box for GeoJSON data.
    Returns (min_lon, min_lat, max_lon, max_lat) or None.
    """
    try:
        coords = []

        def extract_coords(obj):
            if isinstance(obj, dict):
                if 'coordinates' in obj:
                    coords.extend(_flatten_coordinates(obj['coordinates']))
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        extract_coords(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_coords(item)

        extract_coords(geojson_data)

        if coords:
            lons = [c[0] for c in coords if len(c) >= 2]
            lats = [c[1] for c in coords if len(c) >= 2]
            if lons and lats:
                return (min(lons), min(lats), max(lons), max(lats))

        return None
    except:
        return None


def _flatten_coordinates(coordinates):
    """Recursively flatten coordinate arrays."""
    result = []

    def flatten(coord_array):
        if not isinstance(coord_array, list):
            return

        if len(coord_array) >= 2 and all(isinstance(x, (int, float)) for x in coord_array[:2]):
            # This is a coordinate pair
            result.append(coord_array)
        else:
            # This is a nested array
            for item in coord_array:
                flatten(item)

    flatten(coordinates)
    return result
    """
    Calculate bounding box for GeoJSON data.
    Returns (min_lon, min_lat, max_lon, max_lat) or None.
    """
    try:
        coords = []

        def extract_coords(obj):
            if isinstance(obj, dict):
                if 'coordinates' in obj:
                    coords.extend(_flatten_coordinates(obj['coordinates']))
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        extract_coords(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_coords(item)

        extract_coords(geojson_data)

        if coords:
            lons = [c[0] for c in coords if len(c) >= 2]
            lats = [c[1] for c in coords if len(c) >= 2]
            if lons and lats:
                return (min(lons), min(lats), max(lons), max(lats))

        return None
    except:
        return None


def _flatten_coordinates(coordinates):
    """Recursively flatten coordinate arrays."""
    result = []

    def flatten(coord_array):
        if not isinstance(coord_array, list):
            return

        if len(coord_array) >= 2 and all(isinstance(x, (int, float)) for x in coord_array[:2]):
            # This is a coordinate pair
            result.append(coord_array)
        else:
            # This is a nested array
            for item in coord_array:
                flatten(item)

    flatten(coordinates)
    return result


# ==================== UTILITY FUNCTIONS ====================

def get_nextcloud_client(workspace_id: str) -> NextcloudClient:
    """Get or create NextcloudClient for a workspace."""
    return create_client_from_env(workspace_id)


def validate_nextcloud_config() -> bool:
    """Validate that Nextcloud configuration is available."""
    username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
    password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
    return bool(username and password)