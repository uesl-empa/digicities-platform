# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_instance_manager.py
"""
Instance Manager for Replica Builder
Creates and manages component instances
"""
import streamlit as st
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import uuid


@dataclass
class ComponentInstance:
    """Represents a component instance"""
    id: str
    component_type: str
    uri: str
    label: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    class_objects: Dict[str, str] = field(default_factory=dict)  # predicate: target_uri

    def to_dict(self):
        return {
            'id': self.id,
            'component_type': self.component_type,
            'uri': self.uri,
            'label': self.label,
            'attributes': self.attributes,
            'annotations': self.annotations,
            'class_objects': self.class_objects
        }


def initialize_instance_state():
    """Initialize instance-specific state"""
    if 'replica_selected_instance' not in st.session_state:
        st.session_state.replica_selected_instance = None

    if 'replica_instance_filter' not in st.session_state:
        st.session_state.replica_instance_filter = ""


def generate_instance_uri(project_uri: str, component_type: str, instance_id: str, uri_mode: str) -> str:
    """Generate instance URI based on mode"""
    if uri_mode == "default":
        return f"{project_uri}/{component_type}/{instance_id}"
    elif uri_mode == "complete-project-uri":
        return f"{project_uri}#{instance_id}"
    elif uri_mode == "full-uri-in-cell":
        return f"{project_uri}/{instance_id}"
    else:
        return f"{project_uri}/{component_type}/{instance_id}"


def create_instance(component_type: str, instance_id: str, label: str = None) -> Optional[ComponentInstance]:
    """Create a new component instance"""

    # Check if ID already exists
    if any(inst.id == instance_id for inst in st.session_state.replica_instances):
        st.error(f"Instance with ID '{instance_id}' already exists")
        return None

    # Generate URI
    uri = generate_instance_uri(
        st.session_state.replica_project_uri,
        component_type,
        instance_id,
        st.session_state.replica_uri_mode
    )

    # Create instance
    instance = ComponentInstance(
        id=instance_id,
        component_type=component_type,
        uri=uri,
        label=label or instance_id,
        attributes={},
        annotations={}
    )

    st.session_state.replica_instances.append(instance)
    return instance


def delete_instance(instance_id: str) -> bool:
    """Delete an instance"""
    original_count = len(st.session_state.replica_instances)
    st.session_state.replica_instances = [
        inst for inst in st.session_state.replica_instances
        if inst.id != instance_id
    ]

    # Also remove any links involving this instance
    if len(st.session_state.replica_instances) < original_count:
        st.session_state.replica_links = [
            link for link in st.session_state.replica_links
            if link['source_id'] != instance_id and link['target_id'] != instance_id
        ]
        return True

    return False


def get_instance_by_id(instance_id: str) -> Optional[ComponentInstance]:
    """Get instance by ID"""
    for inst in st.session_state.replica_instances:
        if inst.id == instance_id:
            return inst
    return None


def get_instances_by_type(component_type: str) -> List[ComponentInstance]:
    """Get all instances of a specific type"""
    return [inst for inst in st.session_state.replica_instances if inst.component_type == component_type]


def tab_manage_instances():
    """Tab for managing component instances"""
    st.subheader("Component Instances")

    if not st.session_state.replica_ontology_components:
        st.warning("Please load the ontology first")
        return

    # Get available component types
    component_types = [
        name for name, comp in st.session_state.replica_ontology_components.items()
        if not name.endswith('Attribute') and name not in ['Attribute', 'Component']
    ]

    if not component_types:
        st.error("No component types available in ontology")
        return

    # Create new instance section
    with st.expander("Add New Instance", expanded=len(st.session_state.replica_instances) < 5):
        render_create_instance_form(component_types)

    # Display existing instances
    st.write("### Existing Instances")

    if not st.session_state.replica_instances:
        st.info("No instances created yet. Add your first instance above!")
        return

    # Filter and search
    col1, col2 = st.columns([3, 1])

    with col1:
        filter_text = st.text_input(
            "Filter instances",
            value=st.session_state.replica_instance_filter,
            placeholder="Search by ID, type, or label...",
            key="instance_filter_input"
        )
        st.session_state.replica_instance_filter = filter_text

    with col2:
        st.metric("Total Instances", len(st.session_state.replica_instances))

    # Group by component type
    instances_by_type = {}
    for inst in st.session_state.replica_instances:
        if inst.component_type not in instances_by_type:
            instances_by_type[inst.component_type] = []
        instances_by_type[inst.component_type].append(inst)

    # Export the whole replica's TTL straight from the viewer.
    _render_replica_ttl_download(
        st.session_state.replica_instances,
        label="⬇️ Download full replica TTL",
        file_stem="replica",
        key="download_full_replica_ttl",
    )

    # Display by type
    for comp_type in sorted(instances_by_type.keys()):
        instances = instances_by_type[comp_type]

        # Apply filter
        if filter_text:
            instances = [
                inst for inst in instances
                if filter_text.lower() in inst.id.lower() or
                   filter_text.lower() in inst.label.lower() or
                   filter_text.lower() in inst.component_type.lower()
            ]

        if not instances:
            continue

        with st.expander(f"{comp_type} ({len(instances)})", expanded=True):
            # Per-component export: all instances of this type (ignores the text
            # filter above, so the file always holds the complete component).
            _render_replica_ttl_download(
                instances_by_type[comp_type],
                label=f"⬇️ Download {comp_type} TTL",
                file_stem=comp_type,
                key=f"download_ttl_{comp_type}",
            )
            render_instances_table(instances, comp_type)


