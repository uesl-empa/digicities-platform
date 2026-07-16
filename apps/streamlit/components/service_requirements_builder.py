# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import streamlit as st
import yaml
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
import re

from backend.graphdb import queries as gdb_queries

# Try to import rdflib
try:
    import rdflib
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False
    st.error("⚠️ rdflib is required for the Service Requirements Builder. Please install with: pip install rdflib")

# Import GraphDB client (matches the pattern from component_explorer.py)
try:
    from components.graphdb import GraphDBClient

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False
    st.error("⚠️ Triplestore client not available. Please check your installation.")

# Define namespaces
DICI_ONTO = Namespace("https://digicities.info/ontology#")
RDFS_NS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
OWL_NS = Namespace("http://www.w3.org/2002/07/owl#")


@dataclass
class ComponentClass:
    """Represents a component class from the ontology"""
    uri: str
    label: str
    parent_classes: List[str]
    attributes: List[str]


@dataclass
class AttributeClass:
    """Represents an attribute class from the ontology"""
    uri: str
    label: str
    domain: str
    range_type: str
    unit: Optional[str] = None


@dataclass
class ComponentEntry:
    """Represents a component entry in the YAML structure"""
    path: str
    component_type: str
    link_pattern: str
    parent_path: str = ""
    level: int = 1
    configured_attributes: Dict[str, List[str]] = field(default_factory=dict)


def initialize_session_state():
    """Initialize session state for the requirements builder"""
    if 'service_name' not in st.session_state:
        st.session_state.service_name = ""
    if 'service_description' not in st.session_state:
        st.session_state.service_description = ""
    if 'service_connection' not in st.session_state:
        # Template-level `connection:` block (where the service listens). The
        # builder doesn't model it as a component, but preserves it verbatim so
        # loading and re-saving a service keeps its auto-registration block.
        st.session_state.service_connection = None
    if 'component_entries' not in st.session_state:
        st.session_state.component_entries = []
    if 'ontology_uploaded' not in st.session_state:
        st.session_state.ontology_uploaded = False
    if 'ontology_components' not in st.session_state:
        st.session_state.ontology_components = {}
    if 'ontology_attributes' not in st.session_state:
        st.session_state.ontology_attributes = {}
    if 'component_attribute_mappings' not in st.session_state:
        st.session_state.component_attribute_mappings = {}
    if 'graphdb_components' not in st.session_state:
        st.session_state.graphdb_components = {}
    if 'graphdb_attributes' not in st.session_state:
        st.session_state.graphdb_attributes = {}
    if 'custom_field_names' not in st.session_state:
        st.session_state.custom_field_names = {}  # Maps default_field_name -> custom_field_name
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False


def extract_local_name(uri: str) -> str:
    """Extract the local name from a URI"""
    if '#' in uri:
        return uri.split('#')[-1]
    elif '/' in uri:
        return uri.split('/')[-1]
    return uri


def parse_ontology_file(uploaded_file) -> Tuple[Dict[str, ComponentClass], Dict[str, AttributeClass]]:
    """Parse uploaded ontology file using rdflib"""
    if not RDFLIB_AVAILABLE:
        st.error("rdflib is not installed. Cannot parse ontology file.")
        return {}, {}

    try:
        file_content = uploaded_file.read()
        g = Graph()

        try:
            g.parse(data=file_content, format='turtle')
        except:
            try:
                g.parse(data=file_content, format='xml')
            except:
                try:
                    g.parse(data=file_content, format='n3')
                except Exception as e:
                    st.error(f"Could not parse ontology file: {e}")
                    return {}, {}

        components = {}
        attributes = {}

        component_query = """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?class ?label WHERE {
            ?class rdfs:subClassOf* dici_onto:Component .
            OPTIONAL { ?class rdfs:label ?label }
        }
        """

        attribute_query = """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?class ?label WHERE {
            {
                ?class rdfs:subClassOf* dici_onto:StaticAttribute .
            }
            UNION
            {
                ?class rdfs:subClassOf* dici_onto:DynamicAttribute .
            }
            OPTIONAL { ?class rdfs:label ?label }
        }
        """

        try:
            for row in g.query(component_query):
                class_uri = str(row.class_)
                class_name = extract_local_name(class_uri)
                label = str(row.label) if row.label else class_name

                components[class_name] = ComponentClass(
                    uri=class_uri,
                    label=label,
                    parent_classes=[],
                    attributes=[]
                )

            for row in g.query(attribute_query):
                attr_uri = str(row.class_)
                attr_name = extract_local_name(attr_uri)
                label = str(row.label) if row.label else attr_name

                attributes[attr_name] = AttributeClass(
                    uri=attr_uri,
                    label=label,
                    domain="",
                    range_type="string"
                )

        except Exception as e:
            st.warning(f"SPARQL queries failed, falling back to basic RDF parsing: {e}")

            for subj, pred, obj in g:
                if pred == RDFS_NS.subClassOf and obj == DICI_ONTO.Component:
                    class_name = extract_local_name(str(subj))
                    components[class_name] = ComponentClass(
                        uri=str(subj),
                        label=class_name,
                        parent_classes=[],
                        attributes=[]
                    )

        st.success(f"Parsed ontology: {len(components)} components, {len(attributes)} attributes")
        return components, attributes

    except Exception as e:
        st.error(f"Error parsing ontology file: {e}")
        return {}, {}


def query_graphdb_components(client) -> Tuple[Dict[str, ComponentClass], Dict[str, AttributeClass]]:
    """Query GraphDB for all components and attributes"""
    if not client:
        st.warning("No Triplestore client available")
        return {}, {}

    components = {}
    attributes = {}

    try:
        comp_df = gdb_queries.get_component_classes(client)
        for _, row in comp_df.iterrows():
            class_uri = row['class']
            class_name = extract_local_name(class_uri)
            label = row.get('label', class_name) if pd.notna(row.get('label')) else class_name

            components[class_name] = ComponentClass(
                uri=class_uri,
                label=label,
                parent_classes=[],
                attributes=[]
            )

        attr_df = gdb_queries.get_attribute_classes(client)
        for _, row in attr_df.iterrows():
            attr_uri = row['class']
            attr_name = extract_local_name(attr_uri)
            label = row.get('label', attr_name) if pd.notna(row.get('label')) else attr_name

            attributes[attr_name] = AttributeClass(
                uri=attr_uri,
                label=label,
                domain="",
                range_type="string"
            )

        st.success(f"Retrieved from Triplestore: {len(components)} components, {len(attributes)} attributes")
        return components, attributes

    except Exception as e:
        st.error(f"Error querying Triplestore for components: {e}")
        return {}, {}


