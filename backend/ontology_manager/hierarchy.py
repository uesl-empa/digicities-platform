# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The class tree of a workspace ontology (core + extension), read deterministically.

Where can a new class go, is ``X`` under ``Y``, what sits below ``Turbine`` —
the questions a user (or the onboarding agent on their behalf) asks while
building an extension. All functions take an rdflib graph holding the core and
the extension (``OntologyFunctions.merge_ontologies(ext)`` or the temp graph)
and work on ``dici_onto:`` local names, ``rdfs:subClassOf`` only — never string
matching on names.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef

DICI = Namespace("https://digicities.info/ontology#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def _local(u) -> Optional[str]:
    from backend.ontology_kinds import dici_local_name
    return dici_local_name(u)


def classes(g: Graph) -> Set[str]:
    """Every dici class (``owl:Class``) in the graph."""
    return {n for n in (_local(s) for s in g.subjects(RDF.type, OWL.Class)) if n}


def parents(g: Graph, name: str) -> List[str]:
    """Direct dici superclasses of ``name``."""
    return sorted(n for n in (_local(o) for o in g.objects(DICI[name], RDFS.subClassOf)) if n)


def ancestors(g: Graph, name: str) -> List[str]:
    """Every dici superclass, nearest first (breadth-first over subClassOf)."""
    seen: List[str] = []
    frontier = parents(g, name)
    while frontier:
        nxt = []
        for p in frontier:
            if p not in seen and p != name:
                seen.append(p)
                nxt += parents(g, p)
        frontier = nxt
    return seen


def is_subclass_of(g: Graph, name: str, other: str) -> bool:
    """``name rdfs:subClassOf* other``."""
    return name == other or other in ancestors(g, name)


def children(g: Graph, name: str) -> List[str]:
    """Direct dici subclasses of ``name``."""
    return sorted(n for n in (_local(s) for s in g.subjects(RDFS.subClassOf, DICI[name]))
                  if n and n != name)


def descendants(g: Graph, name: str) -> List[str]:
    out: List[str] = []
    frontier = children(g, name)
    while frontier:
        nxt = []
        for c in frontier:
            if c not in out:
                out.append(c)
                nxt += children(g, c)
        frontier = nxt
    return out


def would_cycle(g: Graph, name: str, new_parent: str) -> bool:
    """Would making ``new_parent`` the parent of ``name`` close a loop?"""
    return new_parent == name or new_parent in descendants(g, name)


def is_component(g: Graph, name: str) -> bool:
    return is_subclass_of(g, name, "Component")


def tree(g: Graph, root: str = "Component", depth: int = 6,
         skip_attributes: bool = True) -> Dict:
    """``{"name", "label", "children": [...]}`` below ``root`` — the component tree
    a user picks a parent from. Attribute classes (``rdfs:subClassOf*
    dici_onto:Attribute``) are left out."""
    def node(n: str, d: int) -> Dict:
        kids = [] if d <= 0 else [
            node(c, d - 1) for c in children(g, n)
            if not (skip_attributes and is_subclass_of(g, c, "Attribute"))]
        label = next((str(o) for o in g.objects(DICI[n], RDFS.label)), n)
        return {"name": n, "label": label, "children": kids}
    return node(root, depth)


def render_tree(t: Dict, highlight: Set[str] = frozenset(), indent: str = "") -> str:
    """A plain-text tree (for chat): new or changed classes marked with ``*``."""
    lines = [f"{indent}{t['name']}{' *' if t['name'] in highlight else ''}"]
    for c in t["children"]:
        lines.append(render_tree(c, highlight, indent + "  "))
    return "\n".join(lines)


_TOK = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _tokens(s: str) -> Set[str]:
    return {t.lower() for t in _TOK.findall(str(s or "")) if len(t) > 2}


# Words that end a noun phrase: "electricity flow FROM the grid to a building" is a flow.
_PREP = {"from", "to", "of", "for", "in", "into", "with", "at", "on", "by", "via", "per",
         "backing", "under", "over", "between", "inside", "within", "through"}
_STOP = {"the", "and", "any", "all", "one", "two", "each", "such", "its", "their", "this",
         "that", "new"}


def _stem(t: str) -> str:
    """A crude singular: ``buildings`` -> ``building`` (``class`` stays ``class``)."""
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def _head(phrase: str):
    """``(head noun, modifiers)`` of one noun phrase: "a building heating load" ->
    (load, {building, heating}); "electricity flow from the grid to a building" ->
    (flow, {electricity}); "WindTurbine" -> (turbine, {wind})."""
    toks = []
    for t in _TOK.findall(str(phrase or "")):
        t = t.lower()
        if t in _PREP:
            break
        if len(t) > 2 and t not in _STOP:
            toks.append(_stem(t))
    return (toks[-1], set(toks[:-1])) if toks else (None, set())


def _phrases(text: str) -> List[str]:
    return [x for x in re.split(r"[,;]|\band\b|\bor\b", str(text or ""), flags=re.I) if x.strip()]


def parent_candidates(g: Graph, text: str, limit: int = 5,
                      root: str = "Component") -> List[Dict]:
    """Classes under ``root`` that could be a parent of the thing ``text`` names
    ('horizontal axis wind turbine' → ``Turbine``), best first — a shortlist to
    OFFER the user, never an automatic choice.

    Compared as noun phrases, by their HEAD noun: the head of ``text``'s first
    phrase must be the head of the class's name, label, alternative label or of
    one of its example phrases ("Buildings, turbines, …"). When that phrase of the
    class also has modifiers ("EV charging station"), one of them must be in
    ``text`` too ("weather station" is not one). A word used only as a modifier
    ("a building heating load", "Building Management System") or after a
    preposition ("… flow from the grid to a building") is no evidence: that put
    CompositeWeatherObservation, LiquidFuel and Controller on a Building's list.
    Name/label matches beat example matches; more shared modifiers, then deeper
    (more specific) classes win."""
    first = next(iter(_phrases(text)), "")
    qhead, qmods = _head(first)
    if not qhead:
        return []
    scored = []
    for n in classes(g):
        if n == root or not is_subclass_of(g, n, root) or is_subclass_of(g, n, "Attribute"):
            continue
        u = DICI[n]
        named = [n] + [str(o) for p in (RDFS.label, SKOS.altLabel) for o in g.objects(u, p)]
        examples = [ph for o in g.objects(u, SKOS.example) for ph in _phrases(o)]
        best, matched = 0, set()
        for weight, phrases in ((3, named), (2, examples)):
            for ph in phrases:
                h, m = _head(ph)
                if h != qhead or (m and not m & qmods):
                    continue
                score = weight + len(m & qmods)
                if score > best:
                    best, matched = score, {h} | (m & qmods)
        if best:
            scored.append((best, len(ancestors(g, n)), n, sorted(matched)))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [{"name": n, "matched": m, "path": list(reversed(ancestors(g, n))) + [n]}
            for _s, _d, n, m in scored[:limit]]
