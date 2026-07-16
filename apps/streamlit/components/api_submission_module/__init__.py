# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
API Submission Module Package
File: components/api_submission_module/__init__.py

Main API submission module with all functionality contained within the package.
Fixed to avoid circular dependencies.
Now includes Past Results viewer tab.
"""

import streamlit as st
import os
from typing import Optional


def is_development_mode() -> bool:
    """Check if running in development mode"""
    return os.getenv('STREAMLIT_ENV') == 'development' or os.getenv('DEBUG') == 'true'


def initialize_session_state():
    """Initialize session state for API submission module"""
    if 'registered_apis' not in st.session_state:
        st.session_state.registered_apis = {}
    if 'selected_scenarios' not in st.session_state:
        st.session_state.selected_scenarios = []
    if 'validation_results' not in st.session_state:
        st.session_state.validation_results = {}
    if 'submission_history' not in st.session_state:
        st.session_state.submission_history = []
    if 'conversion_results' not in st.session_state:
        st.session_state.conversion_results = {}
    if 'target_service' not in st.session_state:
        st.session_state.target_service = ""
    if 'uploaded_scenarios' not in st.session_state:
        st.session_state.uploaded_scenarios = {}
    if 'temp_files' not in st.session_state:
        st.session_state.temp_files = []
    # Energy Simulation specific
    if 'energy_sim_results' not in st.session_state:
        st.session_state.energy_sim_results = []
    # Debug mode
    if 'debug_mode' not in st.session_state:
        st.session_state.debug_mode = False


def api_submission_module(client=None):
    """Main API submission module interface"""

    st.header("🚀 API Data Submission")
    st.markdown("Upload scenario files and submit them to Energy Simulation API")

    # Initialize session state
    initialize_session_state()

    # Create tabs - NOW WITH PAST RESULTS TAB
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔧 API Configuration",
        "📁 Upload & Convert",
        "🚀 API Submission",
        "📊 View Past Results"  # NEW TAB
    ])

    with tab1:
        try:
            # Import here to avoid circular dependency
            from .api_config import render_api_configuration_tab
            render_api_configuration_tab()
        except Exception as e:
            st.error(f"API Configuration tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab2:
        try:
            # Import here to avoid circular dependency
            from .ttl_convert import render_scenario_selection_tab
            render_scenario_selection_tab()
        except Exception as e:
            st.error(f"TTL Converter tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab3:
        try:
            # Import here to avoid circular dependency
            from .submission_core import render_api_submission_tab
            render_api_submission_tab()
        except Exception as e:
            st.error(f"API Submission tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    with tab4:
        try:
            # Import here to avoid circular dependency
            from .results_viewer import render_past_results_tab
            render_past_results_tab()
        except Exception as e:
            st.error(f"Past Results tab error: {str(e)}")
            if is_development_mode():
                import traceback
                st.code(traceback.format_exc())

    # Footer with status
    try:
        # Import here to avoid circular dependency
        from .submission_core import render_footer
        render_footer()
    except Exception as footer_error:
        if is_development_mode():
            st.error(f"Footer rendering error: {str(footer_error)}")

    # Cleanup temp files on exit
    try:
        # Import here to avoid circular dependency
        from .ttl_convert import cleanup_temp_files
        cleanup_temp_files()
    except Exception:
        pass  # Cleanup errors are not critical


# Export the main function
__all__ = ['api_submission_module']