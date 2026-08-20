# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The component model the Service Requirements Builder works in.

Three small dataclasses, shared by the ontology loaders, the template
generator/parser, and the validator. They carry no behavior; equality is
field-by-field (dataclass default), which the round-trip tests rely on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ComponentClass:
    """A component class from the ontology (a subclass of Component)."""
    uri: str
    label: str
    parent_classes: List[str]
    attributes: List[str]


@dataclass
class AttributeClass:
    """An attribute class from the ontology (a Static/DynamicAttribute subclass)."""
    uri: str
    label: str
    domain: str
    range_type: str
    unit: Optional[str] = None


@dataclass
class ComponentEntry:
    """One component in the service template being built.

    ``path`` is the YAML key the component appears under; ``level`` 1 means a
    root block (name/uri), anything deeper is a child block
    (``link: CL.<Parent>.<Child>`` + ``template``). ``configured_attributes``
    maps attribute name -> list of flavors ("Static", "Historic", "Live",
    "Future"); one attribute can carry several flavors at once.
    """
    path: str
    component_type: str
    link_pattern: str
    parent_path: str = ""
    level: int = 1
    configured_attributes: Dict[str, List[str]] = field(default_factory=dict)
