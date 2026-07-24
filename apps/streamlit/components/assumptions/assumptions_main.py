# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/assumptions/assumptions_main.py
"""
Assumptions-Based Scenario Modification Module
Integrated with NextCloud workspace and scenario builder infrastructure
Now includes manual modification alongside predefined assumptions
"""
import streamlit as st
from typing import Optional
from datetime import datetime


def assumptions_module(client):
    """
    Main entry point for the Assumptions module
    Integrates with existing TTL loader and scenario export infrastructure
    """
    st.title("🎯 Assumptions-Based Scenario Modification")

    # Initialize session state
    initialize_assumptions_session_state()

    # Check if we have a GraphDB client
    if not client:
        st.warning("⚠️ Triplestore client not available. Some features may be limited.")
        st.info("💡 You can still work with workspace TTL files and data products")

    # Main tabs - NOW WITH MANUAL MODIFICATION
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📂 Load Baseline",
        "🎯 Apply Assumptions",
        "✏️ Manual Modification",
        "📊 View Scenarios",
        "💾 Export Results"
    ])

    with tab1:
        tab_load_baseline()

    with tab2:
        tab_apply_assumptions()

    with tab3:
        tab_manual_modification()

    with tab4:
        tab_view_scenarios()

    with tab5:
        tab_export_results()


def initialize_assumptions_session_state():
    """Initialize session state for assumptions module"""
    if 'assumptions_baseline_scenario' not in st.session_state:
        st.session_state.assumptions_baseline_scenario = None

    if 'assumptions_baseline_components' not in st.session_state:
        st.session_state.assumptions_baseline_components = []

    if 'assumptions_generated_scenarios' not in st.session_state:
        st.session_state.assumptions_generated_scenarios = []

    if 'assumptions_predefined' not in st.session_state:
        from backend.assumptions.assumption_types import create_predefined_assumptions
        st.session_state.assumptions_predefined = create_predefined_assumptions()

    if 'assumptions_baseline_namespace' not in st.session_state:
        st.session_state.assumptions_baseline_namespace = 'https://digicities.info/proj/REFORMERS'

    # NEW: Manual modification session state
    if 'manual_modifications_pending' not in st.session_state:
        st.session_state.manual_modifications_pending = {}


def tab_load_baseline():
    """Tab 1: Load baseline scenario from workspace scenarios or upload"""
    st.subheader("📂 Load Baseline Scenario")

    st.write("""
    Load a baseline scenario file to use as the starting point for assumption-based modifications.
    Scenarios are TTL files created by the Scenario Builder module.
    """)

    # Shared loader: baseline can come from workspace files, the knowledge
    # graph, or an upload.
    from components.scenario_loader import render_scenario_loader

    current_workspace = st.session_state.get('current_workspace')
    workspace_id = current_workspace['id'] if current_workspace else 'workspace'

    selected = render_scenario_loader(
        client=st.session_state.get("workspace_client"),
        key_prefix="assumptions_baseline",
        allow_multiple=False,
    )

    if selected and st.button("✅ Load as baseline", type="primary", key="assumptions_load_btn"):
        item = selected[0]
        with st.spinner(f"Loading {item['name']}..."):
            parsed = parse_scenario_ttl_with_builder(item['content'], workspace_id, item['name'])
            if parsed and parsed.get('components'):
                st.session_state.assumptions_baseline_scenario = parsed
                st.session_state.assumptions_baseline_components = parsed['components']
                st.session_state.assumptions_baseline_namespace = parsed.get(
                    'namespace', f'https://digicities.info/proj/{workspace_id}'
                )
                st.success(
                    f"✅ Loaded scenario: **{parsed['scenario_name']}** "
                    f"({len(parsed['components'])} components)"
                )
                st.rerun()
            else:
                err = (parsed or {}).get('error', 'no components found')
                st.error(f"❌ Could not parse scenario: {err}")

    # Show current baseline status
    show_baseline_status()


