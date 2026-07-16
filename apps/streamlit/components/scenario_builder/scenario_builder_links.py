# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/scenario_builder_links.py
"""
Optimized scenario builder links module with form-based link creation
Modified to use vertical checkbox layout for better performance with many components
UPDATED: Added system description graph link detection and bulk import
"""
import streamlit as st
from typing import Dict, List, Any, Optional, Tuple

# Pure URI helper (relocated out of the legacy ttl_use_case_loader).
from components.scenario_builder.component_display_utils import get_uri_fragment

TTL_UTILS_AVAILABLE = True

# Import system description loader module
try:
    from components.scenario_builder.graphdb_system_description_loader import (
        get_system_description_loader,
        get_system_description_links_for_requirement
    )

    SYSTEM_LINKS_AVAILABLE = True
except ImportError:
    SYSTEM_LINKS_AVAILABLE = False


def get_component_type_from_uri(uri: str) -> str:
    """Extract component type from URI by parsing the path structure"""
    try:
        # Remove the base URL and split by '/'
        if '://' in uri:
            # Split off the protocol and domain
            path_part = uri.split('://', 1)[1]
            # Find the first '/' after the domain to get the path
            if '/' in path_part:
                path = path_part.split('/', 1)[1]
            else:
                return 'Unknown'
        else:
            path = uri

        # Split the path into segments
        segments = [seg for seg in path.split('/') if seg]  # Remove empty segments

        # The component type should be the second-to-last segment
        # Format: .../project/use_case/ComponentType/instance_name
        if len(segments) >= 2:
            return segments[-2]  # Second-to-last segment
        elif len(segments) == 1:
            return segments[0]  # If only one segment, use it
        else:
            return 'Unknown'

    except Exception:
        # Fallback to the original logic if parsing fails
        return 'Unknown'


def get_all_component_types_in_scenario() -> List[str]:
    """Get all unique component types currently in the scenario"""
    if not st.session_state.scenario_components:
        return []

    component_types = set()
    for comp in st.session_state.scenario_components:
        # Use the component's stored type if available, otherwise extract from URI
        comp_type = comp.get('type') or get_component_type_from_uri(comp.get('uri', ''))
        if comp_type != 'Unknown':
            component_types.add(comp_type)

    return sorted(list(component_types))


def get_components_by_type(component_type: str) -> List[Dict[str, Any]]:
    """Get all components of a specific type from the scenario"""
    if not st.session_state.scenario_components:
        return []

    return [
        comp for comp in st.session_state.scenario_components
        if comp.get('type') == component_type or
           get_component_type_from_uri(comp.get('uri', '')) == component_type
    ]


def get_mock_existing_links():
    """Mock existing physical links between components with enhanced NextCloud context"""
    return {
        'https://digicities.info/proj/Example_Energy_Strategy/Region/hub1': [
            {
                'target': 'https://digicities.info/proj/Example_Energy_Strategy/Region/hub1/ElectricityDemandProfile',
                'type': 'ElectricityDemandProfile',
                'link_type': 'physical'
            },
            {
                'target': 'https://digicities.info/proj/Example_Energy_Strategy/Region/hub1/SolarPotentialProfile',
                'type': 'SolarPotentialProfile',
                'link_type': 'physical'
            }
        ],
        'https://digicities.info/proj/Extended_Energy_System/Region/commercialHub2025': [
            {
                'target': 'https://digicities.info/proj/Extended_Energy_System/Region/commercialHub2025/ElectricityDemandProfile',
                'type': 'ElectricityDemandProfile',
                'link_type': 'physical'
            }
        ]
    }


