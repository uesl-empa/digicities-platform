# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder_main.py
"""
ENHANCED Replica Builder - Build Digital Replica Instance Graphs
Creates classes_and_attributes and system_description named graphs
NOW WITH ONTOLOGY CONSTRAINTS ENFORCEMENT
"""
import streamlit as st
from typing import Dict, List, Any, Optional

# Import enhanced submodules
try:
    from components.replica_builder.replica_ontology_loader import (
        load_ontology_from_graphdb,
        show_ontology_status
    )
    from components.replica_builder.replica_instance_manager import (
        tab_manage_instances,
        initialize_instance_state
    )
    from components.replica_builder.replica_attribute_manager import (
        tab_manage_attributes
    )
    from components.replica_builder.replica_graph_loader import (
        load_existing_graphs,
        show_existing_graphs_status
    )
    from components.replica_builder.replica_link_manager import (
        tab_manage_links
    )
    from components.replica_builder.replica_ttl_generator import (
        tab_preview_and_export
    )
    from components.replica_builder.replica_service_guide import (
        show_service_guide_expander
    )
    from components.replica_builder.replica_excel_importer import (
        tab_excel_import
    )

    SUBMODULES_AVAILABLE = True
except ImportError as e:
    SUBMODULES_AVAILABLE = False
    st.error(f"Replica Builder submodules not available: {e}")


def initialize_replica_builder_state():
    """Initialize session state for replica builder"""

    # Project configuration
    if 'replica_project_uri' not in st.session_state:
        current_workspace = st.session_state.get('current_workspace', {})
        workspace_name = current_workspace.get('name', 'MyProject').replace(' ', '_')
        st.session_state.replica_project_uri = f"https://digicities.info/proj/{workspace_name}"

    if 'replica_uri_mode' not in st.session_state:
        st.session_state.replica_uri_mode = "default"

    # Ontology data
    if 'replica_ontology_components' not in st.session_state:
        st.session_state.replica_ontology_components = {}

    if 'replica_ontology_attributes' not in st.session_state:
        st.session_state.replica_ontology_attributes = {}

    if 'replica_component_attribute_mappings' not in st.session_state:
        st.session_state.replica_component_attribute_mappings = {}

    # NEW: Named individuals for categorical attributes
    if 'replica_named_individuals' not in st.session_state:
        st.session_state.replica_named_individuals = {}

    # NEW: Available QUDT units
    if 'replica_available_units' not in st.session_state:
        st.session_state.replica_available_units = []

    # Instance data
    if 'replica_instances' not in st.session_state:
        st.session_state.replica_instances = []

    # Links data
    if 'replica_links' not in st.session_state:
        st.session_state.replica_links = []

    # Existing graph data
    if 'replica_existing_classes_graph' not in st.session_state:
        st.session_state.replica_existing_classes_graph = None

    if 'replica_existing_system_graph' not in st.session_state:
        st.session_state.replica_existing_system_graph = None

    # Graph mode
    if 'replica_graph_mode' not in st.session_state:
        st.session_state.replica_graph_mode = "append"

    # Initialize submodule states
    if SUBMODULES_AVAILABLE:
        initialize_instance_state()


