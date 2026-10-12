# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""How a contract is read: references, links, control lists, required inputs.

ONE definition, used by every module that reads a contract (the converter, its
clean step, payload validation and the Scenario Builder's completeness gate),
so they cannot disagree about what a contract asks for.

* A **reference** is a template leaf of the grammar's shape
  ``class-token "." member`` (docs/SERVICE_REQUIREMENTS_SPEC.md section 3):
  dot-separated local names, at least two. ``CL.`` is the link namespace, so a
  ``CL.S.T`` string is a link, never a reference.
* The **control lists** (``optional_attributes``, ``derived_attributes``,
  ``required_attributes``) and ``connection`` describe the contract; they are
  never part of the payload sent to the service.
* **Required unless listed optional** (James, 2026-10-10): every reference in
  ``scenario_data`` is required unless it, or the attribute it reads
  (``T.A`` for ``T.A.p``), is listed under ``optional_attributes`` or
  ``derived_attributes``. The lists hold references as written (``T.A``),
  never payload field names. ``required_attributes`` is deprecated: every
  reference is required already.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator, Optional

OPTIONAL_KEY = "optional_attributes"
DERIVED_KEY = "derived_attributes"
REQUIRED_KEY = "required_attributes"  # deprecated, see module docstring
CONTROL_KEYS = (OPTIONAL_KEY, DERIVED_KEY, REQUIRED_KEY)
# Top-level keys that describe the contract and never reach the payload.
NON_PAYLOAD_KEYS = ("connection",) + CONTROL_KEYS

LINK_KEY = "link"
TEMPLATE_KEY = "template"
LINK_NAMESPACE = "CL"
IDENTITY_MEMBERS = ("uri", "label")  # grammar: matched without regard to case

_LOCAL_NAME = r"[A-Za-z_][A-Za-z0-9_\-]*"
_DOTTED = re.compile(rf"^{_LOCAL_NAME}(?:\.{_LOCAL_NAME})+$")


@dataclass(frozen=True)
class Reference:
    """A parsed ``T.member[.property...]`` reference."""
    owner: str
    members: tuple

    @property
    def text(self) -> str:
        return ".".join((self.owner,) + self.members)

    @property
    def identity(self) -> Optional[str]:
        """``"uri"`` / ``"label"`` for an identity field, else None."""
        if len(self.members) == 1 and self.members[0].lower() in IDENTITY_MEMBERS:
            return self.members[0].lower()
        return None

    @property
    def attribute(self) -> Optional[str]:
        """The attribute class the reference reads, None for an identity field."""
        return None if self.identity else self.members[0]

    @property
    def attribute_ref(self) -> Optional[str]:
        """``T.A`` for ``T.A`` and ``T.A.p``; None for an identity field."""
        return None if self.identity else f"{self.owner}.{self.members[0]}"


def _split(leaf: Any) -> Optional[list]:
    if not isinstance(leaf, str) or not _DOTTED.match(leaf):
        return None
    return leaf.split(".")


def parse_reference(leaf: Any) -> Optional[Reference]:
    """The reference a template leaf states, or None for a literal or a link."""
    parts = _split(leaf)
    if parts is None or parts[0] == LINK_NAMESPACE:
        return None
    return Reference(parts[0], tuple(parts[1:]))


def is_reference(leaf: Any) -> bool:
    return parse_reference(leaf) is not None


def parse_link(leaf: Any) -> Optional[tuple]:
    """``(source, target)`` for a ``CL.S.T`` link-ref, else None."""
    parts = _split(leaf)
    if parts is None or parts[0] != LINK_NAMESPACE or len(parts) != 3:
        return None
    return parts[1], parts[2]


def is_link_block(node: Any) -> bool:
    return isinstance(node, dict) and LINK_KEY in node and TEMPLATE_KEY in node


def payload_template(contract: Any) -> Any:
    """The contract without the keys that describe it (connection, control lists)."""
    if not isinstance(contract, dict):
        return contract
    return {k: v for k, v in contract.items() if k not in NON_PAYLOAD_KEYS}


def iter_references(block: Any) -> Iterator[Reference]:
    """Every reference in a template block, in document order.

    Link values are links, not references. A YAML list is read for the blocks
    it holds; a string directly inside a list is a literal.
    """
    if isinstance(block, list):
        for item in block:
            if isinstance(item, (dict, list)):
                yield from iter_references(item)
    elif isinstance(block, dict):
        for key, value in block.items():
            if key == LINK_KEY:
                continue
            if isinstance(value, (dict, list)):
                yield from iter_references(value)
            else:
                ref = parse_reference(value)
                if ref is not None:
                    yield ref


def exempt_references(contract: Any) -> set:
    """The references the contract lists as optional or derived, as written."""
    if not isinstance(contract, dict):
        return set()
    listed = list(contract.get(OPTIONAL_KEY) or []) + list(contract.get(DERIVED_KEY) or [])
    return {str(item).strip() for item in listed}


def derived_references(contract: Any) -> list:
    """The ``derived_attributes`` entries as references (``Tree.WeightMean``),
    deduplicated, in the order listed. An entry that is not a reference is
    left out: the list names attributes, never free text."""
    if not isinstance(contract, dict):
        return []
    seen: dict = {}
    for item in contract.get(DERIVED_KEY) or []:
        ref = parse_reference(str(item).strip())
        if ref is not None and ref.attribute is not None:
            seen.setdefault(ref.text, ref)
    return list(seen.values())


def is_required(ref: Reference, exempt: set) -> bool:
    """Required unless the reference, or the attribute it reads, is listed."""
    if ref.text in exempt:
        return False
    return ref.attribute_ref is None or ref.attribute_ref not in exempt


def required_references(contract: Any) -> list:
    """The references in ``scenario_data`` the contract requires, deduplicated,
    in document order."""
    if not isinstance(contract, dict):
        return []
    exempt = exempt_references(contract)
    seen: dict = {}
    for ref in iter_references(contract.get("scenario_data") or {}):
        if is_required(ref, exempt):
            seen.setdefault(ref.text, ref)
    return list(seen.values())
