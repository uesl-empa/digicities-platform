# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_ontology_loader.py
"""
Ontology Loader for Replica Builder — UI shell over the backend shaping layer.

The SPARQL lives in ``backend/graphdb/queries/ontology.py``; the DataFrame →
constraint-model shaping moved to ``backend/replica_builder/ontology_queries.py``
(Phase 5 of the backend/UI split). What stays here is the Streamlit wiring:
the spinner-per-step orchestration into session state, st.error reporting
around each backend call (same fallbacks as before), and the status display.
"""
import streamlit as st
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple, Set

try:
    from components.graphdb import GraphDBClient

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False

from backend.replica_builder import ontology_queries as _oq

# Constraint model + pure helpers, re-exported verbatim from the backend.
from backend.replica_builder.ontology_queries import (  # noqa: F401
    ComponentClass,
    AttributeClass,
    extract_local_name,
    get_common_qudt_units,
)
from backend.replica_builder.attribute_rules import TEMPORAL_PRECISIONS  # noqa: F401


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
    """Query all component classes from ontology (via backend.replica_builder.ontology_queries)."""
    try:
        return _oq.query_components(client)
    except Exception as e:
        st.error(f"Error querying components: {e}")
        return {}


def query_attributes_with_constraints(client) -> Dict[str, AttributeClass]:
    """Query all attribute classes from ontology WITH their constraints
    (via backend.replica_builder.ontology_queries)."""
    try:
        return _oq.query_attributes_with_constraints(client)
    except Exception as e:
        st.error(f"Error querying attributes: {e}")
        import traceback
        st.exception(traceback.format_exc())
        return {}


def query_component_attribute_mappings(client) -> Dict[str, List[str]]:
    """Query component-attribute mappings using naming convention"""
    try:
        return _oq.query_component_attribute_mappings(client)
    except Exception as e:
        st.error(f"Error querying component-attribute mappings: {e}")
        return {}


def query_named_individuals(client) -> Dict[str, List[str]]:
    """Query named individuals for categorical attributes
    (via backend.replica_builder.ontology_queries)."""
    try:
        return _oq.query_named_individuals(client)
    except Exception as e:
        st.error(f"Error querying named individuals: {e}")
        return {}


def query_available_units(client) -> List[str]:
    """Query available QUDT units from ontology (via backend.replica_builder.ontology_queries)."""
    try:
        return _oq.query_available_units(client)
    except Exception as e:
        st.warning(f"Could not query units from ontology, using common units: {e}")
        return get_common_qudt_units()


def query_ratio_units(client) -> Dict[str, Tuple[str, str]]:
    """Query hasRatioUnits blank-node patterns for CustomPhysicalRatio attributes
    (via backend.replica_builder.ontology_queries)."""
    try:
        return _oq.query_ratio_units(client)
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
    return list(TEMPORAL_PRECISIONS)


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