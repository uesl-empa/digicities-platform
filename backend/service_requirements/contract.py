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
* A **value spec** is a field that also names the unit its value must be in:
  ``{ref: T.A, unit: KiloW}``, and for a cost ``{ref: T.A, unit: KiloW-HR,
  currency: CHF}`` (the unit is what the cost is per). Units are QUDT codes. The
  converter sends the value in that unit (``backend.unit_conversion``); its
  ``ref`` is a reference like any other.
* **Units in the payload**: the payload carries the unit of every value the
  data states one for, in a top-level ``units`` block that mirrors it; what the
  service does with them is up to the service. ``units_in_payload: false``
  leaves the block out.
* **Outputs** (``outputs``, optional): what the service returns, and which input
  component each result belongs to. Describes the contract and is never sent.
  A contract without the block means the same as before: what comes back is
  undeclared. See :func:`parse_outputs`.
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
# A registration that says ``units_in_payload: false`` is sent its values
# without the ``units`` block (docs/SERVICE_REQUIREMENTS_SPEC.md section 4.7).
UNITS_IN_PAYLOAD_KEY = "units_in_payload"
# The payload's top-level key that gives the unit of every value it holds.
UNITS_KEY = "units"
# Top-level keys that describe the contract and never reach the payload.
OUTPUTS_KEY = "outputs"
NON_PAYLOAD_KEYS = ("connection", UNITS_IN_PAYLOAD_KEY, OUTPUTS_KEY) + CONTROL_KEYS
# An output of the whole run, not of one component in it.
SCENARIO_CLASS = "Scenario"

LINK_KEY = "link"
TEMPLATE_KEY = "template"
LINK_NAMESPACE = "CL"
IDENTITY_MEMBERS = ("uri", "label")  # grammar: matched without regard to case
# A flow's two ends (``EnergyCarrierFlow.hasSource``): the components it links,
# read by the converter as URIs. Links, not attributes: never required as one.
FLOW_END_MEMBERS = ("hassource", "hasdestination")

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
    def flow_end(self) -> Optional[str]:
        """``"hassource"`` / ``"hasdestination"`` for a flow's end, else None."""
        if len(self.members) == 1 and self.members[0].lower() in FLOW_END_MEMBERS:
            return self.members[0].lower()
        return None

    @property
    def attribute(self) -> Optional[str]:
        """The attribute class the reference reads; None for an identity field
        or a flow's end."""
        return None if self.identity or self.flow_end else self.members[0]

    @property
    def attribute_ref(self) -> Optional[str]:
        """``T.A`` for ``T.A`` and ``T.A.p``; None for an identity field or a flow's end."""
        return None if self.identity or self.flow_end else f"{self.owner}.{self.members[0]}"


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


REF_KEY = "ref"
UNIT_KEY = "unit"
CURRENCY_KEY = "currency"
_VALUE_SPEC_KEYS = {REF_KEY, UNIT_KEY, CURRENCY_KEY}


@dataclass(frozen=True)
class ValueSpec:
    """A field that names the unit (and, for a cost, the currency) its value
    must be in: ``{ref: T.A, unit: KiloW}``."""
    ref: Reference
    unit: Optional[str] = None
    currency: Optional[str] = None


def parse_value_spec(node: Any) -> Optional[ValueSpec]:
    """The value spec a template node states, or None.

    A mapping whose keys are ``ref`` with ``unit`` and/or ``currency`` and
    nothing else, its ``ref`` a reference."""
    if not isinstance(node, dict) or REF_KEY not in node or not set(node) <= _VALUE_SPEC_KEYS:
        return None
    if UNIT_KEY not in node and CURRENCY_KEY not in node:
        return None
    ref = parse_reference(node[REF_KEY])
    if ref is None:
        return None
    text = lambda k: str(node[k]).strip() if node.get(k) not in (None, "") else None
    return ValueSpec(ref, text(UNIT_KEY), text(CURRENCY_KEY))


def leaf_reference(node: Any) -> Optional[Reference]:
    """The reference a template leaf reads: a plain reference, or a value spec's."""
    spec = parse_value_spec(node)
    return spec.ref if spec is not None else parse_reference(node)


# A value the converter could not give in the unit asked for travels in the raw
# payload as {"unit_refused": "<why>"}: validation reports it, the clean step
# drops it, the service never receives a wrong number.
REFUSED_KEY = "unit_refused"


def refused(reason: str) -> dict:
    return {REFUSED_KEY: reason}


def refusal_reason(value: Any) -> Optional[str]:
    """Why the converter refused this value, or None for a value it sent."""
    if isinstance(value, dict) and set(value) == {REFUSED_KEY}:
        return str(value[REFUSED_KEY])
    return None


