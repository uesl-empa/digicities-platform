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

The functions are deliberately verbatim ports: the extraction is heuristic
(``Component.Attribute`` string patterns, a small context map for well-known
collection keys), and the emitter's completeness gate keys off exactly the
dotted-path form produced here, so behaviour must not drift from what the
Streamlit builder pinned.
"""
from __future__ import annotations

from typing import Any

def extract_component_links(yaml_content: dict) -> list[str]:
    """All ``CL.Source.Target`` patterns found under any ``link:`` key."""
    links: list[str] = []

    def find_links(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "link" and isinstance(value, str) and value.startswith("CL."):
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
    the ``ComponentType.Attribute`` prefixes of template values."""
    component_types: set[str] = set()

    def find_component_types(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict) and "type" in value:
                    comp_type = value["type"]
                    if isinstance(comp_type, str) and not comp_type.startswith("CL."):
                        component_types.add(comp_type)
                elif key == "template" and isinstance(value, dict):
                    for template_value in value.values():
                        if isinstance(template_value, str) and "." in template_value:
                            comp_type = template_value.split(".")[0]
                            if comp_type and not comp_type.startswith("CL"):
                                component_types.add(comp_type)
                elif isinstance(value, (dict, list)):
                    find_component_types(value)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_component_types(item)

    find_component_types(yaml_content.get("scenario_data", {}))
    return component_types


def drop_optional_requirements(yaml_content: dict, required: dict, nested: dict | None = None) -> None:
    """Remove the template's ``optional_attributes`` (``Type.Attr``) from the
    required sets, in place.

    An optional attribute stays in the payload template, but an instance without
    a value for it is sent without it instead of being dropped from the scenario.
    The onboarding agent marks an input optional when the source data has it for
    some instances but not all — requiring it would silently throw away the
    instances the data does describe. Templates without the key are unchanged.
    """
    for key in (yaml_content or {}).get("optional_attributes") or []:
        comp_type, _, attr = str(key).partition(".")
        if not attr or comp_type not in required:
            continue
        kept = [a for a in required[comp_type] if a != attr and not str(a).startswith(attr + ".")]
        if isinstance(required[comp_type], set):
            kept = set(kept)
        required[comp_type] = kept
        if nested is not None and comp_type in nested:
            nested[comp_type].pop(attr, None)


def extract_required_attributes_enhanced(
    yaml_content: dict,
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    """Required attributes per component type, in the dotted-path form the
    emitter's completeness gate resolves.

    Returns ``(required_attributes, nested_requirements)``:
    - ``required_attributes[CompType]`` holds simple names (``HubHeight``) and,
      for nested requirements, BOTH the base attribute (``Power``) and the full
      dotted path (``Power.hasHistoricTimeSeriesReference``).
    - ``nested_requirements[CompType][BaseAttr]`` lists the nested properties.
    """
    required_attributes: dict[str, set] = {}
    nested_requirements: dict[str, dict[str, set]] = {}

    def process_attribute_pattern(pattern_value: str) -> None:
        parts = pattern_value.split(".")
        if len(parts) < 2:
            return
        comp_type = parts[0]
        required_attributes.setdefault(comp_type, set())
        if len(parts) > 2:
            base_attr = parts[1]
            nested_prop = ".".join(parts[2:])
            required_attributes[comp_type].add(base_attr)
            nested_requirements.setdefault(comp_type, {}).setdefault(base_attr, set()).add(nested_prop)
            required_attributes[comp_type].add(f"{base_attr}.{nested_prop}")
        else:
            required_attributes[comp_type].add(parts[1])

    def find_attributes(data: Any) -> None:
        # NOTE: component types come from the dotted values themselves
        # (``GlobalWindAtlasSite.Roughness`` names its type). The verbatim
        # Streamlit port carried a hardcoded collection-key → usecase-class
        # context map here, whose result was threaded through the recursion
        # but never read — removed 2026-09-24 (hardcoding audit), behavior
        # identical.
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "template" and isinstance(value, dict):
                    for template_value in value.values():
                        if isinstance(template_value, str) and "." in template_value:
                            process_attribute_pattern(template_value)
                        elif isinstance(template_value, dict):
                            find_attributes(template_value)
                elif isinstance(value, str) and "." in value and key != "link":
                    process_attribute_pattern(value)
                elif isinstance(value, (dict, list)):
                    find_attributes(value)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    find_attributes(item)

    find_attributes(yaml_content.get("scenario_data", {}))
    drop_optional_requirements(yaml_content, required_attributes, nested_requirements)

    result_attributes = {
        comp_type: sorted(attrs)
        for comp_type, attrs in required_attributes.items()
        if attrs and comp_type != "CL"
    }
    result_nested = {
        comp_type: {base: sorted(props) for base, props in nested.items() if props}
        for comp_type, nested in nested_requirements.items()
        if nested and comp_type != "CL"
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
    component_types.update(t for t in required_attributes if t != "Scenario")

    component_types.update(extract_component_types_from_templates(yaml_content))

    component_types.discard("Scenario")
    return sorted(component_types)


def parse_service_requirements(yaml_content: dict) -> dict[str, Any]:
    """The full constraint object the builder UI needs for one service."""
    required_attributes, nested_requirements = extract_required_attributes_enhanced(yaml_content)
    return {
        "service_name": yaml_content.get("service_name"),
        "component_links": extract_component_links(yaml_content),
        "required_component_types": extract_all_required_component_types(yaml_content),
        "required_attributes": required_attributes,
        "nested_requirements": nested_requirements,
    }