def get_component_label_by_uri(uri: str) -> str:
    """Get component label by URI with improved flexibility and NextCloud integration"""
    # First check scenario components for URI fragment
    for component in st.session_state.get('scenario_components', []):
        if component.get('uri') == uri:
            return component.get('uri_fragment', component.get('label', get_uri_fragment(uri)))

    # Try to get from NextCloud knowledge graph components dynamically
    try:
        from components.scenario_builder.scenario_builder_components import get_mock_components_with_instances

        # Get the component type from URI to know which type to search
        component_type = get_component_type_from_uri(uri)
        if component_type != 'Unknown':
            components = get_mock_components_with_instances(component_type)
            for comp in components:
                if comp['uri'] == uri:
                    return comp['label']
    except Exception:
        pass

    # Try NextCloud data products
    try:
        from components.scenario_builder.scenario_builder_components import get_data_product_components_by_type
        component_type = get_component_type_from_uri(uri)
        if component_type != 'Unknown':
            dp_components = get_data_product_components_by_type(component_type)
            for comp in dp_components:
                if comp['uri'] == uri:
                    return comp.get('label', get_uri_fragment(uri))
    except Exception:
        pass

    # Try workspace TTL components
    try:
        from components.scenario_builder.scenario_builder_components import get_ttl_use_case_components_by_type
        component_type = get_component_type_from_uri(uri)
        if component_type != 'Unknown':
            ttl_components = get_ttl_use_case_components_by_type(component_type)
            for comp in ttl_components:
                if comp['uri'] == uri:
                    return comp.get('uri_fragment', get_uri_fragment(uri))
    except Exception:
        pass

    # Fallback to URI fragment
    return get_uri_fragment(uri)


def create_link(source_comp: Dict[str, Any], target_comp: Dict[str, Any], link_type: str) -> bool:
    """Create a link between components with validation and enhanced source tracking"""
    if not source_comp.get('uri') or not target_comp.get('uri'):
        st.error("Cannot create link: Missing URI information")
        return False

    new_link = {
        'source': source_comp['uri'],
        'target': target_comp['uri'],
        'link_type': link_type,
        'source_info': {
            'label': source_comp.get('uri_fragment', source_comp.get('label')),
            'type': source_comp.get('type'),
            'source_type': source_comp.get('source'),  # Track if from TTL, data products, etc.
            'workspace_id': source_comp.get('workspace_id')
        },
        'target_info': {
            'label': target_comp.get('uri_fragment', target_comp.get('label')),
            'type': target_comp.get('type'),
            'source_type': target_comp.get('source'),
            'workspace_id': target_comp.get('workspace_id')
        }
    }

    # Check if link already exists
    existing = any(
        link['source'] == new_link['source'] and link['target'] == new_link['target']
        for link in st.session_state.scenario_links
        if link.get('link_type') != 'scenario_automatic'
    )

    if not existing:
        st.session_state.scenario_links.append(new_link)
        return True
    else:
        st.warning("Link already exists")
        return False


def create_link_from_uris(source_uri: str, target_uri: str, link_type: str = "system_description") -> bool:
    """
    Create a link from URIs (for system description imports)
    """
    source_comp = find_component_in_scenario(source_uri)
    target_comp = find_component_in_scenario(target_uri)

    if not source_comp or not target_comp:
        return False

    return create_link(source_comp, target_comp, link_type)


def remove_link(link: Dict[str, Any]) -> bool:
    """Remove a link from the scenario"""
    try:
        st.session_state.scenario_links.remove(link)
        return True
    except ValueError:
        return False