def query_graphdb_component_attributes_new(client) -> Dict[str, List[str]]:
    """Query GraphDB for component-attribute mappings using naming convention"""
    if not client:
        return {}

    try:
        components_result = gdb_queries.get_component_subclasses(client)

        if components_result is None or components_result.empty:
            st.warning("No components found in Triplestore")
            return {}

        component_attributes = {}

        for _, row in components_result.iterrows():
            component_uri = row['component']
            component_name = extract_local_name(component_uri)

            attribute_class_name = f"{component_name}Attribute"

            try:
                attributes_result = gdb_queries.get_attribute_subclasses_for(client, attribute_class_name)

                if attributes_result is not None and not attributes_result.empty:
                    component_attributes[component_name] = []

                    for _, attr_row in attributes_result.iterrows():
                        attr_uri = attr_row['attribute']
                        attr_name = extract_local_name(attr_uri)

                        if attr_name not in component_attributes[component_name]:
                            component_attributes[component_name].append(attr_name)

                    if 'label' not in component_attributes[component_name]:
                        component_attributes[component_name].insert(0, 'label')

                else:
                    component_attributes[component_name] = ['label']

            except Exception as attr_e:
                st.warning(f"Could not find attributes for {component_name}: {attr_e}")
                component_attributes[component_name] = ['label']
                continue

        st.success(f"Retrieved component-attribute mappings for {len(component_attributes)} components using naming convention")
        return component_attributes

    except Exception as e:
        st.error(f"Error querying Triplestore with new method: {e}")
        return {}


def query_graphdb_component_attributes(client) -> Dict[str, List[str]]:
    """Query GraphDB for component-attribute mappings"""
    if not client:
        return {}

    component_attributes = query_graphdb_component_attributes_new(client)

    if component_attributes:
        return component_attributes

    st.info("Falling back to original object property method...")

    try:
        result = gdb_queries.get_component_attribute_object_properties(client)

        if result is not None and not result.empty:
            component_attributes = {}

            for _, row in result.iterrows():
                component_uri = row['component']
                attribute_uri = row['attribute']

                component_name = extract_local_name(component_uri)
                attribute_name = extract_local_name(attribute_uri)

                if component_name not in component_attributes:
                    component_attributes[component_name] = []

                if attribute_name not in component_attributes[component_name]:
                    component_attributes[component_name].append(attribute_name)

            st.success(f"Retrieved component-attribute mappings for {len(component_attributes)} components (fallback method)")
            return component_attributes
        else:
            st.info("No component-attribute mappings found in Triplestore")
            return {}

    except Exception as e:
        st.error(f"Error querying Triplestore: {e}")
        return {}


def get_current_ontology_data():
    """Get current ontology data from session state"""
    components = {}
    attributes = {}

    if st.session_state.ontology_components:
        components.update(st.session_state.ontology_components)

    if st.session_state.graphdb_components:
        components.update(st.session_state.graphdb_components)

    if st.session_state.ontology_attributes:
        attributes.update(st.session_state.ontology_attributes)

    if st.session_state.graphdb_attributes:
        attributes.update(st.session_state.graphdb_attributes)

    return components, attributes


def generate_yaml_structure(use_custom_names=True) -> Dict:
    """Generate the complete YAML structure with optional custom field names"""
    if not st.session_state.service_name:
        return {}

    structure = {'service_name': st.session_state.service_name}
    # Preserve template-level metadata (order matches the shipped service
    # templates: service_name, description, connection, scenario_data).
    if st.session_state.get('service_description'):
        structure['description'] = st.session_state.service_description
    if st.session_state.get('service_connection'):
        structure['connection'] = st.session_state.service_connection
    structure['scenario_data'] = {
        'uri': 'Scenario.URI',
        'label': 'Scenario.label'
    }

    def get_field_name(default_name, component_path, attr_name, attr_type):
        """Get the field name, using custom name if available and requested"""
        key = f"{component_path}|{attr_name}|{attr_type}"
        if use_custom_names and key in st.session_state.custom_field_names:
            return st.session_state.custom_field_names[key]
        return default_name

    def build_nested_structure(entries, parent_path=""):
        result = {}

        for entry in entries:
            if entry.parent_path == parent_path:
                if entry.level == 1:
                    entry_structure = {
                        'name': f'{entry.component_type}.label',
                        'uri': f'{entry.component_type}.URI'
                    }
                else:
                    entry_structure = {
                        'link': entry.link_pattern,
                        'template': {
                            'uri': f'{entry.component_type}.URI'
                        }
                    }

                for attr_name, attr_types in entry.configured_attributes.items():
                    for attr_type in attr_types:
                        if attr_type == "Static":
                            if attr_name == "label":
                                continue
                            else:
                                default_field_name = attr_name
                                field_name = get_field_name(default_field_name, entry.path, attr_name, attr_type)
                                reference = f'{entry.component_type}.{attr_name}'
                        else:
                            default_field_name = f"{attr_name}_{attr_type.lower()}"
                            field_name = get_field_name(default_field_name, entry.path, attr_name, attr_type)

                            ts_reference_map = {
                                'Historic': 'hasHistoricTimeSeriesReference',
                                'Live': 'hasLiveTimeSeriesReference',
                                'Future': 'hasFutureTimeSeriesReference'
                            }
                            ts_reference = ts_reference_map.get(attr_type, 'hasHistoricTimeSeriesReference')
                            reference = f'{entry.component_type}.{attr_name}.{ts_reference}'

                        if entry.level == 1:
                            if not (attr_name == "label" and attr_type == "Static" and "name" in entry_structure):
                                entry_structure[field_name] = reference
                        else:
                            if attr_name == "label" and attr_type == "Static":
                                entry_structure['template']['label'] = reference
                            else:
                                entry_structure['template'][field_name] = reference

                children = build_nested_structure(entries, entry.path)
                if children:
                    for child_key, child_value in children.items():
                        entry_structure[child_key] = child_value

                result[entry.path] = entry_structure

        return result

    nested_structure = build_nested_structure(st.session_state.component_entries)
    structure['scenario_data'].update(nested_structure)

    return structure


def validate_component_attributes() -> Dict[str, Any]:
    """
    Validate that all configured component-attribute pairs exist in the ontology mappings
    Returns a validation report with errors, warnings, and successes
    """
    validation_report = {
        'errors': [],
        'warnings': [],
        'successes': [],
        'summary': {
            'total_attributes': 0,
            'valid_attributes': 0,
            'invalid_attributes': 0,
            'unmapped_components': 0
        }
    }

    if not st.session_state.component_entries:
        validation_report['warnings'].append("No components configured to validate")
        return validation_report

    components, attributes = get_current_ontology_data()

    for entry in st.session_state.component_entries:
        component_name = entry.component_type
        component_path = entry.path

        # Check if component exists in ontology
        if component_name not in components:
            validation_report['errors'].append({
                'type': 'UNKNOWN_COMPONENT',
                'component': component_name,
                'path': component_path,
                'message': f"Component '{component_name}' not found in ontology"
            })
            validation_report['summary']['unmapped_components'] += 1
            continue

        # Check if component has any mapped attributes
        if (component_name not in st.session_state.component_attribute_mappings or
                not st.session_state.component_attribute_mappings[component_name]):
            validation_report['warnings'].append({
                'type': 'NO_MAPPINGS',
                'component': component_name,
                'path': component_path,
                'message': f"Component '{component_name}' has no attribute mappings in Triplestore"
            })
            validation_report['summary']['unmapped_components'] += 1

        # Get valid attributes for this component
        valid_attributes = []
        if component_name in st.session_state.component_attribute_mappings:
            valid_attributes = st.session_state.component_attribute_mappings[component_name]

        # Check each configured attribute
        for attr_name, attr_types in entry.configured_attributes.items():
            validation_report['summary']['total_attributes'] += 1

            # Special case: 'label' is always valid
            if attr_name == 'label':
                validation_report['successes'].append({
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"✓ Standard attribute 'label' is valid"
                })
                validation_report['summary']['valid_attributes'] += 1
                continue

            # Check if attribute is in the valid list for this component
            if attr_name in valid_attributes:
                validation_report['successes'].append({
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"✓ Attribute '{attr_name}' is valid for '{component_name}'"
                })
                validation_report['summary']['valid_attributes'] += 1
            else:
                validation_report['errors'].append({
                    'type': 'INVALID_ATTRIBUTE',
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"Attribute '{attr_name}' is not valid for component '{component_name}'",
                    'suggestion': f"Valid attributes for '{component_name}': {', '.join(valid_attributes) if valid_attributes else 'None'}"
                })
                validation_report['summary']['invalid_attributes'] += 1

    return validation_report


