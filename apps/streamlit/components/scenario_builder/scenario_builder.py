# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/scenario_builder.py
"""
Optimized scenario builder interface with caching and reduced redundant operations
UPDATED: Added TTL Data Products tab for private and global data products support
"""
import streamlit as st
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
import time

# Import modular components from the new structure
from components.scenario_builder.scenario_builder_components import tab_add_components
from components.scenario_builder.scenario_builder_links import tab_manage_links
from components.scenario_builder.scenario_builder_summary import tab_summary_ttl
from components.scenario_builder.attribute_validation_system import (
    tab_enhanced_attribute_validation,
    validate_component_attributes_detailed,
    get_component_attribute_sources
)
from components.scenario_builder.data_products_tab import (
    tab_ttl_data_products,
    show_data_products_status_compact
)

# Try to import data products (check both new and old locations) - DEPRECATED: Now using TTL data products
try:
    from components.data_products import tab_data_products

    DATA_PRODUCTS_AVAILABLE = True
except ImportError:
    try:
        # Fallback to old location
        from components.data_products.data_products import tab_data_products

        DATA_PRODUCTS_AVAILABLE = True
    except ImportError:
        DATA_PRODUCTS_AVAILABLE = False

# Import the enhanced data loaders for NextCloud integration
try:
    from components.data_loaders import nextcloud_data_loader

    DATA_LOADER_AVAILABLE = True
except ImportError:
    DATA_LOADER_AVAILABLE = False

# Shared service discovery/reading (workspace services/ + global library).
from components.service_catalog import services_by_name, read_service_text


def initialize_session_state():
    """Initialize basic session state for scenario builder with workspace context"""
    if 'scenario_components' not in st.session_state:
        st.session_state.scenario_components = []

    if 'scenario_name' not in st.session_state:
        # Use workspace context for default scenario name
        current_workspace = st.session_state.get('current_workspace')
        if current_workspace:
            workspace_name = current_workspace['name'].replace(' ', '_')
            st.session_state.scenario_name = f"New_Scenario_{workspace_name}"
        else:
            st.session_state.scenario_name = "New Scenario"

    if 'scenario_links' not in st.session_state:
        st.session_state.scenario_links = []

    if 'selected_requirements' not in st.session_state:
        st.session_state.selected_requirements = None

    if 'enabled_data_products' not in st.session_state:
        st.session_state.enabled_data_products = []

    # NEW: Initialize TTL data products state
    if 'enabled_ttl_data_products' not in st.session_state:
        st.session_state.enabled_ttl_data_products = []

    if 'required_attributes' not in st.session_state:
        st.session_state.required_attributes = {}

    if 'nested_requirements' not in st.session_state:
        st.session_state.nested_requirements = {}

    # Add cache for expensive operations
    if 'yaml_files_cache' not in st.session_state:
        st.session_state.yaml_files_cache = None

    if 'yaml_files_cache_time' not in st.session_state:
        st.session_state.yaml_files_cache_time = 0


def load_yaml_files():
    """Available services keyed by name (workspace `services/` + global library),
    with a short session-state cache. Values are ServiceRef objects."""
    current_time = time.time()
    if (st.session_state.yaml_files_cache is not None and
            current_time - st.session_state.yaml_files_cache_time < 30):
        return st.session_state.yaml_files_cache

    yaml_files = services_by_name()

    st.session_state.yaml_files_cache = yaml_files
    st.session_state.yaml_files_cache_time = current_time
    return yaml_files


