# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Backend SPARQL query layer.

Pure, UI-independent query functions for the knowledge graph. Every function
takes a SPARQL client (anything exposing ``sparql_api_query(query, out_format)``,
i.e. ``UnifiedGraphDBClient``) and returns plain data — a pandas DataFrame — with
no Streamlit or other UI dependency. Graph scoping is sourced from the single
source of truth in ``backend.graphdb.graphs`` so the queries stay portable across
triple stores.

This is the layer a non-Streamlit front end (or a service / notebook) would call
directly. The Streamlit components are thin wrappers that call these functions
and handle presentation only.
"""

from backend.graphdb.queries.components import (
    get_component_types_with_instances,
    get_component_instances,
    get_component_attributes_comprehensive,
    get_component_basic_properties,
    get_component_sources,
    get_component_classes,
    get_attribute_classes,
    get_component_subclasses,
    get_attribute_subclasses_for,
    get_component_attribute_object_properties,
    get_all_component_instances,
    get_all_instance_attribute_links,
    get_attribute_kinds,
    get_all_attribute_values,
    get_all_instance_direct_properties,
    get_leaf_component_types,
    get_instances_of_type,
    get_instance_attributes,
    get_instance_direct_properties,
)
from backend.graphdb.queries.inspector import recommended_queries

__all__ = [
    "recommended_queries",
    "get_component_types_with_instances",
    "get_component_instances",
    "get_component_attributes_comprehensive",
    "get_component_basic_properties",
    "get_component_sources",
    "get_component_classes",
    "get_attribute_classes",
    "get_component_subclasses",
    "get_attribute_subclasses_for",
    "get_component_attribute_object_properties",
    "get_all_component_instances",
    "get_all_instance_attribute_links",
    "get_attribute_kinds",
    "get_all_attribute_values",
    "get_all_instance_direct_properties",
    "get_leaf_component_types",
    "get_instances_of_type",
    "get_instance_attributes",
    "get_instance_direct_properties",
]
