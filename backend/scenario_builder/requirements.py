# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Service-template requirements for the Scenario Builder, headless.

A service template (services/*.yaml) constrains what a scenario needs: which
component types must be present, which ``CL.Source.Target`` links must exist,
and which attributes (including dotted ``Base.nestedProp`` paths) each
component must carry. The Streamlit builder derived these constraints inline
(apps/streamlit/components/scenario_builder/scenario_builder.py); this module
is that logic moved behind the backend seam so the REST API — and with it the
React builder — can drive the same service-constrained flow.

What counts as a reference, a link and a required input is defined once in
``backend.service_requirements.contract`` (shared with the converter and payload
validation). The emitter's completeness gate keys off exactly the dotted-path
form produced here.
"""
from __future__ import annotations

from typing import Any

from backend.scenario_builder.semantics import names_scenario_class
from backend.service_requirements.contract import (
    LINK_KEY,
    TEMPLATE_KEY,
    exempt_references,
    parse_link,
    parse_reference,
    required_references,
)


def extract_component_links(yaml_content: dict) -> list[str]:
    """All ``CL.Source.Target`` patterns found under any ``link:`` key."""
    links: list[str] = []

    def find_links(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if key == LINK_KEY and parse_link(value) is not None:
                    links.append(value)
                elif isinstance(value, (dict, list)):
                    find_links(value)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_links(item)

    find_links(yaml_content)
    return sorted(set(links))


def extract_component_types_from_templates(yaml_content: dict) -> set[str]:
    """Component types named in template blocks: explicit ``type:`` fields and
    the owners of the references in ``template`` blocks."""
    component_types: set[str] = set()

    def find_component_types(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict) and "type" in value:
                    comp_type = value["type"]
                    if isinstance(comp_type, str) and parse_link(comp_type) is None:
                        component_types.add(comp_type)
                elif key == TEMPLATE_KEY and isinstance(value, dict):
                    for template_value in value.values():
                        ref = parse_reference(template_value)
                        if ref is not None:
                            component_types.add(ref.owner)
                elif isinstance(value, (dict, list)):
                    find_component_types(value)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_component_types(item)

    find_component_types(yaml_content.get("scenario_data", {}))
    return component_types


def drop_optional_requirements(yaml_content: dict, required: dict, nested: dict | None = None) -> None:
    """Remove the template's ``optional_attributes`` and ``derived_attributes``
    (``Type.Attr``) from already-extracted required sets, in place.

    An optional attribute stays in the payload template, but an instance without
    a value for it is sent without it instead of being dropped from the scenario.
    A derived attribute (an aggregate such as ``Tree.WeightMean``) is computed at
    convert time, so no stored instance carries it. The rule itself lives in
    ``backend.service_requirements.contract`` (``is_required``);
    ``extract_required_attributes_enhanced`` applies it while extracting, this
    helper applies it to sets a caller built itself.
    """
    for key in exempt_references(yaml_content):
        ref = parse_reference(key)
        if ref is None or ref.owner not in required:
            continue
        attr = ".".join(ref.members)
        kept = [a for a in required[ref.owner]
                if a != attr and not str(a).startswith(attr + ".")]
        if isinstance(required[ref.owner], set):
            kept = set(kept)
        required[ref.owner] = kept
        if nested is not None and ref.owner in nested:
            nested[ref.owner].pop(attr, None)


def extract_required_attributes_enhanced(
    yaml_content: dict,
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    """Required attributes per component type, in the dotted-path form the
    emitter's completeness gate resolves.

    Which references are required is decided by
    ``backend.service_requirements.contract.required_references`` (required
    unless listed under ``optional_attributes`` / ``derived_attributes``), the
    same function payload validation uses. Returns
    ``(required_attributes, nested_requirements)``:
    - ``required_attributes[CompType]`` holds simple names (``HubHeight``,
      ``URI``) and, for nested requirements, BOTH the base attribute (``Power``)
      and the full dotted path (``Power.hasHistoricTimeSeriesReference``).
    - ``nested_requirements[CompType][BaseAttr]`` lists the nested properties.
    """
    required_attributes: dict[str, set] = {}
    nested_requirements: dict[str, dict[str, set]] = {}

    for ref in required_references(yaml_content):
        attrs = required_attributes.setdefault(ref.owner, set())
        if len(ref.members) > 1:
            base_attr = ref.members[0]
            nested_prop = ".".join(ref.members[1:])
            attrs.add(base_attr)
            attrs.add(f"{base_attr}.{nested_prop}")
            nested_requirements.setdefault(ref.owner, {}).setdefault(base_attr, set()).add(nested_prop)
        else:
            attrs.add(ref.members[0])

    result_attributes = {
        comp_type: sorted(attrs)
        for comp_type, attrs in required_attributes.items()
        if attrs
    }
    result_nested = {
        comp_type: {base: sorted(props) for base, props in nested.items() if props}
        for comp_type, nested in nested_requirements.items()
        if nested
    }
    return result_attributes, result_nested


def extract_all_required_component_types(yaml_content: dict) -> list[str]:
    """Every component type the service needs: CL link endpoints, attribute
    owners, and template-declared types — minus ``Scenario`` itself."""
    component_types: set[str] = set()

    for link in extract_component_links(yaml_content):
        parts = link.split(".")
        if len(parts) >= 3:
            component_types.add(parts[1])
            component_types.add(parts[2])

    required_attributes, _ = extract_required_attributes_enhanced(yaml_content)
    component_types.update(required_attributes)
    component_types.update(extract_component_types_from_templates(yaml_content))

    # The scenario itself is a link endpoint, never a component to pick.
    return sorted(t for t in component_types if not names_scenario_class(t))


def parse_service_requirements(yaml_content: dict) -> dict[str, Any]:
    """The full constraint object the builder UI needs for one service.

    ``requirements_by_class`` maps each component class to the attributes the
    contract requires of it (``{"Building": ["URI", "GroundFloorArea"]}``).
    It is not the contract's deprecated ``required_attributes`` list of
    references, hence its own name."""
    by_class, nested_requirements = extract_required_attributes_enhanced(yaml_content)
    return {
        "service_name": yaml_content.get("service_name"),
        "component_links": extract_component_links(yaml_content),
        "required_component_types": extract_all_required_component_types(yaml_content),
        "requirements_by_class": by_class,
        "nested_requirements": nested_requirements,
    }