def load_service_requirements():
    """Load and display service requirements selection - optimized version"""
    st.header("🏗️ Scenario Builder")

    # Load YAML files from NextCloud
    yaml_files = load_yaml_files()

    if not yaml_files:
        st.info("No service requirement YAMLs found. Add one to the workspace `services/` folder (or NextCloud `global/services/`).")

        with st.expander("📁 Expected workspace structure", expanded=True):
            st.write("**Service YAMLs are read from the workspace `services/` folder:**")
            st.code("""
<workspace>/
├── services/
│   ├── service.yaml          # A service requirement definition
│   ├── WindForecasting.yaml  # Additional services
│   └── [YourService].yaml    # More services
└── private_data_products/
            """)

        st.write("**Enhanced YAML format with NextCloud integration support:**")
        st.code("""
service_name: YourServiceName
scenario_data:
  uri: Scenario.URI
  name: Scenario.label
  site:
    name: GlobalWindAtlasSite.label
    roughness: GlobalWindAtlasSite.Roughness
    turbines:
      link: CL.GlobalWindAtlasSite.WindTurbine
      template:
        rated_power: WindTurbine.RatedPower
        hub_height: WindTurbine.HubHeight
        # Enhanced: Nested property support from workspace TTL
        future_power_projection: WindTurbine.PowerProduction.hasFutureTimeSeries
        historical_power_output: WindTurbine.PowerProduction.hasHistoricTimeSeries
        # NEW: EventAttribute support for temporal data
        construction_year: Building.YearOfConstruction
        """)

        return None

    # Create dropdown with service names (not filenames)
    selected_service = st.selectbox(
        "Select Service:",
        options=list(yaml_files.keys()),
        key="service_selector"
    )

    if selected_service:
        service_ref = yaml_files[selected_service]  # ServiceRef (workspace or global)
        yaml_file_path = service_ref.ref

        try:
            # Read from workspace storage or the global library (per the ref's source).
            yaml_content_text = read_service_text(service_ref)

            if not yaml_content_text:
                st.error(f"❌ Could not read {yaml_file_path}")
                return None

            # Parse the YAML content
            yaml_content = yaml.safe_load(yaml_content_text)

            service_name = yaml_content.get('service_name', selected_service)
            component_links = extract_component_links(yaml_content)

            # Use enhanced attribute extraction
            required_attributes, nested_requirements = extract_required_attributes_enhanced(yaml_content)

            # Get all required component types (from both links and direct requirements)
            all_required_component_types = extract_all_required_component_types(yaml_content)

            # Analyze YAML complexity
            complexity_analysis = analyze_yaml_requirement_complexity(yaml_content)

            requirements = {
                'service_name': service_name,
                'yaml_content': yaml_content,
                'component_links': component_links,
                'required_attributes': required_attributes,
                'nested_requirements': nested_requirements,
                'complexity_analysis': complexity_analysis,
                'file_path': yaml_file_path,  # NextCloud path
                'all_required_component_types': all_required_component_types
            }

            st.session_state.selected_requirements = requirements
            st.session_state.required_attributes = required_attributes
            st.session_state.nested_requirements = nested_requirements

            # Enhanced service display with workspace context
            display_enhanced_service_overview(requirements)

            return requirements

        except Exception as e:
            st.error(f"Error loading service definition from NextCloud: {str(e)}")
            st.write(f"**NextCloud Path:** `{yaml_file_path}`")
            return None

    return None


def extract_component_links(yaml_content):
    """Extract CL.X.Y patterns from YAML"""
    links = []

    def find_links(data, path=""):
        if isinstance(data, dict):
            for key, value in data.items():
                if key == 'link' and isinstance(value, str) and value.startswith('CL.'):
                    links.append(value)
                elif isinstance(value, (dict, list)):
                    find_links(value, f"{path}.{key}")
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_links(item, path)

    find_links(yaml_content)
    return list(set(links))


def extract_all_required_component_types(yaml_content):
    """Extract all required component types from YAML including both CL patterns and direct component requirements"""
    component_types = set()

    # First, get component types from CL patterns
    component_links = extract_component_links(yaml_content)
    for link in component_links:
        parts = link.split('.')
        if len(parts) >= 3:
            component_types.add(parts[1])  # Source component type
            component_types.add(parts[2])  # Target component type

    # Second, extract component types from required attributes
    required_attributes, _ = extract_required_attributes_enhanced(yaml_content)
    for comp_type in required_attributes.keys():
        if comp_type != 'Scenario':  # Skip scenario itself
            component_types.add(comp_type)

    # Third, extract component types from direct template definitions
    component_types.update(extract_component_types_from_templates(yaml_content))

    # Remove 'Scenario' if it exists and return sorted list
    component_types.discard('Scenario')
    return sorted(list(component_types))