def load_from_workspace_scenarios():
    """Load baseline from workspace scenarios folder (where scenario_builder saves)"""
    st.write("### 📁 Load from Workspace Scenarios")

    try:
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            st.error("❌ No workspace selected")
            return

        workspace_id = current_workspace['id']

        # Read scenarios from the active workspace's storage (local FS,
        # NextCloud, or S3) instead of a hard-coded NextCloud WebDAV call.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is None:
            st.error("❌ No active workspace storage. Open a workspace first.")
            return

        # Canonical workspace layout stores scenarios under `scenarios/`.
        scenarios_folder = "scenarios"

        try:
            rels = storage.glob(f"{scenarios_folder}/*.ttl") if storage.exists(scenarios_folder) else []
            ttl_files = sorted(r.rsplit("/", 1)[-1] for r in rels)

            if not ttl_files:
                st.info("ℹ️ No scenario files found in graph/scenarios folder")
                st.caption("💡 Create scenarios using Scenario Builder first, or upload a scenario file")

                # Show helpful info
                with st.expander("📋 About Scenario Files"):
                    st.write("""
                    **Where are scenarios stored?**
                    - Scenarios created by Scenario Builder are saved to `graph/scenarios/` in your workspace
                    - Each scenario is a TTL file containing component definitions and relationships

                    **How to create scenarios:**
                    1. Go to the **Scenario Builder** module
                    2. Build your scenario by adding components
                    3. Export to workspace - it will be saved to graph/scenarios/
                    4. Return here to load it as a baseline for assumptions
                    """)
                return

            st.success(f"✅ Found {len(ttl_files)} scenario files")

            # Let user select a scenario file
            selected_file = st.selectbox(
                "Select scenario file:",
                ttl_files,
                format_func=lambda x: x.replace('.ttl', '').replace('_', ' ')
            )

            if st.button("✅ Load Selected Scenario", type="primary", key="load_scenario_btn"):
                with st.spinner(f"Loading {selected_file}..."):
                    # Read the scenario file from workspace storage
                    file_path = f"{scenarios_folder}/{selected_file}"
                    ttl_content = storage.read_text(file_path)

                    if ttl_content:
                        # Parse the scenario using scenario_builder's TTL parser
                        parsed_scenario = parse_scenario_ttl_with_builder(ttl_content, workspace_id, selected_file)

                        if parsed_scenario and parsed_scenario.get('components'):
                            # Store in session state
                            st.session_state.assumptions_baseline_scenario = parsed_scenario
                            st.session_state.assumptions_baseline_components = parsed_scenario['components']
                            st.session_state.assumptions_baseline_namespace = parsed_scenario.get(
                                'namespace',
                                f'https://digicities.info/proj/{workspace_id}'
                            )

                            st.success(f"✅ Loaded scenario: **{parsed_scenario['scenario_name']}**")

                            # Show summary
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Components", len(parsed_scenario['components']))
                            with col2:
                                component_types = set(c['type'] for c in parsed_scenario['components'])
                                st.metric("Component Types", len(component_types))
                            with col3:
                                total_attrs = sum(len(c.get('attributes', {})) for c in parsed_scenario['components'])
                                st.metric("Attributes", total_attrs)

                            st.rerun()
                        else:
                            error_msg = parsed_scenario.get('error', 'Unknown parsing error')
                            st.error(f"❌ Could not parse scenario file: {error_msg}")

                            # Show debug info
                            with st.expander("🔍 Parser Debug Info"):
                                st.write("**Parsed data:**")
                                st.json(parsed_scenario)
                    else:
                        st.error("❌ Could not download scenario file")

        except Exception as e:
            st.error(f"❌ Error accessing scenarios folder: {str(e)}")

            # Show helpful debug info
            with st.expander("🔧 Troubleshooting"):
                st.write("""
                **Common issues:**
                1. The `graph/scenarios` folder doesn't exist in your workspace yet
                2. No scenarios have been created with Scenario Builder
                3. Network or permission issues

                **Solutions:**
                1. Create a scenario using Scenario Builder and export it
                2. Or upload a scenario file manually using the upload option
                """)

                st.write("**Debug details:**")
                st.write(f"- Workspace ID: `{workspace_id}`")
                st.write(f"- Full path: `{workspace_id}/{scenarios_folder}/`")
                st.write(f"- Error: `{str(e)}`")

    except Exception as e:
        st.error(f"❌ Error loading workspace scenarios: {str(e)}")
        if st.checkbox("Show debug info", key="debug_main"):
            st.exception(e)


def parse_scenario_ttl_with_builder(ttl_content: str, workspace_id: str, filename: str):
    """
    Parse scenario TTL using scenario_builder's infrastructure
    This ensures all attributes are extracted correctly with proper types
    """
    try:
        from rdflib import Graph

        # Create and parse graph using rdflib (same as scenario_builder)
        graph = Graph()
        graph.parse(data=ttl_content, format="turtle")

        # Use the TTL loader to extract components with full attribute support
        from components.scenario_builder.ttl_use_case_loader import NextCloudTTLUseCaseLoader

        # Create a temporary loader instance
        loader = NextCloudTTLUseCaseLoader(workspace_id=workspace_id)

        # Extract components using the proven extraction method
        components_by_type = loader.extract_components_from_graph(graph, f"scenario_{filename}")

        # Flatten into a single list, keeping only genuine components. The loader
        # indexes every rdf:type, so attribute nodes (BuildingAge, GroundFloorArea,
        # …), ComponentLinks, the Scenario, and categorical value-classes also come
        # back here. Real components are the ones that own attributes; drop the rest
        # so the "Select Components to Modify" list shows only replica components.
        all_components = []
        for comp_type, components in components_by_type.items():
            if comp_type in ('ComponentLink', 'Scenario'):
                continue
            for c in components:
                real_attrs = {
                    k: v for k, v in (c.get('attributes') or {}).items()
                    if k not in ('URI', 'label') and isinstance(v, dict)
                }
                if real_attrs:
                    all_components.append(c)

        if not all_components:
            return None

        # Extract scenario metadata from graph
        from rdflib.namespace import RDF, RDFS
        from rdflib import Namespace

        DICI = Namespace("https://digicities.info/ontology#")

        scenario_uri = None
        scenario_name = None
        namespace = None
        service = None
        workspace = None

        # Find scenario declaration
        for s, p, o in graph.triples((None, RDF.type, DICI.Scenario)):
            scenario_uri = str(s)
            # Extract namespace from URI
            namespace = '/'.join(scenario_uri.split('/')[:-1])
            # Get scenario name from label or URI
            for label in graph.objects(s, RDFS.label):
                scenario_name = str(label)
            # Carry the service + workspace labels so a generated scenario stays
            # attached to the same service (else the submission filter hides it).
            for svc in graph.objects(s, DICI.builtForService):
                service = str(svc)
            for ws in graph.objects(s, DICI.createdInWorkspace):
                workspace = str(ws)
            break

        if not scenario_name:
            # Use filename as fallback
            scenario_name = filename.replace('.ttl', '').replace('_', ' ')

        if not namespace:
            namespace = f'https://digicities.info/proj/{workspace_id}'

        # Extract component links if present
        component_links = []
        for s, p, o in graph.triples((None, RDF.type, DICI.ComponentLink)):
            link_props = {}
            for pred, obj in graph.predicate_objects(s):
                pred_str = str(pred)
                if 'hasInputEntity' in pred_str or 'linksInputyEntityTo' in pred_str:
                    link_props[pred_str.split('#')[-1]] = str(obj)

            if link_props:
                component_links.append({
                    'uri': str(s),
                    'properties': link_props
                })

        return {
            'scenario_uri': scenario_uri or f"{namespace}/baseline_scenario",
            'scenario_name': scenario_name,
            'namespace': namespace,
            'components': all_components,
            'component_links': component_links,
            'service': service,
            'workspace': workspace or workspace_id,
            'source': 'workspace_ttl'
        }

    except Exception as e:
        st.error(f"Error parsing TTL: {str(e)}")
        return None


