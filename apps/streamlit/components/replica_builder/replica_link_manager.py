# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_link_manager.py
"""
Link Manager for Replica Builder — UI shell over the backend model.

Link CRUD and the ontology link-property loading moved to
``backend/replica_builder/model.py`` (Phase 5 of the backend/UI split). What
stays here is the Streamlit wiring: tab rendering plus session-state adapters
with the old signatures (``create_link`` / ``delete_link`` /
``load_link_properties_from_ontology`` read and write ``st.session_state``
and surface st.error/st.warning exactly as before).
"""
import streamlit as st
from typing import Dict, List, Any, Optional

from backend.replica_builder import model as _model
from backend.replica_builder.model import DEFAULT_LINK_PROPERTIES  # noqa: F401


def initialize_link_state():
    """Initialize link-specific state"""
    if 'replica_available_link_properties' not in st.session_state:
        st.session_state.replica_available_link_properties = []

    # Load from ontology if not already loaded
    if not st.session_state.replica_available_link_properties:
        load_link_properties_from_ontology()


def load_link_properties_from_ontology():
    """Load linksComponent subproperties from ontology"""
    client = st.session_state.get('workspace_client')
    try:
        st.session_state.replica_available_link_properties = \
            _model.load_link_properties(client)
    except Exception as e:
        st.warning(f"Could not load link properties from ontology: {e}")
        st.session_state.replica_available_link_properties = list(DEFAULT_LINK_PROPERTIES)


def create_link(source_id: str, target_id: str, link_property: str, custom_property: str = None) -> bool:
    """Create a link between instances"""
    link, problem = _model.create_link(
        st.session_state.replica_instances,
        st.session_state.replica_links,
        source_id, target_id, link_property, custom_property,
    )
    if problem == "not_found":
        st.error("Source or target instance not found")
        return False
    if problem == "duplicate":
        st.warning("Link already exists")
        return False
    return True


def delete_link(source_id: str, target_id: str, property_name: str) -> bool:
    """Delete a link"""
    links, deleted = _model.delete_link(
        st.session_state.replica_links, source_id, target_id, property_name)
    st.session_state.replica_links = links
    return deleted


def get_links_for_instance(instance_id: str) -> List[Dict[str, Any]]:
    """Get all links involving an instance"""
    return _model.get_links_for_instance(st.session_state.replica_links, instance_id)


def tab_manage_links():
    """Tab for managing component links"""
    st.subheader("Component Links")

    initialize_link_state()

    # Show loaded link properties and refresh option
    if st.session_state.replica_available_link_properties:
        with st.expander("Available Link Properties from Ontology", expanded=False):
            st.write(f"Loaded {len(st.session_state.replica_available_link_properties)} link properties:")

            # Display in columns
            cols = st.columns(3)
            for idx, prop in enumerate(st.session_state.replica_available_link_properties):
                with cols[idx % 3]:
                    st.write(f"• {prop}")

            if st.button("Reload from Ontology"):
                load_link_properties_from_ontology()
                st.success("Link properties reloaded")
                st.rerun()

    if not st.session_state.replica_instances:
        st.info("Create instances first in the Instances tab")
        return

    if len(st.session_state.replica_instances) < 2:
        st.info("Add at least 2 instances to create links between them")
        return

    # Create new link section
    with st.expander("Create New Link", expanded=True):
        render_create_link_form()

    # Display existing links
    st.write("### Existing Links")

    if not st.session_state.replica_links:
        st.info("No links created yet")
    else:
        render_links_display()

    # Statistics
    render_link_statistics()


def render_create_link_form():
    """Render form to create new link"""

    instance_options = {
        inst.id: f"{inst.label} ({inst.component_type})"
        for inst in st.session_state.replica_instances
    }

    with st.form("create_link_form"):
        col1, col2 = st.columns(2)

        with col1:
            source_id = st.selectbox(
                "Source Instance",
                options=list(instance_options.keys()),
                format_func=lambda x: instance_options[x],
                key="link_source"
            )

        with col2:
            # Filter out source from target options
            target_options = {k: v for k, v in instance_options.items() if k != source_id}

            target_id = st.selectbox(
                "Target Instance",
                options=list(target_options.keys()),
                format_func=lambda x: target_options[x],
                key="link_target"
            )

        # Link property selection
        col1, col2 = st.columns([2, 2])

        with col1:
            property_mode = st.radio(
                "Property Type",
                ["From Ontology", "Custom"],
                horizontal=True
            )

        with col2:
            if property_mode == "From Ontology":
                if not st.session_state.replica_available_link_properties:
                    st.warning("No link properties loaded from ontology")
                    link_property = "locatedIn"
                else:
                    link_property = st.selectbox(
                        "Link Property",
                        options=st.session_state.replica_available_link_properties,
                        help="linksComponent subproperties from ontology"
                    )
                custom_property = None
            else:
                link_property = None
                custom_property = st.text_input(
                    "Custom Property",
                    placeholder="e.g., myCustomLink",
                    help="Define a custom link property"
                )

        # Show link preview
        if source_id and target_id:
            source_inst = next(inst for inst in st.session_state.replica_instances if inst.id == source_id)
            target_inst = next(inst for inst in st.session_state.replica_instances if inst.id == target_id)

            prop_display = custom_property if custom_property else link_property

            st.caption(f"Link: `{source_inst.uri}` --[{prop_display}]--> `{target_inst.uri}`")

        submit = st.form_submit_button("Create Link", type="primary", use_container_width=True)

        if submit:
            if property_mode == "Custom" and not custom_property:
                st.error("Please provide a custom property name")
            else:
                if create_link(source_id, target_id, link_property, custom_property):
                    st.success("Link created successfully")
                    st.rerun()


def render_links_display():
    """Display existing links"""

    # Group links by property
    links_by_property = {}
    for link in st.session_state.replica_links:
        prop = link['property']
        if prop not in links_by_property:
            links_by_property[prop] = []
        links_by_property[prop].append(link)

    for property_name in sorted(links_by_property.keys()):
        links = links_by_property[property_name]

        with st.expander(f"{property_name} ({len(links)})", expanded=True):
            for link in links:
                col1, col2, col3, col4 = st.columns([3, 1, 3, 1])

                with col1:
                    st.write(f"**{link['source_label']}**")
                    st.caption(link['source_type'])

                with col2:
                    st.write("→")

                with col3:
                    st.write(f"**{link['target_label']}**")
                    st.caption(link['target_type'])

                with col4:
                    if st.button("Delete", key=f"del_link_{link['source_id']}_{link['target_id']}_{property_name}"):
                        if delete_link(link['source_id'], link['target_id'], property_name):
                            st.success("Link deleted")
                            st.rerun()


def render_link_statistics():
    """Display link statistics"""
    if not st.session_state.replica_links:
        return

    st.write("---")
    st.write("### Link Statistics")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Links", len(st.session_state.replica_links))

    with col2:
        unique_properties = len(set(link['property'] for link in st.session_state.replica_links))
        st.metric("Unique Properties", unique_properties)

    with col3:
        linked_instances = set()
        for link in st.session_state.replica_links:
            linked_instances.add(link['source_id'])
            linked_instances.add(link['target_id'])
        st.metric("Linked Instances", len(linked_instances))