def extract_component_types_from_templates(yaml_content):
    """Extract component types from template definitions in YAML"""
    component_types = set()

    def find_component_types(data, path=""):
        if isinstance(data, dict):
            for key, value in data.items():
                # Check if this key has a 'type' field indicating a component type
                if isinstance(value, dict) and 'type' in value:
                    comp_type = value['type']
                    if isinstance(comp_type, str) and not comp_type.startswith('CL.'):
                        component_types.add(comp_type)

                # Check if this is a template definition with component.attribute patterns
                elif key == 'template' and isinstance(value, dict):
                    for template_key, template_value in value.items():
                        if isinstance(template_value, str) and '.' in template_value:
                            # Extract component type from patterns like ComponentType.AttributeName
                            comp_type = template_value.split('.')[0]
                            if comp_type and not comp_type.startswith('CL'):
                                component_types.add(comp_type)

                # Recursively search nested structures
                elif isinstance(value, (dict, list)):
                    find_component_types(value, f"{path}.{key}")

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_component_types(item, path)

    # Start the search from scenario_data
    scenario_data = yaml_content.get('scenario_data', {})
    find_component_types(scenario_data)

    return component_types


def extract_required_attributes_enhanced(yaml_content):
    """Extract required attributes from YAML with enhanced support for nested properties, complex structures, and EventAttribute"""
    required_attributes = {}
    nested_requirements = {}

    def find_attributes(data, path="", current_component=None):
        if isinstance(data, dict):
            for key, value in data.items():
                if key == 'template' and isinstance(value, dict):
                    # Found a template - extract all Component.Attribute patterns
                    for template_key, template_value in value.items():
                        if isinstance(template_value, str) and '.' in template_value:
                            process_attribute_pattern(template_value, template_key)
                        elif isinstance(template_value, dict):
                            # Handle nested structures like cost.value, cost.unit, etc.
                            find_attributes(template_value, f"{path}.{template_key}", current_component)

                elif isinstance(value, str) and '.' in value and not key == 'link':
                    # Direct Component.Attribute patterns (but not links)
                    process_attribute_pattern(value, key)

                elif isinstance(value, (dict, list)):
                    # Continue traversing for nested templates
                    # Track component context for nested requirements
                    new_component = current_component
                    if key in ['turbines', 'pv', 'site', 'energy_carrier', 'buildings'] and isinstance(value, dict):  # NEW: Added buildings
                        # This might be a component definition
                        if 'type' in value:
                            new_component = value['type']
                        elif 'template' in value:
                            # Infer component type from context
                            new_component = infer_component_type_from_context(key)

                    find_attributes(value, f"{path}.{key}", new_component)

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_attributes(item, path, current_component)

    def process_attribute_pattern(pattern_value, template_key):
        """Process an attribute pattern like WindTurbine.PowerProduction.hasFutureTimeSeries or Building.YearOfConstruction"""
        parts = pattern_value.split('.')

        if len(parts) >= 2:
            comp_type = parts[0]
            attr_path = '.'.join(parts[1:])

            # Initialize component in required_attributes if not exists
            if comp_type not in required_attributes:
                required_attributes[comp_type] = set()

            # Handle nested attribute requirements
            if len(parts) > 2:
                # This is a nested requirement like PowerProduction.hasFutureTimeSeries
                base_attr = parts[1]
                nested_prop = '.'.join(parts[2:])

                # Add the base attribute to required attributes
                required_attributes[comp_type].add(base_attr)

                # Track the nested requirement separately
                if comp_type not in nested_requirements:
                    nested_requirements[comp_type] = {}
                if base_attr not in nested_requirements[comp_type]:
                    nested_requirements[comp_type][base_attr] = set()

                nested_requirements[comp_type][base_attr].add(nested_prop)

                # Also store the full path for validation
                full_path = f"{base_attr}.{nested_prop}"
                required_attributes[comp_type].add(full_path)

            else:
                # Simple attribute requirement (like Building.YearOfConstruction for EventAttribute)
                attr_name = parts[1]
                required_attributes[comp_type].add(attr_name)

    def infer_component_type_from_context(context_key):
        """Infer component type from YAML structure context"""
        context_mapping = {
            'turbines': 'WindTurbine',
            'site': 'GlobalWindAtlasSite',
            'pv': 'PV',
            'energy_carrier': 'EnergyCarrier',
            'grid': 'Grid',
            'battery': 'Battery',
            'buildings': 'Building'  # NEW: Added Building support
        }
        return context_mapping.get(context_key, 'Unknown')

    # Start the extraction
    find_attributes(yaml_content.get('scenario_data', {}))

    # Convert sets to lists and filter out generic attributes
    result_attributes = {}
    result_nested = {}

    for comp_type, attrs in required_attributes.items():
        if attrs and comp_type != 'CL':  # Filter out invalid component types
            filtered_attrs = sorted(list(attrs))
            if filtered_attrs:
                result_attributes[comp_type] = filtered_attrs

    for comp_type, nested_attrs in nested_requirements.items():
        if nested_attrs and comp_type != 'CL':
            result_nested[comp_type] = {}
            for base_attr, nested_props in nested_attrs.items():
                if nested_props:
                    result_nested[comp_type][base_attr] = sorted(list(nested_props))

    return result_attributes, result_nested