def _safe_filename_stem(name: str) -> str:
    """Filesystem-safe stem for a downloaded .ttl file."""
    import re
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_")
    return stem or "replica"


def _render_replica_ttl_download(instances, label: str, file_stem: str, key: str) -> None:
    """Render a download button that exports ``instances`` as classes_and_attributes
    TTL. Shared by the full-replica and per-component export buttons in the viewer."""
    if not instances:
        return
    from components.replica_builder.replica_ttl_generator import (
        generate_classes_and_attributes_ttl,
    )
    ttl_content = generate_classes_and_attributes_ttl(instances)
    st.download_button(
        label,
        data=ttl_content,
        file_name=f"{_safe_filename_stem(file_stem)}.ttl",
        mime="text/turtle",
        key=key,
        use_container_width=True,
    )


def render_create_instance_form(component_types: List[str]):
    """Render form to create new instance"""

    with st.form("create_instance_form"):
        col1, col2 = st.columns(2)

        with col1:
            selected_type = st.selectbox(
                "Component Type",
                options=component_types,
                help="Select the type of component to create"
            )

        with col2:
            instance_id = st.text_input(
                "Instance ID",
                placeholder="e.g., Building123, Turbine_A1",
                help="Unique identifier for this instance"
            )

        label = st.text_input(
            "Label (optional)",
            placeholder="Human-readable label",
            help="Optional: defaults to Instance ID"
        )

        # Show URI preview
        if instance_id:
            preview_uri = generate_instance_uri(
                st.session_state.replica_project_uri,
                selected_type,
                instance_id,
                st.session_state.replica_uri_mode
            )
            st.caption(f"URI Preview: `{preview_uri}`")

        col1, col2 = st.columns(2)

        with col1:
            submit = st.form_submit_button("Create Instance", type="primary", use_container_width=True)

        with col2:
            cancel = st.form_submit_button("Cancel", type="secondary", use_container_width=True)

        if submit:
            if not instance_id:
                st.error("Please provide an Instance ID")
            else:
                instance = create_instance(selected_type, instance_id, label or instance_id)
                if instance:
                    st.success(f"Created instance: {instance_id}")
                    st.rerun()


def render_instances_table(instances: List[ComponentInstance], comp_type: str):
    """Render table of instances for a component type"""

    for idx, inst in enumerate(instances):
        col1, col2, col3, col4, col5 = st.columns([2, 2, 3, 1, 1])

        with col1:
            st.write(f"**{inst.id}**")

        with col2:
            st.write(inst.label)

        with col3:
            st.caption(f"`{inst.uri}`")

        with col4:
            attr_count = len(inst.attributes)
            if attr_count > 0:
                st.caption(f"{attr_count} attrs")

        with col5:
            if st.button("🗑️ Delete", key=f"delete_{inst.id}", help="Delete instance", use_container_width=True):
                if delete_instance(inst.id):
                    st.success(f"Deleted {inst.id}")
                    st.rerun()


def get_available_component_types() -> List[str]:
    """Get list of available component types"""
    return [
        name for name, comp in st.session_state.replica_ontology_components.items()
        if not name.endswith('Attribute') and name not in ['Attribute', 'Component']
    ]