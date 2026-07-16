# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_attribute_manager.py
"""
ENHANCED Attribute Manager for Replica Builder
Handles attribute configuration for instances WITH ONTOLOGY CONSTRAINTS
- Units constrained to ontology defaults
- Categorical values constrained to named individuals
- All attribute types properly structured for TTL generation
"""
import streamlit as st
from typing import Dict, List, Any, Optional
import json

# Import ontology helper functions
try:
    from components.replica_builder.replica_ontology_loader import (
        get_attribute_constraints,
        get_categorical_options,
        get_temporal_precisions
    )

    ONTOLOGY_HELPERS_AVAILABLE = True
except ImportError:
    ONTOLOGY_HELPERS_AVAILABLE = False

# Workspace-storage-backed timeseries file helpers (local / NextCloud / any fsspec).
try:
    from components.replica_builder.replica_nextcloud_integration import (
        check_nextcloud_configured,
        show_nextcloud_status,
        list_timeseries_files,
        upload_file_to_nextcloud,
    )

    NEXTCLOUD_AVAILABLE = True
except ImportError:
    NEXTCLOUD_AVAILABLE = False


# File-type filters per attribute kind.
_DATA_FILE_TYPES = ['csv', 'json', 'parquet', 'xlsx', 'txt']
_GEO_FILE_TYPES = ['geojson', 'json', 'shp', 'kml', 'gpx', 'gml', 'zip']


def _select_existing_timeseries_file(label: str, state_key: str, file_types=None) -> None:
    """Render a selectbox of existing timeseries files (via ctx.storage) and store
    the choice in ``st.session_state[state_key]``. Shared by every attribute type's
    'Select Existing' mode so they all read from the same workspace storage.
    ``file_types=None`` lists every file."""
    ok, files, error = list_timeseries_files(file_types=file_types)
    if not ok:
        st.warning(f"Could not load existing files: {error}")
        st.session_state[state_key] = st.text_input(
            "File", value=st.session_state.get(state_key, ""),
            placeholder="Enter filename", key=f"{state_key}_input_fallback"
        )
        return
    if not files:
        st.warning("No compatible files found in the timeseries directory")
        return
    selected_file = st.selectbox(label, options=[""] + files, key=f"{state_key}_selector")
    if selected_file:
        st.session_state[state_key] = selected_file


def tab_manage_attributes():
    """Tab for managing instance attributes"""
    st.subheader("Instance Attributes")

    # Initialize edit mode state
    if 'editing_attribute' not in st.session_state:
        st.session_state.editing_attribute = None

    # Show NextCloud status
    if NEXTCLOUD_AVAILABLE:
        with st.expander("📁 NextCloud File Upload Status", expanded=False):
            show_nextcloud_status()
            st.caption("File upload is available for Dynamic (Historic/Future), SimpleValue, and Geospatial attributes")

    if not st.session_state.replica_instances:
        st.info("Create instances first in the Instances tab")
        return

    # Instance selection
    instance_options = {
        inst.id: f"{inst.id} ({inst.component_type})"
        for inst in st.session_state.replica_instances
    }

    selected_id = st.selectbox(
        "Select Instance",
        options=list(instance_options.keys()),
        format_func=lambda x: instance_options[x],
        key="attribute_instance_selector"
    )

    if not selected_id:
        return

    instance = next((inst for inst in st.session_state.replica_instances if inst.id == selected_id), None)

    if not instance:
        st.error("Instance not found")
        return

    st.write(f"### Configuring: {instance.label}")
    st.caption(f"Type: {instance.component_type} | URI: `{instance.uri}`")

    # Get available attributes for this component type from ontology
    available_attrs = st.session_state.replica_component_attribute_mappings.get(
        instance.component_type, []
    )

    if not available_attrs or available_attrs == ['label']:
        st.warning(f"No attributes defined for {instance.component_type} in the ontology")
        st.info("Please ensure the ontology has attribute mappings for this component type")
        return

    st.write("---")

    # Add attribute section
    with st.expander("Add Attribute", expanded=True):
        render_add_attribute_form(instance, available_attrs)

    # Display existing attributes
    st.write("### Current Attributes")

    if not instance.attributes:
        st.info("No attributes configured yet")
    else:
        # Check if we're editing an attribute
        if st.session_state.editing_attribute:
            edit_instance_id, edit_attr_name = st.session_state.editing_attribute
            if edit_instance_id == instance.id and edit_attr_name in instance.attributes:
                with st.expander(f"✏️ Editing: {edit_attr_name}", expanded=True):
                    # Check if this is SimpleValue or Geospatial with File Reference option
                    attr_data = instance.attributes[edit_attr_name]
                    attr_type = attr_data.get('type', 'Unknown')

                    # Render file upload UI OUTSIDE form for SimpleValue and Geospatial
                    if attr_type == "SimpleValue" and NEXTCLOUD_AVAILABLE:
                        simplevalue_edit_key = f"{instance.id}_{edit_attr_name}_edit"
                        # Initialize session state for this key if not exists
                        if simplevalue_edit_key not in st.session_state:
                            st.session_state[simplevalue_edit_key] = attr_data.get('value', '')
                        render_simplevalue_file_upload(edit_attr_name, simplevalue_edit_key)
                        st.write("---")
                    elif attr_type == "Geospatial" and NEXTCLOUD_AVAILABLE:
                        geospatial_edit_key = f"{instance.id}_{edit_attr_name}_edit"
                        # Initialize session state for this key if not exists
                        if geospatial_edit_key not in st.session_state:
                            st.session_state[geospatial_edit_key] = attr_data.get('value', '')
                        render_geospatial_file_upload(edit_attr_name, geospatial_edit_key)
                        st.write("---")

                    # Render the edit form
                    render_edit_attribute_form(instance, edit_attr_name)
                st.write("---")

        render_attributes_display(instance)

    # Display annotations
    if instance.annotations:
        st.write("### Annotations")
        render_annotations_display(instance)


