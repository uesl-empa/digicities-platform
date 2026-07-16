# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/data_products_tab.py
"""
TTL Data Products Selection Tab - OPTIMIZED
Uses fast metadata loading for 10-100x faster initial display
"""
import streamlit as st
from typing import Dict, List, Any, Optional
import os

# Import the data product processor
try:
    from components.data_products.data_loader import DataProductProcessor

    DATA_LOADER_AVAILABLE = True
except ImportError:
    DATA_LOADER_AVAILABLE = False

# Import the enhanced TTL loader for workspace knowledge graph
try:
    from components.scenario_builder.ttl_use_case_loader import get_workspace_ttl_loader

    TTL_LOADER_AVAILABLE = True
except ImportError:
    TTL_LOADER_AVAILABLE = False


def tab_ttl_data_products():
    """Tab for selecting TTL data products with optimized loading"""
    st.subheader("📊 TTL Data Products")

    if not DATA_LOADER_AVAILABLE:
        st.error("Data loader not available. Please check your installation.")
        return

    # Local mode loads TTL data products from the active workspace's storage
    # (private_data_products/); NextCloud is only needed for global products.
    username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
    password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
    ctx = st.session_state.get("workspace_context")
    has_storage = ctx is not None and getattr(ctx, "storage", None) is not None

    if not has_storage and not (username and password):
        st.info(
            "Open a workspace to load its `private_data_products/`, "
            "or configure NextCloud credentials for global data products."
        )
        return

    current_workspace = st.session_state.get('current_workspace')
    if not current_workspace:
        st.warning("No workspace selected. Please select a workspace first.")
        return

    workspace_name = current_workspace['name']
    workspace_id = current_workspace.get('id')

    st.info(f"📁 **Workspace:** {workspace_name}")
    st.write("Select TTL data products to enable for component loading.")

    # Initialize session state
    if 'enabled_ttl_data_products' not in st.session_state:
        st.session_state.enabled_ttl_data_products = []

    # Cache for metadata (fast) and full data (slow, on-demand)
    if 'cached_data_products' not in st.session_state:
        st.session_state.cached_data_products = {}

    # Show workspace knowledge graph status
    if TTL_LOADER_AVAILABLE:
        show_workspace_knowledge_graph_status()

    # Initialize processor
    processor = DataProductProcessor(workspace_id)

    # Load available data products - OPTIMIZED: Get metadata first
    with st.spinner("Loading available data products..."):
        try:
            # Get folder lists (fast)
            private_folders = processor.list_private_folders()
            open_folders = processor.list_open_folders()

            # Get metadata for each (fast - no TTL parsing!)
            private_products = []
            for folder_name in private_folders:
                cache_key = f"private:{folder_name}"

                # Check if we have full data cached
                if cache_key in st.session_state.cached_data_products:
                    # Already have full data
                    private_products.append(st.session_state.cached_data_products[cache_key])
                else:
                    # Get lightweight metadata only
                    metadata = processor.get_product_metadata(folder_name, is_private=True)
                    if metadata:
                        private_products.append(metadata)

            open_products = []
            for folder_name in open_folders:
                cache_key = f"global:{folder_name}"

                # Check if we have full data cached
                if cache_key in st.session_state.cached_data_products:
                    # Already have full data
                    open_products.append(st.session_state.cached_data_products[cache_key])
                else:
                    # Get lightweight metadata only
                    metadata = processor.get_product_metadata(folder_name, is_private=False)
                    if metadata:
                        open_products.append(metadata)

        except Exception as e:
            st.error(f"Error loading data products: {str(e)}")
            return

    # Display data products in two columns
    col1, col2 = st.columns(2)

    with col1:
        display_private_data_products(private_products, workspace_name, processor)

    with col2:
        display_open_data_products(open_products, processor)

    # Show summary of enabled data products
    display_enabled_products_summary()

    # Show preview of available components
    if st.session_state.enabled_ttl_data_products:
        display_data_products_component_preview()


def show_workspace_knowledge_graph_status():
    """
    Show status of workspace knowledge graph.

    NOTE: This function is deprecated and no longer displays status.
    Workspace knowledge graphs are now loaded via GraphDB export mode (not NextCloud TTL files).
    The status is shown in the Component Source Configuration section instead.
    This function is kept for backward compatibility but displays nothing.
    """
    # DISABLED: Workspace graph status is now shown in the Component Source Configuration
    # (see scenario_builder_components.py -> show_export_loader_controls)
    pass