def analyze_yaml_requirement_complexity(yaml_content):
    """Analyze the complexity and structure of YAML requirements"""
    analysis = {
        'total_components': 0,
        'nested_structures': 0,
        'template_definitions': 0,
        'link_patterns': 0,
        'attribute_patterns': 0,
        'complex_nested_paths': 0,
        'event_attributes': 0  # NEW: Count potential EventAttribute requirements
    }

    def analyze_structure(data, depth=0):
        if isinstance(data, dict):
            analysis['total_components'] += 1

            for key, value in data.items():
                if key == 'template':
                    analysis['template_definitions'] += 1
                    if isinstance(value, dict):
                        for template_key, template_value in value.items():
                            if isinstance(template_value, str) and '.' in template_value:
                                analysis['attribute_patterns'] += 1
                                # Count complex nested paths (more than 2 levels)
                                if len(template_value.split('.')) > 2:
                                    analysis['complex_nested_paths'] += 1

                                # NEW: Count potential EventAttribute patterns
                                if any(indicator in template_value.upper() for indicator in ['YEAR', 'DATE', 'TIME', 'AGE', 'CONSTRUCTION']):
                                    analysis['event_attributes'] += 1

                elif key == 'link' and isinstance(value, str) and value.startswith('CL.'):
                    analysis['link_patterns'] += 1

                elif isinstance(value, dict) and depth > 1:
                    analysis['nested_structures'] += 1

                if isinstance(value, (dict, list)):
                    analyze_structure(value, depth + 1)

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    analyze_structure(item, depth)

    analyze_structure(yaml_content.get('scenario_data', {}))
    return analysis