def render_timeseries_file_uploads(instance_id: str, attr_name: str, historic_key: str, future_key: str, live_key: str):
    """Render time series file upload UI OUTSIDE the form for better interactivity"""

    st.write("**⏱️ Time Series Data (Optional)**")
    st.caption("✅ Uploaded files are saved automatically - you can continue filling the form below")

    # Historic Time Series
    col1, col2, col3 = st.columns(3)

    with col1:
        add_historic = st.checkbox(
            "Historic Time Series",
            key=f"{instance_id}_{attr_name}_has_historic",
            help="Add reference to historical data"
        )

    with col2:
        add_future = st.checkbox(
            "Future Time Series",
            key=f"{instance_id}_{attr_name}_has_future",
            help="Add reference to forecast/scenario data"
        )

    with col3:
        add_live = st.checkbox(
            "Live Time Series",
            key=f"{instance_id}_{attr_name}_has_live",
            help="Add reference to real-time data source"
        )

    # Historic upload UI
    if add_historic:
        with st.container():
            st.write("**📊 Historic Data**")

            # Option to upload new or select existing
            historic_mode = st.radio(
                "File Source:",
                options=["Upload New", "Select Existing"],
                key=f"{historic_key}_mode",
                horizontal=True
            )

            if historic_mode == "Select Existing" and NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                _select_existing_timeseries_file("Select Historic File:", historic_key, _DATA_FILE_TYPES)
            else:
                # Upload new file mode
                col_a, col_b = st.columns([2, 1])

                with col_a:
                    st.session_state[historic_key] = st.text_input(
                        "Historic File",
                        value=st.session_state[historic_key],
                        placeholder="Enter filename or upload below",
                        help="Filename in NextCloud timeseries directory",
                        key=f"{historic_key}_input"
                    )

                with col_b:
                    if NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                        uploaded_historic = st.file_uploader(
                            "Upload",
                            type=['csv', 'json', 'parquet', 'xlsx', 'txt'],
                            key=f"{historic_key}_uploader",
                            label_visibility="collapsed"
                        )

                        if uploaded_historic:
                            from components.replica_builder.replica_nextcloud_integration import upload_file_to_nextcloud
                            with st.spinner("Uploading..."):
                                success, filename, error = upload_file_to_nextcloud(uploaded_historic)
                                if success:
                                    st.session_state[historic_key] = filename
                                    st.success(f"✓ {filename}")
                                    # Don't rerun - just show success and let user continue
                                else:
                                    st.error(f"Failed: {error}")

    # Future upload UI
    if add_future:
        with st.container():
            st.write("**🔮 Future Data**")

            # Option to upload new or select existing
            future_mode = st.radio(
                "File Source:",
                options=["Upload New", "Select Existing"],
                key=f"{future_key}_mode",
                horizontal=True
            )

            if future_mode == "Select Existing" and NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                _select_existing_timeseries_file("Select Future File:", future_key, _DATA_FILE_TYPES)
            else:
                # Upload new file mode
                col_a, col_b = st.columns([2, 1])

                with col_a:
                    st.session_state[future_key] = st.text_input(
                        "Future File",
                        value=st.session_state[future_key],
                        placeholder="Enter filename or upload below",
                        help="Filename in NextCloud timeseries directory",
                        key=f"{future_key}_input"
                    )

                with col_b:
                    if NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                        uploaded_future = st.file_uploader(
                            "Upload",
                            type=['csv', 'json', 'parquet', 'xlsx', 'txt'],
                            key=f"{future_key}_uploader",
                            label_visibility="collapsed"
                        )

                        if uploaded_future:
                            from components.replica_builder.replica_nextcloud_integration import upload_file_to_nextcloud
                            with st.spinner("Uploading..."):
                                success, filename, error = upload_file_to_nextcloud(uploaded_future)
                                if success:
                                    st.session_state[future_key] = filename
                                    st.success(f"✓ {filename}")
                                    # Don't rerun - just show success and let user continue
                                else:
                                    st.error(f"Failed: {error}")

    # Live reference UI
    if add_live:
        with st.container():
            st.write("**⚡ Live Data Source**")
            st.session_state[live_key] = st.text_input(
                "Live Source Reference",
                value=st.session_state[live_key],
                placeholder="e.g., mqtt://broker/topic, api_endpoint",
                help="Real-time data source reference",
                key=f"{live_key}_input"
            )


