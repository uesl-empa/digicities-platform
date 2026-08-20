# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Replica Builder in-app model: instances + links, headless.

The Streamlit Replica Builder edits a digital replica as two session lists —
``replica_instances`` (:class:`ComponentInstance` objects) and ``replica_links``
(plain dicts). This module owns that model and its CRUD rules, operating on the
lists passed in — never on ``st.session_state``. The Streamlit components
(``replica_instance_manager`` / ``replica_link_manager``) are thin shims that
hand the session lists to these functions and render the outcome.

Moved verbatim from ``components/replica_builder/replica_instance_manager.py``
and ``replica_link_manager.py`` (Phase 5 of the backend/UI split); UI error
reporting became exceptions / return values:

* :func:`create_instance` raises ``ValueError`` on a duplicate id (was
  ``st.error`` + ``None``).
* :func:`create_link` returns ``(link, None)`` on success and ``(None, reason)``
  with reason ``"not_found"`` / ``"duplicate"`` otherwise (was ``st.error`` /
  ``st.warning`` + ``False``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ComponentInstance:
    """Represents a component instance"""
    id: str
    component_type: str
    uri: str
    label: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    class_objects: Dict[str, str] = field(default_factory=dict)  # predicate: target_uri

    def to_dict(self):
        return {
            'id': self.id,
            'component_type': self.component_type,
            'uri': self.uri,
            'label': self.label,
            'attributes': self.attributes,
            'annotations': self.annotations,
            'class_objects': self.class_objects
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComponentInstance":
        return cls(
            id=data['id'],
            component_type=data['component_type'],
            uri=data['uri'],
            label=data.get('label', data['id']),
            attributes=data.get('attributes', {}) or {},
            annotations=data.get('annotations', {}) or {},
            class_objects=data.get('class_objects', {}) or {},
        )


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------

def generate_instance_uri(project_uri: str, component_type: str, instance_id: str, uri_mode: str) -> str:
    """Generate instance URI based on mode"""
    if uri_mode == "default":
        return f"{project_uri}/{component_type}/{instance_id}"
    elif uri_mode == "complete-project-uri":
        return f"{project_uri}#{instance_id}"
    elif uri_mode == "full-uri-in-cell":
        return f"{project_uri}/{instance_id}"
    else:
        return f"{project_uri}/{component_type}/{instance_id}"


def create_instance(
    instances: List[ComponentInstance],
    component_type: str,
    instance_id: str,
    project_uri: str,
    uri_mode: str,
    label: Optional[str] = None,
) -> ComponentInstance:
    """Create a new component instance and append it to ``instances``.

    Raises ``ValueError`` when an instance with the same id already exists.
    """
    if any(inst.id == instance_id for inst in instances):
        raise ValueError(f"Instance with ID '{instance_id}' already exists")

    uri = generate_instance_uri(project_uri, component_type, instance_id, uri_mode)

    instance = ComponentInstance(
        id=instance_id,
        component_type=component_type,
        uri=uri,
        label=label or instance_id,
        attributes={},
        annotations={}
    )

    instances.append(instance)
    return instance


def delete_instance(
    instances: List[ComponentInstance],
    links: List[Dict[str, Any]],
    instance_id: str,
) -> Tuple[List[ComponentInstance], List[Dict[str, Any]], bool]:
    """Delete an instance (and any links involving it).

    Returns ``(new_instances, new_links, deleted)`` — the input lists are not
    mutated; assign the results back (the Streamlit shim writes them to session
    state).
    """
    new_instances = [inst for inst in instances if inst.id != instance_id]

    if len(new_instances) < len(instances):
        new_links = [
            link for link in links
            if link['source_id'] != instance_id and link['target_id'] != instance_id
        ]
        return new_instances, new_links, True

    return new_instances, list(links), False


def get_instance_by_id(instances: List[ComponentInstance], instance_id: str) -> Optional[ComponentInstance]:
    """Get instance by ID"""
    for inst in instances:
        if inst.id == instance_id:
            return inst
    return None


def get_instances_by_type(instances: List[ComponentInstance], component_type: str) -> List[ComponentInstance]:
    """Get all instances of a specific type"""
    return [inst for inst in instances if inst.component_type == component_type]


def component_type_names(ontology_components: Dict[str, Any]) -> List[str]:
    """Instantiable component types from the loaded ontology components map.

    Filters out the attribute-class side of the naming convention and the
    abstract roots — same rule the Instances tab has always applied.
    """
    return [
        name for name in ontology_components
        if not name.endswith('Attribute') and name not in ['Attribute', 'Component']
    ]


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

DEFAULT_LINK_PROPERTIES = ['locatedIn', 'connectedTo']


def extract_link_property_names(result) -> List[str]:
    """Local names of link properties from a ``get_link_properties`` DataFrame.

    Returns the sorted, de-duplicated local names, or ``[]`` when the frame is
    ``None``/empty (the caller decides on a fallback).
    """
    if result is None or getattr(result, "empty", True):
        return []
    properties: List[str] = []
    for _, row in result.iterrows():
        prop_uri = row['property']
        # Extract local name
        if '#' in prop_uri:
            prop_name = prop_uri.split('#')[-1]
        elif '/' in prop_uri:
            prop_name = prop_uri.split('/')[-1]
        else:
            prop_name = prop_uri

        if prop_name not in properties:
            properties.append(prop_name)
    return sorted(properties)


def load_link_properties(client) -> List[str]:
    """linksComponent subproperty local names from the ontology.

    Falls back to :data:`DEFAULT_LINK_PROPERTIES` when there is no client or the
    query returns nothing. Query errors propagate (the UI shim catches them and
    warns).
    """
    if not client:
        return list(DEFAULT_LINK_PROPERTIES)
    from backend.graphdb.queries import ontology as gq_ont

    names = extract_link_property_names(gq_ont.get_link_properties(client))
    return names if names else list(DEFAULT_LINK_PROPERTIES)


def create_link(
    instances: List[ComponentInstance],
    links: List[Dict[str, Any]],
    source_id: str,
    target_id: str,
    link_property: Optional[str],
    custom_property: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Create a link between instances, appending it to ``links``.

    Returns ``(link, None)`` on success, ``(None, "not_found")`` when either
    instance is missing, ``(None, "duplicate")`` when the link already exists.
    """
    source = next((inst for inst in instances if inst.id == source_id), None)
    target = next((inst for inst in instances if inst.id == target_id), None)

    if not source or not target:
        return None, "not_found"

    # Use custom property if provided
    property_name = custom_property if custom_property else link_property

    # Check if link already exists
    existing = any(
        link['source_id'] == source_id and
        link['target_id'] == target_id and
        link['property'] == property_name
        for link in links
    )

    if existing:
        return None, "duplicate"

    link = {
        'source_id': source_id,
        'target_id': target_id,
        'source_uri': source.uri,
        'target_uri': target.uri,
        'source_type': source.component_type,
        'target_type': target.component_type,
        'property': property_name,
        'source_label': source.label,
        'target_label': target.label
    }

    links.append(link)
    return link, None


def delete_link(
    links: List[Dict[str, Any]],
    source_id: str,
    target_id: str,
    property_name: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Delete a link. Returns ``(new_links, deleted)`` — assign the list back."""
    new_links = [
        link for link in links
        if not (link['source_id'] == source_id and
                link['target_id'] == target_id and
                link['property'] == property_name)
    ]
    return new_links, len(new_links) < len(links)


def get_links_for_instance(links: List[Dict[str, Any]], instance_id: str) -> List[Dict[str, Any]]:
    """Get all links involving an instance"""
    return [
        link for link in links
        if link['source_id'] == instance_id or link['target_id'] == instance_id
    ]


__all__ = [
    "ComponentInstance",
    "generate_instance_uri",
    "create_instance",
    "delete_instance",
    "get_instance_by_id",
    "get_instances_by_type",
    "component_type_names",
    "DEFAULT_LINK_PROPERTIES",
    "extract_link_property_names",
    "load_link_properties",
    "create_link",
    "delete_link",
    "get_links_for_instance",
]