def display_enhanced_service_overview(requirements):
    """Display enhanced service overview - simplified version with EventAttribute indicators"""
    service_name = requirements['service_name']
    component_links = requirements['component_links']
    required_attributes = requirements['required_attributes']
    all_required_component_types = requirements.get('all_required_component_types', [])
    complexity_analysis = requirements.get('complexity_analysis', {})

    # Create enhanced success message
    success_parts = [
        f"**Service:** {service_name}",
        f"**{len(component_links)}** component links",
        f"**{len(all_required_component_types)}** component types"
    ]

    # NEW: Add EventAttribute indicator
    event_attrs_count = complexity_analysis.get('event_attributes', 0)
    if event_attrs_count > 0:
        success_parts.append(f"**{event_attrs_count}** temporal attributes 📅")

    st.success(" | ".join(success_parts))

    # Show required component types in expander (not expanded by default)
    if all_required_component_types:
        with st.expander("🔧 Required Component Types", expanded=False):
            cols = st.columns(3)
            for i, comp_type in enumerate(all_required_component_types):
                with cols[i % 3]:
                    # NEW: Add indicator for components with EventAttribute requirements
                    event_indicator = ""
                    comp_attrs = required_attributes.get(comp_type, [])
                    if any(any(indicator in attr.upper() for indicator in ['YEAR', 'DATE', 'TIME', 'AGE', 'CONSTRUCTION'])
                           for attr in comp_attrs):
                        event_indicator = " 📅"

                    st.write(f"• **{comp_type}**{event_indicator}")


def _reconstruct_scenario_from_ttl(ttl_content: str, workspace_id: str, name: str):
    """Parse a scenario TTL back into the builder's editable session shape.

    Reuses the proven TTL component extractor so attributes, types and nested
    properties come through the same way they do for TTL data products. Returns
    ``(scenario_name, components, links)`` ready to drop into session state.
    """
    from rdflib import Graph, Namespace
    from rdflib.namespace import RDF, RDFS

    DICI = Namespace("https://digicities.info/ontology#")
    graph = Graph()
    graph.parse(data=ttl_content, format="turtle")

    from components.scenario_builder.ttl_use_case_loader import NextCloudTTLUseCaseLoader

    loader = NextCloudTTLUseCaseLoader(workspace_id=workspace_id)
    comps_by_type = loader.extract_components_from_graph(graph, f"loaded_{name}")

    # Scenario name from its label.
    scenario_uri = None
    scenario_name = None
    for s in graph.subjects(RDF.type, DICI.Scenario):
        scenario_uri = str(s)
        for lbl in graph.objects(s, RDFS.label):
            scenario_name = str(lbl)
        break
    if not scenario_name:
        scenario_name = name.replace("_", " ")

    # The extractor's attribute filter is name-based and misclassifies attribute
    # individuals (GroundFloorArea, EVCount, ...) as components. Keep only the
    # real components: nodes wired into the scenario's ComponentLink graph, or
    # nodes that actually carry attribute predicates.
    linked_uris = set()
    for link in graph.subjects(RDF.type, DICI.ComponentLink):
        linked_uris.update(str(o) for o in graph.objects(link, DICI.hasInputEntity))
        linked_uris.update(str(o) for o in graph.objects(link, DICI.linksInputyEntityTo))
    linked_uris.discard(scenario_uri)

    attribute_holders = {
        str(s) for s, p, _ in graph
        if "hasAttribute" in str(p) or (str(p).startswith(str(DICI)) and str(p).endswith("Attribute"))
    }
    real_uris = linked_uris | attribute_holders

    components = []
    for ctype, items in comps_by_type.items():
        if ctype in ("Scenario", "ComponentLink"):
            continue
        for c in items:
            if c.get("uri") not in real_uris:
                continue  # skip attribute individuals misread as components
            c.setdefault("source", "ttl_use_case")
            c.setdefault("workspace_id", workspace_id)
            c.setdefault("uri_fragment", c.get("label") or str(c.get("uri", "")).rsplit("/", 1)[-1])
            components.append(c)

    # Rebuild links in the builder's shape (source/target/link_type/pattern).
    type_by_uri = {c["uri"]: c["type"] for c in components}
    links = []
    for link in graph.subjects(RDF.type, DICI.ComponentLink):
        srcs = list(graph.objects(link, DICI.hasInputEntity))
        tgts = list(graph.objects(link, DICI.linksInputyEntityTo))
        if not srcs or not tgts:
            continue
        src, tgt = str(srcs[0]), str(tgts[0])
        tgt_type = type_by_uri.get(tgt, "Component")
        if src == scenario_uri:
            links.append({"source": "scenario", "target": tgt,
                          "link_type": "scenario_automatic",
                          "pattern": f"CL.Scenario.{tgt_type}"})
        else:
            src_type = type_by_uri.get(src, "Component")
            links.append({"source": src, "target": tgt, "link_type": "manual",
                          "pattern": f"CL.{src_type}.{tgt_type}"})

    return scenario_name, components, links


