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
    s = str(u)
    return s[len(str(DICI)):] if s.startswith(str(DICI)) else None


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
    a user picks a parent from. ``…Attribute`` scaffolding is left out."""
    def node(n: str, d: int) -> Dict:
        kids = [] if d <= 0 else [
            node(c, d - 1) for c in children(g, n)
            if not (skip_attributes and c.endswith("Attribute"))]
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


def parent_candidates(g: Graph, text: str, limit: int = 5,
                      root: str = "Component") -> List[Dict]:
    """Classes under ``root`` whose name, label, alternative labels or examples share
    words with ``text`` ('horizontal axis wind turbine' → ``WindTurbine``,
    ``Turbine``), best first — a shortlist to OFFER the user, never an automatic
    choice. Deeper (more specific) classes win ties."""
    want = _tokens(text)
    if not want:
        return []
    scored = []
    for n in classes(g):
        if n.endswith("Attribute") or not is_subclass_of(g, n, root):
            continue
        u = DICI[n]
        words = _tokens(n)
        for p in (RDFS.label, SKOS.altLabel, SKOS.example):
            for o in g.objects(u, p):
                words |= _tokens(o)
        hit = want & words
        if hit:
            scored.append((len(hit), len(ancestors(g, n)), n, sorted(hit)))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [{"name": n, "matched": m, "path": list(reversed(ancestors(g, n))) + [n]}
            for _s, _d, n, m in scored[:limit]]