def display_validation_report(report: Dict[str, Any]):
    """Display the validation report in a user-friendly format"""

    # Summary metrics
    st.write("### 📊 Validation Summary")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Attributes", report['summary']['total_attributes'])
    with col2:
        st.metric("✅ Valid", report['summary']['valid_attributes'])
    with col3:
        st.metric("❌ Invalid", report['summary']['invalid_attributes'])
    with col4:
        st.metric("⚠️ Unmapped Components", report['summary']['unmapped_components'])

    st.write("---")

    # Overall status
    if report['summary']['invalid_attributes'] > 0 or report['summary']['unmapped_components'] > 0:
        st.error("❌ **Validation Failed** - Please review and fix the errors below")
    elif report['summary']['total_attributes'] == 0:
        st.info("ℹ️ No attributes configured yet")
    else:
        st.success("✅ **All Validations Passed** - Your configuration is valid!")

    st.write("---")

    # Errors section
    if report['errors']:
        with st.expander(f"❌ Errors ({len(report['errors'])})", expanded=True):
            for error in report['errors']:
                if error['type'] == 'UNKNOWN_COMPONENT':
                    st.error(f"**{error['path']}**: {error['message']}")
                elif error['type'] == 'INVALID_ATTRIBUTE':
                    st.error(
                        f"**{error['path']}.{error['attribute']}** ({', '.join(error['types'])})\n\n"
                        f"{error['message']}\n\n"
                        f"💡 {error['suggestion']}"
                    )

    # Warnings section
    if report['warnings']:
        with st.expander(f"⚠️ Warnings ({len(report['warnings'])})", expanded=False):
            for warning in report['warnings']:
                st.warning(f"**{warning['path']}**: {warning['message']}")

    # Successes section
    if report['successes']:
        with st.expander(f"✅ Valid Attributes ({len(report['successes'])})", expanded=False):
            # Group by component for better readability
            by_component = {}
            for success in report['successes']:
                comp_key = f"{success['path']} ({success['component']})"
                if comp_key not in by_component:
                    by_component[comp_key] = []
                by_component[comp_key].append(success)

            for comp_key, successes in by_component.items():
                st.write(f"**{comp_key}**")
                for success in successes:
                    types_str = ', '.join(success['types'])
                    st.success(f"  • {success['attribute']} [{types_str}]")


def get_validation_suggestions(report: Dict[str, Any]) -> List[str]:
    """Generate actionable suggestions based on validation report"""
    suggestions = []

    if report['summary']['unmapped_components'] > 0:
        suggestions.append("🔄 **Reload component-attribute mappings** from Triplestore in the Data Source tab")

    if report['summary']['invalid_attributes'] > 0:
        suggestions.append("🗑️ **Remove invalid attributes** from the Attributes tab")
        suggestions.append("🔍 **Check ontology** to verify which attributes are valid for each component")

    if report['summary']['total_attributes'] == 0:
        suggestions.append("🎯 **Configure attributes** for your components in the Attributes tab")

    if not st.session_state.component_attribute_mappings:
        suggestions.append("📊 **Load Triplestore mappings** to enable validation")

    return suggestions


def parse_yaml_to_components(yaml_content: str) -> Tuple[str, List[ComponentEntry]]:
    """
    Parse a YAML file and extract components and their attributes
    Returns: (service_name, list of ComponentEntry objects)
    """
    try:
        yaml_data = yaml.safe_load(yaml_content)

        if not yaml_data or 'service_name' not in yaml_data:
            raise ValueError("Invalid YAML: missing 'service_name' field")

        service_name = yaml_data['service_name']
        scenario_data = yaml_data.get('scenario_data', {})

        component_entries = []

        def extract_component_type_from_reference(ref: str) -> str:
            """Extract component type from a reference like 'ComponentType.attribute'"""
            if isinstance(ref, str) and '.' in ref:
                return ref.split('.')[0]
            return ""

        def parse_component(key, value, parent_path="", parent_component_type="", level=1):
            """Recursively parse component structure"""
            # Skip metadata fields
            if key in ['uri', 'label', 'name']:
                return None

            entry = ComponentEntry(
                path=key,
                component_type="",
                link_pattern="",
                parent_path=parent_path,
                level=level,
                configured_attributes={}
            )

            if not isinstance(value, dict):
                return None

            # Check if this is a child component (has 'link' and 'template')
            if 'link' in value and 'template' in value:
                # Child component
                entry.link_pattern = value['link']

                # Extract component type from link pattern (CL.Parent.ComponentType)
                if entry.link_pattern.startswith('CL.'):
                    parts = entry.link_pattern.split('.')
                    if len(parts) >= 3:
                        entry.component_type = parts[2]

                # Parse attributes from template
                template = value.get('template', {})
                if 'uri' in template:
                    # Also try to get component type from URI if not found in link
                    if not entry.component_type:
                        entry.component_type = extract_component_type_from_reference(template['uri'])

                entry.configured_attributes = extract_attributes_from_dict(template, entry.component_type)

                # Nested child components can live either INSIDE the template
                # (hand-written services like the demo energy simulator, where
                # `buildings` sits under the location's template) or as SIBLINGS of
                # link/template (services exported by this builder). Look in both
                # so any valid service loads its full component tree, not just the
                # top level. (Without this, a template-nested child like Building —
                # and all its attributes — was silently dropped.)
                child_candidates = {}
                child_candidates.update(template)
                child_candidates.update({k: v for k, v in value.items()
                                         if k not in ('link', 'template')})
                for child_key, child_value in child_candidates.items():
                    if child_key in ('uri', 'label', 'name'):
                        continue
                    if isinstance(child_value, dict):
                        child_entry = parse_component(child_key, child_value, key, entry.component_type, level + 1)
                        if child_entry:
                            component_entries.append(child_entry)

            # Check if this is a root component (has 'uri' and either 'label' or 'name')
            elif 'uri' in value and ('label' in value or 'name' in value):
                # Root component
                entry.level = 1
                entry.link_pattern = ""

                # Extract component type from URI reference
                uri_ref = value.get('uri', '')
                entry.component_type = extract_component_type_from_reference(uri_ref)

                # If still no component type, try from label/name
                if not entry.component_type:
                    label_ref = value.get('label') or value.get('name')
                    entry.component_type = extract_component_type_from_reference(label_ref)

                # Parse attributes from the component dict
                entry.configured_attributes = extract_attributes_from_dict(value, entry.component_type)

                # Process nested children
                for child_key, child_value in value.items():
                    if child_key not in ['label', 'name', 'uri'] and isinstance(child_value, dict):
                        child_entry = parse_component(child_key, child_value, key, entry.component_type, level + 1)
                        if child_entry:
                            component_entries.append(child_entry)

            return entry if entry.component_type else None

        # Parse all top-level components in scenario_data
        for key, value in scenario_data.items():
            if key not in ['uri', 'label', 'name']:
                entry = parse_component(key, value)
                if entry:
                    component_entries.append(entry)

        return service_name, component_entries

    except Exception as e:
        raise ValueError(f"Error parsing YAML: {str(e)}")


