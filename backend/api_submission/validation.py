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
about a specific service. A template may optionally list `required_attributes`
(leaf field names that must resolve); those become blocking errors rather than
warnings.

Headless: the Streamlit report renderer (``render_validation``) lives in the
``components.api_submission_module.validation`` shim, not here.
"""

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

# A template leaf is an ontology reference (e.g. "Building.GroundFloorArea",
# "Scenario.URI") when it is a CapitalisedComponent.attribute string. Plain string
# constants in the template (service_name: FlexibilityOptimizer, free-text
# description) are not references and need no checking.
_REFERENCE_RE = re.compile(r'^[A-Z][A-Za-z0-9_]*\.[A-Za-z0-9_.]+$')


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
    """True if a template leaf is an ontology reference the converter should resolve."""
    return isinstance(template_leaf, str) and bool(_REFERENCE_RE.match(template_leaf))


def _is_unresolved(value: Any, reference: str) -> bool:
    """A reference is unresolved when the converter handed the literal reference
    back unchanged, or left a `<...not_found>` marker in place."""
    if not isinstance(value, str):
        return False
    return value == reference or '_not_found' in value


def validate_payload(payload: Any, template: Any,
                     required: Optional[List[str]] = None) -> ValidationResult:
    """Validate a converted payload against the service requirements template.

    Validate the RAW (pre-clean) converted payload so unresolved references are
    still visible, since placeholder cleaning strips them.

    Args:
        payload: the converted payload (nested dict/list mirroring the template).
        template: the service requirements template (nested dict).
        required: leaf field names that must resolve. Defaults to the template's
            top-level `required_attributes` list if present.
    """
    result = ValidationResult()

    if required is None and isinstance(template, dict):
        required = template.get('required_attributes') or []
    required_set = set(required or [])

    def walk(t: Any, p: Any, path: str) -> None:
        if isinstance(t, dict):
            # A link node: the converter expands it into a list of components.
            if 'link' in t and 'template' in t:
                if not isinstance(p, list) or len(p) == 0:
                    result.errors.append(
                        f"{path or 'scenario'}: no components found for link '{t['link']}'"
                    )
                else:
                    for i, item in enumerate(p):
                        walk(t['template'], item, f"{path}[{i + 1}]")
                return
            # A regular mapping: recurse into each field.
            for k, sub in t.items():
                if k in ('link', 'template', 'required_attributes'):
                    continue
                child = p.get(k) if isinstance(p, dict) else None
                walk(sub, child, f"{path}.{k}" if path else k)
            return

        # A leaf. Only ontology references need resolving; literals are constants.
        if _is_reference(t):
            key = path.split('.')[-1].split('[')[0]
            is_required = key in required_set
            if p is None:
                result.missing_fields.append(path)
                msg = f"{path} ({t}) did not resolve to a value"
                (result.errors if is_required else result.warnings).append(
                    ("Required attribute missing: " if is_required else "") + msg
                )
            elif _is_unresolved(p, t):
                result.unresolved_fields.append(path)
                result.placeholder_count += 1
                msg = f"{path} still holds the unresolved reference '{p}'"
                (result.errors if is_required else result.warnings).append(
                    ("Required attribute unresolved: " if is_required else "") + msg
                )

    walk(template, payload, "")

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