def render_simplevalue_file_upload(attr_name: str, simplevalue_key: str):
    """Render SimpleValue file upload UI OUTSIDE the form for better interactivity"""

    st.write("**📄 File Reference (Optional)**")
    st.caption("✅ Upload new or select existing files - saved automatically")

    # Option to upload new or select existing
    simplevalue_mode = st.radio(
        "File Source:",
        options=["Upload New", "Select Existing"],
        key=f"{simplevalue_key}_mode",
        horizontal=True
    )

    if simplevalue_mode == "Select Existing" and NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
        # SimpleValue accepts any file type (no extension filter).
        _select_existing_timeseries_file("Select File:", simplevalue_key, None)
    else:
        # Upload new file mode
        col_a, col_b = st.columns([2, 1])

        with col_a:
            st.session_state[simplevalue_key] = st.text_input(
                "Filename",
                value=st.session_state[simplevalue_key],
                placeholder="Enter filename or upload below",
                help="Filename in NextCloud timeseries directory",
                key=f"{simplevalue_key}_input"
            )

        with col_b:
            if NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                uploaded_file = st.file_uploader(
                    "Upload",
                    type=None,  # Allow all file types
                    key=f"{simplevalue_key}_uploader",
                    label_visibility="collapsed"
                )

                if uploaded_file:
                    from components.replica_builder.replica_nextcloud_integration import upload_file_to_nextcloud
                    with st.spinner("Uploading..."):
                        success, filename, error = upload_file_to_nextcloud(uploaded_file)
                        if success:
                            st.session_state[simplevalue_key] = filename
                            st.success(f"✓ {filename}")
                        else:
                            st.error(f"Failed: {error}")


def render_geospatial_file_upload(attr_name: str, geospatial_key: str):
    """Render Geospatial file upload UI OUTSIDE the form for better interactivity"""

    st.write("**🗺️ Geospatial File Reference (Optional)**")
    st.caption("✅ Upload new or select existing geospatial files - saved automatically")

    # Option to upload new or select existing
    geospatial_mode = st.radio(
        "File Source:",
        options=["Upload New", "Select Existing"],
        key=f"{geospatial_key}_mode",
        horizontal=True
    )

    if geospatial_mode == "Select Existing" and NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
        _select_existing_timeseries_file("Select Geospatial File:", geospatial_key, _GEO_FILE_TYPES)
    else:
        # Upload new file mode
        col_a, col_b = st.columns([2, 1])

        with col_a:
            st.session_state[geospatial_key] = st.text_input(
                "Geospatial Filename",
                value=st.session_state[geospatial_key],
                placeholder="Enter filename or upload below",
                help="Filename in NextCloud timeseries directory",
                key=f"{geospatial_key}_input"
            )

        with col_b:
            if NEXTCLOUD_AVAILABLE and check_nextcloud_configured():
                uploaded_file = st.file_uploader(
                    "Upload",
                    type=['geojson', 'json', 'shp', 'kml', 'gpx', 'gml', 'zip'],
                    key=f"{geospatial_key}_uploader",
                    label_visibility="collapsed"
                )

                if uploaded_file:
                    from components.replica_builder.replica_nextcloud_integration import upload_file_to_nextcloud
                    with st.spinner("Uploading..."):
                        success, filename, error = upload_file_to_nextcloud(uploaded_file)
                        if success:
                            st.session_state[geospatial_key] = filename
                            st.success(f"✓ {filename}")
                        else:
                            st.error(f"Failed: {error}")


def render_add_attribute_form(instance, available_attrs: List[str]):
    """Render form to add new attribute - CONSTRAINED by ontology"""

    # Filter out already used attributes and 'label'
    unused_attrs = [a for a in available_attrs if a not in instance.attributes and a != 'label']

    if not unused_attrs:
        st.warning(f"All available attributes for {instance.component_type} have been configured")
        return

    # IMPORTANT: Attribute selection OUTSIDE the form so it triggers re-render
    # Use session state to track selected attribute
    attr_select_key = f"attr_select_{instance.id}"
    if attr_select_key not in st.session_state:
        st.session_state[attr_select_key] = unused_attrs[0]

    col1, col2 = st.columns([3, 2])

    with col1:
        # Attribute name selection - ONLY from ontology
        attr_name = st.selectbox(
            "Attribute Name",
            options=unused_attrs,
            key=attr_select_key,
            help="Select from ontology-defined attributes for this component type"
        )

    # Get ontology constraints for this attribute
    attr_constraints = get_attribute_constraints(attr_name) if ONTOLOGY_HELPERS_AVAILABLE else None

    with col2:
        if attr_constraints:
            st.info(f"Type: **{attr_constraints.attribute_type}**")
            if attr_constraints.default_unit:
                st.caption(f"Default unit: `{attr_constraints.default_unit}`")
        else:
            st.caption("No constraints found in ontology")

    st.write("---")

    # PRE-FORM: File upload section for Physical/Dynamic attributes (OUTSIDE form for interactivity)
    # Initialize session state for file references
    historic_key = f"{instance.id}_{attr_name}_historic_file"
    future_key = f"{instance.id}_{attr_name}_future_file"
    live_key = f"{instance.id}_{attr_name}_live_ref"
    simplevalue_key = f"{instance.id}_{attr_name}_simplevalue_file"
    geospatial_key = f"{instance.id}_{attr_name}_geospatial_file"

    if historic_key not in st.session_state:
        st.session_state[historic_key] = ""
    if future_key not in st.session_state:
        st.session_state[future_key] = ""
    if live_key not in st.session_state:
        st.session_state[live_key] = ""
    if simplevalue_key not in st.session_state:
        st.session_state[simplevalue_key] = ""
    if geospatial_key not in st.session_state:
        st.session_state[geospatial_key] = ""

    # Show file upload UI for Physical attributes BEFORE the form
    if attr_constraints and attr_constraints.attribute_type == "Physical":
        render_timeseries_file_uploads(instance.id, attr_name, historic_key, future_key, live_key)
        st.write("---")

    # Show file upload UI for SimpleValue attributes BEFORE the form
    if attr_constraints and attr_constraints.attribute_type == "SimpleValue":
        render_simplevalue_file_upload(attr_name, simplevalue_key)
        st.write("---")

    # Show file upload UI for Geospatial attributes BEFORE the form
    if attr_constraints and attr_constraints.attribute_type == "Geospatial":
        render_geospatial_file_upload(attr_name, geospatial_key)
        st.write("---")

    # NOW the form - with fields that match the selected attribute
    with st.form(f"add_attribute_{instance.id}_{attr_name}"):
        # Render fields based on attribute constraints from ontology
        attribute_data = render_attribute_type_fields_constrained(
            attr_name,
            attr_constraints,
            historic_key,
            future_key,
            live_key,
            simplevalue_key,
            geospatial_key
        )

        # Datasource (optional for most types)
        if attr_constraints and attr_constraints.attribute_type not in ["Annotation", "Identifier"]:
            datasource = st.text_input(
                "Data Source (optional)",
                placeholder="e.g., sensor_system, manual_input",
                help="Optional: source of this data"
            )
            if datasource:
                attribute_data['datasource'] = datasource

        submit = st.form_submit_button("Add Attribute", type="primary", use_container_width=True)

        if submit:
            if not attr_name:
                st.error("Please provide an attribute name")
            elif attr_name in instance.attributes:
                st.error(f"Attribute '{attr_name}' already exists")
            else:
                # Determine attribute type
                if attr_constraints:
                    attr_type = attr_constraints.attribute_type
                else:
                    attr_type = "Physical"  # Default fallback

                # Handle annotations separately
                if attr_type == "Annotation":
                    instance.annotations[attr_name] = attribute_data['text']
                else:
                    attribute_data['type'] = attr_type
                    instance.attributes[attr_name] = attribute_data

                # Clear session state for file uploads so next attribute starts fresh
                if historic_key in st.session_state:
                    st.session_state[historic_key] = ""
                if future_key in st.session_state:
                    st.session_state[future_key] = ""
                if live_key in st.session_state:
                    st.session_state[live_key] = ""

                st.success(f"Added attribute: {attr_name}")
                st.rerun()