def load_from_upload():
    """Load baseline from uploaded TTL file"""
    st.write("### 📤 Upload TTL File")

    uploaded_file = st.file_uploader(
        "Upload baseline scenario TTL file",
        type=['ttl', 'txt'],
        help="Upload a TTL file containing scenario components"
    )

    if uploaded_file is not None:
        ttl_content = uploaded_file.read().decode('utf-8')

        try:
            current_workspace = st.session_state.get('current_workspace')
            workspace_id = current_workspace['id'] if current_workspace else 'uploaded'

            # Parse using scenario_builder's infrastructure
            parsed_scenario = parse_scenario_ttl_with_builder(
                ttl_content,
                workspace_id,
                uploaded_file.name
            )

            if parsed_scenario and parsed_scenario.get('components'):
                # Show preview
                st.success(f"✅ Successfully parsed: **{parsed_scenario['scenario_name']}**")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Components", len(parsed_scenario['components']))
                with col2:
                    component_types = set(comp['type'] for comp in parsed_scenario['components'])
                    st.metric("Component Types", len(component_types))
                with col3:
                    total_attrs = sum(len(comp.get('attributes', {})) for comp in parsed_scenario['components'])
                    st.metric("Total Attributes", total_attrs)

                # Load button
                if st.button("✅ Load as Baseline Scenario", type="primary"):
                    st.session_state.assumptions_baseline_scenario = parsed_scenario
                    st.session_state.assumptions_baseline_components = parsed_scenario['components']
                    st.session_state.assumptions_baseline_namespace = parsed_scenario.get(
                        'namespace',
                        f'https://digicities.info/proj/{workspace_id}'
                    )
                    st.success("✅ Baseline scenario loaded!")
                    st.rerun()
            else:
                st.error("❌ Could not parse TTL file - no components found")

        except Exception as e:
            st.error(f"❌ Error parsing TTL: {str(e)}")
            if st.checkbox("Show debug info", key="upload_debug"):
                st.exception(e)


def show_baseline_status():
    """Show current baseline scenario status"""
    if st.session_state.assumptions_baseline_scenario:
        st.markdown("---")
        st.write("### 📊 Current Baseline Scenario")

        baseline = st.session_state.assumptions_baseline_scenario

        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"**Name:** {baseline['scenario_name']}")
            st.write(f"**Source:** {baseline.get('source', 'unknown')}")
            st.write(f"**Namespace:** `{st.session_state.assumptions_baseline_namespace}`")
            st.write(f"**Components:** {len(baseline['components'])}")

            # Component type breakdown
            component_types = {}
            for comp in baseline['components']:
                comp_type = comp['type']
                component_types[comp_type] = component_types.get(comp_type, 0) + 1

            if component_types:
                st.write("**Component Types:**")
                for comp_type, count in sorted(component_types.items()):
                    st.caption(f"  • {comp_type}: {count}")

        with col2:
            if st.button("🗑️ Clear Baseline"):
                st.session_state.assumptions_baseline_scenario = None
                st.session_state.assumptions_baseline_components = []
                st.session_state.assumptions_generated_scenarios = []
                st.rerun()


def tab_apply_assumptions():
    """Tab 2: Apply assumptions to baseline scenario"""
    st.subheader("🎯 Apply Assumptions")

    if not st.session_state.assumptions_baseline_scenario:
        st.warning("⚠️ Please load a baseline scenario first (Tab 1)")
        return

    # Show the full assumption interface directly (no imports needed)
    show_assumption_application_interface()


