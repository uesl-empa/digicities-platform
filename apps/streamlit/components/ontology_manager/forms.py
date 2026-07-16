# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Forms - Fixed Version with Dynamic Updates
File: components/ontology_manager/forms.py

Handles all form rendering and submission logic for the Ontology Manager.
Contains all 14 forms for managing components, attributes, properties, and mappings.

FIXES:
1. Add Attribute form now dynamically updates based on attribute type (matching Next.js)
2. Removed dynamic_or_static field completely
3. Bulk Link form now stays open after linking/unlinking
"""

import streamlit as st
from typing import Optional
from datetime import datetime
from .displays import (
    render_component_selector,
    render_attribute_selector,
    render_property_selector,
    extract_local_name,
    sort_by_label
)

import streamlit as st
from typing import Optional
from datetime import datetime
from .displays import (
    render_component_selector,
    render_attribute_selector,
    render_property_selector,
    extract_local_name,
    sort_by_label
)


def refresh_cached_data(api_client, extension_filename):
    """
    Refresh all cached data in session state after modifications

    Call this after any operation that changes the ontology structure:
    - Adding/removing components
    - Adding/removing attributes
    - Linking/unlinking attributes
    - Adding named individuals
    - Adding to categories

    Args:
        api_client: The OntologyAPIClient instance
        extension_filename: The current extension filename
    """
    # Always refresh these core lists
    st.session_state.ontology_attributes = api_client.fetch_attributes(extension_filename)
    st.session_state.ontology_components = api_client.fetch_components(extension_filename)
    st.session_state.ontology_properties = api_client.fetch_properties(extension_filename)

    # Clear cached categorical data so it reloads
    if 'categorical_attributes' in st.session_state:
        del st.session_state.categorical_attributes

    if 'attribute_categories' in st.session_state:
        del st.session_state.attribute_categories


def render_forms_content(api_client, form_type: str):
    """Main form content renderer - called from dialog"""

    form_handlers = {
        "addComponent": render_add_component_form,
        "removeComponent": render_remove_component_form,
        "changeParent": render_change_parent_form,
        "addAttribute": render_add_attribute_form,
        "removeAttribute": render_remove_attribute_form,
        "linkAttribute": render_link_attribute_form,
        "removeAttributeLink": render_remove_attribute_link_form,
        "bulkLinkAttributes": render_bulk_link_attributes_form,
        "manageAttributeCategories": render_manage_categories_form,
        "manageNamedIndividuals": render_manage_individuals_form,
        "mapComponent": render_map_component_form,
        "mapAttribute": render_map_attribute_form,
        "mapProperty": render_map_property_form,
        "managePropertyMappings": render_manage_property_mappings_form,
        "uploadToGraphDB": render_upload_graphdb_form,
        "proposeUpstream": render_propose_upstream_form,
    }

    handler = form_handlers.get(form_type)
    if handler:
        handler(api_client)
    else:
        st.error(f"Unknown form type: {form_type}")


# =================== Component Forms ===================

def render_add_component_form(api_client):
    """Render the add component form"""
    st.markdown("#### ➕ Add New Component")

    with st.form("add_component_form"):
        component_label = st.text_input(
            "Component Label",
            placeholder="e.g., Holistic Energy Model",
            help="Human-readable label for the component"
        )

        parent_component = render_component_selector("Parent Component", "add_comp_parent")

        submitted = st.form_submit_button("✅ Add Component", type="primary")

        if submitted:
            if not component_label:
                st.error("Please enter a component label")
                return

            # Compute ID from label (remove spaces)
            component_id = component_label.replace(" ", "")

            with st.spinner("Adding component..."):
                success = api_client.add_component(
                    st.session_state.ontology_selected_extension,
                    component_id,
                    component_label,
                    parent_component
                )

                if success:
                    st.success("✅ Component added successfully!")

                    # ADD: Refresh cached data
                    refresh_cached_data(
                        api_client,
                        st.session_state.ontology_selected_extension
                    )

                    st.session_state.ontology_active_form = None
                    st.rerun()


def render_remove_component_form(api_client):
    """Render the remove component form"""
    st.markdown("#### 🗑️ Remove Component")
    st.warning("⚠️ This action cannot be undone!")

    with st.form("remove_component_form"):
        component_to_remove = render_component_selector("Select Component to Remove", "remove_comp")

        submitted = st.form_submit_button("🗑️ Remove Component", type="primary")

        if submitted:
            if st.session_state.get('confirm_remove_component'):
                with st.spinner("Removing component..."):
                    success = api_client.remove_component(
                        st.session_state.ontology_selected_extension,
                        component_to_remove
                    )

                    if success:
                        st.success("✅ Component removed successfully!")
                        st.session_state.ontology_components = api_client.fetch_components(
                            st.session_state.ontology_selected_extension
                        )
                        st.session_state.confirm_remove_component = False
                        st.session_state.ontology_active_form = None
                        st.rerun()
            else:
                st.session_state.confirm_remove_component = True
                st.warning("Click 'Remove Component' again to confirm deletion")
                st.rerun()


def render_change_parent_form(api_client):
    """Render the change parent form"""
    st.markdown("#### ↕️ Change Component Parent")

    with st.form("change_parent_form"):
        component = render_component_selector("Select Component", "change_parent_comp")
        new_parent = render_component_selector("Select New Parent", "change_parent_new")

        submitted = st.form_submit_button("✅ Update Parent", type="primary")

        if submitted:
            if component == new_parent:
                st.error("Component cannot be its own parent!")
                return

            with st.spinner("Changing parent..."):
                success = api_client.change_component_parent(
                    st.session_state.ontology_selected_extension,
                    component,
                    new_parent
                )

                if success:
                    st.success("✅ Parent changed successfully!")
                    st.session_state.ontology_components = api_client.fetch_components(
                        st.session_state.ontology_selected_extension
                    )
                    st.session_state.ontology_active_form = None
                    st.rerun()


# =================== Attribute Forms ===================

def render_add_attribute_form(api_client):
    """Render the add attribute form - FIXED with dynamic updates"""
    st.markdown("#### ➕ Add New Attribute")

    # Load QUDT units and temporal precisions if not already loaded
    if 'qudt_units' not in st.session_state:
        with st.spinner("Loading QUDT units..."):
            st.session_state.qudt_units = api_client.fetch_qudt_units()

    if 'temporal_precisions' not in st.session_state:
        with st.spinner("Loading temporal precisions..."):
            st.session_state.temporal_precisions = api_client.fetch_temporal_precisions()

    # Initialize attribute type in session state if not present
    if 'add_attr_type' not in st.session_state:
        st.session_state.add_attr_type = "Physical"

    # Attribute Type Selection - OUTSIDE FORM so it can trigger updates
    attribute_type = st.selectbox(
        "Attribute Type",
        options=[
            "Physical",
            "Simple Cost",
            "Unit-Based Cost",
            "Curve",
            "Categorical",
            "Geospatial",
            "CustomPhysicalRatio",
            "Event",
            "SimpleValue"
        ],
        index=["Physical", "Simple Cost", "Unit-Based Cost", "Curve", "Categorical",
               "Geospatial", "CustomPhysicalRatio", "Event", "SimpleValue"].index(st.session_state.add_attr_type),
        key="attr_type_selector"
    )

    # Update session state when selection changes
    if attribute_type != st.session_state.add_attr_type:
        st.session_state.add_attr_type = attribute_type
        st.rerun()

    # Now render the form with conditional fields based on the selected type
    with st.form("add_attribute_form"):
        # Attribute Label
        attribute_label = st.text_input(
            "Attribute Label",
            placeholder="e.g., Power generated per hour",
            help="Human-readable label for the attribute"
        )

        # Initialize all optional fields
        qudt_unit = ""
        y_qudt_unit = ""
        x_unit = ""
        temporal_precision = ""

        # Conditional fields based on attribute type
        # Physical, Geospatial, Unit-Based Cost: need qudtUnit
        if attribute_type in ["Physical", "Geospatial", "Unit-Based Cost"]:
            qudt_unit = st.selectbox(
                "QUDT Unit",
                options=[""] + st.session_state.qudt_units,
                help="Select the unit for this attribute"
            )

        # Curve: needs X-axis and Y-axis units
        elif attribute_type == "Curve":
            qudt_unit = st.selectbox(
                "X-axis QUDT Unit",
                options=[""] + st.session_state.qudt_units,
                help="Select the unit for the X-axis"
            )
            y_qudt_unit = st.selectbox(
                "Y-axis QUDT Unit",
                options=[""] + st.session_state.qudt_units,
                help="Select the unit for the Y-axis"
            )

        # CustomPhysicalRatio: needs numerator and denominator units
        elif attribute_type == "CustomPhysicalRatio":
            x_unit = st.selectbox(
                "QUDT X Unit (Numerator)",
                options=[""] + st.session_state.qudt_units,
                help="Select the numerator unit"
            )
            y_qudt_unit = st.selectbox(
                "QUDT Y Unit (Denominator)",
                options=[""] + st.session_state.qudt_units,
                help="Select the denominator unit"
            )

        # Event: needs temporal precision
        elif attribute_type == "Event":
            if st.session_state.temporal_precisions:
                precision_labels = [p['label'] for p in st.session_state.temporal_precisions]
                precision_values = [p['value'] for p in st.session_state.temporal_precisions]

                selected_precision_label = st.selectbox(
                    "Temporal Precision",
                    options=[""] + precision_labels,
                    help="Select the temporal precision level"
                )

                if selected_precision_label:
                    precision_idx = precision_labels.index(selected_precision_label)
                    temporal_precision = precision_values[precision_idx]

        # Info boxes for different attribute types
        st.markdown("---")
        if attribute_type == "CustomPhysicalRatio":
            st.info("💡 Creates ratio attributes like kg/m² or EUR/kWh. Specify numerator and denominator units.")
        elif attribute_type == "Event":
            st.info("💡 Creates temporal/date-based attributes with configurable precision levels.")
        elif attribute_type == "SimpleValue":
            st.info("💡 Creates basic attributes with just a value, no units required.")
        elif attribute_type == "Physical":
            st.info("💡 Creates physical attributes with QUDT units.")
        elif attribute_type == "Curve":
            st.info("💡 Creates curve attributes with X and Y axis units.")
        elif attribute_type == "Simple Cost":
            st.info("💡 Creates simple cost attributes without units.")
        elif attribute_type == "Unit-Based Cost":
            st.info("💡 Creates cost attributes with QUDT units.")
        elif attribute_type == "Categorical":
            st.info("💡 Creates categorical attributes with named individuals.")
        elif attribute_type == "Geospatial":
            st.info("💡 Creates geospatial attributes with QUDT units.")

        submitted = st.form_submit_button("✅ Add Attribute", type="primary", use_container_width=True)

        if submitted:
            if not attribute_label:
                st.error("Please enter an attribute label")
                return

            # Validate type-specific requirements
            if attribute_type in ["Physical", "Geospatial", "Unit-Based Cost"] and not qudt_unit:
                st.error(f"Please select a QUDT unit for {attribute_type} attributes")
                return

            if attribute_type == "Curve" and (not qudt_unit or not y_qudt_unit):
                st.error("Please select both X-axis and Y-axis QUDT units for Curve attributes")
                return

            if attribute_type == "CustomPhysicalRatio" and (not x_unit or not y_qudt_unit):
                st.error("Please select both QUDT X (numerator) and QUDT Y (denominator) units")
                return

            if attribute_type == "Event" and not temporal_precision:
                st.error("Please select temporal precision for Event attributes")
                return

            # Compute ID from label (remove spaces)
            attribute_id = attribute_label.replace(" ", "")

            with st.spinner("Adding attribute..."):
                success = api_client.add_attribute(
                    st.session_state.ontology_selected_extension,
                    attribute_type,
                    attribute_id,
                    attribute_label,
                    qudt_unit=qudt_unit,
                    y_qudt_unit=y_qudt_unit,
                    x_unit=x_unit,
                    temporal_precision=temporal_precision,
                    dynamic_or_static="Static",
                    parent_property=""
                )

                if success:
                    st.success("✅ Attribute added successfully!")

                    # FIX: Use the refresh helper to clear all caches
                    refresh_cached_data(
                        api_client,
                        st.session_state.ontology_selected_extension
                    )

                    # Reset the attribute type for next use
                    st.session_state.add_attr_type = "Physical"
                    st.session_state.ontology_active_form = None
                    st.rerun()


def render_remove_attribute_form(api_client):
    """Render the remove attribute form"""
    st.markdown("#### 🗑️ Remove Attribute")
    st.warning("⚠️ This action cannot be undone!")

    with st.form("remove_attribute_form"):
        attribute_to_remove = render_attribute_selector("Select Attribute to Remove", "remove_attr")

        submitted = st.form_submit_button("🗑️ Remove Attribute", type="primary")

        if submitted:
            if st.session_state.get('confirm_remove_attribute'):
                with st.spinner("Removing attribute..."):
                    success = api_client.remove_attribute(
                        st.session_state.ontology_selected_extension,
                        attribute_to_remove
                    )

                    if success:
                        st.success("✅ Attribute removed successfully!")
                        st.session_state.ontology_attributes = api_client.fetch_attributes(
                            st.session_state.ontology_selected_extension
                        )
                        st.session_state.confirm_remove_attribute = False
                        st.session_state.ontology_active_form = None
                        st.rerun()
            else:
                st.session_state.confirm_remove_attribute = True
                st.warning("Click 'Remove Attribute' again to confirm deletion")
                st.rerun()

def render_link_attribute_form(api_client):
    """Render the link attribute form"""
    st.markdown("#### 🔗 Link Attribute to Component")

    with st.form("link_attribute_form"):
        component = render_component_selector("Select Component", "link_attr_comp")
        attribute = render_attribute_selector("Select Attribute", "link_attr_attr")

        submitted = st.form_submit_button("✅ Link Attribute", type="primary")

        if submitted:
            with st.spinner("Linking attribute..."):
                success = api_client.link_attribute(
                    st.session_state.ontology_selected_extension,
                    component,
                    attribute
                )

                if success:
                    st.success("✅ Attribute linked successfully!")

                    # ADD: Refresh cached data
                    refresh_cached_data(
                        api_client,
                        st.session_state.ontology_selected_extension
                    )

                    st.session_state.ontology_active_form = None
                    st.rerun()

def render_remove_attribute_link_form(api_client):
    """Render the remove attribute link form"""
    st.markdown("#### ❌ Remove Attribute Link")

    # Component selector
    component = render_component_selector("Select Component", "unlink_comp")

    # Fetch component attributes
    component_attrs = api_client.get_component_attributes(
        st.session_state.ontology_selected_extension,
        component
    )

    if not component_attrs:
        st.info("No attributes linked to this component")
        return

    with st.form("remove_link_form"):
        # Attribute selector from component's attributes
        sorted_attrs = sort_by_label(component_attrs)
        attr_labels = [attr.get('label') or extract_local_name(attr['class']) for attr in sorted_attrs]
        attr_uris = [attr['class'] for attr in sorted_attrs]
        attr_map = dict(zip(attr_labels, attr_uris))

        selected_attr_label = st.selectbox("Select Attribute to Unlink", options=attr_labels)
        selected_attr = attr_map[selected_attr_label]

        submitted = st.form_submit_button("❌ Remove Link", type="primary")

        if submitted:
            if st.session_state.get('confirm_unlink'):
                with st.spinner("Removing link..."):
                    success = api_client.remove_attribute_link(
                        st.session_state.ontology_selected_extension,
                        component,
                        selected_attr
                    )

                    if success:
                        st.success("✅ Link removed successfully!")
                        st.session_state.confirm_unlink = False
                        st.session_state.ontology_active_form = None
                        st.rerun()
            else:
                st.session_state.confirm_unlink = True
                st.warning("Click 'Remove Link' again to confirm")
                st.rerun()


# =================== Bulk Operations ===================

def render_bulk_link_attributes_form(api_client):
    """Render the bulk link attributes form - FIXED to stay open"""
    st.markdown("#### 🔗 Bulk Link Attributes")

    # Component selector (outside form so it persists)
    component = render_component_selector("Select Component", "bulk_link_comp")

    # Fetch component's currently linked attributes
    linked_attrs = api_client.get_component_attributes(
        st.session_state.ontology_selected_extension,
        component
    )
    linked_uris = set([attr['class'] for attr in linked_attrs])

    # Filter available attributes (not yet linked)
    available_attrs = [attr for attr in st.session_state.ontology_attributes
                       if attr['class'] not in linked_uris]

    st.markdown("---")

    # Link new attribute section
    st.markdown("**Link New Attribute:**")
    if available_attrs:
        sorted_available = sort_by_label(available_attrs)
        avail_labels = [attr.get('label') or extract_local_name(attr['class'])
                        for attr in sorted_available]
        avail_uris = [attr['class'] for attr in sorted_available]
        avail_map = dict(zip(avail_labels, avail_uris))

        selected_avail_label = st.selectbox(
            "Select Attribute to Link",
            options=avail_labels,
            key=f"bulk_link_select_{component}"  # Unique key per component
        )
        selected_avail = avail_map[selected_avail_label]

        if st.button("✅ Link Attribute", key="bulk_link_add_btn", type="primary"):
            with st.spinner("Linking attribute..."):
                success = api_client.link_attribute(
                    st.session_state.ontology_selected_extension,
                    component,
                    selected_avail
                )
                if success:
                    st.success("✅ Attribute linked!")
                    # Rerun to refresh the lists - dialog will stay open
                    st.rerun()
    else:
        st.info("All attributes are already linked to this component")

    st.markdown("---")

    # Currently linked attributes section
    st.markdown("**Currently Linked Attributes:**")
    if linked_attrs:
        for attr in sort_by_label(linked_attrs):
            col1, col2 = st.columns([4, 1])
            with col1:
                label = attr.get('label') or extract_local_name(attr['class'])
                st.text(label)
            with col2:
                if st.button("❌", key=f"unlink_{attr['class']}", help="Unlink this attribute"):
                    with st.spinner("Unlinking..."):
                        success = api_client.remove_attribute_link(
                            st.session_state.ontology_selected_extension,
                            component,
                            attr['class']
                        )
                        if success:
                            st.success("✅ Unlinked!")
                            # Rerun to refresh the lists - dialog will stay open
                            st.rerun()

        # Summary
        st.markdown("---")
        st.info(f"""
        **Summary:**
        - Component: {extract_local_name(component)}
        - Linked Attributes: {len(linked_attrs)}
        - Available to Link: {len(available_attrs)}
        """)
    else:
        st.info("No attributes linked to this component")

    st.markdown("---")

    # Explicit close button
    if st.button("✅ Done - Close Form", key="bulk_link_close", use_container_width=True):
        st.session_state.ontology_active_form = None
        st.rerun()


# =================== Category Management ===================

def render_manage_categories_form(api_client):
    """Render the manage attribute categories form"""
    st.markdown("#### 📂 Manage Attribute Categories")

    # Fetch categories if not already loaded
    if 'attribute_categories' not in st.session_state:
        st.session_state.attribute_categories = api_client.get_attribute_categories(
            st.session_state.ontology_selected_extension
        )

    # Attribute selector
    attribute = render_attribute_selector("Select Attribute", "cat_attr_select")

    # Fetch categories for this attribute
    attr_categories = api_client.get_attribute_categories_for_attribute(
        st.session_state.ontology_selected_extension,
        attribute
    )
    attr_category_uris = set([cat['class'] for cat in attr_categories])

    st.markdown("---")

    # Add to category section
    st.markdown("**Add to Category:**")
    available_categories = [cat for cat in st.session_state.attribute_categories
                            if cat['class'] not in attr_category_uris]

    if available_categories:
        sorted_cats = sort_by_label(available_categories)
        cat_labels = [cat.get('label') or extract_local_name(cat['class']) for cat in sorted_cats]
        cat_uris = [cat['class'] for cat in sorted_cats]
        cat_map = dict(zip(cat_labels, cat_uris))

        selected_cat_label = st.selectbox("Select Category", options=cat_labels, key="cat_select")
        selected_cat = cat_map[selected_cat_label]

        if st.button("✅ Add to Category", key="add_to_cat_btn", type="primary"):
            with st.spinner("Adding to category..."):
                success = api_client.add_attribute_to_category(
                    st.session_state.ontology_selected_extension,
                    attribute,
                    selected_cat
                )
                if success:
                    st.success("✅ Added to category!")
                    st.rerun()
    else:
        st.info("Attribute is in all available categories")

    st.markdown("---")

    # Current categories section
    st.markdown("**Current Categories:**")
    if attr_categories:
        for cat in sort_by_label(attr_categories):
            col1, col2 = st.columns([4, 1])
            with col1:
                label = cat.get('label') or extract_local_name(cat['class'])
                st.text(label)
            with col2:
                if st.button("❌", key=f"remove_cat_{cat['class']}", help="Remove from category"):
                    with st.spinner("Removing..."):
                        success = api_client.remove_attribute_from_category(
                            st.session_state.ontology_selected_extension,
                            attribute,
                            cat['class']
                        )
                        if success:
                            st.success("✅ Removed from category!")
                            st.rerun()
    else:
        st.info("No categories assigned")


# =================== Named Individuals Management ===================

def render_manage_individuals_form(api_client):
    """Render the manage named individuals form - WITH FRESH DATA"""
    st.markdown("#### 👤 Manage Named Individuals")

    # FIX: Always fetch fresh categorical attributes - DON'T cache
    categorical_attributes = api_client.get_categorical_attributes(
        st.session_state.ontology_selected_extension
    )

    if not categorical_attributes:
        st.info("No categorical attributes available")
        return


    # Attribute selector - FIX: Use the local variable, not session state
    sorted_cats = sort_by_label(categorical_attributes)
    cat_labels = [attr.get('label') or extract_local_name(attr['class']) for attr in sorted_cats]
    cat_uris = [attr['class'] for attr in sorted_cats]
    cat_map = dict(zip(cat_labels, cat_uris))

    selected_cat_label = st.selectbox("Select Categorical Attribute", options=cat_labels,
                                      key="ind_cat_select")
    selected_attribute = cat_map[selected_cat_label]

    # Fetch named individuals for this attribute
    named_individuals = api_client.get_named_individuals(
        st.session_state.ontology_selected_extension,
        selected_attribute
    )

    st.markdown("---")

    # Add new individual section
    st.markdown("**Add New Individual:**")
    with st.form("add_individual_form"):
        individual_label = st.text_input(
            "Individual Label",
            placeholder="e.g., Crystalline PV",
            help="Label for the new named individual"
        )

        submitted = st.form_submit_button("✅ Add Individual", type="primary")

        if submitted:
            if not individual_label:
                st.error("Please enter an individual label")
            else:
                with st.spinner("Adding individual..."):
                    success = api_client.add_named_individual(
                        st.session_state.ontology_selected_extension,
                        individual_label,
                        selected_attribute
                    )
                    if success:
                        st.success("✅ Individual added!")
                        st.rerun()

    st.markdown("---")

    # Current individuals section
    st.markdown("**Current Named Individuals:**")
    if named_individuals:
        for ind in named_individuals:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text(ind.get('label', extract_local_name(ind['uri'])))
            with col2:
                if st.button("❌", key=f"remove_ind_{ind['uri']}", help="Remove individual"):
                    with st.spinner("Removing..."):
                        success = api_client.remove_named_individual(
                            st.session_state.ontology_selected_extension,
                            ind['uri']
                        )
                        if success:
                            st.success("✅ Individual removed!")
                            st.rerun()

        st.markdown("---")
        st.info(f"""
        **Info:**
        - Attribute: {extract_local_name(selected_attribute)}
        - Named Individuals: {len(named_individuals)}
        """)
    else:
        st.info("No named individuals defined for this attribute")


# =================== Mapping Forms ===================

def render_map_component_form(api_client):
    """Render the map component form"""
    st.markdown("#### 🗺️ Map Component")

    # Fetch mapping classes
    if not st.session_state.ontology_selected_mapping:
        st.error("No mapping file selected")
        return

    mapping_classes = api_client.fetch_mapping_classes(st.session_state.ontology_selected_mapping)

    if not mapping_classes:
        st.info("No mapping classes available")
        return

    with st.form("map_component_form"):
        component = render_component_selector("Select Component", "map_comp_comp")

        linkage_relation = st.selectbox(
            "Linkage Relation",
            options=["owl:equivalentClass", "rdfs:subClassOf", "skos:closeMatch"]
        )

        mapping_class_options = [mc['local'] for mc in mapping_classes]
        selected_mapping_class = st.selectbox("Select Mapping Class", options=mapping_class_options)

        submitted = st.form_submit_button("✅ Submit Mapping", type="primary")

        if submitted:
            with st.spinner("Saving mapping..."):
                success = api_client.map_component(
                    component,
                    linkage_relation,
                    selected_mapping_class,
                    st.session_state.ontology_selected_mapping
                )

                if success:
                    st.success("✅ Component mapping saved!")
                    st.session_state.ontology_active_form = None
                    st.rerun()


def render_map_attribute_form(api_client):
    """Render the map attribute form"""
    st.markdown("#### 🗺️ Map Attribute")

    if not st.session_state.ontology_selected_mapping:
        st.error("No mapping file selected")
        return

    mapping_classes = api_client.fetch_mapping_classes(st.session_state.ontology_selected_mapping)

    if not mapping_classes:
        st.info("No mapping classes available")
        return

    with st.form("map_attribute_form"):
        attribute = render_attribute_selector("Select Attribute", "map_attr_attr")

        linkage_relation = st.selectbox(
            "Linkage Relation",
            options=["owl:equivalentClass", "rdfs:subClassOf", "skos:closeMatch"]
        )

        mapping_class_options = [mc['local'] for mc in mapping_classes]
        selected_mapping_class = st.selectbox("Select Mapping Class", options=mapping_class_options)

        submitted = st.form_submit_button("✅ Submit Mapping", type="primary")

        if submitted:
            with st.spinner("Saving mapping..."):
                success = api_client.map_attribute(
                    attribute,
                    linkage_relation,
                    selected_mapping_class,
                    st.session_state.ontology_selected_mapping
                )

                if success:
                    st.success("✅ Attribute mapping saved!")
                    st.session_state.ontology_active_form = None
                    st.rerun()


def render_map_property_form(api_client):
    """Render the map property form"""
    st.markdown("#### 🗺️ Map Property")

    if not st.session_state.ontology_selected_mapping:
        st.error("No mapping file selected")
        return

    mapping_properties = api_client.fetch_mapping_properties(st.session_state.ontology_selected_mapping)

    if not mapping_properties:
        st.info("No mapping properties available")
        return

    with st.form("map_property_form"):
        property_uri = render_property_selector("Select Object Property", "map_prop_prop")

        linkage_relation = st.selectbox(
            "Linkage Relation",
            options=["owl:equivalentProperty", "rdfs:subPropertyOf", "skos:closeMatch"]
        )

        mapping_prop_options = [mp['local'] for mp in mapping_properties]
        selected_mapping_prop = st.selectbox("Select Mapping Property", options=mapping_prop_options)

        submitted = st.form_submit_button("✅ Submit Mapping", type="primary")

        if submitted:
            with st.spinner("Saving mapping..."):
                success = api_client.map_property(
                    property_uri,
                    linkage_relation,
                    selected_mapping_prop,
                    st.session_state.ontology_selected_mapping
                )

                if success:
                    st.success("✅ Property mapping saved!")
                    st.session_state.ontology_active_form = None
                    st.rerun()


def render_manage_property_mappings_form(api_client):
    """Render the manage property mappings form"""
    st.markdown("#### 🔧 Manage Property Mappings")

    if not st.session_state.ontology_selected_mapping:
        st.error("No mapping file selected")
        return

    # Fetch property mappings
    property_mappings = api_client.get_property_mappings(st.session_state.ontology_selected_mapping)

    if not property_mappings:
        st.info("No property mappings found")
        return

    st.markdown("**Current Property Mappings:**")

    def get_predicate_label(predicate: str) -> str:
        if "equivalentProperty" in predicate:
            return "equivalentProperty"
        elif "subPropertyOf" in predicate:
            return "subPropertyOf"
        elif "closeMatch" in predicate:
            return "closeMatch"
        return extract_local_name(predicate)

    for mapping in property_mappings:
        with st.container():
            st.markdown(f"""
            **Subject:** {extract_local_name(mapping['subject'])}
            
            **Relation:** {get_predicate_label(mapping['predicate'])}
            
            **Object:** {extract_local_name(mapping['object'])}
            """)

            if st.button("🗑️ Remove", key=f"remove_mapping_{mapping['subject']}_{mapping['object']}"):
                with st.spinner("Removing mapping..."):
                    success = api_client.remove_property_mapping(
                        st.session_state.ontology_selected_mapping,
                        mapping['subject'],
                        mapping['predicate'],
                        mapping['object']
                    )
                    if success:
                        st.success("✅ Mapping removed!")
                        st.rerun()

            st.markdown("---")


# =================== GraphDB Upload Form ===================

def render_upload_graphdb_form(api_client):
    """Render the GraphDB upload form - BETTER UX"""
    st.markdown("#### 📤 Upload to Triplestore")

    # Check if we just completed an upload
    if st.session_state.get('upload_success_result'):
        result = st.session_state.upload_success_result

        st.success("🎉 Successfully uploaded to Triplestore!")
        st.balloons()

        st.info(f"""
        **Repository:** `{result.get('repository')}`  
        **Named Graph:** `{result.get('graph_name')}`  
        **Export File:** `{result.get('export_file')}`
        """)

        st.markdown("---")

        # Done button OUTSIDE form
        if st.button("✅ Done", type="primary", use_container_width=True):
            del st.session_state.upload_success_result
            st.session_state.confirm_upload_graphdb = False
            st.session_state.ontology_active_form = None
            st.rerun()

        return  # Don't show the form again

    # Check export file (silently)
    export_info = None

    try:
        export_info = api_client.get_export_info(st.session_state.ontology_selected_extension)

        if not (export_info and export_info.get('exists')):
            st.error("❌ Export file not found")
            st.info(export_info.get('message', 'Please load the extension and try again') if export_info else 'Error loading export info')
            if st.button("Close", key="close_no_export"):
                st.session_state.ontology_active_form = None
                st.rerun()
            return

    except Exception as e:
        st.error(f"Error loading export info: {str(e)}")
        if st.button("Close", key="close_error"):
            st.session_state.ontology_active_form = None
            st.rerun()
        return

    # Show upload configuration
    workspace_info = api_client.get_workspace_info()
    workspace_id = workspace_info.get('workspace_id', 'Unknown')

    st.info(f"""
    **Upload Details:**
    - Repository: `{workspace_id}`
    - Named Graph: `<http://ontology_dici_onto>`
    - Extension: `{st.session_state.ontology_selected_extension}`
    - Action: Replace existing ontology in this graph
    """)

    st.markdown("---")

    # Upload form
    with st.form("upload_graphdb_form", clear_on_submit=False):
        if st.session_state.get('confirm_upload_graphdb'):
            st.warning("⚠️ Click 'Upload' again to confirm!")

        submitted = st.form_submit_button("📤 Upload to Triplestore", type="primary", use_container_width=True)

        if submitted:
            if not st.session_state.get('confirm_upload_graphdb'):
                st.session_state.confirm_upload_graphdb = True
                st.warning(f"""
                ⚠️ **Confirmation Required**

                This will replace any existing ontology in `{workspace_id}` repository.

                Click 'Upload to Triplestore' again to proceed.
                """)
                st.rerun()
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()

                try:
                    status_text.text("📤 Uploading ontology to Triplestore...")
                    progress_bar.progress(30)

                    success, result = api_client.upload_to_graphdb(
                        st.session_state.ontology_selected_extension,
                        workspace_id
                    )

                    progress_bar.progress(100)

                    if success:
                        status_text.empty()
                        progress_bar.empty()

                        # Store the result and rerun to show success page
                        st.session_state.upload_success_result = result
                        st.session_state.confirm_upload_graphdb = False
                        st.rerun()
                    else:
                        progress_bar.empty()
                        status_text.empty()

                        error_msg = result.get('error', 'Unknown error')
                        st.error(f"❌ Upload failed: {error_msg}")

                        if 'error' in result:
                            with st.expander("🔍 Error Details"):
                                st.code(result.get('error'))

                        st.session_state.confirm_upload_graphdb = False

                except Exception as e:
                    progress_bar.empty()
                    status_text.empty()
                    st.error(f"❌ Upload error: {str(e)}")

                    import traceback
                    with st.expander("🔍 Error Traceback"):
                        st.code(traceback.format_exc())

                    st.session_state.confirm_upload_graphdb = False

    # Cancel button OUTSIDE form
    st.markdown("---")
    if st.button("❌ Cancel", key="cancel_upload_form", use_container_width=True):
        st.session_state.confirm_upload_graphdb = False
        st.session_state.ontology_active_form = None
        st.rerun()


# =================== Propose Upstream Form ===================

def render_propose_upstream_form(api_client):
    """Render the form for promoting an extension's concepts into core dici_onto.

    Surfaces the extension TTL for download and walks the user through opening a
    promote-to-core PR against digicities-ontology. No GitHub API calls — keeps the
    workflow inspectable.
    """
    import os
    from urllib.parse import quote

    st.markdown("#### 🌱 Propose this extension for promotion into core")
    ontology_repo_for_link = os.environ.get("DIGICITIES_ONTOLOGY_REPO", "uesl-empa/digicities-ontology")
    st.markdown(
        f"Once concepts in this extension have been adopted across **multiple workpackages** and "
        f"have been stable for a few months, propose promoting them into "
        f"[digicities-ontology](https://github.com/{ontology_repo_for_link}) so they become part "
        f"of the shared core vocabulary. See "
        f"[`CORE_EVOLUTION.md`](https://github.com/{ontology_repo_for_link}/blob/main/docs/CORE_EVOLUTION.md) "
        f"for the full promotion criteria and lifecycle. Premature promotion is worse than no "
        f"promotion — concepts that haven't proven their generality lock the shared vocabulary "
        f"into a workspace's idiosyncrasies."
    )

    extension_filename = st.session_state.get("ontology_selected_extension")
    if not extension_filename or extension_filename == "CORE_ONTOLOGY_MODIFICATION":
        st.warning("⚠️ Select a regular extension (not the core ontology) before proposing upstream.")
        st.markdown("---")
        if st.button("Close", key="close_no_ext_propose"):
            st.session_state.ontology_active_form = None
            st.rerun()
        return

    try:
        export_info = api_client.get_export_info(extension_filename)
    except Exception as exc:
        st.error(f"Could not read export info: {exc}")
        if st.button("Close", key="close_propose_err"):
            st.session_state.ontology_active_form = None
            st.rerun()
        return

    if not (export_info and export_info.get("exists")):
        st.error("❌ Export file not found. Load the extension first (Operations tab → Save & Export).")
        if st.button("Close", key="close_propose_noexp"):
            st.session_state.ontology_active_form = None
            st.rerun()
        return

    ttl_content = api_client.get_export_ttl_content(extension_filename)
    if not ttl_content:
        st.error("❌ Could not read TTL content for this extension.")
        if st.button("Close", key="close_propose_nottl"):
            st.session_state.ontology_active_form = None
            st.rerun()
        return

    base_name = extension_filename.replace(".ttl", "")
    target_filename = f"{base_name}.ttl"

    st.info(
        f"**Extension:** `{extension_filename}`  \n"
        f"**Promotion target:** the concepts below get merged into "
        f"`core/dici_onto_core.ttl` in the ontology repo  \n"
        f"**Size:** {format_file_size(export_info.get('file_size', 0))}, "
        f"{export_info.get('line_count', '?')} lines"
    )

    st.markdown("##### Step 1 — Download the extension TTL")
    st.markdown(
        "Reviewers will copy the relevant class and property declarations from your TTL into "
        "`core/dici_onto_core.ttl`. The IRI doesn't change (you've been using `dici_onto:` all "
        "along), so your workspace's existing data and queries keep working after promotion."
    )
    st.download_button(
        label=f"⬇️ Download {target_filename}",
        data=ttl_content,
        file_name=target_filename,
        mime="text/turtle",
        use_container_width=True,
    )

    st.markdown("##### Step 2 — Open a promote-to-core PR")
    ontology_repo = os.environ.get("DIGICITIES_ONTOLOGY_REPO", "").strip() or "uesl-empa/digicities-ontology"
    edit_core_url = f"https://github.com/{ontology_repo}/edit/main/core/dici_onto_core.ttl"
    st.markdown(
        f"Open [**`core/dici_onto_core.ttl` in the GitHub web editor**]({edit_core_url}). "
        f"Paste your new class and property declarations into the appropriate section, then "
        f"commit to a new branch and open a PR. In the PR description, link this workspace and "
        f"any other workpackages that have adopted the concept — promotion requires ≥2 "
        f"workpackages in active use.\n\n"
        f"If the link 404s (private repo, or you're not signed in), use the manual flow below."
    )

    with st.expander("Manual flow"):
        st.markdown(
            f"""1. Clone the ontology repo: `git clone https://github.com/{ontology_repo}.git`