def render_attribute_type_fields_constrained(
        attr_name: str,
        constraints: Optional[Any],
        historic_key: str = "",
        future_key: str = "",
        live_key: str = "",
        simplevalue_key: str = "",
        geospatial_key: str = ""
) -> Dict[str, Any]:
    """Render input fields based on attribute type WITH ontology constraints

    Args:
        attr_name: Name of the attribute
        constraints: Ontology constraints for this attribute
        historic_key: Session state key for historic file reference
        future_key: Session state key for future file reference
        live_key: Session state key for live reference
        simplevalue_key: Session state key for simplevalue file reference
        geospatial_key: Session state key for geospatial file reference
    """
    data = {}

    if not constraints:
        # Fallback to basic Physical attribute if no constraints
        data['value'] = st.number_input("Value", value=0.0, format="%.4f")
        data['unit'] = st.text_input("Unit", placeholder="e.g., kW, m, kg")
        return data

    attr_type = constraints.attribute_type

    if attr_type == "Physical":
        st.write("**Static Value (Optional)**")
        st.caption("ℹ️ Leave at 0 if this attribute only has time series data (no static value)")
        col1, col2 = st.columns(2)
        with col1:
            data['value'] = st.number_input("Value", value=0.0, format="%.6f")
        with col2:
            # Use default unit from ontology
            if constraints.default_unit:
                available_units = st.session_state.get('replica_available_units', [constraints.default_unit])
                if constraints.default_unit not in available_units:
                    available_units.insert(0, constraints.default_unit)

                # Check if default unit is in the list, otherwise add it
                default_index = 0
                if constraints.default_unit in available_units:
                    default_index = available_units.index(constraints.default_unit)

                data['unit'] = st.selectbox(
                    "Unit",
                    options=available_units,
                    index=default_index,
                    help=f"Ontology default: {constraints.default_unit}"
                )
            else:
                # Allow free text if no default specified
                available_units = st.session_state.get('replica_available_units', [])
                if available_units:
                    data['unit'] = st.selectbox("Unit", options=available_units)
                else:
                    data['unit'] = st.text_input("Unit", placeholder="e.g., kW, m, kg")

        # Read time series references from session state (uploaded OUTSIDE the form)
        if historic_key and st.session_state.get(historic_key):
            data['historic_reference'] = st.session_state[historic_key]

        if future_key and st.session_state.get(future_key):
            data['future_reference'] = st.session_state[future_key]

        if live_key and st.session_state.get(live_key):
            data['live_reference'] = st.session_state[live_key]

    elif attr_type == "Categorical":
        # Get named individuals from ontology
        categorical_options = get_categorical_options(attr_name) if ONTOLOGY_HELPERS_AVAILABLE else []

        if categorical_options:
            data['category_value'] = st.selectbox(
                "Category Value",
                options=categorical_options,
                help="Select from ontology-defined named individuals"
            )
        else:
            st.warning(f"No named individuals found in ontology for {attr_name}")
            data['category_value'] = st.text_input(
                "Category Value",
                placeholder="e.g., Residential, Commercial",
                help="WARNING: No named individuals defined in ontology"
            )

    elif attr_type == "Event":
        col1, col2 = st.columns(2)
        with col1:
            data['temporal_value'] = st.text_input(
                "Temporal Value",
                placeholder="e.g., 1970, 2024-01-15, 07.1970"
            )
        with col2:
            temporal_precisions = get_temporal_precisions() if ONTOLOGY_HELPERS_AVAILABLE else ["Year", "YearMonth", "Date", "DateTime"]
            data['temporal_precision'] = st.selectbox(
                "Precision",
                options=temporal_precisions
            )

    elif attr_type == "SimpleCost":
        col1, col2 = st.columns(2)
        with col1:
            data['value'] = st.number_input("Cost", value=0.0, format="%.2f")
        with col2:
            data['currency'] = st.selectbox("Currency", options=["CHF", "EUR", "USD", "GBP"], index=0)

    elif attr_type == "UnitBasedCost":
        col1, col2, col3 = st.columns(3)
        with col1:
            data['value'] = st.number_input("Cost", value=0.0, format="%.2f")
        with col2:
            # Unit selection
            available_units = st.session_state.get('replica_available_units', [])
            if available_units:
                data['unit'] = st.selectbox("Unit", options=available_units)
            else:
                data['unit'] = st.text_input("Unit", placeholder="e.g., kWh")
        with col3:
            data['currency'] = st.selectbox("Currency", options=["CHF", "EUR", "USD", "GBP"], index=0)

    elif attr_type == "Curve":
        # X and Y units with ontology constraints
        col1, col2 = st.columns(2)

        available_units = st.session_state.get('replica_available_units', [])

        with col1:
            if available_units:
                data['x_unit'] = st.selectbox("X Unit", options=available_units)
            else:
                data['x_unit'] = st.text_input("X Unit", placeholder="e.g., m")

        with col2:
            if available_units:
                data['y_unit'] = st.selectbox("Y Unit", options=available_units)
            else:
                data['y_unit'] = st.text_input("Y Unit", placeholder="e.g., kW")

        data_points_text = st.text_area(
            "Data Points",
            placeholder="[(0,0);(1,10);(2,20)]",
            help="Format: [(x1,y1);(x2,y2);...]"
        )
        data['data_points'] = data_points_text

    elif attr_type == "Resource":
        data['data_path'] = st.text_input(
            "Resource Path",
            placeholder="e.g., /data/file.csv, https://..."
        )

    elif attr_type == "SimpleValue":
        # SimpleValue can either be a text value OR a file reference
        value_type = st.radio(
            "Value Type:",
            options=["Text Value", "File Reference"],
            key=f"{attr_name}_simplevalue_type",
            horizontal=True
        )

        if value_type == "Text Value":
            data['value'] = st.text_input("Value", placeholder="Enter value")
        else:  # File Reference
            # Read from session state (uploaded OUTSIDE the form)
            if simplevalue_key and st.session_state.get(simplevalue_key):
                data['value'] = st.session_state[simplevalue_key]
                st.info(f"Using uploaded file: {data['value']}")
            else:
                data['value'] = st.text_input(
                    "Filename",
                    placeholder="Upload file above or enter filename",
                    help="Filename in NextCloud timeseries directory"
                )

    elif attr_type == "CustomPhysicalRatio":
        available_units = st.session_state.get('replica_available_units', [])
        if constraints and constraints.ratio_numerator_unit and constraints.ratio_denominator_unit:
            st.caption(f"Ontology defined unit: **{constraints.ratio_numerator_unit} / {constraints.ratio_denominator_unit}**")
        elif constraints and constraints.default_unit:
            st.caption(f"Ontology default unit: **{constraints.default_unit}**")
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            data['value'] = st.number_input("Value", value=0.0, format="%.4f")
        if available_units:
            ont_num = constraints.ratio_numerator_unit if constraints else None
            ont_den = constraints.ratio_denominator_unit if constraints else None
            num_idx = available_units.index(ont_num) if ont_num and ont_num in available_units else 0
            den_idx = available_units.index(ont_den) if ont_den and ont_den in available_units else 0
            with col2:
                numerator_unit = st.selectbox(
                    "Numerator unit", options=available_units, index=num_idx, key=f"cpr_num_{attr_name}"
                )
            with col3:
                denominator_unit = st.selectbox(
                    "/ Denominator unit", options=available_units, index=den_idx, key=f"cpr_den_{attr_name}"
                )
            data['custom_unit'] = f"{numerator_unit}/{denominator_unit}"
        else:
            with col2:
                data['custom_unit'] = st.text_input(
                    "Unit (num/den)", placeholder="e.g., KiloW-HR/M2",
                    help="No QUDT units loaded — enter manually"
                )

    elif attr_type == "Identifier":
        data['identifier_value'] = st.text_input(
            "Identifier Value",
            placeholder="e.g., ID-12345"
        )

    elif attr_type == "Annotation":
        data['text'] = st.text_area(
            "Annotation Text",
            placeholder="Enter annotation..."
        )

    elif attr_type == "Geospatial":
        # Geospatial can be a text value (coordinates, WKT, etc.) OR a file reference (GeoJSON, Shapefile, etc.)
        value_type = st.radio(
            "Geospatial Value Type:",
            options=["Text/Coordinates", "File Reference"],
            key=f"{attr_name}_geospatial_type",
            horizontal=True
        )

        if value_type == "Text/Coordinates":
            data['value'] = st.text_area(
                "Geospatial Value",
                placeholder="e.g., POINT(8.5417 47.3769) or coordinates",
                help="Enter WKT, GeoJSON, coordinates, or other geospatial data"
            )
        else:  # File Reference
            # Read from session state (uploaded OUTSIDE the form)
            if geospatial_key and st.session_state.get(geospatial_key):
                data['value'] = st.session_state[geospatial_key]
                st.info(f"Using uploaded file: {data['value']}")
            else:
                data['value'] = st.text_input(
                    "Geospatial Filename",
                    placeholder="Upload file above or enter filename",
                    help="Filename in NextCloud timeseries directory"
                )

    else:
        # Unknown type fallback
        st.warning(f"Unknown attribute type: {attr_type}")
        data['value'] = st.text_input("Value", placeholder="Enter value")

    return data