def show_assumption_application_interface():
    """Complete interface for applying assumptions - integrated directly"""

    assumptions = st.session_state.assumptions_predefined
    baseline_components = st.session_state.assumptions_baseline_components

    st.write("""
    Apply predefined assumptions to modify your baseline scenario. 
    Assumptions can target specific component attributes and create modified scenarios.
    """)

    # Filtering section
    st.write("### 🔍 Filter Assumptions")

    from backend.assumptions.assumption_types import (
        get_supported_attribute_categories,
        get_supported_component_types
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        categories = ['All'] + get_supported_attribute_categories()
        selected_category = st.selectbox(
            "Attribute Category:",
            categories,
            key="assumption_category_filter"
        )

    with col2:
        component_types = ['All'] + get_supported_component_types()
        selected_component = st.selectbox(
            "Component Type:",
            component_types,
            key="assumption_component_filter"
        )

    with col3:
        assumption_types = ['All', 'single', 'series']
        selected_type = st.selectbox(
            "Assumption Type:",
            assumption_types,
            key="assumption_type_filter"
        )

    # Apply filters
    filtered_assumptions = assumptions

    if selected_category != 'All':
        filtered_assumptions = [a for a in filtered_assumptions if a.get('attribute_category') == selected_category]

    if selected_component != 'All':
        filtered_assumptions = [a for a in filtered_assumptions if a.get('target_component') == selected_component]

    if selected_type != 'All':
        filtered_assumptions = [a for a in filtered_assumptions if a.get('type') == selected_type]

    if not filtered_assumptions:
        st.info("ℹ️ No assumptions match the current filters. Adjust your criteria.")
        return

    # Show compatibility overview
    from backend.assumptions.assumption_types import validate_assumption_compatibility

    compatible_count = sum(1 for a in filtered_assumptions
                           if validate_assumption_compatibility(a, baseline_components)[0])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Filtered Assumptions", len(filtered_assumptions))
    with col2:
        st.metric("Compatible", compatible_count)
    with col3:
        st.metric("Incompatible", len(filtered_assumptions) - compatible_count)

    # Assumption selection
    st.write("### 🎯 Select and Apply Assumption")

    assumption_options = []
    compatibility_status = []

    for assumption in filtered_assumptions:
        is_compatible, _ = validate_assumption_compatibility(assumption, baseline_components)

        category_emoji = {
            'physical': '⚙️',
            'cost': '💰',
            'geospatial': '🌍',
            'curve': '📈',
            'categorical': '🏷️',
            'dynamic': '📊'
        }.get(assumption.get('attribute_category', 'unknown'), '📋')

        type_emoji = '🎯' if assumption['type'] == 'single' else '📊'
        status_emoji = '✅' if is_compatible else '❌'

        option_text = f"{status_emoji} {category_emoji} {type_emoji} {assumption['name']}"
        assumption_options.append(option_text)
        compatibility_status.append(is_compatible)

    selected_idx = st.selectbox(
        "Select Assumption:",
        range(len(assumption_options)),
        format_func=lambda x: assumption_options[x],
        key="assumption_selector"
    )

    if selected_idx is not None:
        selected_assumption = filtered_assumptions[selected_idx]
        is_compatible = compatibility_status[selected_idx]

        # Show assumption details
        st.write("### 📋 Assumption Details")

        col1, col2 = st.columns([2, 1])

        with col1:
            st.write(f"**Name:** {selected_assumption['name']}")
            st.write(f"**Description:** {selected_assumption['description']}")
            st.write(f"**Target:** `{selected_assumption['target_component']}.{selected_assumption['target_attribute']}`")
            st.write(f"**Modifier:** `{selected_assumption['modifier']} {selected_assumption.get('modifier_value', '')}`")

        with col2:
            if is_compatible:
                st.success("✅ Compatible")
                affected = len([c for c in baseline_components if c['type'] == selected_assumption['target_component']])
                st.metric("Affected Components", affected)
            else:
                st.error("❌ Not Compatible")

        # Application section
        if is_compatible:
            st.markdown("---")
            st.write("### 🚀 Apply Assumption")

            baseline_scenario = st.session_state.assumptions_baseline_scenario

            if selected_assumption['type'] == 'single':
                # Single assumption form
                new_scenario_name = st.text_input(
                    "New Scenario Name:",
                    value=f"{baseline_scenario['scenario_name']}_{selected_assumption['id']}",
                    key="single_assumption_name"
                )

                if st.button("🎯 Apply Single Assumption", type="primary"):
                    if new_scenario_name:
                        apply_single_assumption_inline(selected_assumption, new_scenario_name)
                    else:
                        st.error("❌ Please enter a scenario name")
            else:
                # Series assumption form
                import json
                timesteps = json.loads(selected_assumption['assumption_timesteps'])

                base_name = st.text_input(
                    "Base Scenario Name:",
                    value=f"{baseline_scenario['scenario_name']}_{selected_assumption['id']}",
                    key="series_assumption_base"
                )

                st.info(f"📊 This will create **{len(timesteps)} scenarios** for timesteps: {', '.join(map(str, timesteps))}")

                if st.button("📊 Apply Series Assumption", type="primary"):
                    if base_name:
                        apply_series_assumption_inline(selected_assumption, base_name)
                    else:
                        st.error("❌ Please enter a base scenario name")


def apply_single_assumption_inline(assumption, new_scenario_name):
    """Apply single assumption - inline version"""
    try:
        from backend.assumptions.assumption_engine import apply_single_assumption

        baseline_scenario = st.session_state.assumptions_baseline_scenario
        namespace = st.session_state.get('assumptions_baseline_namespace')

        with st.spinner("Applying assumption..."):
            scenario_data = apply_single_assumption(
                baseline_scenario,
                assumption,
                new_scenario_name,
                namespace=namespace,
            )

            st.session_state.assumptions_generated_scenarios.append(scenario_data)

            st.success(f"✅ Generated scenario: **{new_scenario_name}**")
            st.info(f"📊 **Modified {scenario_data.get('modified_count', 0)} attributes** in {len(scenario_data['components'])} components")

    except Exception as e:
        st.error(f"❌ Error applying assumption: {str(e)}")
        if st.checkbox("Show error details", key="error_single"):
            st.exception(e)


def apply_series_assumption_inline(assumption, base_name):
    """Apply series assumption - inline version"""
    try:
        from backend.assumptions.assumption_engine import apply_series_assumption

        baseline_scenario = st.session_state.assumptions_baseline_scenario
        namespace = st.session_state.get('assumptions_baseline_namespace')

        with st.spinner("Applying series assumption..."):
            scenario_series = apply_series_assumption(
                baseline_scenario,
                assumption,
                base_name,
                namespace=namespace,
            )

            st.session_state.assumptions_generated_scenarios.extend(scenario_series)

            st.success(f"✅ Generated **{len(scenario_series)} scenarios** in series")

            with st.expander("📊 Series Summary", expanded=True):
                for scenario in scenario_series:
                    st.write(f"**{scenario['timestep']}:** {scenario['scenario_name']} ({scenario.get('modified_count', 0)} modifications)")

    except Exception as e:
        st.error(f"❌ Error applying series assumption: {str(e)}")
        if st.checkbox("Show error details", key="error_series"):
            st.exception(e)


def tab_manual_modification():
    """Tab 3: Manual modification of component attributes"""
    st.subheader("✏️ Manual Attribute Modification")

    if not st.session_state.assumptions_baseline_scenario:
        st.warning("⚠️ Please load a baseline scenario first (Tab 1)")
        return

    # Constrain categorical edits to the ontology's valid values (cached per workspace).
    _ensure_categorical_options()

    st.write("""
    Manually modify individual component attributes to create custom scenarios.
    Select components, edit their attributes, and generate modified scenarios.
    """)

    baseline_components = st.session_state.assumptions_baseline_components

    # Component filtering
    st.write("### 🔍 Select Components to Modify")

    # Get unique component types
    component_types = sorted(list(set(comp['type'] for comp in baseline_components)))

    col1, col2 = st.columns(2)

    with col1:
        selected_type = st.selectbox(
            "Filter by component type:",
            ['All Types'] + component_types,
            key="manual_mod_type_filter"
        )

    with col2:
        # Search box
        search_term = st.text_input(
            "Search by label:",
            placeholder="Enter component name...",
            key="manual_mod_search"
        )

    # Filter components
    filtered_components = baseline_components

    if selected_type != 'All Types':
        filtered_components = [c for c in filtered_components if c['type'] == selected_type]

    if search_term:
        filtered_components = [c for c in filtered_components
                               if search_term.lower() in c['label'].lower()]

    if not filtered_components:
        st.info("ℹ️ No components match your filters")
        return

    st.write(f"**Found {len(filtered_components)} component(s)**")

    # Component selection
    component_labels = [f"{c['type']}: {c['label']}" for c in filtered_components]

    selected_component_idx = st.selectbox(
        "Select component to modify:",
        range(len(filtered_components)),
        format_func=lambda i: component_labels[i],
        key="manual_mod_component_select"
    )

    selected_component = filtered_components[selected_component_idx]

    # Show component details and attribute editor
    st.markdown("---")
    show_manual_modification_interface(selected_component)


def show_manual_modification_interface(component):
    """Show interface for manually modifying a component's attributes"""
    st.write("### 📝 Modify Component Attributes")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.write(f"**Component:** {component['label']}")
        st.write(f"**Type:** {component['type']}")
        st.write(f"**URI:** `{component['uri']}`")

    with col2:
        st.metric("Total Attributes", len(component.get('attributes', {})))

    attributes = component.get('attributes', {})

    if not attributes:
        st.info("ℹ️ This component has no editable attributes")
        return

    st.write("#### Edit Attribute Values")

    # Create a form for attribute editing
    component_key = component['uri']

    # Initialize pending modifications for this component if not exists
    if component_key not in st.session_state.manual_modifications_pending:
        st.session_state.manual_modifications_pending[component_key] = {}

    # Group attributes by category
    attributes_by_category = {}
    for attr_name, attr_data in attributes.items():
        if attr_name not in ['URI', 'label'] and isinstance(attr_data, dict):
            category = attr_data.get('category', 'unknown')
            if category not in attributes_by_category:
                attributes_by_category[category] = []
            attributes_by_category[category].append((attr_name, attr_data))

    # Display attributes by category with editors - NO EXPANDERS, just headers
    for category in sorted(attributes_by_category.keys()):
        st.markdown(f"#### 📋 {category.title()} Attributes")
        for attr_name, attr_data in attributes_by_category[category]:
            show_attribute_editor(
                component_key,
                attr_name,
                attr_data,
                category
            )
        st.markdown("---")

    # Show modification summary
    if st.session_state.manual_modifications_pending.get(component_key):
        show_modification_summary(component_key, component['label'])


def _load_categorical_options(client):
    """Map each categorical attribute class -> {value_name: label} from the ontology.

    Covers both modelling patterns (subclass values and named individuals). Returns
    {} when no client/ontology is available so callers fall back to free text.
    """
    if client is None:
        return {}
    try:
        from backend.graphdb.queries.ontology import get_categorical_value_options
        df = get_categorical_value_options(client)
    except Exception:
        return {}
    if df is None or getattr(df, "empty", True):
        return {}
    options = {}
    for _, row in df.iterrows():
        attr_cls = str(row["attrClass"]).split("#")[-1].split("/")[-1]
        value = str(row["value"]).split("#")[-1].split("/")[-1]
        raw_label = row.get("label")
        label = str(raw_label).strip()
        if label.lower() in ("", "nan", "none"):
            label = ""
        options.setdefault(attr_cls, {})
        options[attr_cls].setdefault(value, label or value)
    return options


def _ensure_categorical_options():
    """Load + cache the ontology's categorical value options for this workspace."""
    ws = st.session_state.get("current_workspace") or {}
    ws_id = ws.get("id")
    cache = st.session_state.get("assumptions_categorical_options_cache")
    if cache and cache.get("ws") == ws_id:
        return
    client = st.session_state.get("workspace_client")
    st.session_state.assumptions_categorical_options_cache = {
        "ws": ws_id,
        "opts": _load_categorical_options(client),
    }


def _categorical_options_for(attr_name):
    """The {value: label} options for a categorical attribute class, or {}."""
    cache = st.session_state.get("assumptions_categorical_options_cache") or {}
    return (cache.get("opts") or {}).get(attr_name, {})


def show_attribute_editor(component_key, attr_name, attr_data, category):
    """Show editor for a single attribute"""
    current_value = attr_data.get('value', '')
    unit = attr_data.get('unit', '')

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        st.write(f"**{attr_name}**")
        if unit:
            st.caption(f"Unit: {unit}")

    with col2:
        # Determine input type based on category
        if category in ['physical', 'cost', 'geospatial']:
            try:
                float_value = float(current_value)
                new_value = st.number_input(
                    f"Value for {attr_name}",
                    value=float_value,
                    key=f"edit_{component_key}_{attr_name}",
                    label_visibility="collapsed"
                )
            except (ValueError, TypeError):
                new_value = st.text_input(
                    f"Value for {attr_name}",
                    value=str(current_value),
                    key=f"edit_{component_key}_{attr_name}",
                    label_visibility="collapsed"
                )
        elif category == 'categorical':
            # Constrain to the ontology's valid values for this attribute (named
            # individuals / subclasses), same as the Replica Builder. Fall back to
            # free text only when the ontology defines none.
            opts = _categorical_options_for(attr_name)
            if opts:
                names = list(opts.keys())
                current = str(current_value)
                index = names.index(current) if current in names else 0
                new_value = st.selectbox(
                    f"Value for {attr_name}",
                    options=names,
                    index=index,
                    format_func=lambda n: opts.get(n) or n,
                    key=f"edit_{component_key}_{attr_name}",
                    label_visibility="collapsed",
                    help="Ontology-defined values for this attribute",
                )
            else:
                new_value = st.text_input(
                    f"Value for {attr_name}",
                    value=str(current_value),
                    key=f"edit_{component_key}_{attr_name}",
                    label_visibility="collapsed",
                    help="No ontology-defined values found for this attribute; free text",
                )
        else:
            new_value = st.text_input(
                f"Value for {attr_name}",
                value=str(current_value),
                key=f"edit_{component_key}_{attr_name}",
                label_visibility="collapsed"
            )

    with col3:
        # Check if value changed
        try:
            value_changed = float(new_value) != float(current_value)
        except (ValueError, TypeError):
            value_changed = str(new_value) != str(current_value)

        if value_changed:
            if st.button("✅", key=f"apply_{component_key}_{attr_name}", help="Apply change"):
                # Store the modification
                if component_key not in st.session_state.manual_modifications_pending:
                    st.session_state.manual_modifications_pending[component_key] = {}

                st.session_state.manual_modifications_pending[component_key][attr_name] = {
                    'old_value': current_value,
                    'new_value': new_value,
                    'unit': unit,
                    'category': category,
                    'attr_data': attr_data
                }
                st.rerun()
        else:
            # Check if there's a pending modification
            pending = st.session_state.manual_modifications_pending.get(component_key, {})
            if attr_name in pending:
                if st.button("❌", key=f"clear_{component_key}_{attr_name}", help="Clear change"):
                    del st.session_state.manual_modifications_pending[component_key][attr_name]
                    if not st.session_state.manual_modifications_pending[component_key]:
                        del st.session_state.manual_modifications_pending[component_key]
                    st.rerun()


def show_modification_summary(component_key, component_label):
    """Show summary of pending modifications for a component"""
    st.write("### 📊 Pending Modifications")

    modifications = st.session_state.manual_modifications_pending[component_key]

    st.write(f"**Component:** {component_label}")
    st.write(f"**Changes:** {len(modifications)}")

    # Show details
    for attr_name, mod_data in modifications.items():
        col1, col2, col3 = st.columns([2, 2, 1])

        with col1:
            st.write(f"**{attr_name}**")

        with col2:
            old_val = mod_data['old_value']
            new_val = mod_data['new_value']
            unit = mod_data.get('unit', '')

            try:
                old_float = float(old_val)
                new_float = float(new_val)
                change_pct = ((new_float - old_float) / old_float * 100) if old_float != 0 else 0
                st.write(f"{old_val} → {new_val} {unit} ({change_pct:+.1f}%)")
            except (ValueError, TypeError):
                st.write(f"{old_val} → {new_val} {unit}")

        with col3:
            if st.button("🗑️", key=f"remove_{component_key}_{attr_name}"):
                del modifications[attr_name]
                if not modifications:
                    del st.session_state.manual_modifications_pending[component_key]
                st.rerun()

    # Generate scenario button
    st.markdown("---")

    scenario_name = st.text_input(
        "New scenario name:",
        value=f"Manual_Mod_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        key=f"scenario_name_{component_key}"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🚀 Generate Modified Scenario", type="primary", key=f"generate_{component_key}"):
            if scenario_name:
                generate_manually_modified_scenario(
                    component_key,
                    component_label,
                    scenario_name
                )
            else:
                st.error("❌ Please enter a scenario name")

    with col2:
        if st.button("🗑️ Clear All Changes", key=f"clear_all_{component_key}"):
            del st.session_state.manual_modifications_pending[component_key]
            st.rerun()


def generate_manually_modified_scenario(component_key, component_label, scenario_name):
    """Generate a new scenario with manual modifications applied"""
    try:
        from backend.assumptions.manual_modification_engine import apply_manual_modifications

        baseline_scenario = st.session_state.assumptions_baseline_scenario
        modifications = st.session_state.manual_modifications_pending[component_key]
        namespace = st.session_state.get('assumptions_baseline_namespace')

        with st.spinner("Generating modified scenario..."):
            scenario_data = apply_manual_modifications(
                baseline_scenario,
                component_key,
                modifications,
                scenario_name,
                namespace=namespace,
            )

            st.session_state.assumptions_generated_scenarios.append(scenario_data)

            # Clear pending modifications
            del st.session_state.manual_modifications_pending[component_key]

            st.success(f"✅ Generated scenario: **{scenario_name}**")
            st.info(f"📊 Modified **{len(modifications)} attributes** in {component_label}")

            st.balloons()
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error generating scenario: {str(e)}")
        if st.checkbox("Show error details", key="error_manual_gen"):
            st.exception(e)


def tab_view_scenarios():
    """Tab 4: View generated scenarios"""
    st.subheader("📊 Generated Scenarios")

    if not st.session_state.assumptions_generated_scenarios:
        st.info("ℹ️ No scenarios generated yet. Apply assumptions in Tab 2 or use manual modification in Tab 3.")
        return

    scenarios = st.session_state.assumptions_generated_scenarios

    st.write(f"**Total Scenarios:** {len(scenarios)}")

    # Filter options
    col1, col2 = st.columns(2)

    with col1:
        filter_type = st.selectbox(
            "Filter by type:",
            ["All", "Single Assumption", "Series", "Manual Modification"]
        )

    with col2:
        sort_by = st.selectbox(
            "Sort by:",
            ["Creation Order", "Name", "Component Count", "Modifications"]
        )

    # Apply filters
    filtered_scenarios = scenarios
    if filter_type == "Single Assumption":
        filtered_scenarios = [s for s in scenarios if s.get('type') == 'single']
    elif filter_type == "Series":
        filtered_scenarios = [s for s in scenarios if s.get('type') == 'series_member']
    elif filter_type == "Manual Modification":
        filtered_scenarios = [s for s in scenarios if s.get('type') == 'manual_modification']

    # Apply sorting
    if sort_by == "Name":
        filtered_scenarios = sorted(filtered_scenarios, key=lambda x: x['scenario_name'])
    elif sort_by == "Component Count":
        filtered_scenarios = sorted(filtered_scenarios, key=lambda x: len(x['components']), reverse=True)
    elif sort_by == "Modifications":
        filtered_scenarios = sorted(filtered_scenarios, key=lambda x: x.get('modified_count', 0), reverse=True)

    # Display scenarios
    for i, scenario in enumerate(filtered_scenarios, 1):
        show_scenario_card(scenario, i)


def show_scenario_card(scenario, index):
    """Display a scenario card"""
    scenario_type = scenario.get('type', 'unknown')

    if scenario_type == 'manual_modification':
        type_icon = "✏️"
    elif scenario_type == 'single':
        type_icon = "🎯"
    else:
        type_icon = "📊"

    with st.expander(f"{type_icon} {index}. {scenario['scenario_name']}", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Components", len(scenario['components']))

        with col2:
            st.metric("Modifications", scenario.get('modified_count', 0))

        with col3:
            scenario_type_label = {
                'single': 'Single',
                'series_member': 'Series Member',
                'manual_modification': 'Manual Mod'
            }.get(scenario_type, 'Unknown')
            st.write(f"**Type:** {scenario_type_label}")

        # Show assumption details (if applicable)
        assumption = scenario.get('assumption', {})
        if assumption:
            st.write("**Applied Assumption:**")
            st.write(f"  • **Name:** {assumption.get('name', 'Unknown')}")
            st.write(f"  • **Target:** {assumption.get('target_component', 'Unknown')}.{assumption.get('target_attribute', 'Unknown')}")
            st.write(f"  • **Modifier:** {assumption.get('modifier', 'Unknown')} {assumption.get('modifier_value', 'Unknown')}")

            # Show category
            category = assumption.get('attribute_category', 'unknown')
            category_emoji = {
                'physical': '⚙️',
                'cost': '💰',
                'geospatial': '🌍',
                'curve': '📈',
                'categorical': '🏷️',
                'dynamic': '📊'
            }.get(category, '📋')
            st.write(f"  • **Category:** {category_emoji} {category.title()}")

        # Show modification log - NO NESTED EXPANDER, just a collapsible section
        if scenario.get('modification_log'):
            st.markdown("**📋 Modification Details:**")
            # Show first 5 modifications
            for mod in scenario['modification_log'][:5]:
                st.caption(f"• **{mod['component']}** - {mod['attribute']}: {mod.get('old_value')} → {mod.get('new_value')}")

            if len(scenario['modification_log']) > 5:
                st.caption(f"... and {len(scenario['modification_log']) - 5} more modifications")

        # Action buttons
        col1, col2 = st.columns(2)

        with col1:
            if st.button(f"📄 View TTL", key=f"view_ttl_{scenario['scenario_name']}"):
                st.session_state[f"show_ttl_{scenario['scenario_name']}"] = True

        with col2:
            if st.button(f"💾 Export", key=f"export_{scenario['scenario_name']}"):
                export_single_scenario(scenario)

    # Show TTL in a separate container outside the expander if requested
    if st.session_state.get(f"show_ttl_{scenario['scenario_name']}", False):
        with st.container():
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"### 📄 TTL Preview: {scenario['scenario_name']}")
            with col2:
                if st.button("✖️ Close", key=f"close_ttl_{scenario['scenario_name']}"):
                    st.session_state[f"show_ttl_{scenario['scenario_name']}"] = False
                    st.rerun()

            ttl_content = generate_scenario_ttl_with_builder_infrastructure(scenario)
            st.code(ttl_content, language="turtle")

            st.download_button(
                "💾 Download TTL",
                ttl_content,
                file_name=f"{scenario['scenario_name']}.ttl",
                mime="text/turtle",
                use_container_width=True,
                key=f"download_ttl_view_{scenario['scenario_name']}"
            )
            st.markdown("---")


def show_scenario_ttl(scenario):
    """Show TTL for a scenario using scenario_builder infrastructure"""
    try:
        # Use scenario_builder_summary's TTL generation
        ttl_content = generate_scenario_ttl_with_builder_infrastructure(scenario)

        # Use container to control width
        st.markdown("### 📄 TTL Preview")

        # Full width code block
        st.code(ttl_content, language="turtle")

        # Download button
        st.download_button(
            "💾 Download TTL",
            ttl_content,
            file_name=f"{scenario['scenario_name']}.ttl",
            mime="text/turtle",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"❌ Error generating TTL: {str(e)}")


def export_single_scenario(scenario):
    """Export a single scenario using scenario_builder infrastructure"""
    try:
        ttl_content = generate_scenario_ttl_with_builder_infrastructure(scenario)

        st.download_button(
            "💾 Download TTL",
            ttl_content,
            file_name=f"{scenario['scenario_name']}.ttl",
            mime="text/turtle",
            key=f"download_{scenario['scenario_name']}_export"
        )

        st.success("✅ TTL generated successfully!")

    except Exception as e:
        st.error(f"❌ Error exporting: {str(e)}")


def generate_scenario_ttl_with_builder_infrastructure(scenario_data):
    """
    Generate a THIN scenario TTL for an assumptions result.

    Delegates to the backend single-source-of-truth builder
    ``backend.assumptions.thin_scenario_ttl.build_thin_scenario_ttl`` so
    assumption scenarios have the exact same shape as Scenario Builder / hand-
    authored scenarios: they reference the canonical replica components and
    carry only ``supersedesAttribute`` overrides for what changed. Unchanged
    attributes (resource data paths, curves, time series, …) inherit from the
    replica via ``materialize_scenario_graphs`` instead of being re-serialised.
    """
    from backend.assumptions.thin_scenario_ttl import build_thin_scenario_ttl
    return build_thin_scenario_ttl(scenario_data)


def tab_export_results():
    """Tab 5: Export all results"""
    st.subheader("💾 Export Results")

    if not st.session_state.assumptions_generated_scenarios:
        st.info("ℹ️ No scenarios to export. Apply assumptions in Tab 2 or use manual modification in Tab 3.")
        return

    scenarios = st.session_state.assumptions_generated_scenarios

    st.write(f"**Total Scenarios to Export:** {len(scenarios)}")

    # Export options
    export_format = st.radio(
        "Export format:",
        ["Individual TTL Files", "Combined ZIP Archive", "Upload to Workspace"],
        horizontal=True
    )

    if export_format == "Individual TTL Files":
        export_individual_ttl()
    elif export_format == "Combined ZIP Archive":
        export_zip_archive()
    else:
        export_to_workspace()


def export_individual_ttl():
    """Export individual TTL files"""
    st.write("### 📄 Export Individual TTL Files")

    scenarios = st.session_state.assumptions_generated_scenarios

    for scenario in scenarios:
        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"**{scenario['scenario_name']}**")

        with col2:
            export_single_scenario(scenario)