def import_physical_link(source_comp: Dict[str, Any], phys_link: Dict[str, Any]) -> bool:
    """Import a physical link and add target component if needed with enhanced NextCloud integration"""
    try:
        from components.scenario_builder.scenario_builder_components import (
            get_mock_components_with_instances,
            get_data_product_components_by_type,
            get_ttl_use_case_components_by_type,
            add_component_to_scenario
        )

        # First, check if target component is in scenario
        target_in_scenario = any(
            comp['uri'] == phys_link['target']
            for comp in st.session_state.scenario_components
        )

        if not target_in_scenario:
            # Try to find target component in all NextCloud sources
            target_comp = None

            # Check NextCloud knowledge graph
            kg_components = get_mock_components_with_instances(phys_link['type'])
            target_comp = next((c for c in kg_components if c['uri'] == phys_link['target']), None)

            # Check NextCloud data products if not found
            if not target_comp:
                dp_components = get_data_product_components_by_type(phys_link['type'])
                target_comp = next((c for c in dp_components if c['uri'] == phys_link['target']), None)

            # Check workspace TTL if still not found
            if not target_comp:
                ttl_components = get_ttl_use_case_components_by_type(phys_link['type'])
                target_comp = next((c for c in ttl_components if c['uri'] == phys_link['target']), None)

            if target_comp:
                add_component_to_scenario(target_comp, phys_link['type'])
            else:
                st.error(f"Could not find target component: {phys_link['target']} in any NextCloud source")
                return False

        # Create the link with enhanced tracking
        new_link = {
            'source': source_comp['uri'],
            'target': phys_link['target'],
            'link_type': phys_link['link_type'],
            'imported': True,  # Mark as imported link
            'source_info': {
                'label': source_comp.get('uri_fragment', source_comp.get('label')),
                'type': source_comp.get('type'),
                'source_type': source_comp.get('source'),
                'workspace_id': source_comp.get('workspace_id')
            }
        }

        # Check if link already exists
        existing = any(
            link['source'] == new_link['source'] and link['target'] == new_link['target']
            for link in st.session_state.scenario_links
        )

        if not existing:
            st.session_state.scenario_links.append(new_link)
            return True
        else:
            st.warning("Link already exists")
            return False

    except Exception as e:
        st.error(f"Error importing physical link: {str(e)}")
        return False


def parse_requirement_pattern(pattern: str) -> Dict[str, str]:
    """Parse requirement pattern into components"""
    parts = pattern.split('.')

    if len(parts) < 3:
        return {'source_type': 'Unknown', 'target_type': 'Unknown', 'valid': False}

    # Skip the first part (usually 'CL' or similar prefix)
    source_type = parts[1]
    target_type = parts[2]

    return {
        'source_type': source_type,
        'target_type': target_type,
        'valid': True
    }


def get_requirement_status(requirement_pattern: str) -> Dict[str, Any]:
    """Get status of a specific requirement pattern"""
    parsed = parse_requirement_pattern(requirement_pattern)

    if not parsed['valid']:
        return {'count': 0, 'links': [], 'status': 'invalid'}

    source_type = parsed['source_type']
    target_type = parsed['target_type']

    # Check if this is an automatic scenario link
    is_automatic = source_type == 'Scenario'

    if is_automatic:
        # Count automatic links for this requirement
        auto_links = [
            link for link in st.session_state.scenario_links
            if (link.get('link_type') == 'scenario_automatic' and
                get_component_type_from_uri(link['target']) == target_type)
        ]
        return {
            'count': len(auto_links),
            'links': auto_links,
            'status': 'automatic'
        }
    else:
        # Count manual links for this requirement
        manual_links = [
            link for link in st.session_state.scenario_links
            if (get_component_type_from_uri(link['source']) == source_type and
                get_component_type_from_uri(link['target']) == target_type and
                link.get('link_type') != 'scenario_automatic')
        ]
        return {
            'count': len(manual_links),
            'links': manual_links,
            'status': 'manual'
        }


def get_all_requirements_with_status() -> List[Dict[str, Any]]:
    """Get all requirements with their current fulfillment status"""
    if not st.session_state.selected_requirements or not st.session_state.scenario_components:
        return []

    requirements = st.session_state.selected_requirements['component_links']
    requirement_status = []

    for req in requirements:
        parsed = parse_requirement_pattern(req)
        if not parsed['valid']:
            continue

        status_info = get_requirement_status(req)

        requirement_status.append({
            'pattern': req,
            'source_type': parsed['source_type'],
            'target_type': parsed['target_type'],
            'status': status_info['status'],
            'count': status_info['count'],
            'links': status_info['links']
        })

    return requirement_status


