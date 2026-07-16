# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Display Components
File: components/ontology_manager/displays.py

Handles rendering of tables, lists, and data displays.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict


def extract_local_name(uri: str) -> str:
    """Extract the local name from a URI"""
    if '#' in uri:
        return uri.split('#')[1]
    elif '/' in uri:
        return uri.split('/')[-1]
    return uri


def sort_by_label(items: List[Dict]) -> List[Dict]:
    """Sort items by label or class name"""
    return sorted(items, key=lambda x: (x.get('label') or extract_local_name(x.get('class', ''))).lower())


def render_main_display(api_client, view_mode: str):
    """Render the main display area based on view mode"""

    if view_mode == "components":
        render_components_view(api_client)
    elif view_mode == "attributes":
        render_attributes_view()
    elif view_mode == "properties":
        render_properties_view()


def render_components_view(api_client):
    """Render the components view"""
    st.subheader("📦 Components")

    if not st.session_state.ontology_components:
        st.info("No components available")
        return

    # Create DataFrame
    components_data = []
    for comp in st.session_state.ontology_components:
        components_data.append({
            "Class URI": comp.get('class', ''),
            "Local Name": extract_local_name(comp.get('class', '')),
            "Label": comp.get('label', '-')
        })

    df = pd.DataFrame(components_data)

    # Display with formatting
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Class URI": st.column_config.TextColumn("Class URI", width="medium"),
            "Local Name": st.column_config.TextColumn("Local Name", width="small"),
            "Label": st.column_config.TextColumn("Label", width="medium")
        }
    )

    st.markdown("---")

    # Component range explorer
    st.subheader("🔍 Component Range Explorer")

    # Sort components for dropdown
    sorted_components = sort_by_label(st.session_state.ontology_components)

    component_options = [comp['class'] for comp in sorted_components]
    component_labels = [comp.get('label') or extract_local_name(comp['class'])
                        for comp in sorted_components]

    # Create a mapping for display
    component_map = dict(zip(component_labels, component_options))

    selected_label = st.selectbox(
        "Select a component to explore",
        options=component_labels,
        key="component_range_selector"
    )

    selected_component = component_map[selected_label]

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔍 Get Range", key="get_range_btn"):
            with st.spinner("Fetching component range..."):
                range_data = api_client.fetch_component_range(
                    st.session_state.ontology_selected_extension,
                    selected_component
                )
                st.session_state.ontology_component_range = range_data
                st.rerun()

    # Display range if available
    if st.session_state.ontology_component_range:
        st.markdown("**Component Range:**")
        range_items = []
        for item in st.session_state.ontology_component_range:
            label = item.get('label') or extract_local_name(item.get('range', ''))
            range_items.append(f"- {label}")

        st.markdown("\n".join(range_items))


def render_attributes_view():
    """Render the attributes view"""
    st.subheader("🏷️ Attributes")

    if not st.session_state.ontology_attributes:
        st.info("No attributes available")
        return

    # Create DataFrame
    attributes_data = []
    for attr in st.session_state.ontology_attributes:
        attributes_data.append({
            "Class URI": attr.get('class', ''),
            "Local Name": extract_local_name(attr.get('class', '')),
            "Label": attr.get('label', '-')
        })

    df = pd.DataFrame(attributes_data)

    # Display with formatting
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Class URI": st.column_config.TextColumn("Class URI", width="medium"),
            "Local Name": st.column_config.TextColumn("Local Name", width="small"),
            "Label": st.column_config.TextColumn("Label", width="medium")
        }
    )

    # Add statistics
    st.metric("Total Attributes", len(st.session_state.ontology_attributes))


def render_properties_view():
    """Render the object properties view"""
    st.subheader("🔗 Object Properties")

    if not st.session_state.ontology_properties:
        st.info("No object properties available")
        return

    # Create DataFrame
    properties_data = []
    for prop in st.session_state.ontology_properties:
        properties_data.append({
            "Property URI": prop.get('class', ''),
            "Local Name": extract_local_name(prop.get('class', '')),
            "Label": prop.get('label', '-')
        })

    df = pd.DataFrame(properties_data)

    # Display with formatting
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Property URI": st.column_config.TextColumn("Property URI", width="medium"),
            "Local Name": st.column_config.TextColumn("Local Name", width="small"),
            "Label": st.column_config.TextColumn("Label", width="medium")
        }
    )

    # Add statistics
    st.metric("Total Properties", len(st.session_state.ontology_properties))


def render_component_selector(label: str = "Select Component", key: str = "component_select") -> str:
    """Render a component selector dropdown

    Returns:
        Selected component URI
    """
    sorted_components = sort_by_label(st.session_state.ontology_components)

    component_labels = [comp.get('label') or extract_local_name(comp['class'])
                        for comp in sorted_components]
    component_uris = [comp['class'] for comp in sorted_components]

    component_map = dict(zip(component_labels, component_uris))

    selected_label = st.selectbox(
        label,
        options=component_labels,
        key=key
    )

    return component_map[selected_label]


def render_attribute_selector(label: str = "Select Attribute", key: str = "attribute_select") -> str:
    """Render an attribute selector dropdown

    Returns:
        Selected attribute URI
    """
    sorted_attributes = sort_by_label(st.session_state.ontology_attributes)

    attribute_labels = [attr.get('label') or extract_local_name(attr['class'])
                        for attr in sorted_attributes]
    attribute_uris = [attr['class'] for attr in sorted_attributes]

    attribute_map = dict(zip(attribute_labels, attribute_uris))

    selected_label = st.selectbox(
        label,
        options=attribute_labels,
        key=key
    )

    return attribute_map[selected_label]


def render_property_selector(label: str = "Select Property", key: str = "property_select") -> str:
    """Render a property selector dropdown

    Returns:
        Selected property URI
    """
    sorted_properties = sort_by_label(st.session_state.ontology_properties)

    property_labels = [prop.get('label') or extract_local_name(prop['class'])
                       for prop in sorted_properties]
    property_uris = [prop['class'] for prop in sorted_properties]

    property_map = dict(zip(property_labels, property_uris))

    selected_label = st.selectbox(
        label,
        options=property_labels,
        key=key
    )

    return property_map[selected_label]