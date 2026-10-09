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
from rdflib import URIRef

from backend.graphdb.queries import ontology as gq_ont
from backend.ontology_kinds import KIND_CLASS, AttributeKind, kind_for_class


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
    rank = {kind: i for i, kind in enumerate(KIND_CLASS)}
    kinds: Dict[str, AttributeKind] = {}
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

        # Attribute type: the kind whose class the query found above this one
        # (rdfs:subClassOf*), by exact IRI; the first in KIND_CLASS order when
        # there are several rows; Physical when there is none.
        kind = kind_for_class(URIRef(row['attrType'])) if pd.notna(row.get('attrType')) else None
        best = kinds.get(attr_name)
        if kind is not None and (best is None or rank[kind] < rank[best]):
            kinds[attr_name] = kind
        attr_type = kinds.get(attr_name, AttributeKind.PHYSICAL).value

        attributes[attr_name] = AttributeClass(
            uri=attr_uri,
            label=label,
            attribute_type=attr_type,
            default_unit=default_unit,
            quantity_kind=quantity_kind
        )

    return attributes


def query_component_attribute_mappings(client) -> Dict[str, List[str]]:
    """Component -> attribute names: the attribute classes under each
    component's own category, which the workspace ontology graph states as the
    range of the component's general predicate
    (:func:`backend.ontology_scaffold.category_members_by_component`). Every
    component lists ``label`` first."""
    from backend.graphdb.graphs import ONTOLOGY_GRAPH
    from backend.graphdb.queries import graph_io
    from backend.ontology_scaffold import category_members_by_component

    onto = graph_io.construct_named_graph(client, ONTOLOGY_GRAPH)
    if onto is None:
        raise RuntimeError("the workspace ontology graph could not be read")
    component_attributes: Dict[str, List[str]] = {}
    for comp, members in category_members_by_component(onto).items():
        names = ['label']
        for member in members:
            name = extract_local_name(str(member))
            if name not in names:
                names.append(name)
        component_attributes[extract_local_name(str(comp))] = names
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