def extract_attributes_from_dict(data_dict: Dict, component_type: str) -> Dict[str, List[str]]:
    """
    Extract attributes and their types from a component dictionary
    Returns: Dict mapping attribute names to list of types
    """
    attributes = {}

    for key, value in data_dict.items():
        if key in ['uri', 'link', 'template']:
            continue

        # Parse the reference to determine attribute name and type
        if isinstance(value, str) and component_type and component_type in value:
            # Format: ComponentType.AttributeName or ComponentType.AttributeName.hasXTimeSeriesReference
            parts = value.split('.')

            if len(parts) >= 2:
                attr_name = parts[1]

                # Backward compatibility: if field name is 'name' and reference is to 'label', convert to 'label'
                if key == 'name' and attr_name == 'label':
                    key = 'label'

                # Determine type based on field name and reference
                if len(parts) == 2:
                    # Static attribute
                    attr_type = "Static"
                elif len(parts) == 3:
                    # Dynamic attribute with time series reference
                    ts_ref = parts[2]
                    if 'Historic' in ts_ref:
                        attr_type = "Historic"
                    elif 'Live' in ts_ref:
                        attr_type = "Live"
                    elif 'Future' in ts_ref:
                        attr_type = "Future"
                    else:
                        attr_type = "Static"
                else:
                    attr_type = "Static"

                # Handle field names with suffixes like attr_historic, attr_live, etc.
                if key.endswith('_historic'):
                    attr_name = key.replace('_historic', '')
                    attr_type = "Historic"
                elif key.endswith('_live'):
                    attr_name = key.replace('_live', '')
                    attr_type = "Live"
                elif key.endswith('_future'):
                    attr_name = key.replace('_future', '')
                    attr_type = "Future"

                # Add to attributes dict
                if attr_name not in attributes:
                    attributes[attr_name] = []
                if attr_type not in attributes[attr_name]:
                    attributes[attr_name].append(attr_type)

        # A nested dict that is itself a child component (has link+template, or
        # uri+label/name) is parsed separately by parse_component — don't fold its
        # fields into this component's attributes. Recurse only into other nested
        # structures.
        elif isinstance(value, dict):
            if ('link' in value and 'template' in value) or \
                    ('uri' in value and ('label' in value or 'name' in value)):
                continue
            nested_attrs = extract_attributes_from_dict(value, component_type)
            for attr_name, types in nested_attrs.items():
                if attr_name not in attributes:
                    attributes[attr_name] = []
                for attr_type in types:
                    if attr_type not in attributes[attr_name]:
                        attributes[attr_name].append(attr_type)

    return attributes


def load_yaml_configuration(yaml_content: str) -> bool:
    """
    Load a YAML configuration and populate the session state
    Returns True if successful, False otherwise
    """
    try:
        service_name, component_entries = parse_yaml_to_components(yaml_content)

        # Update session state
        st.session_state.service_name = service_name
        st.session_state.component_entries = component_entries

        # Preserve template-level metadata the builder doesn't model as
        # components — the `connection:` block (where the service listens, used
        # for auto-registration) and the description — so a load → edit → save
        # round-trip keeps them instead of silently dropping them.
        raw = yaml.safe_load(yaml_content) or {}
        st.session_state.service_connection = raw.get('connection')
        if raw.get('description'):
            st.session_state.service_description = raw['description']

        return True

    except Exception as e:
        st.error(f"Failed to load YAML: {str(e)}")
        return False


def get_all_yaml_fields():
    """Extract all editable field names from the current configuration
    Returns: List of (component_path, attr_name, attr_type, default_field_name, reference)
    """
    fields = []

    for entry in st.session_state.component_entries:
        for attr_name, attr_types in entry.configured_attributes.items():
            for attr_type in attr_types:
                if attr_type == "Static":
                    if attr_name == "label":
                        continue
                    default_field_name = attr_name
                    reference = f'{entry.component_type}.{attr_name}'
                else:
                    default_field_name = f"{attr_name}_{attr_type.lower()}"
                    ts_reference_map = {
                        'Historic': 'hasHistoricTimeSeriesReference',
                        'Live': 'hasLiveTimeSeriesReference',
                        'Future': 'hasFutureTimeSeriesReference'
                    }
                    ts_reference = ts_reference_map.get(attr_type, 'hasHistoricTimeSeriesReference')
                    reference = f'{entry.component_type}.{attr_name}.{ts_reference}'

                fields.append((entry.path, attr_name, attr_type, default_field_name, reference))

    return fields


