# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Data Products Module Package
File: components/data_products/__init__.py

Main data products module for exploring TTL-based data products from NextCloud.
Supports both global and private workspace data products.
"""

import streamlit as st
import os
from typing import Optional

# Check for required dependencies
try:
    from rdflib import Graph
    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False

try:
    import folium
    from streamlit_folium import st_folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


def is_development_mode() -> bool:
    """Check if running in development mode"""
    return os.getenv('STREAMLIT_ENV') == 'development' or os.getenv('DEBUG') == 'true'


def initialize_session_state():
    """Initialize session state for data products module"""
    if 'loaded_data_products' not in st.session_state:
        st.session_state.loaded_data_products = {}
    if 'selected_data_product' not in st.session_state:
        st.session_state.selected_data_product = None
    if 'selected_component' not in st.session_state:
        st.session_state.selected_component = None
    if 'visualization_cache' not in st.session_state:
        st.session_state.visualization_cache = {}
    if 'data_product_filters' not in st.session_state:
        st.session_state.data_product_filters = {
            'product_type': 'all',  # all, global, private
            'component_types': [],
            'visualization_type': 'all'
        }


def data_products_module(workspace_or_client=None):
    """Main data products module interface

    Args:
        workspace_or_client: Either a workspace dict or GraphDBClient object
    """

    st.header("🔍 Data Products Explorer")

    # Check dependencies
    if not RDFLIB_AVAILABLE:
        st.error("❌ RDFLib not available - required for TTL parsing")
        st.info("💡 Install with: pip install rdflib")
        return

    # Initialize session state
    initialize_session_state()

    # Handle both workspace dict and client object
    workspace = None
    if workspace_or_client:
        # Check if it's a GraphDBClient or workspace dict
        if hasattr(workspace_or_client, '__class__') and workspace_or_client.__class__.__name__ == 'GraphDBClient':
            # It's a client, get workspace from session state
            workspace = st.session_state.get('current_workspace')
        else:
            # It's a workspace dict
            workspace = workspace_or_client
    else:
        # Try to get from session state
        workspace = st.session_state.get('current_workspace')

    # Get workspace info
    workspace_name = workspace.get('name', 'Unknown') if workspace else 'No Workspace'
    workspace_id = workspace.get('id') if workspace else None

    st.write(f"Explore TTL-based data products from **{workspace_name}** workspace")

    # Create tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs([
        "📦 Data Products",
        "🔍 Explorer",
        "📊 Analytics",
        "📁 Resources"
    ])

    with tab1:
        try:
            from .data_loader import render_data_products_tab
            render_data_products_tab(workspace_id)
        except Exception as e:
            st.error(f"Data Products tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab2:
        try:
            from .data_explorer import render_explorer_tab
            render_explorer_tab()
        except Exception as e:
            st.error(f"Explorer tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab3:
        try:
            from .data_visualizer import render_analytics_tab
            render_analytics_tab()
        except Exception as e:
            st.error(f"Analytics tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab4:
        try:
            from .resource_analyzer import render_resources_tab
            render_resources_tab()
        except Exception as e:
            st.error(f"Resources tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())


# Export the main function
__all__ = ['data_products_module']

# Also export with the expected name for backward compatibility
data_products = data_products_module