# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Ontology constraint loading for the Replica Builder, headless.

The SPARQL itself has lived in ``backend/graphdb/queries/ontology.py`` since
the named-graph decoupling — these functions are the shaping layer that used to
sit in ``components/replica_builder/replica_ontology_loader.py``: DataFrames →
the editor's constraint model (:class:`ComponentClass` / :class:`AttributeClass`
maps, component→attribute mappings, named individuals, unit lists).

Errors propagate; the Streamlit shim keeps its old ``st.error`` + empty-dict
behavior around these calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

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


def query_components(client) -> Dict[str, ComponentClass]:
    """Query all component classes from ontology (via backend.graphdb.queries.ontology)."""
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


def query_attributes_with_constraints(client) -> Dict[str, AttributeClass]:
    """Query all attribute classes from ontology WITH their constraints
    (via backend.graphdb.queries.ontology)."""
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


def query_component_attribute_mappings(client) -> Dict[str, List[str]]:
    """Query component-attribute mappings using naming convention"""
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


def query_named_individuals(client) -> Dict[str, List[str]]:
    """Query named individuals for categorical attributes
    (via backend.graphdb.queries.ontology)."""
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


def query_available_units(client) -> List[str]:
    """Query available QUDT units from ontology (via backend.graphdb.queries.ontology)."""
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


def query_ratio_units(client) -> Dict[str, Tuple[str, str]]:
    """Query hasRatioUnits blank-node patterns for CustomPhysicalRatio attributes
    (via backend.graphdb.queries.ontology)."""
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


__all__ = [
    "ComponentClass",
    "AttributeClass",
    "extract_local_name",
    "query_components",
    "query_attributes_with_constraints",
    "query_component_attribute_mappings",
    "query_named_individuals",
    "get_common_qudt_units",
    "query_available_units",
    "query_ratio_units",
]