def get_existing_physical_links_for_requirement(source_comp: Dict[str, Any], target_type: str) -> List[Dict[str, Any]]:
    """Get existing physical links that match a requirement"""
    existing_physical = get_mock_existing_links().get(source_comp['uri'], [])
    return [link for link in existing_physical if link['type'] == target_type]


def display_link_source_info(link: Dict[str, Any], is_source: bool = True):
    """Display enhanced source information for links including workspace context"""
    info_key = 'source_info' if is_source else 'target_info'
    info = link.get(info_key, {})

    if not info:
        # Fallback to basic URI display
        uri = link.get('source' if is_source else 'target', '')
        return get_component_label_by_uri(uri)

    label = info.get('label', 'Unknown')
    source_type = info.get('source_type')
    workspace_id = info.get('workspace_id')

    # Add source badge
    source_badges = {
        'ttl_use_case': '',
        'data_products': '',
        'knowledge_graph': ''
    }

    badge = source_badges.get(source_type, '')
    display_text = f"{badge} {label}" if badge else label

    # Add workspace info for TTL components
    if source_type == 'ttl_use_case' and workspace_id:
        current_workspace = st.session_state.get('current_workspace')
        if current_workspace and current_workspace['id'] == workspace_id:
            workspace_name = current_workspace['name']
            display_text += f" ({workspace_name})"

    return display_text


def create_link_pair_key(source_uri: str, target_uri: str) -> str:
    """Create a unique key for a link pair"""
    return f"{source_uri}→{target_uri}"