def service_requirements_builder(client=None):
    """Main function for the Service Requirements Builder module"""

    st.header("🔧 Service Requirements Builder")
    st.markdown("Create service requirement YAML files with proper hierarchical component structure")

    if not RDFLIB_AVAILABLE or not GRAPHDB_AVAILABLE:
        st.error("⚠️ Service Requirements Builder requires both rdflib and a Triplestore client")
        if not RDFLIB_AVAILABLE:
            st.code("pip install rdflib")
        return

    initialize_session_state()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🔗 Data Source",
        "🏷️ Service Info",
        "🗃️ Component Structure",
        "🎯 Attributes",
        "✅ Validation",
        "📄 Preview & Export"
    ])

    with tab1:
        st.subheader("🔗 Data Source")

        if not client:
            st.error("⚠️ No Triplestore client available. Please ensure you're connected to a workspace.")
            st.info("Triplestore connection is required to load components, attributes, and their relationships.")
            return

        st.success(f"✅ Connected to Triplestore repository: {getattr(client, 'selected_repo', 'Unknown')}")

        st.write("### 🎯 Load Data from Triplestore")

        if st.button("🔄 Load Components, Attributes & Mappings", type="primary", use_container_width=True):
            with st.spinner("Loading all data from Triplestore..."):
                try:
                    components, attributes = query_graphdb_components(client)

                    if components or attributes:
                        st.session_state.graphdb_components = components
                        st.session_state.graphdb_attributes = attributes
                        st.success(f"✅ Loaded {len(components)} components, {len(attributes)} attributes")
                    else:
                        st.warning("No components or attributes found in Triplestore")

                    mappings = query_graphdb_component_attributes(client)

                    if mappings:
                        st.session_state.component_attribute_mappings = mappings

                        all_components, all_attributes = get_current_ontology_data()

                        for comp_name, comp_attrs in mappings.items():
                            if comp_name in all_components:
                                existing_attrs = set(all_components[comp_name].attributes)
                                new_attrs = existing_attrs.union(set(comp_attrs))
                                all_components[comp_name].attributes = list(new_attrs)

                        if st.session_state.ontology_components:
                            st.session_state.ontology_components = {k: v for k, v in all_components.items()
                                                                    if k in st.session_state.ontology_components}
                        if st.session_state.graphdb_components:
                            st.session_state.graphdb_components = {k: v for k, v in all_components.items()
                                                                   if k in st.session_state.graphdb_components}

                        st.success(f"✅ Loaded {len(mappings)} component-attribute mappings using naming convention")
                    else:
                        st.warning("No component-attribute mappings found in Triplestore")

                    if (components or attributes) and mappings:
                        st.balloons()
                        st.rerun()

                except Exception as e:
                    st.error(f"Error loading from Triplestore: {e}")

        graphdb_components = len(st.session_state.graphdb_components)
        graphdb_attributes = len(st.session_state.graphdb_attributes)
        mappings_count = len(st.session_state.component_attribute_mappings)

        if graphdb_components > 0 or graphdb_attributes > 0:
            st.info(f"📊 Triplestore data loaded: {graphdb_components} components, {graphdb_attributes} attributes")

        if mappings_count > 0:
            st.info(f"🎯 Component-attribute mappings: {mappings_count} components mapped")

        if st.session_state.component_attribute_mappings:
            with st.expander("🎯 Current Triplestore Mappings", expanded=False):
                for comp_name, attrs in st.session_state.component_attribute_mappings.items():
                    st.write(f"**{comp_name}**: {', '.join(attrs)}")

        st.markdown("---")
        st.write("### 📁 Alternative: Manual Ontology Upload")
        st.caption("Optional: Upload an ontology file to supplement or override Triplestore data")

        with st.expander("📤 Upload Ontology File", expanded=False):
            uploaded_file = st.file_uploader(
                "Choose an ontology file (.ttl, .rdf, .owl)",
                type=['ttl', 'turtle', 'rdf', 'owl', 'n3'],
                help="Upload a Turtle (.ttl), RDF/XML (.rdf), or N3 (.n3) format ontology file"
            )

            if uploaded_file is not None:
                with st.spinner("Parsing ontology file..."):
                    components, attributes = parse_ontology_file(uploaded_file)

                    if components:
                        st.session_state.ontology_components = components
                        st.session_state.ontology_attributes = attributes
                        st.session_state.ontology_uploaded = True

                        st.success(f"✅ Ontology loaded: {len(components)} components, {len(attributes)} attributes")

                        with st.expander("📋 Loaded Components (sample)", expanded=False):
                            sample_components = list(components.items())[:10]
                            for name, comp in sample_components:
                                st.write(f"• **{comp.label}** ({name})")
                    else:
                        st.error("Failed to parse the ontology file")

            if st.session_state.ontology_uploaded:
                components, attributes = st.session_state.ontology_components, st.session_state.ontology_attributes
                st.info(f"📋 Manual ontology loaded: {len(components)} components, {len(attributes)} attributes")

    with tab2:
        st.subheader("🏷️ Service Information")

        # Add YAML Import functionality at the top
        st.write("### 📥 Import Existing Configuration")

        with st.expander("📤 Load YAML File", expanded=False):
            st.caption("Upload an existing YAML file to populate the entire configuration including service info, components, and attributes")

            uploaded_yaml = st.file_uploader(
                "Choose a YAML file",
                type=['yaml', 'yml'],
                help="Upload a service requirements YAML file",
                key="yaml_uploader"
            )

            if uploaded_yaml is not None:
                try:
                    yaml_content = uploaded_yaml.read().decode('utf-8')

                    # Show preview directly (no nested expander)
                    st.write("**YAML Preview:**")
                    st.code(yaml_content, language='yaml')

                    st.write("---")

                    col1, col2 = st.columns(2)

                    with col1:
                        if st.button("✅ Load Configuration", type="primary", use_container_width=True):
                            with st.spinner("Parsing YAML and loading configuration..."):
                                if load_yaml_configuration(yaml_content):
                                    st.success("✅ Successfully loaded YAML configuration!")
                                    st.info(f"📝 Service: **{st.session_state.service_name}**")
                                    st.info(f"📦 Components: **{len(st.session_state.component_entries)}**")

                                    # Count total attributes
                                    total_attrs = sum(len(entry.configured_attributes) for entry in st.session_state.component_entries)
                                    st.info(f"🎯 Attributes: **{total_attrs}**")

                                    st.balloons()
                                    st.rerun()

                    with col2:
                        if st.button("❌ Cancel", use_container_width=True):
                            st.rerun()

                except Exception as e:
                    st.error(f"Error reading YAML file: {str(e)}")

        with st.expander("📂 Load an Existing Service (workspace or global)", expanded=False):
            st.caption("Pick a service already saved in this workspace's `services/` folder or in the "
                       "global services library and load it into the builder to view or edit.")

            from components.service_catalog import list_services, read_service_text

            refs = list_services()  # workspace + global ServiceRefs
            labels = {
                f"{'🌐' if r.source == 'global' else '🗂️'} {r.name} ({r.source})": r
                for r in refs
            }

            if not labels:
                st.info("No existing services found in the workspace or global library.")
            else:
                choice = st.selectbox("Existing service",
                                      ["-- Select --"] + sorted(labels.keys()),
                                      key="existing_service_pick")
                if choice != "-- Select --":
                    content = read_service_text(labels[choice])
                    if not content:
                        st.error("Could not read the selected service")
                    else:
                        # Preview the raw YAML before loading, so it's clear what
                        # the builder will import.
                        st.write("**YAML Preview:**")
                        st.code(content, language="yaml")

                        if st.button("📥 Load Selected Service", type="primary",
                                     key="load_existing_service"):
                            if load_yaml_configuration(content):
                                total_attrs = sum(len(e.configured_attributes)
                                                  for e in st.session_state.component_entries)
                                st.success(f"✅ Loaded **{st.session_state.service_name}** into the builder")
                                st.info(f"📦 Components: **{len(st.session_state.component_entries)}**  •  "
                                        f"🎯 Attributes: **{total_attrs}**")
                                st.rerun()
                            else:
                                st.error("Failed to parse the selected service YAML")

        st.write("---")
        st.write("### ✏️ Manual Entry")

        col1, col2 = st.columns(2)
        with col1:
            st.session_state.service_name = st.text_input(
                "Service Name",
                value=st.session_state.service_name,
                placeholder="e.g., WindForecasting, EnergySimulation"
            )

        with col2:
            st.session_state.service_description = st.text_area(
                "Service Description",
                value=st.session_state.service_description,
                placeholder="Brief description of what this service does...",
                height=100
            )

        if st.session_state.service_name:
            st.success(f"✅ Service: {st.session_state.service_name}")
        else:
            st.info("Please enter a service name to continue")

    with tab3:
        st.subheader("🗃️ Build Component Structure")
        st.write("Build the hierarchical component structure with proper linking")

        components, attributes = get_current_ontology_data()

        if not components:
            st.warning("⚠️ No components available. Please load ontology data from the Data Source tab.")
            return

        component_options = [name for name, comp in components.items()
                             if not name.endswith('Attribute') and name not in ['Attribute', 'Component']]

        if not component_options:
            st.warning("⚠️ No suitable components found. Please check your ontology data.")
            return

        def get_component_attributes(component_name):
            available_attrs = []

            if (st.session_state.component_attribute_mappings and
                    component_name in st.session_state.component_attribute_mappings):
                graphdb_attrs = st.session_state.component_attribute_mappings[component_name]
                available_attrs.extend([attr for attr in graphdb_attrs if attr not in available_attrs])

            if component_name in components:
                ontology_attrs = components[component_name].attributes
                available_attrs.extend([attr for attr in ontology_attrs if attr not in available_attrs])

            return available_attrs

        with st.expander("➕ Add Root Component", expanded=True):
            col1, col2, col3 = st.columns([2, 2, 2])

            with col1:
                root_component = st.selectbox(
                    "Component Type",
                    options=[""] + component_options,
                    help="Select component type from ontology",
                    key="root_component"
                )

            with col2:
                default_path = root_component if root_component else ""
                root_path = st.text_input(
                    "YAML Path",
                    value=default_path,
                    placeholder="Auto-filled from component selection",
                    help="The key name in the YAML structure (auto-filled, but you can customize)",
                    key="root_path"
                )

            with col3:
                if st.button("Add Root Component", type="primary"):
                    if root_path and root_component:
                        link_pattern = ""
                        new_entry = ComponentEntry(
                            path=root_path,
                            component_type=root_component,
                            link_pattern=link_pattern,
                            level=1
                        )
                        st.session_state.component_entries.append(new_entry)
                        st.success(f"Added root component: {root_path} ({root_component})")
                        st.rerun()
                    else:
                        st.error("Please select a component type first")

            if root_component:
                root_attrs = get_component_attributes(root_component)
                if root_attrs:
                    st.info(f"📋 Available attributes for {root_component}: {', '.join(root_attrs)}")
                else:
                    st.warning(f"⚠️ No attributes found for {root_component}. Load component-attribute mappings to see attributes.")

        if st.session_state.component_entries:
            st.write("### Add Child Components")

            parent_options = []
            for entry in st.session_state.component_entries:
                parent_options.append(f"{entry.path} ({entry.component_type})")

            with st.expander("➕ Add Child Component", expanded=False):
                col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

                with col1:
                    child_component = st.selectbox(
                        "Child Component Type",
                        options=[""] + component_options,
                        help="Select child component type",
                        key="child_component"
                    )

                with col2:
                    parent_selection = st.selectbox(
                        "Parent Component",
                        options=[""] + parent_options,
                        help="Which component this links to",
                        key="parent_selection"
                    )

                with col3:
                    default_child_path = child_component if child_component else ""
                    child_path = st.text_input(
                        "YAML Path",
                        value=default_child_path,
                        placeholder="Auto-filled from component selection",
                        help="The key name for this child component (auto-filled, but you can customize)",
                        key="child_path"
                    )

                with col4:
                    if st.button("Add Child", type="secondary"):
                        if child_path and parent_selection and child_component:
                            parent_path = parent_selection.split(" (")[0]
                            parent_component = parent_selection.split("(")[1].rstrip(")")

                            link_pattern = f"CL.{parent_component}.{child_component}"

                            parent_level = 1
                            for entry in st.session_state.component_entries:
                                if entry.path == parent_path:
                                    parent_level = entry.level
                                    break

                            new_entry = ComponentEntry(
                                path=child_path,
                                component_type=child_component,
                                link_pattern=link_pattern,
                                parent_path=parent_path,
                                level=parent_level + 1
                            )
                            st.session_state.component_entries.append(new_entry)
                            st.success(f"Added child component: {child_path} → {parent_path}")
                            st.rerun()
                        else:
                            st.error("Please select component type and parent first")

                if child_component:
                    child_attrs = get_component_attributes(child_component)
                    if child_attrs:
                        st.info(f"📋 Available attributes for {child_component}: {', '.join(child_attrs)}")
                    else:
                        st.warning(f"⚠️ No attributes found for {child_component}. Load component-attribute mappings to see attributes.")

        if st.session_state.component_entries:
            st.write("### 🌳 Current Component Structure")

            sorted_entries = sorted(st.session_state.component_entries, key=lambda x: (x.level, x.path))

            for i, entry in enumerate(sorted_entries):
                indent = "　" * (entry.level - 1)

                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 2, 1, 1])

                    with col1:
                        st.write(f"{indent}📦 **{entry.path}** ({entry.component_type})")
                        if entry.parent_path:
                            st.caption(f"{indent}└── Links to: {entry.parent_path}")

                    with col2:
                        if entry.link_pattern:
                            st.code(entry.link_pattern)
                        else:
                            st.caption("Root component (no link)")

                    with col3:
                        potential_parents = [e for e in st.session_state.component_entries
                                             if e.path != entry.path and e.level <= entry.level]

                        if entry.level > 1 or potential_parents:
                            with st.popover("🔄 Parent", use_container_width=True):
                                st.write(f"**Change parent for {entry.path}**")

                                if st.button("Make Root Component", key=f"make_root_{i}"):
                                    st.session_state.component_entries[i].parent_path = ""
                                    st.session_state.component_entries[i].link_pattern = ""
                                    st.session_state.component_entries[i].level = 1
                                    st.success(f"Made {entry.path} a root component")
                                    st.rerun()

                                if potential_parents:
                                    st.write("**Or choose new parent:**")
                                    for j, parent_entry in enumerate(potential_parents):
                                        if parent_entry.path != entry.parent_path:
                                            if st.button(f"→ {parent_entry.path} ({parent_entry.component_type})",
                                                         key=f"parent_{i}_{j}"):
                                                st.session_state.component_entries[i].parent_path = parent_entry.path
                                                st.session_state.component_entries[i].link_pattern = f"CL.{parent_entry.component_type}.{entry.component_type}"
                                                st.session_state.component_entries[i].level = parent_entry.level + 1
                                                st.success(f"Changed parent of {entry.path} to {parent_entry.path}")
                                                st.rerun()

                    with col4:
                        if st.button(f"🗑️", key=f"remove_entry_{i}"):
                            children_to_remove = []
                            for j, child_entry in enumerate(st.session_state.component_entries):
                                if child_entry.parent_path == entry.path:
                                    children_to_remove.append(j)

                            for child_idx in reversed(children_to_remove):
                                st.session_state.component_entries.pop(child_idx)
                                if child_idx < i:
                                    i -= 1

                            st.session_state.component_entries.pop(i)
                            st.rerun()

            if st.button("🗑️ Clear All Components"):
                st.session_state.component_entries = []
                st.rerun()
        else:
            st.info("Add some components to see the structure here")

    with tab4:
        st.subheader("🎯 Manage Component Attributes")
        st.markdown("**Enhanced Multi-Type Attributes**: Each attribute can now be configured as Static, Historic, Live, and/or Future simultaneously")

        if not st.session_state.component_entries:
            st.info("Add components first to manage their attributes")
        else:
            st.write("Define attributes for each component. Any attribute can be configured with multiple types (Static, Historic, Live, Future).")

            components, attributes = get_current_ontology_data()

            for i, entry in enumerate(st.session_state.component_entries):
                with st.expander(f"📋 Attributes for {entry.path} ({entry.component_type})", expanded=False):
                    available_attrs = []

                    if (st.session_state.component_attribute_mappings and
                            entry.component_type in st.session_state.component_attribute_mappings):
                        graphdb_attrs = st.session_state.component_attribute_mappings[entry.component_type]
                        available_attrs.extend([attr for attr in graphdb_attrs if attr not in available_attrs])

                    if entry.component_type in components:
                        ontology_attrs = components[entry.component_type].attributes
                        available_attrs.extend([attr for attr in ontology_attrs if attr not in available_attrs])

                    # Include attributes already configured on this entry — e.g.
                    # loaded from an existing service YAML — even if GraphDB
                    # mappings/ontology aren't loaded. Without this they get no
                    # checkbox AND are dropped when configured_attributes is
                    # rewritten from the checkbox state below, so a loaded service
                    # would lose all but the coincidentally-matching attributes.
                    for attr in entry.configured_attributes.keys():
                        if attr not in available_attrs:
                            available_attrs.append(attr)

                    if 'label' not in available_attrs:
                        available_attrs.insert(0, 'label')

                    if available_attrs:
                        st.write("**Available Attributes with Multi-Type Support:**")
                        st.caption(f"Each attribute can be configured as Static, Historic, Live, and/or Future simultaneously")

                        if not hasattr(entry, 'configured_attributes'):
                            entry.configured_attributes = {}

                        st.write("---")

                        col_header = st.columns([2, 1, 1, 1, 1])
                        with col_header[0]:
                            st.write("**Attribute**")
                        with col_header[1]:
                            st.write("**Static**")
                        with col_header[2]:
                            st.write("**Historic**")
                        with col_header[3]:
                            st.write("**Live**")
                        with col_header[4]:
                            st.write("**Future**")

                        updated_attributes = {}

                        for j, attr in enumerate(available_attrs):
                            col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

                            with col1:
                                st.write(f"**{attr}**")

                            current_types = entry.configured_attributes.get(attr, [])
                            selected_types = []

                            with col2:
                                if st.checkbox("", key=f"static_{i}_{j}_{attr}", value="Static" in current_types):
                                    selected_types.append("Static")

                            with col3:
                                if st.checkbox("", key=f"historic_{i}_{j}_{attr}", value="Historic" in current_types):
                                    selected_types.append("Historic")

                            with col4:
                                if st.checkbox("", key=f"live_{i}_{j}_{attr}", value="Live" in current_types):
                                    selected_types.append("Live")

                            with col5:
                                if st.checkbox("", key=f"future_{i}_{j}_{attr}", value="Future" in current_types):
                                    selected_types.append("Future")

                            if selected_types:
                                updated_attributes[attr] = selected_types

                        st.session_state.component_entries[i].configured_attributes = updated_attributes

                        st.write("---")
                        if updated_attributes:
                            st.write("**Current Configuration:**")
                            for attr, types in updated_attributes.items():
                                type_str = ", ".join(types)
                                st.success(f"**{attr}**: {type_str}")

                            st.write("**Generated YAML Fields:**")
                            field_examples = []
                            for attr, types in updated_attributes.items():
                                for attr_type in types:
                                    if attr_type == "Static":
                                        if attr == "label":
                                            field_examples.append(f"label: {entry.component_type}.label")
                                        else:
                                            field_examples.append(f"{attr}: {entry.component_type}.{attr}")
                                    else:
                                        field_name = f"{attr}_{attr_type.lower()}"
                                        ts_ref = {
                                            'Historic': 'hasHistoricTimeSeriesReference',
                                            'Live': 'hasLiveTimeSeriesReference',
                                            'Future': 'hasFutureTimeSeriesReference'
                                        }[attr_type]
                                        field_examples.append(f"{field_name}: {entry.component_type}.{attr}.{ts_ref}")

                            for example in field_examples:
                                st.code(example)
                        else:
                            st.info("No attributes configured for this component")

                    else:
                        st.warning(f"⚠️ No attributes found for {entry.component_type}.")
                        st.info("Components can exist without attributes. Load component-attribute mappings from Triplestore to see available attributes.")

                        with st.expander("Add Custom Attributes", expanded=False):
                            custom_attr = st.text_input(
                                "Attribute name",
                                key=f"custom_attr_{i}",
                                placeholder="e.g., Power, Temperature, Status"
                            )

                            st.write("Select types for custom attribute:")
                            col1, col2, col3, col4 = st.columns(4)
                            custom_types = []

                            with col1:
                                if st.checkbox("Static", key=f"custom_static_{i}"):
                                    custom_types.append("Static")
                            with col2:
                                if st.checkbox("Historic", key=f"custom_historic_{i}"):
                                    custom_types.append("Historic")
                            with col3:
                                if st.checkbox("Live", key=f"custom_live_{i}"):
                                    custom_types.append("Live")
                            with col4:
                                if st.checkbox("Future", key=f"custom_future_{i}"):
                                    custom_types.append("Future")

                            if st.button(f"Add Custom Attribute", key=f"add_custom_{i}"):
                                if custom_attr and custom_types:
                                    if not hasattr(entry, 'configured_attributes'):
                                        entry.configured_attributes = {}
                                    entry.configured_attributes[custom_attr] = custom_types
                                    st.success(f"Added custom attribute: {custom_attr} ({', '.join(custom_types)})")
                                    st.rerun()
                                else:
                                    st.error("Please enter attribute name and select at least one type")

    with tab5:
        st.subheader("✅ Validation")
        st.markdown("Validate that all configured component-attribute pairs are valid according to the ontology")

        if not st.session_state.component_entries:
            st.info("ℹ️ No components configured yet. Add components in the Component Structure tab to enable validation.")
        else:
            st.write("---")

            # Validation controls
            col1, col2 = st.columns([3, 1])

            with col1:
                st.write("Click the button below to validate your current configuration against the ontology mappings.")

            with col2:
                validate_button = st.button("🔍 Run Validation", type="primary", use_container_width=True)

            st.write("---")

            # Run validation
            if validate_button or 'last_validation_report' in st.session_state:
                with st.spinner("Running validation..."):
                    report = validate_component_attributes()
                    st.session_state.last_validation_report = report

                # Display validation report
                display_validation_report(report)

                # Show suggestions
                st.write("---")
                suggestions = get_validation_suggestions(report)
                if suggestions:
                    st.write("### 💡 Suggestions")
                    for suggestion in suggestions:
                        st.info(suggestion)

                # Detailed component breakdown
                st.write("---")
                st.write("### 📋 Component Breakdown")

                for entry in st.session_state.component_entries:
                    component_name = entry.component_type
                    component_path = entry.path

                    # Get valid attributes for this component
                    valid_attributes = []
                    if component_name in st.session_state.component_attribute_mappings:
                        valid_attributes = st.session_state.component_attribute_mappings[component_name]

                    with st.expander(f"📦 {component_path} ({component_name})"):
                        col_info1, col_info2 = st.columns(2)

                        with col_info1:
                            st.write("**Component Information:**")
                            st.write(f"• Type: `{component_name}`")
                            st.write(f"• Path: `{component_path}`")
                            st.write(f"• Level: {entry.level}")
                            if entry.parent_path:
                                st.write(f"• Parent: {entry.parent_path}")

                        with col_info2:
                            st.write("**Available Attributes:**")
                            if valid_attributes:
                                st.write(f"• Total: {len(valid_attributes)}")
                                attr_list = ", ".join(valid_attributes[:5])
                                if len(valid_attributes) > 5:
                                    attr_list += f", ... (+{len(valid_attributes) - 5} more)"
                                st.caption(attr_list)
                            else:
                                st.warning("No mapped attributes")

                        st.write("---")
                        st.write("**Configured Attributes:**")

                        if entry.configured_attributes:
                            for attr_name, attr_types in entry.configured_attributes.items():
                                is_valid = attr_name == 'label' or attr_name in valid_attributes

                                col_attr, col_status = st.columns([3, 1])

                                with col_attr:
                                    types_str = ", ".join(attr_types)
                                    st.write(f"• **{attr_name}** [{types_str}]")

                                with col_status:
                                    if is_valid:
                                        st.success("✓ Valid")
                                    else:
                                        st.error("✗ Invalid")
                        else:
                            st.info("No attributes configured")

            else:
                st.info("👆 Click 'Run Validation' to check your configuration")

                # Show quick stats
                if st.session_state.component_entries:
                    st.write("### 📊 Quick Stats")

                    total_components = len(st.session_state.component_entries)
                    total_attrs = sum(len(entry.configured_attributes) for entry in st.session_state.component_entries)
                    components_with_mappings = sum(
                        1 for entry in st.session_state.component_entries
                        if entry.component_type in st.session_state.component_attribute_mappings
                    )

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.metric("Components", total_components)
                    with col2:
                        st.metric("Configured Attributes", total_attrs)
                    with col3:
                        st.metric("Components with Mappings", components_with_mappings)

    with tab6:
        st.subheader("📄 YAML Preview & Export")

        if not st.session_state.component_entries:
            st.info("Add components and their attributes to see the YAML preview")
        else:
            # Edit mode toggle
            col_toggle, col_reset = st.columns([3, 1])
            with col_toggle:
                st.session_state.edit_mode = st.toggle(
                    "✏️ Edit Field Names",
                    value=st.session_state.edit_mode,
                    help="Enable to customize YAML field names. Component types and attribute names from the ontology cannot be changed."
                )

            with col_reset:
                if st.button("🔄 Reset All Names", help="Reset all custom field names to defaults"):
                    st.session_state.custom_field_names = {}
                    st.success("Reset all field names to defaults")
                    st.rerun()

            if st.session_state.edit_mode:
                st.info("💡 **Edit Mode Active**: Customize field names below. Changes will be reflected in the YAML preview.")

                st.write("### ✏️ Customize Field Names")
                st.caption("📌 Component types and attribute names are from the ontology and cannot be changed. You can only customize the YAML field names.")

                fields = get_all_yaml_fields()

                if fields:
                    for component_path, attr_name, attr_type, default_field_name, reference in fields:
                        key = f"{component_path}|{attr_name}|{attr_type}"
                        current_name = st.session_state.custom_field_names.get(key, default_field_name)

                        col1, col2, col3, col4 = st.columns([2, 2, 3, 1])

                        with col1:
                            st.text(f"{component_path}")

                        with col2:
                            st.code(f"{attr_name} ({attr_type})")

                        with col3:
                            new_name = st.text_input(
                                "Field Name",
                                value=current_name,
                                key=f"field_name_{key}",
                                placeholder=default_field_name,
                                label_visibility="collapsed"
                            )

                            if new_name != default_field_name:
                                st.session_state.custom_field_names[key] = new_name
                            elif key in st.session_state.custom_field_names:
                                del st.session_state.custom_field_names[key]

                        with col4:
                            if key in st.session_state.custom_field_names:
                                if st.button("↺", key=f"reset_{key}", help="Reset to default"):
                                    del st.session_state.custom_field_names[key]
                                    st.rerun()
                else:
                    st.info("No fields to customize. Configure attributes in the Attributes tab first.")

                st.write("---")

            yaml_structure = generate_yaml_structure(use_custom_names=True)
            yaml_content = yaml.dump(yaml_structure, default_flow_style=False, sort_keys=False, indent=2)

            st.write("**Generated YAML:**")
            st.code(yaml_content, language='yaml')

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.session_state.service_name:
                    st.success("✅ Service name provided")
                else:
                    st.error("❌ Service name required")

            with col2:
                if st.session_state.component_entries:
                    st.success(f"✅ {len(st.session_state.component_entries)} components defined")
                else:
                    st.error("❌ No components defined")

            with col3:
                attrs_count = sum(len(entry.configured_attributes) for entry in st.session_state.component_entries)
                total_field_count = sum(sum(len(types) for types in entry.configured_attributes.values()) for entry in st.session_state.component_entries)
                if total_field_count > 0:
                    st.success(f"✅ {attrs_count} attributes, {total_field_count} fields")
                else:
                    st.info("ℹ️ No attributes configured")

            with col4:
                if st.session_state.component_attribute_mappings:
                    st.success("✅ Triplestore mappings loaded")
                else:
                    st.info("ℹ️ No Triplestore mappings")

            if st.session_state.service_name and st.session_state.component_entries:
                st.write("### 💾 Export Options")

                col1, col2, col3 = st.columns(3)

                with col1:
                    filename = f"{st.session_state.service_name.lower().replace(' ', '_')}_input.yaml"
                    st.download_button(
                        label="📥 Download YAML",
                        data=yaml_content,
                        file_name=filename,
                        mime="text/yaml",
                        type="primary"
                    )

                with col2:
                    if st.button("💾 Save to Workspace"):
                        # Save into the active workspace's services/ folder via the
                        # storage abstraction, so the Scenario Builder picks it up.
                        ctx = st.session_state.get("workspace_context")
                        storage = getattr(ctx, "storage", None) if ctx is not None else None
                        if storage is None:
                            st.error("No active workspace; use Download YAML instead.")
                        else:
                            rel_path = f"services/{filename}"
                            storage.write_text(rel_path, yaml_content)
                            st.success(f"Saved to workspace `{rel_path}`")

                with col3:
                    if st.button("📋 Copy to Clipboard"):
                        st.code(yaml_content, language='yaml')
                        st.info("Copy the YAML above to your clipboard")

    st.markdown("---")

    components, attributes = get_current_ontology_data()
    service_status = "✅ Set" if st.session_state.service_name else "❌ Missing"
    entry_count = len(st.session_state.component_entries)
    attrs_count = sum(len(entry.configured_attributes) for entry in st.session_state.component_entries)
    total_field_count = sum(sum(len(types) for types in entry.configured_attributes.values()) for entry in st.session_state.component_entries)
    ontology_status = "✅ Custom" if st.session_state.ontology_uploaded else "❌ None"
    graphdb_status = "✅ Connected" if client else "❌ Not Connected"
    mappings_status = "✅ Loaded" if st.session_state.component_attribute_mappings else "❌ None"

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Ontology File", ontology_status)
    with col2:
        st.metric("Triplestore", graphdb_status)
    with col3:
        st.metric("Mappings", mappings_status)
    with col4:
        st.metric("Components Available", len(components))
    with col5:
        st.metric("Structure Entries", entry_count)
    with col6:
        st.metric("YAML Fields", total_field_count)


if __name__ == "__main__":
    service_requirements_builder()