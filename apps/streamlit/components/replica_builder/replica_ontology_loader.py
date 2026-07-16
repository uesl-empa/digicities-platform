# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_ontology_loader.py
"""
ENHANCED Ontology Loader for Replica Builder
Loads component types, attributes, and ALL CONSTRAINTS from GraphDB ontology
- Default units for Physical/Dynamic attributes
- Named individuals for Categorical attributes
- Quantity kinds
- Temporal precisions
- Currency codes
"""
import streamlit as st
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field

try:
    from components.graphdb import GraphDBClient

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False

from backend.graphdb.queries import ontology as gq_ont


@dataclass
class ComponentClass:
    """Represents a component class from the ontology"""
    uri: str
    label: str
    parent_classes: List[str]
    attributes: List[str]


@dataclass
class AttributeClass:
    """Represents an attribute class from the ontology with ALL constraints"""
    uri: str
    label: str
    attribute_type: str  # Physical, Dynamic, Categorical, etc.
    default_unit: Optional[str] = None
    quantity_kind: Optional[str] = None
    named_individuals: List[str] = field(default_factory=list)  # For categorical
    temporal_precisions: List[str] = field(default_factory=list)  # For event
    allowed_units: List[str] = field(default_factory=list)  # If multiple units allowed
    ratio_numerator_unit: Optional[str] = None   # For CustomPhysicalRatio
    ratio_denominator_unit: Optional[str] = None  # For CustomPhysicalRatio


def extract_local_name(uri: str) -> str:
    """Extract the local name from a URI"""
    if '#' in uri:
        return uri.split('#')[-1]
    elif '/' in uri:
        return uri.split('/')[-1]
    return uri


def load_ontology_from_graphdb(client) -> bool:
    """Load ontology from GraphDB named graph with ALL constraints"""
    if not client:
        st.error("No Triplestore client available")
        return False

    try:
        with st.spinner("Loading ontology structure..."):
            # Query for components
            components = query_components(client)
            if not components:
                st.error("No components found in ontology")
                return False
            st.session_state.replica_ontology_components = components

        with st.spinner("Loading attribute definitions..."):
            # Query for attributes WITH constraints
            attributes = query_attributes_with_constraints(client)
            st.session_state.replica_ontology_attributes = attributes

        with st.spinner("Loading component-attribute mappings..."):
            # Query for component-attribute mappings
            mappings = query_component_attribute_mappings(client)
            st.session_state.replica_component_attribute_mappings = mappings

        with st.spinner("Loading named individuals for categories..."):
            # Query for named individuals (categorical values)
            named_individuals = query_named_individuals(client)
            st.session_state.replica_named_individuals = named_individuals

        with st.spinner("Loading available units..."):
            # Query for available QUDT units
            available_units = query_available_units(client)
            st.session_state.replica_available_units = available_units

        with st.spinner("Loading ratio units for CustomPhysicalRatio attributes..."):
            ratio_units = query_ratio_units(client)
            attrs = st.session_state.replica_ontology_attributes
            for attr_name, (num_unit, den_unit) in ratio_units.items():
                if attr_name in attrs:
                    attrs[attr_name].ratio_numerator_unit = num_unit
                    attrs[attr_name].ratio_denominator_unit = den_unit

        return True

    except Exception as e:
        st.error(f"Failed to load ontology: {e}")
        import traceback
        st.exception(traceback.format_exc())
        return False


def query_components(client) -> Dict[str, ComponentClass]:
    """Query all component classes from ontology (via backend.graphdb.queries.ontology)."""
    try:
        result = gq_ont.get_components(client)
        if result is None or result.empty:
            return {}

        components = {}
        for _, row in result.iterrows():
            class_uri = row['class']
            class_name = extract_local_name(class_uri)
            label = row.get('label', class_name) if pd.notna(row.get('label')) else class_name

            components[class_name] = ComponentClass(
                uri=class_uri,
                label=label,
                parent_classes=[],
                attributes=[]
            )

        return components

    except Exception as e:
        st.error(f"Error querying components: {e}")
        return {}


