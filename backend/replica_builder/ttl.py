# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Replica TTL generation, headless.

The three generators that used to read ``st.session_state`` in
``components/replica_builder/replica_ttl_generator.py`` now take the model
explicitly: ``instances`` (a list of :class:`~backend.replica_builder.model.
ComponentInstance`, or anything with the same attributes) and ``links`` (the
plain link dicts). Attribute-level TTL comes from the long-standing single
source of truth ``backend.replica_builder.utils.ttl_attribute_helpers``.

Output is byte-for-byte what the Streamlit generator produced.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from backend.replica_builder.utils.ttl_attribute_helpers import (  # noqa: F401
    format_decimal,
    escape_ttl_string,
    process_curve_data_string,
    generate_attribute_ttl,
)


def generate_classes_and_attributes_ttl(instances: Sequence[Any]) -> str:
    """Generate TTL for the classes_and_attributes graph.

    Pass the whole replica, or a subset (e.g. one component type's instances)
    to export just that slice.
    """
    lines = []

    # Add prefixes
    lines.extend([
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix cur: <http://qudt.org/vocab/currency/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        ""
    ])

    # Process each instance
    for instance in instances:
        instance_lines = generate_instance_ttl(instance)
        lines.extend(instance_lines)
        lines.append("")

    return "\n".join(lines)


def generate_instance_ttl(instance: Any) -> List[str]:
    """Generate TTL for a single instance - FIXED semicolon handling"""
    lines = []

    # Instance declaration with proper semicolons
    lines.append(f"<{instance.uri}> a dici_onto:{instance.component_type} ;")

    # Add annotations (rdfs properties)
    if instance.annotations:
        for key, value in instance.annotations.items():
            escaped_value = escape_ttl_string(value)
            lines.append(f'\trdfs:{key} "{escaped_value}" ;')

    # Add class object relationships (direct predicates)
    if hasattr(instance, 'class_objects') and instance.class_objects:
        for predicate, target_uri in instance.class_objects.items():
            lines.append(f'\tdici_onto:{predicate} <{target_uri}> ;')

    # Add label
    lines.append(f'\trdfs:label "{escape_ttl_string(instance.label)}"')

    # Collect attribute URIs
    attribute_uris = []
    attribute_declarations = []

    for attr_name, attr_data in instance.attributes.items():
        attr_uri = f"{instance.uri}/{attr_name}"
        attribute_uris.append(f"<{attr_uri}>")

        # Generate attribute declaration
        attr_lines = generate_attribute_ttl(attr_uri, attr_name, attr_data, instance.component_type)
        attribute_declarations.extend(attr_lines)

    # Add hasAttribute predicates
    if attribute_uris:
        lines.append(f' ;\n\tdici_onto:hasAttribute {", ".join(attribute_uris)}')

    # Close instance declaration with period
    lines[-1] = lines[-1] + " ."

    # Add specific attribute predicates
    if attribute_uris:
        lines.append("")
        for attr_name, attr_uri_str in zip(instance.attributes.keys(), attribute_uris):
            lines.append(f"<{instance.uri}> dici_onto:has{instance.component_type}{attr_name}Attribute {attr_uri_str} .")

    # Add attribute declarations
    if attribute_declarations:
        lines.append("")
        lines.extend(attribute_declarations)

    return lines


def generate_system_description_ttl(links: Sequence[Dict[str, Any]]) -> str:
    """Generate TTL for system_description graph"""

    lines = []

    # Add prefixes
    lines.extend([
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        ""
    ])

    # Process each link
    for link in links:
        lines.append(f"<{link['source_uri']}> dici_onto:{link['property']} <{link['target_uri']}> .")

    return "\n".join(lines)


def validate_ttl(ttl_content: str) -> Tuple[bool, Any]:
    """Validate TTL syntax"""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=ttl_content, format="turtle")
        return True, None
    except Exception as e:
        return False, str(e)


__all__ = [
    "generate_classes_and_attributes_ttl",
    "generate_instance_ttl",
    "generate_system_description_ttl",
    "validate_ttl",
]