def tab_load_existing_scenario():
    """Tab: load an existing scenario (workspace files or graph) into the builder."""
    st.subheader("📂 Load Existing Scenario")
    st.write(
        "Load a scenario from this workspace's files or the knowledge graph to view "
        "and edit it here. Loading replaces the scenario currently in the builder."
    )

    from components.scenario_loader import render_scenario_loader

    current_workspace = st.session_state.get("current_workspace")
    workspace_id = current_workspace["id"] if current_workspace else "workspace"

    selected = render_scenario_loader(
        client=st.session_state.get("workspace_client"),
        key_prefix="builder_load",
        allow_multiple=False,
    )

    if selected and st.button("📥 Load into builder", type="primary", key="builder_load_btn"):
        item = selected[0]
        with st.spinner(f"Loading {item['name']}..."):
            try:
                scenario_name, components, links = _reconstruct_scenario_from_ttl(
                    item["content"], workspace_id, item["name"]
                )
            except Exception as e:
                st.error(f"❌ Could not load scenario: {e}")
                return

            if not components:
                st.error("❌ No editable components found in that scenario.")
                return

            st.session_state.scenario_name = scenario_name
            st.session_state.scenario_components = components
            st.session_state.scenario_links = links
            st.success(
                f"✅ Loaded **{scenario_name}** — {len(components)} component(s), "
                f"{len(links)} link(s). Use the other tabs to edit, then Summary / TTL to save."
            )
            st.rerun()

    if st.session_state.get("scenario_components"):
        st.info(
            f"📦 In the builder now: **{st.session_state.get('scenario_name', '(unnamed)')}** "
            f"with {len(st.session_state.scenario_components)} component(s)."
        )


def scenario_builder(client):
    """Main scenario builder interface with optimized loading and TTL data products support"""
    initialize_session_state()

    # Load service requirements at the top
    requirements = load_service_requirements()

    if not requirements:
        return

    # Simple tab interface; "Load Existing" sits alongside TTL Data Products.
    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📂 Load Existing",
        "📊 TTL Data Products",
        "📦 Add Components",
        "🔍 Attribute Validation",
        "🔗 Manage Links",
        "📊 Summary / TTL",
        "ℹ️ Help"
    ])

    with tab0:
        tab_load_existing_scenario()

    with tab1:
        tab_ttl_data_products()

    with tab2:
        show_data_products_status_compact()
        tab_add_components()

    with tab3:
        tab_enhanced_attribute_validation()

    with tab4:
        tab_manage_links()

    with tab5:
        tab_summary_ttl()

    with tab6:
        show_help_tab()


