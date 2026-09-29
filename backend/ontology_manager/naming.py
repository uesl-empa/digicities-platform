# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Naming rules for ontology terms — the one place they live.

Every path that adds a term to a workspace extension goes through here: the
Ontology Manager UI and REST API (via ``OntologyFunctions.add_component`` /
``add_attribute`` / ``add_named_individual``), the extension-instruction replay
(``instructions.apply_extension_instructions``) and anything that plans an
extension (the onboarding agent). A name is therefore formed and judged the
same way whoever proposes it.

The rules:

* **Classes** (components, attributes, value classes) are PascalCase ASCII:
  a letter first, then letters and digits — ``WindTurbine``, ``HubHeight``,
  ``CO2Sensor``. :func:`class_name` forms one from any label ("wind turbine",
  ``wind_turbine``, "Wind Turbine" → ``WindTurbine``).
* **Object properties** are camelCase: ``partOfWindPark``.
* A class name is at most :data:`MAX_CLASS_NAME` characters — the Excel sheet
  limit; the workbook that carries its instances cuts anything longer, and
  the cut name is a different class.
* ``…Attribute`` is reserved for the attribute scaffolding the Ontology Manager
  generates for every component (``WindTurbineAttribute``).
* A name must not redefine a core term; a class declared in an extension with a
  core name would silently rewrite the core class.
* A new term whose name or label matches a core term's label or alternative
  label is flagged (not refused): the core may already have the concept under
  another name (``WindFarm`` vs core ``WindPark``, alt label "wind farm").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from rdflib import OWL, RDF, RDFS, Graph, Namespace

DICI = Namespace("https://digicities.info/ontology#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

#: Excel's sheet-name limit — a class's instances ride in a sheet of that name.
MAX_CLASS_NAME = 31

_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*$")
_WORDS = re.compile(r"[^0-9A-Za-z]+")


def class_name(label: str) -> str:
    """PascalCase class name from any spelling: 'wind turbine' / 'wind_turbine' /
    'Wind Turbine' → ``WindTurbine``; inner capitals are kept ('CO2 sensor' →
    ``CO2Sensor``, 'PVModule' stays). '' when the label has no letters or digits."""
    return "".join(w[:1].upper() + w[1:] for w in _WORDS.split(str(label or "")) if w)


def property_name(label: str) -> str:
    """camelCase property name: 'part of wind park' → ``partOfWindPark``."""
    p = class_name(label)
    return p[:1].lower() + p[1:]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


@dataclass
class NameCheck:
    """The verdict on a proposed name: ``errors`` refuse it, ``warnings`` inform."""
    name: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: core terms the name or label matches (``[(term, why)]``) — a hint that the
    #: concept may already exist
    similar: List[tuple] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def message(self) -> str:
        return "; ".join(self.errors + self.warnings)


def core_terms(core: Graph) -> dict:
    """``{local name: {"kind", "labels"}}`` for every dici term in the core graph."""
    out: dict = {}
    for kind, typ in (("class", OWL.Class), ("objectProperty", OWL.ObjectProperty),
                      ("dataProperty", OWL.DatatypeProperty),
                      ("individual", OWL.NamedIndividual)):
        for s in core.subjects(RDF.type, typ):
            if not str(s).startswith(str(DICI)):
                continue
            local = str(s)[len(str(DICI)):]
            labels = {str(o) for o in core.objects(s, RDFS.label)}
            labels |= {str(o) for o in core.objects(s, SKOS.altLabel)}
            out.setdefault(local, {"kind": kind, "labels": set()})["labels"] |= labels
    return out


def check_class_name(name: str, core: Optional[Graph] = None,
                     existing: Iterable[str] = (), label: str = "",
                     allow_core: bool = False) -> NameCheck:
    """Judge a proposed CLASS name (component, attribute or value class).

    ``core`` — the core ontology graph (its terms may not be redefined, and its
    labels / alternative labels are searched for the same concept); ``existing``
    — names already declared in the extension; ``label`` — the human label, also
    compared with the core's labels; ``allow_core`` — editing the core itself."""
    chk = NameCheck(name=name)
    if not name:
        chk.errors.append("no name was given")
        return chk
    if not _PASCAL.match(name):
        suggestion = class_name(name)
        chk.errors.append(
            f"`{name}` is not a valid class name — class names are PascalCase letters and "
            f"digits, starting with a capital letter"
            + (f" (e.g. `{suggestion}`)" if suggestion and _PASCAL.match(suggestion) else ""))
    if len(name) > MAX_CLASS_NAME:
        chk.errors.append(f"`{name}` is {len(name)} characters — at most {MAX_CLASS_NAME} "
                          "(the workbook sheet that carries its instances cuts longer names)")
    if name.endswith("Attribute") and name != "Attribute":
        chk.errors.append(f"`{name}` ends in `Attribute`, which is reserved for the attribute "
                          "structure the platform generates for every component")
    if name in set(existing):
        chk.errors.append(f"`{name}` is already declared in this extension")
    if core is not None:
        terms = core_terms(core)
        if name in terms and not allow_core:
            chk.errors.append(f"`{name}` is already a core {terms[name]['kind']} — use it "
                              "instead of declaring it again")
        wanted = {_norm(name), _norm(label)} - {""}
        for term, info in sorted(terms.items()):
            if term == name or info["kind"] != "class":
                continue
            hit = next((lb for lb in sorted(info["labels"]) if _norm(lb) in wanted), None)
            if hit is None and _norm(term) in wanted:
                hit = term
            if hit is not None:
                chk.similar.append((term, hit))
        if chk.similar:
            chk.warnings.append(
                "the core already has " + ", ".join(
                    f"`{t}` (label '{h}')" for t, h in chk.similar[:3])
                + " — consider using it instead")
    return chk


def check_property_name(name: str, core: Optional[Graph] = None,
                        existing: Iterable[str] = ()) -> NameCheck:
    """Judge a proposed OBJECT PROPERTY name (camelCase)."""
    chk = NameCheck(name=name)
    if not name:
        chk.errors.append("no name was given")
        return chk
    if not _CAMEL.match(name):
        suggestion = property_name(name)
        chk.errors.append(f"`{name}` is not a valid property name — property names are "
                          "camelCase letters and digits, starting lower-case"
                          + (f" (e.g. `{suggestion}`)" if suggestion else ""))
    if name in set(existing):
        chk.errors.append(f"`{name}` is already declared in this extension")
    if core is not None and name in core_terms(core):
        chk.warnings.append(f"`{name}` is a core property — reuse it rather than redeclaring")
    return chk
