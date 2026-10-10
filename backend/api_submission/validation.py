# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Payload validation for API submission.

This is P0 of the semantic-layer roadmap (see docs/SEMANTIC_LAYER.md): before a
converted scenario is submitted to a service, check that it actually satisfies what
the service asked for. We validate the converted payload against the service's
requirements template and report:

  - which referenced attributes did not resolve to a value (missing),
  - which template references came back unresolved (still a literal like
    "Building.PeakSpaceHeatingPower" instead of a number),
  - whether the link structure produced any components at all.

The goal: a green tick should mean "this building genuinely has what the model
needs", not "we sent something and the service filled in the blanks".

This module stays GENERIC. It walks any template/payload pair and knows nothing
about a specific service. Every reference is REQUIRED unless the contract lists
it (or the attribute it reads) under `optional_attributes` or
`derived_attributes`: the same rule as the Scenario Builder's completeness gate,
both read through ``backend.service_requirements.contract``. A required field
that does not resolve is a blocking error; an optional one is a warning.

Headless: the Streamlit report renderer (``render_validation``) lives in the
``components.api_submission_module.validation`` shim, not here.
"""

from dataclasses import dataclass, field
from typing import Any, List

from backend.service_requirements.contract import (
    LINK_KEY,
    REQUIRED_KEY,
    TEMPLATE_KEY,
    exempt_references,
    is_link_block,
    is_reference,
    is_required,
    parse_reference,
    payload_template,
)


@dataclass
class ValidationResult:
    """Result of validating a converted payload against a service template."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    unresolved_fields: List[str] = field(default_factory=list)
    data_quality: str = "good"  # good | needs_review | poor
    placeholder_count: int = 0


def _is_reference(template_leaf: Any) -> bool:
    """True if a template leaf is a reference the converter resolves."""
    return is_reference(template_leaf)


def _is_unresolved(value: Any, reference: str) -> bool:
    """A reference is unresolved when the converter handed the literal
    reference back unchanged."""
    return isinstance(value, str) and value == reference


def validate_payload(payload: Any, template: Any) -> ValidationResult:
    """Validate a converted payload against the service contract.

    Validate the RAW (pre-clean) converted payload so unresolved references are
    still visible, since placeholder cleaning strips them.

    Args:
        payload: the converted payload (nested dict/list mirroring the template).
        template: the full service contract (with its control lists).
    """
    result = ValidationResult()
    exempt = exempt_references(template)
    if isinstance(template, dict) and template.get(REQUIRED_KEY):
        result.warnings.append(
            f"'{REQUIRED_KEY}' is deprecated and has no effect: every reference is "
            "required unless listed under optional_attributes or derived_attributes.")

    def walk(t: Any, p: Any, path: str) -> None:
        if isinstance(t, dict):
            # A link node: the converter expands it into a list of components.
            if is_link_block(t):
                if not isinstance(p, list) or len(p) == 0:
                    result.errors.append(
                        f"{path or 'scenario'}: no components found for link '{t[LINK_KEY]}'"
                    )
                else:
                    for i, item in enumerate(p):
                        walk(t[TEMPLATE_KEY], item, f"{path}[{i + 1}]")
                return
            # An implicit root block (component type keyed, no link:) that the
            # converter expanded into a component list — validate each element
            # against the same block.
            if isinstance(p, list):
                if len(p) == 0:
                    result.errors.append(
                        f"{path or 'scenario'}: no components found for '{path or 'root'}'"
                    )
                else:
                    for i, item in enumerate(p):
                        walk(t, item, f"{path}[{i + 1}]")
                return
            # A regular mapping: recurse into each field.
            for k, sub in t.items():
                if k in (LINK_KEY, TEMPLATE_KEY):
                    continue
                child = p.get(k) if isinstance(p, dict) else None
                walk(sub, child, f"{path}.{k}" if path else k)
            return

        # A leaf. Only references need resolving; literals are constants.
        ref = parse_reference(t)
        if ref is not None:
            required = is_required(ref, exempt)
            if p is None:
                result.missing_fields.append(path)
                msg = f"{path} ({t}) did not resolve to a value"
                (result.errors if required else result.warnings).append(
                    ("Required attribute missing: " if required else "Optional attribute missing: ") + msg
                )
            elif _is_unresolved(p, t):
                result.unresolved_fields.append(path)
                result.placeholder_count += 1
                msg = f"{path} still holds the unresolved reference '{p}'"
                (result.errors if required else result.warnings).append(
                    ("Required attribute unresolved: " if required else "Optional attribute unresolved: ") + msg
                )

    walk(payload_template(template), payload, "")

    # Nothing meaningful to submit (service_name/description alone don't count).
    if not payload or (isinstance(payload, dict) and not any(
        k not in ('service_name', 'description') for k in payload
    )):
        result.errors.append("Converted payload is empty, nothing to submit.")

    result.is_valid = len(result.errors) == 0
    if result.errors:
        result.data_quality = "poor"
    elif result.missing_fields or result.unresolved_fields:
        result.data_quality = "needs_review"
    else:
        result.data_quality = "good"
    return result