def display_private_data_products(products_list: List[Dict], workspace_name: str, processor):
    """Display private data products"""
    st.write(f"### 🔒 Private Data Products ({workspace_name})")

    if not products_list:
        st.info("No private data products found for this workspace.")
        st.write("**Expected location:** `{workspace_id}/private_data_products/FOLDER_NAME/`")
        return

    st.write(f"Found {len(products_list)} private data product(s):")

    for product in products_list:
        product_id = f"private:{product['name']}"
        is_enabled = product_id in st.session_state.enabled_ttl_data_products
        has_full_data = 'components' in product  # Check if fully loaded

        col1, col2 = st.columns([0.1, 0.9])

        with col1:
            new_enabled = st.checkbox(
                "Enable",
                value=is_enabled,
                key=f"private_dp_{product['name']}",
                label_visibility="collapsed"
            )

            if new_enabled != is_enabled:
                if new_enabled:
                    if product_id not in st.session_state.enabled_ttl_data_products:
                        st.session_state.enabled_ttl_data_products.append(product_id)

                        # Load full details if not already loaded
                        if not has_full_data:
                            with st.spinner(f"Loading {product['name']}..."):
                                full_data = processor.process_data_product(product['name'], is_private=True)
                                if full_data:
                                    st.session_state.cached_data_products[product_id] = full_data
                                    st.rerun()
                else:
                    if product_id in st.session_state.enabled_ttl_data_products:
                        st.session_state.enabled_ttl_data_products.remove(product_id)

                # Clear component cache when data products change
                clear_component_cache()
                st.rerun()

        with col2:
            status_icon = "✅" if is_enabled else "⭕"
            st.write(f"{status_icon} **{product['name']}**")

            # Show component info
            component_info = []

            if has_full_data:
                # Show exact counts (fully loaded)
                component_info.append(f"{product.get('component_count', 0)} components")
                if product.get('resources'):
                    component_info.append(f"{len(product['resources'])} resources")
            else:
                # Show estimates (metadata only)
                if product.get('component_count', 0) > 0:
                    component_info.append(f"~{product['component_count']} components")
                if product.get('resource_count', 0) > 0:
                    component_info.append(f"{product['resource_count']} resources")

            if component_info:
                st.caption(" | ".join(component_info))

            # Show component types if fully loaded
            if has_full_data and product.get('component_types'):
                st.caption(f"Types: {', '.join(product['component_types'])}")
            elif not has_full_data:
                st.caption(f"TTL: {product.get('ttl_size', 0) // 1024}KB")


def display_open_data_products(products_list: List[Dict], processor):
    """Display open/global data products"""
    st.write("### 🌐 Open Data Products (Global)")

    if not products_list:
        st.info("No open data products found.")
        st.write("**Expected location:** `global/open_data_products/FOLDER_NAME/`")
        return

    st.write(f"Found {len(products_list)} open data product(s):")

    for product in products_list:
        product_id = f"global:{product['name']}"
        is_enabled = product_id in st.session_state.enabled_ttl_data_products
        has_full_data = 'components' in product  # Check if fully loaded

        col1, col2 = st.columns([0.1, 0.9])

        with col1:
            new_enabled = st.checkbox(
                "Enable",
                value=is_enabled,
                key=f"global_dp_{product['name']}",
                label_visibility="collapsed"
            )

            if new_enabled != is_enabled:
                if new_enabled:
                    if product_id not in st.session_state.enabled_ttl_data_products:
                        st.session_state.enabled_ttl_data_products.append(product_id)

                        # Load full details if not already loaded
                        if not has_full_data:
                            with st.spinner(f"Loading {product['name']}..."):
                                full_data = processor.process_data_product(product['name'], is_private=False)
                                if full_data:
                                    st.session_state.cached_data_products[product_id] = full_data
                                    st.rerun()
                else:
                    if product_id in st.session_state.enabled_ttl_data_products:
                        st.session_state.enabled_ttl_data_products.remove(product_id)

                # Clear component cache when data products change
                clear_component_cache()
                st.rerun()

        with col2:
            status_icon = "✅" if is_enabled else "⭕"
            st.write(f"{status_icon} **{product['name']}**")

            # Show component info
            component_info = []

            if has_full_data:
                # Show exact counts (fully loaded)
                component_info.append(f"{product.get('component_count', 0)} components")
                if product.get('resources'):
                    component_info.append(f"{len(product['resources'])} resources")
            else:
                # Show estimates (metadata only)
                if product.get('component_count', 0) > 0:
                    component_info.append(f"~{product['component_count']} components")
                if product.get('resource_count', 0) > 0:
                    component_info.append(f"{product['resource_count']} resources")

            if component_info:
                st.caption(" | ".join(component_info))

            # Show component types if fully loaded
            if has_full_data and product.get('component_types'):
                st.caption(f"Types: {', '.join(product['component_types'])}")
            elif not has_full_data:
                st.caption(f"TTL: {product.get('ttl_size', 0) // 1024}KB")