def is_template_leaf(node: Any) -> bool:
    """A string, or a value spec: what a template walk reads as one field."""
    return not isinstance(node, (dict, list)) or parse_value_spec(node) is not None


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
            if not is_template_leaf(value):
                yield from iter_references(value)
            else:
                ref = leaf_reference(value)
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
        if ref.flow_end:
            continue                     # a link of the flow, not an attribute it must hold
        if is_required(ref, exempt):
            seen.setdefault(ref.text, ref)
    return list(seen.values())


@dataclass(frozen=True)
class OutputAttribute:
    """One thing a service returns: its attribute class, the name the service gives
    it, and the unit (a QUDT code) and currency it comes back in."""
    attribute: str
    field: Optional[str] = None
    unit: Optional[str] = None
    currency: Optional[str] = None


@dataclass(frozen=True)
class OutputBlock:
    """What a service returns for one input component: one value per instance of
    ``component`` (``Building``, or ``Location`` for a whole region), or for the
    whole run (``Scenario``). ``stream`` is where it is published, absent when it
    comes back in the response. ``identified_by`` is the result field that names
    the instance. ``file_field`` is the response field holding a link to the file
    the results are in, whose columns are then the block's fields."""
    component: str
    attributes: tuple = ()
    stream: Optional[str] = None
    identified_by: Optional[str] = None
    file_field: Optional[str] = None


def parse_outputs(contract: Any) -> list:
    """The contract's ``outputs`` block as :class:`OutputBlock` s. A contract without
    one has none. ``attributes`` has the grammar of the request: the service's field
    on the left, and on the right a reference or a value spec. What cannot be read
    is left out, and named by :func:`output_problems`."""
    blocks = contract.get(OUTPUTS_KEY) if isinstance(contract, dict) else None
    out = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or not isinstance(block.get("component"), str):
            continue
        fields = block.get("attributes")
        attrs = []
        for field, node in fields.items() if isinstance(fields, dict) else ():
            ref = leaf_reference(node)
            if ref is None:
                continue
            spec = parse_value_spec(node)
            attrs.append(OutputAttribute(ref.members[0], str(field), spec.unit if spec else None,
                                         spec.currency if spec else None))
        out.append(OutputBlock(block["component"], tuple(attrs), block.get("stream"),
                               block.get("identified_by"), block.get("file_field")))
    return out


def request_classes(contract: Any) -> set:
    """The classes a contract's request reads, whose results it can therefore link
    to. The scenario always counts: it is the run itself."""
    data = contract.get("scenario_data") if isinstance(contract, dict) else None
    return {ref.owner for ref in iter_references(data)} | {SCENARIO_CLASS}


def output_problems(contract: Any) -> list:
    """What is wrong with a contract's ``outputs`` block, in words. Empty when it is
    fine or absent. A result must belong to an input component of the request:
    otherwise nothing can say which thing it describes."""
    if not isinstance(contract, dict) or OUTPUTS_KEY not in contract:
        return []
    blocks = contract[OUTPUTS_KEY]
    if not isinstance(blocks, list):
        return [f"`{OUTPUTS_KEY}` must be a list of blocks"]
    known = request_classes(contract)
    problems = []
    for i, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            problems.append(f"{OUTPUTS_KEY} block {i} is not a block")
            continue
        component = block.get("component")
        if not isinstance(component, str) or not component:
            problems.append(f"{OUTPUTS_KEY} block {i} does not say which input component "
                            "its results belong to (`component`)")
        elif component not in known:
            problems.append(f"{OUTPUTS_KEY} block {i}: `{component}` is not an input of this "
                            f"service, so its results link to nothing. The inputs are: "
                            f"{', '.join(sorted(known))}")
        if block.get("file_field") is not None and not isinstance(block["file_field"], str):
            problems.append(f"{OUTPUTS_KEY} block {i}: `file_field` names the response field "
                            f"holding the link, so it must be a name: {block['file_field']!r}")
        if block.get("file_field") and block.get("stream"):
            problems.append(f"{OUTPUTS_KEY} block {i} says its results are both on a stream and "
                            "in a linked file (`stream` and `file_field`)")
        fields = block.get("attributes")
        if not isinstance(fields, dict) or not fields:
            problems.append(f"{OUTPUTS_KEY} block {i} does not say what comes back: `attributes` "
                            "maps each result field to a reference, as in the request")
            continue
        for field, node in fields.items():
            ref = leaf_reference(node)
            if ref is None:
                problems.append(f"{OUTPUTS_KEY} block {i}: `{field}` names no reference "
                                f"(`T.A`, or `{{ref: T.A, unit: ...}}`): {node!r}")
            elif ref.owner != component:
                problems.append(f"{OUTPUTS_KEY} block {i}: `{field}` reads `{ref.text}`, but the block's "
                                f"results belong to `{component}`")
    return problems
