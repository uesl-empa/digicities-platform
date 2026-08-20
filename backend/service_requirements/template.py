# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Service template YAML: generate from a component model, parse back into one.

The template convention (matching the shipped service templates and what
``backend.api_submission.ttl_converter`` walks at Convert time):

* header — ``service_name``, optional ``description`` and ``connection``,
  then ``scenario_data`` with ``uri: Scenario.URI`` / ``label: Scenario.label``
* root component — a block keyed by its path, carrying
  ``name: <Type>.label`` / ``uri: <Type>.URI`` plus attribute references
* child component — ``link: CL.<Parent>.<Child>`` + ``template:`` with
  ``uri`` and attribute references; nested children sit as siblings of
  ``link``/``template`` (the parser also accepts them inside the template,
  the hand-written style)
* attribute reference — ``<Type>.<attr>`` for a Static flavor,
  ``<Type>.<attr>.has{Historic,Live,Future}TimeSeriesReference`` for a
  dynamic one (field named ``<attr>_historic`` etc. by default)

A load-bearing asymmetry, pinned by the characterization tests: the generator
skips every Static ``label`` — the root keeps its label through the ``name``
field, but a child's label never reaches its template, so a generate -> parse
round trip drops it.

Known consumer-side duplicate: the onboarding agent has its own generator in
``digicities-onboarding-agent/onboarding_agent/core/service_template.py``.
This module is the authoritative one; unifying the onboarder is a follow-up.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from backend.service_requirements.models import ComponentEntry

# Dynamic attribute flavor -> the time-series reference predicate its field
# points at. Anything unknown falls back to the historic reference.
TS_REFERENCE = {
    'Historic': 'hasHistoricTimeSeriesReference',
    'Live': 'hasLiveTimeSeriesReference',
    'Future': 'hasFutureTimeSeriesReference',
}


def pascal_case(s: str) -> str:
    """PascalCase from any spelling ('heat pump' -> 'HeatPump'); '' stays as given."""
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", s) if w) or s


def camel_case(s: str) -> str:
    """camelCase from any spelling ('HeatPump' -> 'heatPump')."""
    p = pascal_case(s)
    return p[:1].lower() + p[1:] if p else s


def attribute_field(component_type: str, attr_name: str, attr_type: str) -> Tuple[str, str]:
    """(default field name, reference string) for one configured attribute."""
    if attr_type == "Static":
        return attr_name, f'{component_type}.{attr_name}'
    ts_reference = TS_REFERENCE.get(attr_type, 'hasHistoricTimeSeriesReference')
    return (f"{attr_name}_{attr_type.lower()}",
            f'{component_type}.{attr_name}.{ts_reference}')


def build_service_template(
    service_name: str,
    component_entries: Sequence[ComponentEntry],
    description: Optional[str] = None,
    connection: Optional[dict] = None,
    custom_field_names: Optional[Dict[str, str]] = None,
    use_custom_names: bool = True,
) -> Dict[str, Any]:
    """The complete service-template structure for the given component model.

    Returns ``{}`` when ``service_name`` is empty (nothing to name the service
    by). ``custom_field_names`` maps ``"<path>|<attr>|<flavor>"`` keys to
    user-chosen YAML field names; the reference string is never customized,
    only the key. Key order matches the shipped templates: service_name,
    description, connection, scenario_data.
    """
    if not service_name:
        return {}

    custom_names = custom_field_names or {}

    structure: Dict[str, Any] = {'service_name': service_name}
    if description:
        structure['description'] = description
    if connection:
        structure['connection'] = connection
    structure['scenario_data'] = {
        'uri': 'Scenario.URI',
        'label': 'Scenario.label'
    }

    def get_field_name(default_name, component_path, attr_name, attr_type):
        key = f"{component_path}|{attr_name}|{attr_type}"
        if use_custom_names and key in custom_names:
            return custom_names[key]
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
                        # Static labels never become fields: the root's label is
                        # its 'name', a child's is dropped (the pinned asymmetry).
                        if attr_type == "Static" and attr_name == "label":
                            continue
                        default_field_name, reference = attribute_field(
                            entry.component_type, attr_name, attr_type)
                        field_name = get_field_name(
                            default_field_name, entry.path, attr_name, attr_type)

                        if entry.level == 1:
                            entry_structure[field_name] = reference
                        else:
                            entry_structure['template'][field_name] = reference

                children = build_nested_structure(entries, entry.path)
                for child_key, child_value in children.items():
                    entry_structure[child_key] = child_value

                result[entry.path] = entry_structure

        return result

    nested_structure = build_nested_structure(component_entries)
    structure['scenario_data'].update(nested_structure)

    return structure


