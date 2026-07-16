# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
TTL to YAML Converter Module - Enhanced with NextCloud Integration
File: components/api_submission_module/ttl_convert.py

Enhanced converter with NextCloud workspace integration to read TTL files
directly from graph/scenarios folder, while maintaining manual upload capability.
"""

import streamlit as st
import yaml
import json
import tempfile
import os
from collections import OrderedDict
from typing import Dict, List, Any, Optional, Tuple, Set
import re

# Service definitions come from the shared catalog (workspace `services/` + the
# global library), the same code path the Scenario Builder and the rest of the
# app use, so the convert tab can never drift to a different template source.
from components.service_catalog import services_by_name, read_service_text

from .validation import validate_payload, render_validation

# Try to import rdflib
try:
    import rdflib
    from rdflib import Graph, URIRef, Literal, Namespace
    from rdflib.namespace import RDF, RDFS, XSD
    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False
    if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
        st.error("⚠️ rdflib not installed. Please install it with: pip install rdflib")


yaml.add_representer(OrderedDict, lambda dumper, data: dumper.represent_mapping('tag:yaml.org,2002:map', data.items()))


from backend.api_submission.ttl_converter import (
    preprocess_ttl_content,
    fix_multiline_string_value,
    RobustTTL2YAMLProcessor,
    clean_placeholder_values,
)


def load_ttl_files_from_nextcloud() -> Dict[str, Dict[str, Any]]:
    """
    Load TTL files from NextCloud workspace graph/scenarios folder.

    Returns:
        Dictionary mapping filename to file info (content, size, modified)
    """
    try:
        # Local mode: read scenario TTLs from the active workspace's storage
        # (local FS, NextCloud, or S3) via the storage abstraction.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is not None:
            ttl_files = {}
            try:
                for rel in storage.glob("scenarios/*.ttl"):
                    content = storage.read_text(rel)
                    ttl_files[rel.rsplit("/", 1)[-1]] = {
                        'content': content,
                        'size': len(content.encode("utf-8")),
                        'last_modified': None,
                        'workspace_id': getattr(ctx, "id", None),
                    }
                return ttl_files
            except Exception:
                pass  # fall through to the NextCloud path below

        # Try to get workspace info from session state
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            return {}

        workspace_id = current_workspace.get('id')
        if not workspace_id:
            return {}

        # Import NextCloud client
        from components.nextcloud_client import NextcloudClient

        # Create client for this workspace
        client = NextcloudClient(workspace_id=workspace_id)

        # List files in graph/scenarios subdirectory
        scenarios_path = "graph/scenarios"
        try:
            # Build full path for scenarios folder
            full_workspace_path = f"{workspace_id}/{scenarios_path}"

            # List files using the full path
            client.workspace_id = full_workspace_path
            files = client.list_files()

            # Filter for TTL files
            ttl_files = {}
            for file_info in files:
                filename = file_info['name']
                if filename.lower().endswith('.ttl'):
                    try:
                        # Download file content
                        content = client.download_text_file(filename)

                        ttl_files[filename] = {
                            'content': content,
                            'size': file_info.get('size', 0),
                            'last_modified': file_info.get('last_modified'),
                            'workspace_id': workspace_id
                        }
                    except Exception as e:
                        if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
                            st.warning(f"⚠️ Could not load {filename}: {str(e)}")

            return ttl_files

        except Exception as e:
            # If graph/scenarios doesn't exist or is empty, return empty dict
            if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
                st.info(f"💡 No scenarios folder found at {scenarios_path}")
            return {}

    except ImportError:
        if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
            st.warning("⚠️ NextCloud client not available")
        return {}

    except Exception as e:
        if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
            st.error(f"Error loading TTL files from NextCloud: {str(e)}")
        return {}


def load_service_requirements():
    """Available service definitions keyed by name (workspace `services/` + the
    global library), via the shared service catalog. Values are ServiceRef objects."""
    services = services_by_name()
    if not services and hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
        st.warning("⚠️ No service templates found in the workspace `services/` folder or the global library.")
    return services


def get_service_template_content(service_ref) -> Optional[Dict]:
    """Parsed template dict for a ServiceRef (read from its own source)."""
    if service_ref is None:
        return None
    # Catalog already parsed it on discovery; re-read for freshness, fall back to
    # the parsed content cached on the ref.
    try:
        text = read_service_text(service_ref)
        if text:
            return yaml.safe_load(text)
    except Exception as e:
        if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
            st.error(f"Error loading service template: {str(e)}")
    return getattr(service_ref, "content", None)


def render_scenario_selection_tab():
    """Render the conversion interface with NextCloud and manual upload options."""
    st.subheader("🚀 TTL to JSON/YAML Converter")
    st.write("Convert scenario TTL files to service-specific JSON/YAML format")

    if not RDFLIB_AVAILABLE:
        st.error("⚠️ rdflib is not installed. Please install it:")
        st.code("pip install rdflib")
        return

    services = load_service_requirements()
    if not services:
        st.warning("⚠️ No service templates found")
        return

    # Service selection
    selected_service = st.selectbox(
        "Select service template:",
        options=list(services.keys()),
        key="service_selector"
    )

    if selected_service:
        service_info = services[selected_service]
        st.success(f"✅ Using template: **{selected_service}**")

        # Pick scenarios from workspace files, the knowledge graph, or upload,
        # via the shared loader used across the platform.
        st.write("### 📂 Select Scenario Source")
        from components.scenario_loader import render_scenario_loader

        selected_scenarios = render_scenario_loader(
            client=st.session_state.get("workspace_client"),
            key_prefix="apisub_convert",
            allow_multiple=True,
            service=selected_service,
        )

        ttl_files_to_process = [
            {'name': item['name'], 'content': item['content']}
            for item in selected_scenarios
        ]

        # Process files if any are available
        if ttl_files_to_process:
            st.write(f"📋 **{len(ttl_files_to_process)} file(s) ready for conversion**")

            # Options
            col1, col2 = st.columns(2)
            with col1:
                debug_mode = st.checkbox("🛠 Debug Mode", value=False)
            with col2:
                clean_missing = st.checkbox("🧹 Clean Missing Values", value=True)

            # Convert button
            if st.button("🚀 Convert", type="primary"):
                with st.spinner("Converting..."):
                    results = {}

                    template_content = get_service_template_content(service_info)
                    if not template_content:
                        st.error("Could not load template")
                        return

                    # 'connection' is registration metadata, not payload shape -
                    # drop it so it isn't converted or flagged by validation.
                    if isinstance(template_content, dict):
                        template_content = {k: v for k, v in template_content.items()
                                            if k != 'connection'}

                    for ttl_file in ttl_files_to_process:
                        try:
                            # Process file
                            filename = ttl_file['name']
                            ttl_content = ttl_file['content']

                            processor = RobustTTL2YAMLProcessor()
                            converted = processor.process(
                                template_content=template_content,
                                ttl_source=ttl_content,
                                is_ttl_file=False,
                                debug=debug_mode
                            )

                            # Validate the RAW payload (before cleaning) against the
                            # template, so unresolved references are still visible.
                            validation = validate_payload(converted, template_content)

                            if clean_missing:
                                converted = clean_placeholder_values(converted)

                            results[filename] = {
                                'success': True,
                                'data': dict(converted) if converted else {},
                                'service': selected_service,
                                'template': template_content,
                                'validation': validation,
                                'stats': {
                                    'data_quality': validation.data_quality,
                                    'placeholder_count': validation.placeholder_count,
                                }
                            }

                        except Exception as e:
                            results[filename] = {
                                'success': False,
                                'error': str(e)
                            }

                    # Store results in session state for API submission
                    if 'conversion_results' not in st.session_state:
                        st.session_state.conversion_results = {}

                    st.session_state.target_service = selected_service

                    for scenario_name, result in results.items():
                        st.session_state.conversion_results[scenario_name] = result

                    # Show results
                    st.success("✅ Conversion complete!")

                    for name, result in results.items():
                        if result['success']:
                            with st.expander(f"✅ {name}", expanded=True):
                                if result.get('validation') is not None:
                                    render_validation(result['validation'])
                                st.json(result['data'])

                                col1, col2 = st.columns(2)
                                with col1:
                                    yaml_str = yaml.dump(result['data'], default_flow_style=False)
                                    st.download_button(
                                        "📄 Download YAML",
                                        yaml_str,
                                        f"{name}.yaml",
                                        "application/x-yaml"
                                    )
                                with col2:
                                    json_str = json.dumps(result['data'], indent=2, ensure_ascii=False)
                                    st.download_button(
                                        "📋 Download JSON",
                                        json_str.encode('utf-8'),
                                        f"{name}.json",
                                        "application/json"
                                    )
                        else:
                            with st.expander(f"❌ {name}"):
                                st.error(f"Error: {result.get('error', 'Unknown error')}")