def display_requirement_section_optimized(req: Dict[str, Any], req_index: int):
    """Display a single requirement section with system description integration"""
    source_type = req['source_type']
    target_type = req['target_type']

    st.write(f"**Pattern:** `{source_type}` → `{target_type}`")

    # Get system description links for this requirement
    system_desc_links = []
    if SYSTEM_LINKS_AVAILABLE:
        req_pattern = req['pattern']
        system_desc_links = get_system_description_links_for_requirement(req_pattern)

    # Show buttons for system description links
    if system_desc_links:
        source_components = get_components_by_type(source_type)
        target_components = get_components_by_type(target_type)

        # Count which links can be imported - handle both directions
        auto_selectable = 0
        for link in system_desc_links:
            # Check both normal and reversed directions
            source_match = any(c['uri'] in [link['source_uri'], link['target_uri']] for c in source_components)
            target_match = any(c['uri'] in [link['source_uri'], link['target_uri']] for c in target_components)

            link_exists = any(
                (l['source'] == link['source_uri'] and l['target'] == link['target_uri']) or
                (l['source'] == link['target_uri'] and l['target'] == link['source_uri'])
                for l in st.session_state.scenario_links
            )

            if source_match and target_match and not link_exists:
                auto_selectable += 1

        if auto_selectable > 0:
            col1, col2 = st.columns(2)

            with col1:
                if st.button(f"⚡ Auto-Select {auto_selectable} from Graph",
                             key=f"auto_select_{req_index}",
                             type="secondary",
                             use_container_width=True,
                             help="Pre-select checkboxes for links found in system description"):
                    # Set checkboxes - handle direction matching
                    for source_idx, source in enumerate(source_components):
                        for target_idx, target in enumerate(target_components):
                            # Match if either direction matches
                            link_match = any(
                                (link['source_uri'] == source['uri'] and link['target_uri'] == target['uri']) or
                                (link['target_uri'] == source['uri'] and link['source_uri'] == target['uri'])
                                for link in system_desc_links
                            )

                            if link_match:
                                if not any(l['source'] == source['uri'] and l['target'] == target['uri']
                                           for l in st.session_state.scenario_links):
                                    checkbox_key = f"new_link_{req_index}_{source_idx}_{target_idx}"
                                    st.session_state[checkbox_key] = True

                    st.rerun()

            with col2:
                if st.button(f"✅ Link All {auto_selectable} from Graph",
                             key=f"link_all_{req_index}",
                             type="primary",
                             use_container_width=True,
                             help="Directly create all links found in system description"):
                    created = 0
                    for link in system_desc_links:
                        # Try both directions to find components
                        source_comp = next((c for c in source_components
                                            if c['uri'] in [link['source_uri'], link['target_uri']]), None)
                        target_comp = next((c for c in target_components
                                            if c['uri'] in [link['source_uri'], link['target_uri']]), None)

                        if source_comp and target_comp:
                            if not any(l['source'] == source_comp['uri'] and l['target'] == target_comp['uri']
                                       for l in st.session_state.scenario_links):
                                if create_link(source_comp, target_comp, "system_description"):
                                    created += 1

                    if created > 0:
                        st.success(f"✅ Created {created} link(s) from system description")
                        st.rerun()
                    else:
                        st.info("All links already exist")

    # Show existing links
    if req['count'] > 0:
        with st.form(f"existing_links_form_{req_index}"):
            st.write("**Current Links:**")
            links_to_delete = []

            for j, link in enumerate(req['links']):
                source_uri = link.get('source', '')
                target_uri = link.get('target', '')
                source_display = get_uri_fragment(source_uri)
                target_display = get_uri_fragment(target_uri)

                col1, col2 = st.columns([0.5, 4.5])
                with col1:
                    delete_selected = st.checkbox(
                        label="Delete",
                        key=f"delete_link_{req_index}_{j}",
                        label_visibility="collapsed"
                    )
                    if delete_selected:
                        links_to_delete.append(link)

                with col2:
                    st.write(f"**{source_display}** → **{target_display}**")
                    st.caption(f"URIs: `{source_uri}` → `{target_uri}`")
                    link_type = link.get('link_type', 'unknown')
                    system_desc_badge = " (from graph)" if link_type == 'system_description' else ""
                    st.caption(f"Type: {link_type}{system_desc_badge}")

            if st.form_submit_button("Delete Selected", type="secondary"):
                for link in links_to_delete:
                    remove_link(link)
                if links_to_delete:
                    st.success(f"Deleted {len(links_to_delete)} link(s)")
                    st.rerun()

    # Get components for manual linking
    source_components = get_components_by_type(source_type)
    target_components = get_components_by_type(target_type)

    if source_components and target_components:
        # Create new links form with VERTICAL CHECKBOX LAYOUT
        with st.form(f"create_links_form_{req_index}"):
            st.write("**Create New Links:**")
            st.caption("Select source-target pairs to create links between components")

            # Track new links to create
            new_links_to_create = []

            # VERTICAL CHECKBOX LAYOUT
            for source_idx, source in enumerate(source_components):
                source_label = get_uri_fragment(source.get('uri', ''))

                st.write(f"**{source_label} → {target_type} Components**")
                st.caption(f"Source: {source.get('source', 'unknown')}")

                # Show targets in vertical list with checkboxes
                for target_idx, target in enumerate(target_components):
                    target_label = get_uri_fragment(target.get('uri', ''))
                    target_source = target.get('source', 'unknown')

                    # Check if link already exists
                    link_exists = any(
                        link['source'] == source['uri'] and link['target'] == target['uri']
                        for link in st.session_state.scenario_links
                    )

                    # Check if this link is available in system description
                    in_system_desc = False
                    if system_desc_links:
                        in_system_desc = any(
                            (sd_link['source_uri'] == source['uri'] and sd_link['target_uri'] == target['uri']) or
                            (sd_link['source_uri'] == target['uri'] and sd_link['target_uri'] == source['uri'])
                            for sd_link in system_desc_links
                        )

                    col1, col2, col3 = st.columns([0.5, 3.5, 1])

                    with col1:
                        if not link_exists:
                            link_key = f"new_link_{req_index}_{source_idx}_{target_idx}"
                            selected = st.checkbox(
                                label="Link",
                                key=link_key,
                                label_visibility="collapsed"
                            )
                            if selected:
                                new_links_to_create.append((source, target))
                        else:
                            st.write("✅")

                    with col2:
                        status = " ✅" if link_exists else ""
                        graph_indicator = " 🔗" if in_system_desc else ""
                        st.write(f"**{target_label}**{status}{graph_indicator}")
                        st.caption(f"URI: `{target['uri']}`")
                        st.caption(f"Source: {target_source}")

                    with col3:
                        if target.get('attributes'):
                            st.caption("Has attributes")

                # Add separator between source components if there are multiple
                if source_idx < len(source_components) - 1:
                    st.markdown("---")

            st.markdown("---")

            # Form submit buttons (REQUIRED)
            col1, col2 = st.columns(2)
            with col1:
                # Create selected links
                create_button = st.form_submit_button("Create Selected Links", type="primary")

            with col2:
                # Clear selections (form rerun)
                clear_button = st.form_submit_button("Clear Selections", type="secondary")

            # Handle form submission
            if create_button:
                created_count = 0
                for source, target in new_links_to_create:
                    if create_link(source, target, "scenario"):
                        created_count += 1

                if created_count > 0:
                    st.success(f"Created {created_count} link(s)")
                    st.rerun()
                elif new_links_to_create:
                    st.info("No new links were created (may already exist)")
                else:
                    st.info("No links selected for creation")

            elif clear_button:
                # Clear selections by rerunning
                st.rerun()

        # Import physical links section
        st.markdown("---")

        # Check if there are any physical links to show
        has_physical_links = any(
            get_existing_physical_links_for_requirement(source_comp, target_type)
            for source_comp in source_components
        )

        if has_physical_links:
            # Create form for importing physical links
            with st.form(f"import_links_form_{req_index}"):
                st.write("**Import Physical Links:**")
                st.caption("Select existing physical links to import into the scenario")

                physical_links_to_import = []

                for source_comp in source_components:
                    existing_physical = get_existing_physical_links_for_requirement(source_comp, target_type)

                    if existing_physical:
                        source_label = source_comp.get('uri_fragment', source_comp.get('label', get_uri_fragment(source_comp.get('uri', ''))))

                        for phys_link in existing_physical:
                            target_label = get_component_label_by_uri(phys_link['target'])

                            # Check if already imported
                            already_imported = any(
                                link['source'] == source_comp['uri'] and link['target'] == phys_link['target']
                                for link in st.session_state.scenario_links
                            )

                            if not already_imported:
                                import_key = f"import_{req_index}_{source_comp['uri']}_{phys_link['target']}"
                                selected = st.checkbox(
                                    f"{source_label} → {target_label}",
                                    key=import_key
                                )

                                if selected:
                                    physical_links_to_import.append((source_comp, phys_link))
                            else:
                                st.caption(f"✅ {source_label} → {target_label} (already imported)")

                if st.form_submit_button("Import Selected Physical Links", type="secondary"):
                    imported_count = 0
                    for source_comp, phys_link in physical_links_to_import:
                        if import_physical_link(source_comp, phys_link):
                            imported_count += 1

                    if imported_count > 0:
                        st.success(f"Imported {imported_count} physical link(s)")
                        st.rerun()
                    elif not physical_links_to_import:
                        st.info("No links selected for import")

    elif not source_components:
        st.info(f"Add {source_type} components in Tab 1 to create links")
    elif not target_components:
        st.info(f"Add {target_type} components in Tab 1 to create links")