def export_zip_archive():
    """Export all scenarios as ZIP archive"""
    st.write("### 📦 Export Combined ZIP Archive")

    try:
        import zipfile
        from io import BytesIO

        scenarios = st.session_state.assumptions_generated_scenarios

        # Create ZIP in memory
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for scenario in scenarios:
                ttl_content = generate_scenario_ttl_with_builder_infrastructure(scenario)
                filename = f"{scenario['scenario_name']}.ttl"
                zip_file.writestr(filename, ttl_content)

        zip_buffer.seek(0)

        st.download_button(
            "💾 Download ZIP Archive",
            zip_buffer,
            file_name=f"assumptions_scenarios_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mime="application/zip",
            type="primary"
        )

        st.success(f"✅ ZIP archive ready with {len(scenarios)} scenarios!")

    except Exception as e:
        st.error(f"❌ Error creating ZIP: {str(e)}")


def export_to_workspace():
    """Export scenarios to workspace scenarios folder (same as scenario_builder)"""
    st.write("### ☁️ Upload to Workspace")

    try:
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            st.error("❌ No workspace selected")
            return

        workspace_id = current_workspace['id']

        # Write scenarios via the active workspace's storage (local FS,
        # NextCloud, or S3) instead of a hard-coded NextCloud WebDAV call.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is None:
            st.error("❌ No active workspace storage. Open a workspace first.")
            return

        st.info(f"📁 **Target:** {current_workspace['name']}/scenarios/")

        scenarios = st.session_state.assumptions_generated_scenarios

        # Upload confirmation
        if st.button(f"💾 Save {len(scenarios)} Scenarios to Workspace", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            success_count = 0

            for i, scenario in enumerate(scenarios):
                try:
                    ttl_content = generate_scenario_ttl_with_builder_infrastructure(scenario)
                    filename = f"scenarios/{scenario['scenario_name']}.ttl"

                    status_text.text(f"Saving {i + 1}/{len(scenarios)}: {scenario['scenario_name']}")

                    storage.write_text(filename, ttl_content)
                    success_count += 1

                    progress_bar.progress((i + 1) / len(scenarios))

                except Exception as e:
                    st.warning(f"⚠️ Failed to save {scenario['scenario_name']}: {str(e)}")

            status_text.empty()
            progress_bar.empty()

            if success_count == len(scenarios):
                st.success(f"✅ Successfully uploaded all {success_count} scenarios!")
            else:
                st.warning(f"⚠️ Uploaded {success_count}/{len(scenarios)} scenarios")

    except Exception as e:
        st.error(f"❌ Error uploading to workspace: {str(e)}")