def query_attributes_with_constraints(client) -> Dict[str, AttributeClass]:
    """Query all attribute classes from ontology WITH their constraints
    (via backend.graphdb.queries.ontology)."""
    try:
        result = gq_ont.get_attributes_with_constraints(client)
        if result is None or result.empty:
            return {}

        attributes = {}
        for _, row in result.iterrows():
            attr_uri = row['class']
            attr_name = extract_local_name(attr_uri)
            label = row.get('label', attr_name) if pd.notna(row.get('label')) else attr_name

            # Extract default unit
            default_unit = None
            if pd.notna(row.get('defaultUnit')):
                default_unit = extract_local_name(row['defaultUnit'])

            # Extract quantity kind
            quantity_kind = None
            if pd.notna(row.get('quantityKind')):
                quantity_kind = extract_local_name(row['quantityKind'])

            # Determine attribute type
            attr_type = "Physical"  # default
            if pd.notna(row.get('attrType')):
                attr_type_uri = row['attrType']
                attr_type = extract_local_name(attr_type_uri).replace('Attribute', '')

            attributes[attr_name] = AttributeClass(
                uri=attr_uri,
                label=label,
                attribute_type=attr_type,
                default_unit=default_unit,
                quantity_kind=quantity_kind
            )

        return attributes

    except Exception as e:
        st.error(f"Error querying attributes: {e}")
        import traceback
        st.exception(traceback.format_exc())
        return {}


def query_component_attribute_mappings(client) -> Dict[str, List[str]]:
    """Query component-attribute mappings using naming convention"""
    try:
        components_result = gq_ont.get_component_subclasses(client)
        if components_result is None or components_result.empty:
            return {}

        component_attributes = {}

        for _, row in components_result.iterrows():
            component_uri = row['component']
            component_name = extract_local_name(component_uri)
            attribute_class_name = f"{component_name}Attribute"

            try:
                attributes_result = gq_ont.get_attribute_subclasses_for(client, attribute_class_name)

                if attributes_result is not None and not attributes_result.empty:
                    component_attributes[component_name] = ['label']

                    for _, attr_row in attributes_result.iterrows():
                        attr_uri = attr_row['attribute']
                        attr_name = extract_local_name(attr_uri)

                        if attr_name not in component_attributes[component_name]:
                            component_attributes[component_name].append(attr_name)
                else:
                    component_attributes[component_name] = ['label']

            except Exception:
                component_attributes[component_name] = ['label']
                continue

        return component_attributes

    except Exception as e:
        st.error(f"Error querying component-attribute mappings: {e}")
        return {}


def query_named_individuals(client) -> Dict[str, List[str]]:
    """Query named individuals for categorical attributes
    (via backend.graphdb.queries.ontology)."""
    try:
        result = gq_ont.get_named_individuals(client)
        if result is None or result.empty:
            return {}

        # Group individuals by their categorical class
        individuals_by_class = {}
        for _, row in result.iterrows():
            class_uri = row['class']
            class_name = extract_local_name(class_uri)

            individual_uri = row['individual']
            individual_name = extract_local_name(individual_uri)

            if class_name not in individuals_by_class:
                individuals_by_class[class_name] = []

            if individual_name not in individuals_by_class[class_name]:
                individuals_by_class[class_name].append(individual_name)

        return individuals_by_class

    except Exception as e:
        st.error(f"Error querying named individuals: {e}")
        return {}


def query_available_units(client) -> List[str]:
    """Query available QUDT units from ontology (via backend.graphdb.queries.ontology)."""
    try:
        result = gq_ont.get_default_units(client)
        if result is None or result.empty:
            # Return common QUDT units as fallback
            return get_common_qudt_units()

        units = []
        for _, row in result.iterrows():
            unit_uri = row['unit']
            unit_name = extract_local_name(unit_uri)
            units.append(unit_name)

        # Add common units if not present
        common_units = get_common_qudt_units()
        for unit in common_units:
            if unit not in units:
                units.append(unit)

        return sorted(list(set(units)))

    except Exception as e:
        st.warning(f"Could not query units from ontology, using common units: {e}")
        return get_common_qudt_units()


