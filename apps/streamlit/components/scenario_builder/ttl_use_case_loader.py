# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: the TTL use-case loader moved to
``backend.scenario_builder.use_case_loader``.

The rdflib parsing/extraction engine is now headless in backend/. What stays
here is exactly the Streamlit wiring the backend class parameterized away:

* ``NextCloudTTLUseCaseLoader`` (same name, same constructor shape) subclasses
  the backend loader and restores the old behavior verbatim — workspace id
  from ``st.session_state['current_workspace']``, enabled data products from
  ``st.session_state['enabled_ttl_data_products']``, the session-aware
  ``DataProductProcessor``, and status messages via ``st.warning`` /
  ``st.error`` / ``st.write``.
* the module-level session-state helpers (``get_workspace_ttl_loader`` & co.)
  and the status banner, unchanged.

Every existing ``from components.scenario_builder.ttl_use_case_loader import
X`` call site keeps working unchanged.
"""
from typing import Dict, List, Optional
import streamlit as st

from backend.scenario_builder.use_case_loader import (
    RDFLIB_AVAILABLE,
    NextCloudTTLUseCaseLoader as _BackendTTLUseCaseLoader,
)

if not RDFLIB_AVAILABLE:
    st.error("rdflib not available. Please install with: pip install rdflib")

# Pure display helpers already relocated in Phase 3; this module used to define
# identical copies, so keep them importable from here.
from backend.scenario_builder.display_utils import (  # noqa: F401
    format_ttl_component_for_display,
    get_uri_fragment,
)

# Import the new data product processor
try:
    from components.data_products.data_loader import DataProductProcessor

    DATA_PROCESSOR_AVAILABLE = True
except ImportError:
    DATA_PROCESSOR_AVAILABLE = False


def _st_status(level: str, message: str) -> None:
    """Map backend status events onto the exact old Streamlit calls."""
    if level == 'error':
        st.error(message)
    elif level == 'warning':
        st.warning(message)
    else:
        st.write(message)


class NextCloudTTLUseCaseLoader(_BackendTTLUseCaseLoader):
    """The backend loader plus the Streamlit session/display behavior it had
    before the move. Constructor signature is unchanged."""

    def __init__(self, workspace_id: str = None):
        """Initialize loader with workspace context"""
        if not workspace_id:
            current_workspace = st.session_state.get('current_workspace')
            if current_workspace:
                workspace_id = current_workspace['id']
        super().__init__(workspace_id=workspace_id, on_status=_st_status)

    def _create_data_processor(self):
        """The session-aware DataProductProcessor, as before the move."""
        if not DATA_PROCESSOR_AVAILABLE:
            return None
        try:
            return DataProductProcessor(workspace_id=self.workspace_id)
        except Exception as e:
            st.error(f"Failed to initialize data processor: {e}")
            return None

    def _enabled_data_products(self) -> List[str]:
        """Enabled TTL data products come from session state, as before."""
        return st.session_state.get('enabled_ttl_data_products', [])

    def clear_cache(self):
        """Clear all caches completely"""
        super().clear_cache()

        # Also clear any session state caches
        keys_to_remove = []
        for key in st.session_state.keys():
            if key.startswith('ttl_components_') or key.startswith('dp_components_'):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del st.session_state[key]


# Global functions for integration
def get_workspace_ttl_loader() -> Optional[NextCloudTTLUseCaseLoader]:
    """Get TTL loader for current workspace"""
    current_workspace = st.session_state.get('current_workspace')
    if not current_workspace:
        return None

    workspace_id = current_workspace['id']

    cache_key = f'ttl_loader_{workspace_id}'
    if cache_key not in st.session_state:
        st.session_state[cache_key] = NextCloudTTLUseCaseLoader(workspace_id)

    return st.session_state[cache_key]


def get_ttl_use_case_components(component_type: str) -> List[Dict]:
    """Get components from workspace TTL and enabled data products"""
    if not RDFLIB_AVAILABLE:
        return []

    loader = get_workspace_ttl_loader()
    if not loader:
        return []

    return loader.get_components_by_type(component_type)


def get_available_ttl_use_cases() -> List[str]:
    """Get list of available TTL use case files from current workspace"""
    loader = get_workspace_ttl_loader()
    if not loader:
        return []

    ttl_files = loader.get_available_ttl_files()
    return ttl_files


def get_available_data_products() -> Dict[str, List[Dict]]:
    """Get available private and global data products"""
    loader = get_workspace_ttl_loader()
    if not loader:
        return {'private': [], 'global': []}

    return {
        'private': loader.get_available_private_data_products(),
        'global': loader.get_available_global_data_products()
    }


def show_ttl_use_cases_status():
    """Show status of workspace TTL files and data products in the UI"""
    if not RDFLIB_AVAILABLE:
        return

    loader = get_workspace_ttl_loader()
    if not loader:
        return

    current_workspace = st.session_state.get('current_workspace')
    workspace_name = current_workspace['name'] if current_workspace else 'Unknown'

    graph = loader.load_workspace_classes_and_attributes()
    workspace_components_count = 0

    if graph:
        components_by_type = loader.extract_components_from_graph(graph, f"workspace_{loader.workspace_id}")
        workspace_components_count = sum(len(comps) for comps in components_by_type.values())

    enabled_data_products = st.session_state.get('enabled_ttl_data_products', [])
    data_product_components_count = 0

    for data_product_id in enabled_data_products:
        if ':' in data_product_id:
            dp_type, dp_name = data_product_id.split(':', 1)
            try:
                data_product = {
                    'name': dp_name,
                    'type': dp_type,
                    'path': f"{'private_data_products' if dp_type == 'private' else 'open_data_products'}/{dp_name}"
                }
                dp_components_by_type = loader.get_components_from_data_product(data_product)
                data_product_components_count += sum(len(comps) for comps in dp_components_by_type.values())
            except Exception as e:
                st.write(f"Error counting components from {dp_name}: {e}")

    total_components = workspace_components_count + data_product_components_count

    if total_components > 0:
        status_parts = []
        if workspace_components_count > 0:
            status_parts.append(f"📄 {workspace_components_count} from workspace")
        if data_product_components_count > 0:
            status_parts.append(f"📊 {data_product_components_count} from data products")

        status_text = " | ".join(status_parts)
        st.success(f"Loaded {total_components} components for **{workspace_name}** ({status_text})")
    elif enabled_data_products:
        st.info(f"📊 Data products enabled but no components found for **{workspace_name}**")


def get_nested_property_from_ttl_component(component: Dict, property_path: str) -> Optional[str]:
    """Get nested property value from TTL component using property path"""
    loader = get_workspace_ttl_loader()
    if not loader:
        return None

    return loader.get_nested_property_value(component, property_path)