def display_enabled_products_summary():
    """Display summary of enabled data products"""
    enabled_products = st.session_state.enabled_ttl_data_products

    if not enabled_products:
        st.info("ℹ️ **No data products enabled.** Components will be loaded from workspace knowledge graph only.")
        return

    st.markdown("---")
    st.write("### ✅ Enabled Data Products Summary")

    private_count = sum(1 for p in enabled_products if p.startswith('private:'))
    global_count = sum(1 for p in enabled_products if p.startswith('global:'))

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Enabled", len(enabled_products))
    with col2:
        st.metric("🔒 Private", private_count)
    with col3:
        st.metric("🌐 Open", global_count)

    # Show list of enabled products
    if len(enabled_products) <= 5:
        enabled_names = []
        for product_id in enabled_products:
            if ':' in product_id:
                dp_type, dp_name = product_id.split(':', 1)
                type_icon = "🔒" if dp_type == "private" else "🌐"
                enabled_names.append(f"{type_icon} {dp_name}")

        st.write("**Enabled:** " + ", ".join(enabled_names))
    else:
        st.write(f"**{len(enabled_products)} data products enabled** (too many to list)")

    # Action buttons
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔄 Refresh Data Products", type="secondary"):
            clear_data_products_cache()
            st.rerun()

    with col2:
        if st.button("❌ Disable All", type="secondary"):
            st.session_state.enabled_ttl_data_products = []
            clear_component_cache()
            st.rerun()


def display_data_products_component_preview():
    """Display preview of components available from enabled data products"""
    st.markdown("---")
    st.write("### 🔍 Component Preview from Enabled Data Products")

    enabled_products = st.session_state.enabled_ttl_data_products
    cached_products = st.session_state.cached_data_products

    # Aggregate components from all enabled products
    all_components = {}
    total_resources = 0

    for product_id in enabled_products:
        if product_id in cached_products:
            product = cached_products[product_id]
            components = product.get('components', {})

            # Merge components by type
            for comp_type, comp_list in components.items():
                if comp_type not in all_components:
                    all_components[comp_type] = []
                all_components[comp_type].extend(comp_list)

            # Count resources
            if product.get('resources'):
                total_resources += len(product['resources'])

    if not all_components:
        st.warning("No components found in enabled data products.")
        return

    # Show summary
    total_components = sum(len(comps) for comps in all_components.values())
    st.write(f"**Total components:** {total_components} | **Component types:** {len(all_components)} | **Total resources:** {total_resources}")

    # Display component types in columns
    num_cols = min(3, len(all_components))
    if num_cols > 0:
        cols = st.columns(num_cols)

        for i, (comp_type, comp_list) in enumerate(sorted(all_components.items())):
            with cols[i % num_cols]:
                st.write(f"**{comp_type}** ({len(comp_list)})")

                # Show first few component names
                for j, comp in enumerate(comp_list[:3]):
                    comp_name = comp.get('name', comp.get('id', 'Unknown'))
                    st.caption(f"• {comp_name}")

                if len(comp_list) > 3:
                    st.caption(f"... and {len(comp_list) - 3} more")

    # Detailed breakdown in expander
    with st.expander("📋 Detailed Component Breakdown", expanded=False):
        for product_id in enabled_products:
            if product_id in cached_products:
                product = cached_products[product_id]
                dp_type, dp_name = product_id.split(':', 1)
                type_icon = "🔒" if dp_type == "private" else "🌐"

                st.write(f"**{type_icon} {dp_name}**")

                components = product.get('components', {})
                if components:
                    for comp_type, comp_list in sorted(components.items()):
                        st.write(f"  • {comp_type}: {len(comp_list)} components")

                        # Show resources linked to these components
                        resource_count = 0
                        for comp in comp_list:
                            if comp.get('resources'):
                                resource_count += len(comp['resources'])

                        if resource_count > 0:
                            st.caption(f"    └─ {resource_count} linked resources")
                else:
                    st.write("  No components")

                st.write("")


def clear_component_cache():
    """Clear component cache to force reload"""
    if TTL_LOADER_AVAILABLE:
        loader = get_workspace_ttl_loader()
        if loader:
            loader.clear_cache()


def clear_data_products_cache():
    """Clear data products cache to force reload"""
    st.session_state.cached_data_products = {}
    if TTL_LOADER_AVAILABLE:
        loader = get_workspace_ttl_loader()
        if loader:
            loader.clear_cache()


def get_enabled_data_products_info() -> Dict[str, Any]:
    """Get information about enabled data products for other components"""
    enabled_products = st.session_state.get('enabled_ttl_data_products', [])

    private_count = sum(1 for p in enabled_products if p.startswith('private:'))
    global_count = sum(1 for p in enabled_products if p.startswith('global:'))

    return {
        'total': len(enabled_products),
        'private': private_count,
        'global': global_count,
        'enabled_ids': enabled_products.copy()
    }


def get_enabled_data_products() -> Dict[str, Dict]:
    """Get the actual data product objects for enabled products"""
    enabled_ids = st.session_state.get('enabled_ttl_data_products', [])
    cached_products = st.session_state.get('cached_data_products', {})

    enabled_products = {}
    for product_id in enabled_ids:
        if product_id in cached_products:
            enabled_products[product_id] = cached_products[product_id]

    return enabled_products


def show_data_products_status_compact():
    """Show compact status of data products for other tabs"""
    info = get_enabled_data_products_info()

    if info['total'] == 0:
        return

    status_parts = []
    if info['private'] > 0:
        status_parts.append(f"🔒 {info['private']} private")
    if info['global'] > 0:
        status_parts.append(f"🌐 {info['global']} open")

    if status_parts:
        st.info(f"📊 **TTL Data Products:** {' | '.join(status_parts)} enabled")