def list_template_fields(
    component_entries: Sequence[ComponentEntry],
) -> List[Tuple[str, str, str, str, str]]:
    """Every customizable field the current model would generate.

    Returns (component_path, attr_name, attr_type, default_field_name,
    reference) tuples — the rename UI's working set. Static labels are
    excluded for the same reason the generator skips them.
    """
    fields = []

    for entry in component_entries:
        for attr_name, attr_types in entry.configured_attributes.items():
            for attr_type in attr_types:
                if attr_type == "Static" and attr_name == "label":
                    continue
                default_field_name, reference = attribute_field(
                    entry.component_type, attr_name, attr_type)
                fields.append((entry.path, attr_name, attr_type,
                               default_field_name, reference))

    return fields


def entries_from_type_tree(
    specs: Iterable[Tuple[str, Optional[str], Sequence[str]]],
) -> List[ComponentEntry]:
    """Component entries from flat (component_type, parent_type, attributes) rows.

    The REST API's template endpoint speaks in types, not paths: each row names
    a component type, optionally its parent's type, and the attributes it needs
    (all Static). This normalizes that shape into :class:`ComponentEntry`
    objects for :func:`build_service_template` — PascalCase types, camelCase
    YAML paths, ``CL.<Parent>.<Child>`` links, levels from the parent chain.

    A row whose parent type matches no other row is kept but unreachable, so
    the generator drops it (same as the API's old recursive builder did); a
    parent cycle terminates instead of recursing forever.
    """
    rows = [(pascal_case(t), pascal_case(p) if p else "", list(attrs))
            for t, p, attrs in specs]
    parent_of = {t: p for t, p, _ in rows}

    def level_of(component_type: str, seen: frozenset) -> int:
        parent = parent_of.get(component_type, "")
        if not parent:
            return 1
        if parent in seen or parent not in parent_of:
            return 2  # orphan or cycle: not a root, and never rendered
        return 1 + level_of(parent, seen | {component_type})

    entries = []
    for t, p, attrs in rows:
        entries.append(ComponentEntry(
            path=camel_case(t),
            component_type=t,
            link_pattern=f"CL.{p}.{t}" if p else "",
            parent_path=camel_case(p) if p else "",
            level=level_of(t, frozenset()),
            configured_attributes={a: ["Static"] for a in attrs},
        ))
    return entries


def parse_yaml_to_components(yaml_content: str) -> Tuple[str, List[ComponentEntry]]:
    """Parse a service-template YAML back into (service_name, component entries).

    Accepts both nesting styles for children (sibling of link/template as this
    generator writes, or inside the template as hand-written services do).
    Raises ``ValueError`` on missing ``service_name`` or unparseable YAML.
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
    """Attribute name -> flavor list, recovered from one component's YAML block.

    Reference strings decide the attribute and its flavor; ``*_historic`` /
    ``*_live`` / ``*_future`` field-name suffixes win over the reference when
    they disagree, and a ``name`` field referencing ``label`` normalizes to
    ``label``. Nested dicts that are themselves child components (link+template
    or uri+label/name) are left to the component parser.
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


def parse_service_template(
    yaml_content: str,
) -> Tuple[str, List[ComponentEntry], Optional[str], Optional[dict]]:
    """One-call load of a service template: components plus template metadata.

    Returns (service_name, component_entries, description, connection). The
    ``connection:`` block (where the service listens, used for
    auto-registration) and the description aren't part of the component model,
    but a load -> edit -> save round trip must keep them rather than silently
    dropping them.
    """
    service_name, component_entries = parse_yaml_to_components(yaml_content)
    raw = yaml.safe_load(yaml_content) or {}
    return service_name, component_entries, raw.get('description'), raw.get('connection')