def render_edit_attribute_form(instance, attr_name: str):
    """Render form to edit existing attribute"""
    attr_data = instance.attributes[attr_name]
    attr_type = attr_data.get('type', 'Unknown')

    # Get ontology constraints
    attr_constraints = get_attribute_constraints(attr_name) if ONTOLOGY_HELPERS_AVAILABLE else None

    st.write(f"**Attribute:** {attr_name}")
    st.caption(f"Type: {attr_type}")

    with st.form(f"edit_attribute_{instance.id}_{attr_name}"):
        # Render fields based on type with current values
        updated_data = render_attribute_type_fields_for_edit(attr_name, attr_data, attr_constraints)

        # Datasource (optional)
        if attr_type not in ["Annotation", "Identifier"]:
            datasource = st.text_input(
                "Data Source (optional)",
                value=attr_data.get('datasource', ''),
                placeholder="e.g., sensor_system, manual_input",
                help="Optional: source of this data"
            )
            if datasource:
                updated_data['datasource'] = datasource

        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True):
                updated_data['type'] = attr_type
                instance.attributes[attr_name] = updated_data
                st.session_state.editing_attribute = None
                st.success(f"Updated attribute: {attr_name}")
                st.rerun()

        with col2:
            if st.form_submit_button("❌ Cancel", use_container_width=True):
                st.session_state.editing_attribute = None
                st.rerun()