def create_link_from_uris(source_uri: str, target_uri: str, link_type: str = "system_description") -> bool:
    """
    Create a link from URIs (for system description imports)
    """
    source_comp = None
    target_comp = None

    # Find components in scenario by URI
    for comp in st.session_state.get('scenario_components', []):
        if comp.get('uri') == source_uri:
            source_comp = comp
        if comp.get('uri') == target_uri:
            target_comp = comp

    if not source_comp or not target_comp:
        return False

    return create_link(source_comp, target_comp, link_type)


def display_discovered_links_interface(discovered_links: List[Dict[str, Any]]):
    """
    Display interface for discovered links with bulk import capability
    """
    st.success(f"Found {len(discovered_links)} links in knowledge graph")

    # Get requirements
    requirements = st.session_state.get('selected_requirements', {})
    requirement_patterns = requirements.get('component_links', [])

    if not requirement_patterns:
        st.warning("No requirement patterns defined in YAML")
        return

    # Match links to requirements
    link_query = get_system_link_query()
    matched_links = link_query.match_links_to_requirements(discovered_links, requirement_patterns)

    if not matched_links:
        st.info("No discovered links match your YAML requirements")

        # Show unmatched links in expander
        with st.expander("Show All Discovered Links", expanded=False):
            for link in discovered_links:
                status = get_link_import_status(link)
                display_str = format_link_display(link,
                                                  status['source_in_scenario'],
                                                  status['target_in_scenario'])
                st.write(f"• {display_str}")
                st.caption(f"  Types: {link['source_type']} →[{link['link_property']}]→ {link['target_type']}")
        return

    # Display matched links grouped by requirement
    st.write("**Links Detected in Knowledge Graph:**")

    for req_pattern, links in matched_links.items():
        parsed = parse_requirement_pattern(req_pattern)
        source_type = parsed['source_type']
        target_type = parsed['target_type']

        with st.expander(f"**Requirement:** `{req_pattern}` ({len(links)} links found)", expanded=True):
            st.write(f"**Pattern:** `{source_type}` → `{target_type}`")
            st.caption(f"Found {len(links)} matching relationship(s) in the knowledge graph")

            # Group links by source component
            grouped_links = link_query.group_links_by_source(links)

            # Form for bulk import
            with st.form(f"import_system_links_{req_pattern}"):
                # Track which links CAN be imported (don't disable button)
                importable_links = []
                checkbox_keys = []

                for source_uri, source_links in grouped_links.items():
                    source_label = get_uri_fragment(source_uri)

                    st.write(f"**Source: {source_label}**")

                    for idx, link in enumerate(source_links):
                        status = get_link_import_status(link)

                        col1, col2, col3 = st.columns([0.5, 3.5, 1])

                        with col1:
                            if status['can_import']:
                                checkbox_key = f"system_link_{req_pattern}_{source_uri}_{idx}"
                                st.checkbox(
                                    "Import",
                                    key=checkbox_key,
                                    label_visibility="collapsed"
                                )
                                # Track this as importable
                                importable_links.append(link)
                                checkbox_keys.append(checkbox_key)
                            elif status['link_exists']:
                                st.write("✅")
                            else:
                                st.write("⚪")

                        with col2:
                            target_label = link['target_label']
                            link_prop = link['link_property']

                            if status['link_exists']:
                                st.write(f"✅ **{target_label}** _(already linked)_")
                            elif status['can_import']:
                                st.write(f"**{target_label}** _[{link_prop}]_")
                            else:
                                st.write(f"⚪ **{target_label}** _[{link_prop}]_")

                            # Show what's missing
                            if status['needs_components']:
                                missing_parts = []
                                if status['missing_source']:
                                    missing_parts.append("source not in scenario")
                                if status['missing_target']:
                                    missing_parts.append("target not in scenario")
                                st.caption(f"Cannot import: {', '.join(missing_parts)}")

                        with col3:
                            # Status indicators
                            if status['source_in_scenario'] and status['target_in_scenario']:
                                if status['link_exists']:
                                    st.caption("✅ Linked")
                                else:
                                    st.caption("Ready")
                            else:
                                st.caption("Missing components")

                    st.markdown("---")

                # Submit button - don't disable, we'll check checkboxes on submit
                col1, col2 = st.columns(2)
                with col1:
                    import_button = st.form_submit_button(
                        "Import Selected Links",
                        type="primary"
                    )

                with col2:
                    cancel_button = st.form_submit_button("Cancel", type="secondary")

                if import_button:
                    # Now check which checkboxes were actually selected
                    selected_links = []
                    for i, checkbox_key in enumerate(checkbox_keys):
                        if st.session_state.get(checkbox_key, False):
                            selected_links.append(importable_links[i])

                    if not selected_links:
                        st.warning("No links selected. Please check the boxes next to links you want to import.")
                    else:
                        if not selected_links:
                            st.warning("No links selected. Please check the boxes next to links you want to import.")
                        else:
                            imported_count = 0
                            failed_count = 0

                            for link in selected_links:
                                if create_link_from_uris(
                                        link['source_uri'],
                                        link['target_uri'],
                                        link_type="system_description"
                                ):
                                    imported_count += 1
                                else:
                                    failed_count += 1

                            if imported_count > 0:
                                st.success(f"✅ Successfully imported {imported_count} link(s) from knowledge graph")
                            if failed_count > 0:
                                st.warning(f"⚠️ Failed to import {failed_count} link(s)")

                            # Clear discovered links and rerun
                            if 'discovered_system_links' in st.session_state:
                                del st.session_state.discovered_system_links
                            st.rerun()

                if cancel_button:
                    # Clear discovered links
                    if 'discovered_system_links' in st.session_state:
                        del st.session_state.discovered_system_links
                    st.rerun()