def get_common_qudt_units() -> List[str]:
    """Return common QUDT units as fallback"""
    return [
        # Power
        "W", "KiloW", "MegaW",
        # Energy
        "J", "KiloJ", "W-HR", "KiloW-HR", "MegaW-HR",
        # Temperature
        "DEG_C", "K", "DEG_F",
        # Length
        "M", "KiloM", "CentiM", "MilliM",
        # Area
        "M2", "KiloM2",
        # Volume
        "M3", "L", "MilliL",
        # Mass
        "KiloGM", "GM", "TON",
        # Flow
        "M3-PER-SEC", "L-PER-SEC", "KiloGM-PER-SEC",
        # Percentage
        "PERCENT",
        # Pressure
        "PA", "KiloPA", "BAR",
        # Currency
        "CHF", "EUR", "USD"
    ]


def query_ratio_units(client) -> Dict[str, Tuple[str, str]]:
    """Query hasRatioUnits blank-node patterns for CustomPhysicalRatio attributes
    (via backend.graphdb.queries.ontology)."""
    try:
        result = gq_ont.get_ratio_units(client)
        if result is None or result.empty:
            return {}

        ratio_units = {}
        for _, row in result.iterrows():
            class_name = extract_local_name(row['class'])
            num_unit = extract_local_name(row['numUnit'])
            den_unit = extract_local_name(row['denUnit'])
            ratio_units[class_name] = (num_unit, den_unit)

        return ratio_units

    except Exception as e:
        st.warning(f"Could not query ratio units: {e}")
        return {}


def get_attribute_constraints(attr_name: str) -> Optional[AttributeClass]:
    """Get constraints for a specific attribute from loaded ontology"""
    return st.session_state.replica_ontology_attributes.get(attr_name)


def get_categorical_options(attr_name: str) -> List[str]:
    """Get named individuals for a categorical attribute"""
    return st.session_state.replica_named_individuals.get(attr_name, [])


def get_temporal_precisions() -> List[str]:
    """Get available temporal precisions for Event attributes"""
    return ["Year", "YearMonth", "Date", "DateTime"]


def show_ontology_status():
    """Display ontology loading status with constraints info"""
    components = st.session_state.replica_ontology_components
    attributes = st.session_state.replica_ontology_attributes
    mappings = st.session_state.replica_component_attribute_mappings
    named_individuals = st.session_state.get('replica_named_individuals', {})

    if not components:
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Component Types", len(components))

    with col2:
        st.metric("Attribute Types", len(attributes))

    with col3:
        st.metric("Mapped Components", len(mappings))

    with col4:
        # Count attributes with constraints
        constrained_attrs = sum(
            1 for attr in attributes.values()
            if attr.default_unit or attr.named_individuals or len(get_categorical_options(attr.label)) > 0
        )
        st.metric("Constrained Attrs", constrained_attrs)

    # Show constraint details in expander
    with st.expander("Constraint Details", expanded=False):

        # Attributes with default units
        attrs_with_units = [
            f"**{name}**: {attr.default_unit}"
            for name, attr in attributes.items()
            if attr.default_unit
        ]
        if attrs_with_units:
            st.write("**Attributes with Default Units:**")
            st.write(", ".join(attrs_with_units[:10]))
            if len(attrs_with_units) > 10:
                st.caption(f"...and {len(attrs_with_units) - 10} more")

        # Categorical attributes with named individuals
        if named_individuals:
            st.write("**Categorical Attributes with Named Individuals:**")
            for cat_name, individuals in list(named_individuals.items())[:5]:
                st.write(f"**{cat_name}**: {', '.join(individuals)}")
            if len(named_individuals) > 5:
                st.caption(f"...and {len(named_individuals) - 5} more categories")