def show_help_tab():
    """Help and guidance tab - enhanced version with TTL data products info"""
    st.subheader("ℹ️ Help & Usage Guide")

    st.write("### How to Use the Scenario Builder")

    with st.expander("1️⃣ Getting Started", expanded=True):
        st.write("""
        **Step 1: Select a Service**
        - Choose from available service definitions
        - Service YAML files are loaded from NextCloud `global/services/`

        **Step 2: Configure Data Sources**
        - **TTL Data Products Tab:** Enable private or global TTL data products
        - **Legacy Data Products Tab:** (if available) Select traditional data catalogs
        - Your workspace knowledge graph is automatically included if available

        **Step 3: Add Components**
        - Select components from available sources
        - Use checkboxes for batch selection
        """)

    with st.expander("2️⃣ Data Sources", expanded=False):
        st.write("""
        **Workspace Knowledge Graph**
        - Loaded from `workspace/graph/classes_and_attributes.ttl`
        - Contains your custom components and attributes
        - Supports EventAttribute for temporal data 📅

        **Private TTL Data Products**
        - Located at `workspace/private_data_products/*.ttl`
        - Workspace-specific data products
        - Same TTL format as knowledge graph

        **Global TTL Data Products** 
        - Located at `global/data_products/catalogs/*.ttl`
        - Shared across all workspaces
        - Standard component libraries

        **Legacy Data Products** (if available)
        - Traditional JSON-based catalogs
        - Technology Catalog 2025, Building Demand Profiles, etc.
        """)

    with st.expander("3️⃣ EventAttribute Support", expanded=False):
        st.write("""
        **New: Temporal Data Support**
        - EventAttribute type for dates, years, construction times
        - Example: `BuildingAge: Building.YearOfConstruction`
        - Supports various temporal precisions (Year, Date, DateTime)
        - Displayed with 📅 indicators throughout the interface

        **TTL Format:**
        ```turtle
        <Building123/YearOfConstruction> a dici_onto:YearOfConstruction ;
            a dici_onto:EventAttribute ;
            dici_onto:hasTemporalValue "1970"^^xsd:gYear ;
            dici_onto:hasTemporalPrecision dici_onto:Year .
        ```
        """)

    with st.expander("4️⃣ Empty Knowledge Graph Support", expanded=False):
        st.write("""
        **Building Scenarios Without Workspace Knowledge Graph**
        - It's now OK to have an empty workspace knowledge graph
        - Use TTL Data Products instead for component sources
        - Enable private and/or global data products as needed
        - Components from data products work identically to workspace components
        """)


def get_attribute_validation_summary():
    """Get summary of attribute validation status for footer metrics"""
    if not st.session_state.selected_requirements or not st.session_state.scenario_components:
        return 0, 0, 0

    required_attributes = st.session_state.required_attributes
    total_missing = 0
    total_components_checked = 0
    fully_compliant = 0

    for component in st.session_state.scenario_components:
        comp_type = component['type']
        if comp_type in required_attributes:
            total_components_checked += 1
            required_attrs = required_attributes[comp_type]

            # Use enhanced validation that handles nested properties and EventAttribute
            missing, _, _ = validate_component_attributes_detailed_enhanced(component, required_attrs)
            total_missing += len(missing)
            if not missing:
                fully_compliant += 1

    return total_missing, total_components_checked, fully_compliant


def validate_component_attributes_detailed_enhanced(component, required_attrs):
    """Enhanced validation function that handles nested property requirements and EventAttribute"""
    missing = []
    present = []
    sources = []

    # Import the enhanced validation from components
    try:
        from components.scenario_builder.scenario_builder_components import resolve_nested_attribute_requirement

        for req_attr in required_attrs:
            # Use the enhanced nested attribute resolution (now supports EventAttribute)
            attr_value = resolve_nested_attribute_requirement(component, req_attr)

            if attr_value:
                present.append(req_attr)
                # Determine source of the attribute
                comp_source = component.get('source', 'unknown')
                if comp_source == 'ttl_use_case':
                    sources.append('Workspace TTL')
                elif comp_source == 'data_product':  # NEW: Support data product source
                    dp_type = component.get('data_product_type', 'unknown')
                    dp_name = component.get('data_product_name', 'unknown')
                    sources.append(f'{dp_type.title()} DP: {dp_name}')
                elif comp_source == 'data_products':
                    sources.append('Legacy Data Products')
                else:
                    sources.append('Unknown Source')
            else:
                missing.append(req_attr)

    except ImportError:
        # Fallback to basic validation if enhanced components not available
        missing, present, sources = validate_component_attributes_detailed(component, required_attrs)

    return missing, present, sources