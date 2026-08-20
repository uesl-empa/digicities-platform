# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: the data-product processor moved to
``backend.data_products.processor`` (Phase 5 of the backend/UI separation).

The listing/loading engine is now headless in backend/. What stays here is
exactly the Streamlit wiring the backend class parameterized away:

* ``DataProductProcessor`` (same name, same constructor shape) subclasses the
  backend processor and restores the old behavior verbatim — workspace id from
  ``st.session_state['current_workspace']``, storage from
  ``st.session_state['workspace_context']``, and status messages via
  ``st.warning`` / ``st.error`` / ``st.success`` / ``st.code`` (info-level
  diagnostics keep going to stdout, as before).
* ``DataProductLoader`` (the legacy wrapper) and ``render_data_products_tab``
  (the tab UI), unchanged.

Every existing ``from components.data_products.data_loader import X`` call
site keeps working unchanged.

Each data product is a folder containing:
- FOLDER_NAME/FOLDER_NAME.ttl
- FOLDER_NAME/resources/[various resource files]
"""

import streamlit as st
from typing import Dict, List, Optional
from dataclasses import dataclass

from backend.data_products.processor import DataProductProcessor as _BackendProcessor


@dataclass
class Resource:
    """Represents a single resource file within a data product."""
    name: str
    path: str
    type: str
    size: int = 0
    last_modified: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'path': self.path,
            'type': self.type,
            'size': self.size,
            'last_modified': self.last_modified
        }


def _st_status(level: str, message: str) -> None:
    """Map backend status events onto the exact old Streamlit calls."""
    if level == 'error':
        st.error(message)
    elif level == 'warning':
        st.warning(message)
    elif level == 'success':
        st.success(message)
    elif level == 'code':
        st.code(message)
    else:
        # The old class print()ed its [data_products] diagnostics.
        print(message)


class DataProductProcessor(_BackendProcessor):
    """The backend processor plus the Streamlit session/display behavior it
    had before the move. Constructor signature is unchanged."""

    def __init__(self, workspace_id: Optional[str] = None):
        # Try to get workspace from session or parameter (as before the move).
        if not workspace_id:
            current_workspace = st.session_state.get('current_workspace')
            if current_workspace:
                workspace_id = current_workspace.get('id')
                self.workspace_name = current_workspace.get('name', '')

        # Pick up the WorkspaceContext storage if the session has one; the
        # backend falls back to the registry lookup otherwise.
        workspace_storage = None
        try:
            ctx = st.session_state.get("workspace_context")
            if ctx is not None:
                workspace_storage = ctx.storage
        except Exception as e:
            print(f"[data_products] workspace storage lookup skipped: {e}")

        super().__init__(workspace_id=workspace_id,
                         workspace_storage=workspace_storage,
                         on_status=_st_status)

    def process_all_data_products(self) -> Dict[str, Dict]:
        """Process all data products, with the old per-product spinners."""
        all_products = {}

        if self.workspace_id:
            for folder_name in self.list_private_folders():
                with st.spinner(f"Processing private: {folder_name}"):
                    product = self.process_data_product(folder_name, is_private=True)
                    if product:
                        all_products[f"private:{folder_name}"] = product

            for folder_name in self.list_open_folders():
                with st.spinner(f"Processing open: {folder_name}"):
                    product = self.process_data_product(folder_name, is_private=False)
                    if product:
                        all_products[f"global:{folder_name}"] = product

        # Single summary message at the end
        if all_products:
            st.success(f"✅ Loaded {len(all_products)} data products")
        else:
            st.warning("No data products found")

        return all_products


# Wrapper for backwards compatibility
class DataProductLoader:
    """Legacy wrapper that uses DataProductProcessor internally."""

    def __init__(self, workspace_id: Optional[str] = None):
        self.processor = DataProductProcessor(workspace_id)
        self.workspace_id = workspace_id

    def load_all_data_products(self) -> Dict[str, Dict]:
        return self.processor.process_all_data_products()

    def load_resource_file(self, product: Dict, resource_filename: str):
        return self.processor.load_resource_file(product, resource_filename)

    def list_resource_files(self, product: Dict) -> List[str]:
        resources = product.get('resources', [])
        if resources and isinstance(resources[0], dict):
            return [r['name'] for r in resources]
        return resources


def render_data_products_tab(workspace_id: Optional[str] = None):
    """Render the data products loading tab."""
    import os

    st.subheader("📦 Available Data Products")

    # Local mode reads data products from the active workspace's storage
    # (private_data_products/); NextCloud is only needed for the legacy global
    # "open" products. Allow the tab through whenever either is available.
    username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
    password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
    ctx = st.session_state.get("workspace_context")
    has_storage = ctx is not None and getattr(ctx, "storage", None) is not None

    if not has_storage and not (username and password):
        st.info(
            "Open a workspace to browse its `private_data_products/`, "
            "or configure NextCloud credentials for global data products."
        )
        return

    # Initialize processor (wires ctx.storage automatically when a workspace is open)
    processor = DataProductProcessor(workspace_id)

    # Debug info
    with st.expander("🔧 Debug Info", expanded=False):
        st.write(f"Username: {processor.username}")
        st.write(f"Workspace ID: {processor.workspace_id}")
        st.write(f"Base URL: {processor.base_url}")
        st.write(f"Auth configured: {'Yes' if processor.headers.get('Authorization') else 'No'}")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.write("Load and manage TTL data products from NextCloud")

    with col2:
        if st.button("🔄 Load/Refresh", type="primary", use_container_width=True):
            with st.spinner("Loading data products..."):
                products = processor.process_all_data_products()
                st.session_state.loaded_data_products = products

                if products:
                    st.success(f"✅ Loaded {len(products)} data products")
                else:
                    st.warning("No data products found")

    with col3:
        if st.button("🗑️ Clear All", use_container_width=True):
            st.session_state.loaded_data_products = {}
            st.session_state.selected_data_product = None
            st.session_state.selected_component = None
            st.info("Cleared all loaded data products")

    # Display loaded data products
    if 'loaded_data_products' in st.session_state and st.session_state.loaded_data_products:
        st.markdown("---")

        # Summary metrics
        global_count = sum(1 for k in st.session_state.loaded_data_products.keys() if k.startswith("global:"))
        private_count = sum(1 for k in st.session_state.loaded_data_products.keys() if k.startswith("private:"))

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Products", len(st.session_state.loaded_data_products))
        with col2:
            st.metric("🌍 Open", global_count)
        with col3:
            st.metric("🔒 Private", private_count)

        # Product cards
        st.markdown("### Loaded Data Products")

        # Show private products first if any
        if private_count > 0:
            st.markdown("#### 🔒 Private Data Products")
            for key, product in st.session_state.loaded_data_products.items():
                if key.startswith("private:"):
                    with st.expander(f"📁 {product['name']}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"**Folder:** `{product.get('folder_path', product['path'])}/`")
                            st.write(f"**TTL File:** `{product.get('ttl_path', product['path'])}`")
                            st.write(f"**Components:** {product.get('component_count', 0)}")
                            st.write(f"**Component Types:** {', '.join(product.get('component_types', []))}")

                            # Show available resources
                            resources = product.get('resources', [])
                            if resources:
                                st.write(f"**Resources ({len(resources)} files):**")
                                for i, resource in enumerate(resources[:5]):
                                    if isinstance(resource, dict):
                                        st.caption(f"  • {resource['name']} ({resource['type']})")
                                    else:
                                        st.caption(f"  • {resource}")
                                if len(resources) > 5:
                                    st.caption(f"  ... and {len(resources) - 5} more")

                        with col2:
                            if st.button(f"Select", key=f"select_{key}", use_container_width=True):
                                st.session_state.selected_data_product = key
                                st.success(f"Selected: {product['name']}")
                                st.rerun()

                            if st.session_state.get('selected_data_product') == key:
                                st.success("✅ Selected")

        # Show global/open products
        if global_count > 0:
            st.markdown("#### 🌍 Open Data Products")
            for key, product in st.session_state.loaded_data_products.items():
                if key.startswith("global:"):
                    with st.expander(f"📁 {product['name']}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"**Folder:** `{product.get('folder_path', product['path'])}/`")
                            st.write(f"**TTL File:** `{product.get('ttl_path', product['path'])}`")
                            st.write(f"**Components:** {product.get('component_count', 0)}")
                            st.write(f"**Component Types:** {', '.join(product.get('component_types', []))}")

                            # Show available resources
                            resources = product.get('resources', [])
                            if resources:
                                st.write(f"**Resources ({len(resources)} files):**")
                                for i, resource in enumerate(resources[:5]):
                                    if isinstance(resource, dict):
                                        st.caption(f"  • {resource['name']} ({resource['type']})")
                                    else:
                                        st.caption(f"  • {resource}")
                                if len(resources) > 5:
                                    st.caption(f"  ... and {len(resources) - 5} more")

                        with col2:
                            if st.button(f"Select", key=f"select_{key}", use_container_width=True):
                                st.session_state.selected_data_product = key
                                st.success(f"Selected: {product['name']}")
                                st.rerun()

                            if st.session_state.get('selected_data_product') == key:
                                st.success("✅ Selected")
    else:
        st.info("👆 Click 'Load/Refresh' to load available data products")

        # Help section
        with st.expander("ℹ️ About Data Products"):
            st.markdown("""
            **Data Products** are self-contained folders with TTL-based semantic descriptions and associated resources.

            **Structure:**
            ```
            DATA_PRODUCT_NAME/
            ├── DATA_PRODUCT_NAME.ttl    # Component definitions
            └── resources/                # Associated data files (lowercase)
                ├── timeseries.csv
                ├── geo.geojson
                └── weather.epw
            ```

            **Locations:**
            - **🌍 Open**: `{username}/global/open_data_products/FOLDER_NAME/`
            - **🔒 Private**: `{username}/{workspace}/private_data_products/FOLDER_NAME/`

            The system lists all folders in these locations and processes each as a data product.
            """)