def replica_builder(client):
    """Main Replica Builder interface"""

    if not client:
        st.error("No Triplestore client available. Please ensure you're connected to a workspace.")
        st.info("Triplestore connection is required to load the ontology and upload graphs.")
        return

    initialize_replica_builder_state()

    st.header("Digital Replica Builder")
    st.markdown("Build **ontology-constrained** instance graphs for classes_and_attributes and system_description")

    # Check if ontology is loaded to determine UI state
    ontology_loaded = bool(st.session_state.replica_ontology_components)

    # Auto-load ontology if not already loaded
    if not ontology_loaded:
        with st.spinner("🔄 Loading ontology from Triplestore..."):
            if load_ontology_from_graphdb(client):
                st.success("✅ Ontology loaded successfully!")
                st.info(f"Loaded {len(st.session_state.replica_named_individuals)} categorical types with named individuals")
                st.session_state.replica_ontology_auto_loaded = True
                st.rerun()
            else:
                st.error("❌ Failed to auto-load ontology from Triplestore")
                st.warning("Please check your Triplestore connection and ensure the ontology graph exists.")

                # Show manual reload button as fallback
                if st.button("🔄 Retry Loading Ontology", type="primary"):
                    st.rerun()
                return

    # Project Configuration Section - collapsed after ontology loads
    with st.expander("⚙️ Project Configuration", expanded=False):
        render_project_configuration()

    # Once ontology is loaded, show compact status and working area
    st.success("✅ Setup Complete - Ready to build your digital replica!")

    # Show ontology status in compact form (already has its own expander)
    show_ontology_status()

    # Auto-load existing instances + links from GraphDB once per workspace, so
    # the builder opens already populated with the workspace's digital replica
    # (no manual "Load Graphs" / "Populate Instances" clicks needed).
    current_id = (st.session_state.get("current_workspace") or {}).get("id")
    if st.session_state.get("replica_existing_auto_loaded_ws") != current_id:
        load_existing_graphs(client, populate_instances=True)
        st.session_state.replica_existing_auto_loaded_ws = current_id

    # Load existing graphs status (already has its own expander)
    show_existing_graphs_status(client)

    # Show service guide for building components
    show_service_guide_expander()

    st.markdown("---")

    # Main tabs - now more prominent
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📦 Instances",
        "🏷️ Attributes",
        "🔗 Links",
        "📊 Excel Import",
        "👁️ Preview & Export",
        "❓ Help"
    ])

    with tab1:
        tab_manage_instances()

    with tab2:
        tab_manage_attributes()

    with tab3:
        tab_manage_links()

    with tab4:
        tab_excel_import()

    with tab5:
        tab_preview_and_export(client)

    with tab6:
        show_help_tab()


def render_project_configuration():
    """Render project configuration UI"""

    st.write("### Project URI Configuration")

    st.session_state.replica_project_uri = st.text_input(
        "Project Base URI",
        value=st.session_state.replica_project_uri,
        help="Base URI for all instances created in this project",
        key="project_uri_input"
    )

    # Show example URI
    st.caption(f"Example instance URI: `{st.session_state.replica_project_uri}/ComponentType/InstanceID`")

    st.write("---")

    # Graph mode selection
    st.write("### Graph Update Mode")

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
                "Append to Existing",
                type="primary" if st.session_state.replica_graph_mode == "append" else "secondary",
                use_container_width=True
        ):
            st.session_state.replica_graph_mode = "append"
            st.rerun()

    with col2:
        if st.button(
                "Replace Existing",
                type="primary" if st.session_state.replica_graph_mode == "replace" else "secondary",
                use_container_width=True
        ):
            st.session_state.replica_graph_mode = "replace"
            st.rerun()

    if st.session_state.replica_graph_mode == "append":
        st.info("New instances will be **added** to existing graphs")
    else:
        st.warning("Existing graphs will be **replaced** with new content")