2. Create a branch: `git checkout -b promote-{base_name}`
3. Open the downloaded `{target_filename}`. Pick the class and property declarations you want to promote.
4. Append them to the appropriate section of `core/dici_onto_core.ttl`.
5. (Optional) Validate your local extension against the current core: `python tools/validate_extension.py /path/to/your/workspace/ontology/extensions/{target_filename}`
6. `pytest` to confirm core still parses cleanly.
7. Commit, push, and open a PR. In the body, link the originating workspaces and note how long the concept has been in use.
"""
        )

    st.markdown("##### Step 3 — Pre-PR checklist")
    st.markdown(
        f"""Before submitting, double-check:

- The concept is in use across **≥2 workpackages**. If only your workspace uses it, keep it as a workspace extension.
- The definition has been **stable for a few months**. Promotion locks the IRI into the public core release contract.
- Every new class declares `rdfs:subClassOf` pointing into core (or another class declared earlier in your extension).
- Every new term carries an English `rdfs:label` and `rdfs:comment`.
- Your extension uses the **`dici_onto:` namespace** — yes, the same as core. This is intentional. The IRI stays stable across promotion so your workspace's existing TTL data and queries don't break.
- See [`CORE_EVOLUTION.md`](https://github.com/{ontology_repo}/blob/main/docs/CORE_EVOLUTION.md) for the full promotion criteria.
"""
    )

    st.markdown("---")
    if st.button("Close", key="close_propose_done", use_container_width=True):
        st.session_state.ontology_active_form = None
        st.rerun()


# =================== Utility Functions ===================

def format_file_size(bytes_size: int) -> str:
    """Format file size in human-readable format"""
    if bytes_size == 0:
        return '0 Bytes'
    k = 1024
    sizes = ['Bytes', 'KB', 'MB', 'GB']
    i = 0
    size = float(bytes_size)
    while size >= k and i < len(sizes) - 1:
        size /= k
        i += 1
    return f"{size:.2f} {sizes[i]}"


def format_timestamp(timestamp) -> str:
    """Format timestamp as readable date"""
    try:
        if isinstance(timestamp, str):
            # Already a string, return as-is
            return timestamp
        elif isinstance(timestamp, (int, float)):
            # Unix timestamp, convert to string
            from datetime import datetime
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        else:
            return "Unknown"
    except:
        return "Unknown"