def tab_manage_links():
    """Tab 2: Manage component links with integrated system description support"""
    st.subheader("Manage Component Links")

    if not st.session_state.selected_requirements:
        st.warning("Please select service requirements first")
        return

    if not st.session_state.scenario_components:
        st.warning("Please add components in Tab 1 first")
        return

    current_workspace = st.session_state.get('current_workspace')
    if current_workspace:
        st.info(f"Working in workspace: **{current_workspace['name']}**")

    # Get all requirements with status
    requirement_status = get_all_requirements_with_status()

    if not requirement_status:
        st.warning("No valid requirements found")
        return

    # Show automatic scenario links
    automatic_reqs = [req for req in requirement_status if req['status'] == 'automatic']
    if automatic_reqs:
        with st.expander("Automatic Scenario Links", expanded=False):
            st.info("These links are created automatically when you add components:")
            for req in automatic_reqs:
                if req['count'] > 0:
                    st.write(f"✅ **{req['pattern']}** - {req['count']} link(s)")
                    for link in req['links']:
                        target_label = get_uri_fragment(link.get('target', ''))
                        st.caption(f"   • Scenario → {target_label}")
                else:
                    st.write(f"⚪ **{req['pattern']}** - No components added yet")

    # Show manual requirements with integrated system description
    manual_reqs = [req for req in requirement_status if req['status'] == 'manual']

    if not manual_reqs:
        st.success("✅ All requirements handled automatically!")
        return

    st.write("**Manual Component Relationships:**")
    st.info("🔗 indicates links available in the knowledge graph system description")

    # Process each requirement
    for i, req in enumerate(manual_reqs):
        requirement_title = f"Requirement {i + 1}: {req['pattern']}"
        if req['count'] > 0:
            requirement_title += f" ✅ ({req['count']} link(s))"
        else:
            requirement_title += " ⚪ (0 links)"

        with st.expander(requirement_title, expanded=req['count'] == 0):
            display_requirement_section_optimized(req, i)

    # Summary
    st.markdown("---")
    st.write("**Requirements Summary:**")

    total_requirements = len(requirement_status)
    fulfilled_requirements = len([req for req in requirement_status if req['count'] > 0])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Requirements", total_requirements)
    with col2:
        st.metric("Fulfilled", fulfilled_requirements)
    with col3:
        st.metric("Unfulfilled", total_requirements - fulfilled_requirements)
    with col4:
        completion_pct = int((fulfilled_requirements / total_requirements * 100)) if total_requirements > 0 else 0
        st.metric("Completion", f"{completion_pct}%")