def render_attribute_type_fields_for_edit(attr_name: str, current_data: Dict[str, Any], constraints: Optional[Any]) -> Dict[str, Any]:
    """Render input fields for editing with current values pre-filled"""
    data = {}
    attr_type = current_data.get('type', 'Unknown')

    if attr_type == "Physical":
        st.write("**Static Value (Optional)**")
        st.caption("ℹ️ Leave at 0 if this attribute only has time series data (no static value)")
        col1, col2 = st.columns(2)
        with col1:
            data['value'] = st.number_input("Value", value=float(current_data.get('value', 0.0)), format="%.6f")
        with col2:
            current_unit = current_data.get('unit', '')
            if constraints and constraints.default_unit:
                available_units = st.session_state.get('replica_available_units', [constraints.default_unit])
                if current_unit and current_unit not in available_units:
                    available_units.insert(0, current_unit)
                if constraints.default_unit not in available_units:
                    available_units.insert(0, constraints.default_unit)
                default_index = available_units.index(current_unit) if current_unit in available_units else 0
                data['unit'] = st.selectbox("Unit", options=available_units, index=default_index)
            else:
                available_units = st.session_state.get('replica_available_units', [])
                if available_units:
                    if current_unit and current_unit not in available_units:
                        available_units.insert(0, current_unit)
                    default_index = available_units.index(current_unit) if current_unit in available_units else 0
                    data['unit'] = st.selectbox("Unit", options=available_units, index=default_index)
                else:
                    data['unit'] = st.text_input("Unit", value=current_unit, placeholder="e.g., kW, m, kg")

        # Historic/Future/Live references
        st.write("**Time Series References**")

        historic_ref = current_data.get('historic_reference', '')
        if historic_ref:
            data['historic_reference'] = st.text_input(
                "Historic Reference",
                value=historic_ref,
                help="Filename in NextCloud timeseries directory"
            )
        else:
            add_historic = st.checkbox("Add Historic Time Series", key=f"{attr_name}_edit_add_historic")
            if add_historic:
                data['historic_reference'] = st.text_input(
                    "Historic Reference",
                    placeholder="e.g., historic_data.csv",
                    help="Filename in NextCloud timeseries directory"
                )

        future_ref = current_data.get('future_reference', '')
        if future_ref:
            data['future_reference'] = st.text_input(
                "Future Reference",
                value=future_ref,
                help="Filename in NextCloud timeseries directory"
            )
        else:
            add_future = st.checkbox("Add Future Time Series", key=f"{attr_name}_edit_add_future")
            if add_future:
                data['future_reference'] = st.text_input(
                    "Future Reference",
                    placeholder="e.g., future_data.csv",
                    help="Filename in NextCloud timeseries directory"
                )

        live_ref = current_data.get('live_reference', '')
        if live_ref:
            data['live_reference'] = st.text_input(
                "Live Reference",
                value=live_ref,
                help="API endpoint or live data source"
            )
        else:
            add_live = st.checkbox("Add Live Time Series", key=f"{attr_name}_edit_add_live")
            if add_live:
                data['live_reference'] = st.text_input(
                    "Live Reference",
                    placeholder="e.g., https://api.example.com/live",
                    help="API endpoint or live data source"
                )

    elif attr_type == "Categorical":
        current_category = current_data.get('category_value', '')
        if constraints and ONTOLOGY_HELPERS_AVAILABLE:
            category_options = get_categorical_options(attr_name)
            if category_options:
                default_index = category_options.index(current_category) if current_category in category_options else 0
                data['category_value'] = st.selectbox("Category", options=category_options, index=default_index)
            else:
                data['category_value'] = st.text_input("Category Value", value=current_category)
        else:
            data['category_value'] = st.text_input("Category Value", value=current_category)

    elif attr_type == "Event":
        if constraints and ONTOLOGY_HELPERS_AVAILABLE:
            precisions = get_temporal_precisions()
            current_precision = current_data.get('temporal_precision', 'Date')
            default_index = precisions.index(current_precision) if current_precision in precisions else 2
            data['temporal_precision'] = st.selectbox("Temporal Precision", options=precisions, index=default_index)
        else:
            data['temporal_precision'] = st.selectbox(
                "Temporal Precision",
                options=["Year", "YearMonth", "Date", "DateTime"],
                index=2
            )
        data['temporal_value'] = st.text_input(
            "Temporal Value",
            value=current_data.get('temporal_value', ''),
            placeholder="e.g., 2024, 2024-03, 2024-03-15, 2024-03-15T14:30:00"
        )

    elif attr_type in ["SimpleCost", "UnitBasedCost"]:
        col1, col2 = st.columns(2)
        with col1:
            data['value'] = st.number_input("Value", value=float(current_data.get('value', 0.0)), format="%.2f")
        with col2:
            data['currency'] = st.text_input("Currency", value=current_data.get('currency', 'CHF'))

        if attr_type == "UnitBasedCost":
            available_units = st.session_state.get('replica_available_units', [])
            current_unit = current_data.get('unit', '')
            if available_units:
                if current_unit and current_unit not in available_units:
                    available_units.insert(0, current_unit)
                default_index = available_units.index(current_unit) if current_unit in available_units else 0
                data['unit'] = st.selectbox("Per Unit", options=available_units, index=default_index)
            else:
                data['unit'] = st.text_input("Per Unit", value=current_unit, placeholder="e.g., kWh, m2")

    elif attr_type == "SimpleValue":
        # SimpleValue can either be a text value OR a file reference
        current_value = current_data.get('value', '')

        # Determine current type based on value (if it looks like a filename, default to file reference)
        is_file_ref = current_value and ('.' in current_value or '/' in current_value)
        default_type = "File Reference" if is_file_ref else "Text Value"

        value_type = st.radio(
            "Value Type:",
            options=["Text Value", "File Reference"],
            index=1 if default_type == "File Reference" else 0,
            key=f"{attr_name}_edit_simplevalue_type",
            horizontal=True
        )

        if value_type == "File Reference":
            # Show file reference with upload option (similar to creation form)
            st.caption("📄 Use file upload below or enter filename directly")
            data['value'] = st.text_input(
                "Filename",
                value=current_value,
                placeholder="Enter filename or upload below",
                help="File reference for this attribute"
            )
        else:
            # Text value
            data['value'] = st.text_input(
                "Value",
                value=current_value,
                placeholder="Enter value"
            )

    elif attr_type == "Identifier":
        data['identifier_value'] = st.text_input(
            "Identifier Value",
            value=current_data.get('identifier_value', ''),
            placeholder="e.g., ID-12345"
        )

    elif attr_type == "CustomPhysicalRatio":
        available_units = st.session_state.get('replica_available_units', [])
        if constraints and constraints.ratio_numerator_unit and constraints.ratio_denominator_unit:
            st.caption(f"Ontology defined unit: **{constraints.ratio_numerator_unit} / {constraints.ratio_denominator_unit}**")
        elif constraints and constraints.default_unit:
            st.caption(f"Ontology default unit: **{constraints.default_unit}**")
        # Pre-fill from stored value (format: "Num/Den"), falling back to ontology-defined units
        existing_unit = current_data.get('custom_unit', '')
        parts = existing_unit.split('/', 1)
        existing_num = parts[0] if len(parts) > 0 else ''
        existing_den = parts[1] if len(parts) > 1 else ''
        if not existing_num and constraints and constraints.ratio_numerator_unit:
            existing_num = constraints.ratio_numerator_unit
        if not existing_den and constraints and constraints.ratio_denominator_unit:
            existing_den = constraints.ratio_denominator_unit
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            data['value'] = st.number_input("Value", value=float(current_data.get('value', 0.0)), format="%.4f")
        if available_units:
            num_idx = available_units.index(existing_num) if existing_num in available_units else 0
            den_idx = available_units.index(existing_den) if existing_den in available_units else 0
            with col2:
                numerator_unit = st.selectbox(
                    "Numerator unit", options=available_units, index=num_idx,
                    key=f"cpr_num_edit_{attr_name}"
                )
            with col3:
                denominator_unit = st.selectbox(
                    "/ Denominator unit", options=available_units, index=den_idx,
                    key=f"cpr_den_edit_{attr_name}"
                )
            data['custom_unit'] = f"{numerator_unit}/{denominator_unit}"
        else:
            with col2:
                data['custom_unit'] = st.text_input(
                    "Unit (num/den)", value=existing_unit, placeholder="e.g., KiloW-HR/M2",
                    help="No QUDT units loaded — enter manually"
                )

    elif attr_type == "Curve":
        st.write("**Curve Data**")
        col1, col2 = st.columns(2)
        available_units = st.session_state.get('replica_available_units', [])

        current_x_unit = current_data.get('x_unit', '')
        current_y_unit = current_data.get('y_unit', '')

        with col1:
            if available_units:
                if current_x_unit and current_x_unit not in available_units:
                    available_units_x = [current_x_unit] + available_units
                else:
                    available_units_x = available_units
                default_index = available_units_x.index(current_x_unit) if current_x_unit in available_units_x else 0
                data['x_unit'] = st.selectbox("X Unit", options=available_units_x, index=default_index)
            else:
                data['x_unit'] = st.text_input("X Unit", value=current_x_unit, placeholder="e.g., m")

        with col2:
            if available_units:
                if current_y_unit and current_y_unit not in available_units:
                    available_units_y = [current_y_unit] + available_units
                else:
                    available_units_y = available_units
                default_index = available_units_y.index(current_y_unit) if current_y_unit in available_units_y else 0
                data['y_unit'] = st.selectbox("Y Unit", options=available_units_y, index=default_index)
            else:
                data['y_unit'] = st.text_input("Y Unit", value=current_y_unit, placeholder="e.g., kW")

        data['data_points'] = st.text_area(
            "Data Points",
            value=current_data.get('data_points', ''),
            placeholder="[(0,0);(1,10);(2,20)]",
            help="Format: [(x1,y1);(x2,y2);...]"
        )

    elif attr_type == "Resource":
        data['data_path'] = st.text_input(
            "Resource Path",
            value=current_data.get('data_path', ''),
            placeholder="e.g., /data/file.csv, https://..."
        )

    elif attr_type == "Geospatial":
        # Geospatial can be a text value (coordinates, WKT, etc.) OR a file reference (GeoJSON, Shapefile, etc.)
        current_value = current_data.get('value', '')

        # Determine current type based on value
        is_file_ref = current_value and ('.' in current_value or '/' in current_value)
        default_type = "File Reference" if is_file_ref else "Text/Coordinates"

        value_type = st.radio(
            "Geospatial Value Type:",
            options=["Text/Coordinates", "File Reference"],
            index=1 if default_type == "File Reference" else 0,
            key=f"{attr_name}_edit_geospatial_type",
            horizontal=True
        )

        if value_type == "Text/Coordinates":
            data['value'] = st.text_area(
                "Geospatial Value",
                value=current_value,
                placeholder="e.g., POINT(8.5417 47.3769), WKT, GeoJSON",
                help="Enter coordinates, WKT, or GeoJSON directly"
            )
        else:
            # File reference
            st.caption("🗺️ Use file upload above or enter filename directly")
            data['value'] = st.text_input(
                "Filename",
                value=current_value,
                placeholder="Enter filename or upload above",
                help="GeoJSON, Shapefile, or other geospatial file"
            )

    else:
        data['value'] = st.text_input("Value", value=str(current_data.get('value', '')), placeholder="Enter value")

    return data