def show_help_tab():
    """Show help and guidance"""
    st.subheader("Replica Builder Help")

    st.write("### Overview")
    st.write("""
    The Replica Builder helps you create **ontology-constrained** instance graphs for your digital replica:

    - **classes_and_attributes** - Component instances with their attribute values
    - **system_description** - Relationships between components

    **NEW:** All attributes are now constrained by the ontology:
    - Units must match ontology defaults
    - Categorical values must be named individuals from the ontology
    - Attribute types are enforced
    """)

    with st.expander("Getting Started", expanded=True):
        st.write("""
        **Step 1: Configure Project**
        - Set your project base URI
        - Select append or replace mode

        **Step 2: Load Ontology**
        - Click "Load Ontology" to fetch component types from Triplestore
        - The ontology defines:
          - Available component types
          - Available attributes for each component
          - Default units for physical/dynamic attributes
          - Named individuals for categorical attributes
          - All constraints

        **Step 3: Create Instances**
        - Go to the Instances tab
        - Select a component type
        - Add instances with unique IDs

        **Step 4: Configure Attributes**
        - Go to the Attributes tab
        - Select an instance
        - Add attributes (constrained by ontology)
        - Units and categories will be pre-populated from ontology
        """)

    with st.expander("Using the Service Guide", expanded=False):
        st.write("""
        **What is the Service Guide?**
        The Service Guide helps you build replicas that are compatible with specific services.
        It shows you exactly what components and attributes each service requires.

        **How to Use It:**
        1. Expand the "📋 Service Guide" section (below the ontology status)
        2. Select a service from the dropdown
        3. Review the required component types and attributes
        4. Follow the checklist to build your replica

        **Service Requirements Display:**
        - ✓ Green checkmarks = Component/attribute exists in ontology
        - ⚠ Warning symbols = Not defined in ontology (may need custom implementation)

        **Building for a Service:**
        - Create instances of all required component types
        - Add all required attributes to each instance
        - Create the required links between components
        - The service guide ensures your replica has everything the service needs

        **Note:** Services are read from the workspace `services/` folder (where the Scenario Builder's "Save to Workspace" writes them), or from NextCloud `global/services/` when configured.
        """)

    with st.expander("Ontology Constraints", expanded=False):
        st.write("""
        **Physical & Dynamic Attributes:**
        - Units are constrained to ontology defaults
        - If an attribute has `dici_onto:hasDefaultUnit`, that unit will be pre-selected
        - You can only choose from QUDT units defined in the ontology

        **Categorical Attributes:**
        - Categories are constrained to named individuals
        - Only named individuals defined in the ontology are available
        - Example: BuildingType can only be "MFH", "Office", etc.

        **Event Attributes:**
        - Temporal precision is enforced (Year, YearMonth, Date, DateTime)
        - Proper XSD types are used in TTL generation

        **Cost Attributes:**
        - Currency codes are standardized
        - Units for UnitBasedCost come from ontology
        """)

    with st.expander("Working with Attributes", expanded=False):
        st.write("""
        **Supported Attribute Types:**
        - **Physical** - Numeric values with units (e.g., Power: 100 kW)
        - **Dynamic** - Time series data (Historic/Live/Future)
        - **Categorical** - Category values (named individuals)
        - **Event** - Temporal data (dates, years)
        - **SimpleCost** - Cost without units
        - **UnitBasedCost** - Cost per unit
        - **Curve** - Data points for curves
        - **Resource** - File paths/URLs
        - **SimpleValue** - Basic values without units
        - **CustomPhysicalRatio** - Custom unit expressions
        - **Identifier** - Unique identifiers
        - **Annotation** - Text annotations

        All attributes are constrained to those defined in the ontology for each component type.
        """)

    with st.expander("Creating Links", expanded=False):
        st.write("""
        **System Description Links:**
        - Links define relationships between components
        - Only subproperties of `dici_onto:linksComponent` from the ontology are available
        - Example: `locatedIn`, `connectedTo`, `supplies`

        **How to Create Links:**
        1. Go to the Links tab
        2. Select source and target components
        3. Choose a link property from the ontology
        4. Add the link

        Links are stored in the system_description graph.
        """)

    with st.expander("Preview and Export", expanded=False):
        st.write("""
        **Before Uploading:**
        - Review the generated TTL in the Preview tab
        - Check for validation errors
        - Download TTL for backup
        - TTL format matches the exact structure from Excel imports

        **Upload to Triplestore:**
        - Click "Upload to Triplestore" to create/update graphs
        - Choose append or replace mode
        - Named graphs created:
          - `<http://classes_and_attributes>`
          - `<http://system_description>`
        """)

    with st.expander("Validation & Quality", expanded=False):
        st.write("""
        **Automatic Validation:**
        - Units are validated against ontology defaults
        - Categorical values are validated against named individuals
        - TTL syntax is validated before upload
        - Proper XSD types are enforced

        **Quality Checks:**
        - All instances must have a component type from ontology
        - All attributes must be defined in ontology for that component
        - Units must match QUDT vocabulary
        - Named individuals must exist in ontology
        """)


if __name__ == "__main__":
    replica_builder(None)