def render_attributes_display(instance):
    """Display configured attributes"""

    for attr_name, attr_data in instance.attributes.items():
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 4, 1, 1])

            with col1:
                st.write(f"**{attr_name}**")
                st.caption(f"Type: {attr_data.get('type', 'Unknown')}")

            with col2:
                render_attribute_value_display(attr_data)

            with col3:
                if st.button("✏️ Edit", key=f"edit_attr_{instance.id}_{attr_name}"):
                    st.session_state.editing_attribute = (instance.id, attr_name)
                    st.rerun()

            with col4:
                if st.button("🗑️", key=f"del_attr_{instance.id}_{attr_name}"):
                    del instance.attributes[attr_name]
                    if st.session_state.editing_attribute and st.session_state.editing_attribute[1] == attr_name:
                        st.session_state.editing_attribute = None
                    st.rerun()

            st.write("---")


def render_attribute_value_display(attr_data: Dict[str, Any]):
    """Display attribute value based on type"""
    attr_type = attr_data.get('type', 'Unknown')

    if attr_type == "Physical":
        value = attr_data.get('value', 0)
        unit = attr_data.get('unit', '')

        # Check if this is a time series only attribute (no static value)
        has_timeseries = (
                attr_data.get('historic_reference') or
                attr_data.get('future_reference') or
                attr_data.get('live_reference')
        )

        if value and value != 0:
            st.write(f"Value: {value} {unit}")
        elif has_timeseries:
            st.write(f"⏱️ Time series only (no static value)")
        else:
            st.write(f"Value: {value} {unit}")

        # Show time series info if present
        if attr_data.get('historic_reference'):
            st.caption(f"📊 Historic: {attr_data['historic_reference']}")
        if attr_data.get('future_reference'):
            st.caption(f"🔮 Future: {attr_data['future_reference']}")
        if attr_data.get('live_reference'):
            st.caption(f"⚡ Live: {attr_data['live_reference']}")

    elif attr_type == "Categorical":
        st.write(f"Category: {attr_data.get('category_value', 'N/A')}")

    elif attr_type == "Event":
        st.write(f"{attr_data.get('temporal_value', 'N/A')}")
        st.caption(f"Precision: {attr_data.get('temporal_precision', 'Unknown')}")

    elif attr_type in ["SimpleCost", "UnitBasedCost"]:
        value = attr_data.get('value', 0)
        currency = attr_data.get('currency', '')
        unit = attr_data.get('unit', '')
        if unit:
            st.write(f"{value} {currency}/{unit}")
        else:
            st.write(f"{value} {currency}")

    elif attr_type == "Curve":
        st.caption(f"X: {attr_data.get('x_unit', 'N/A')}, Y: {attr_data.get('y_unit', 'N/A')}")
        st.caption(f"Points: {attr_data.get('data_points', 'N/A')}")

    elif attr_type == "Resource":
        st.caption(f"Path: {attr_data.get('data_path', 'N/A')}")

    elif attr_type == "SimpleValue":
        st.write(f"Value: {attr_data.get('value', 'N/A')}")

    elif attr_type == "CustomPhysicalRatio":
        unit = attr_data.get('custom_unit', '')
        st.write(f"Value: {attr_data.get('value', 'N/A')} [{unit}]")

    elif attr_type == "Identifier":
        st.write(f"ID: {attr_data.get('identifier_value', 'N/A')}")

    if attr_data.get('datasource'):
        st.caption(f"Source: {attr_data['datasource']}")


def render_annotations_display(instance):
    """Display annotations"""
    for key, value in instance.annotations.items():
        col1, col2 = st.columns([1, 4])
        with col1:
            st.write(f"**{key}:**")
        with col2:
            st.write(value)