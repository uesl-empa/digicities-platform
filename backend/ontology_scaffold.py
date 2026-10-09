# SPDX-License-Identifier: Apache-2.0

"""The Entity–Attribute–Relation scaffold of a component class, read from the
ontology and written by construction.

Every component class ``X`` has

* a **category** ``XAttribute`` (``⊑`` its parent's category): the class its
  attributes sit under;
* a **general predicate** ``has<X>Attribute`` (``⊑`` its parent's general
  predicate) with ``rdfs:domain X`` and ``rdfs:range XAttribute``. The range is
  the category and nothing else;
* one **specific predicate** per linked attribute ``A``:
  ``has<X><A>Attribute ⊑ has<X>Attribute`` with ``rdfs:domain X`` and
  ``rdfs:range A``. The attribute itself is ``⊑ XAttribute``.

The readers below find these terms by their triples (domain, range,
sub-property, sub-class), never by building a name. The names above are how
:func:`ensure_scaffold` and the Ontology Manager MINT new terms; nothing finds
a term by spelling it.

A component with no scaffold of its own (a core leaf such as ``GasMeter``)
inherits its nearest ancestor's; the Ontology Manager mints its own the first
time something is placed under it or linked to it. ``dici_onto:Component`` is
the root of the pattern: its general predicate is ``hasComponentAttribute`` and
its category ``ComponentAttribute``.

All functions take a graph holding the core and the extension (the Ontology
Manager's merged view, or ``with_core(ext)``). They read authored ontology
files; reflexive closure triples (``C ⊑ C``) are ignored.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import split_uri

from backend.ontology_kinds import (
    DICI, KIND_CLASS, is_attribute_class, is_component_class, is_subclass_of,
    is_subproperty_of,
)

ROOT_COMPONENT = DICI.Component
ROOT_PREDICATE = DICI.hasComponentAttribute
ROOT_CATEGORY = DICI.ComponentAttribute

_KIND_CLASSES = frozenset(KIND_CLASS.values())
_ROOTS = frozenset({DICI.Attribute, ROOT_CATEGORY})


def _value_kinds(g: Graph) -> Set[URIRef]:
    """The value-kind classes. None of them is inside the component-attribute
    tree, so none is ever a component's category."""
    return set(_KIND_CLASSES)


def _not_category(g: Graph) -> Set[URIRef]:
    """Classes that are never a component's category: the roots and the kinds."""
    return _value_kinds(g) | _ROOTS
# What a declared property is typed as.
_PROPERTY_TYPES = (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
                   RDF.Property)


class ScaffoldError(ValueError):
    """The ontology does not state a component's scaffold unambiguously, or a
    term the pattern would mint is already taken by something else."""


# -- reading ------------------------------------------------------------------

def local_name(term: URIRef) -> str:
    """The local part of an IRI. Used to MINT names, never to find a term."""
    return split_uri(URIRef(term))[1]


def component_classes(g: Graph) -> Set[URIRef]:
    """Every class ``rdfs:subClassOf+ dici_onto:Component``."""
    return {c for c in g.transitive_subjects(RDFS.subClassOf, ROOT_COMPONENT)
            if isinstance(c, URIRef) and c != ROOT_COMPONENT}


def component_parents(g: Graph, x: URIRef) -> List[URIRef]:
    """The direct superclasses of ``x`` that are components (or ``Component``)."""
    x = URIRef(x)
    return sorted({p for p in g.objects(x, RDFS.subClassOf)
                   if isinstance(p, URIRef) and p != x and is_component_class(g, p)})


def _ancestor_order(g: Graph, x: URIRef) -> List[URIRef]:
    """``x`` then its component ancestors, nearest first (breadth-first)."""
    order: List[URIRef] = []
    frontier = [URIRef(x)]
    while frontier:
        nxt: List[URIRef] = []
        for c in frontier:
            if c in order:
                continue
            order.append(c)
            if c != ROOT_COMPONENT:
                nxt += component_parents(g, c)
        frontier = nxt
    return order


def _strict_superproperties(g: Graph, p: URIRef) -> Set[URIRef]:
    return set(g.transitive_objects(p, RDFS.subPropertyOf)) - {p}


def _general_candidates(g: Graph, x: URIRef) -> Set[URIRef]:
    """Predicates with ``rdfs:domain x`` under ``hasComponentAttribute`` whose
    super-properties do not have domain ``x`` (those are its specific ones)."""
    out = set()
    for p in set(g.subjects(RDFS.domain, URIRef(x))):
        if not isinstance(p, URIRef) or p == ROOT_PREDICATE:
            continue
        if not is_subproperty_of(g, p, ROOT_PREDICATE):
            continue
        if any((q, RDFS.domain, URIRef(x)) in g for q in _strict_superproperties(g, p)):
            continue
        out.add(p)
    return out


def _specific_ranges(g: Graph, x: URIRef, general: URIRef) -> Set[URIRef]:
    """Ranges of the predicates with domain ``x`` strictly under ``general``."""
    return {r for p in g.subjects(RDFS.domain, URIRef(x))
            if p != general and general in _strict_superproperties(g, p)
            for r in g.objects(p, RDFS.range) if isinstance(r, URIRef)}


def _range_categories(g: Graph, x: URIRef, general: URIRef) -> Set[URIRef]:
    """The category ranges of a general predicate: attribute classes that are
    not a value kind or root and not the range of one of ``x``'s specific
    predicates (an older Ontology Manager also wrote linked attributes there),
    most specific only."""
    linked = _specific_ranges(g, x, general)
    excluded = _not_category(g)
    ranges = {r for r in g.objects(general, RDFS.range)
              if isinstance(r, URIRef) and r not in excluded and r not in linked
              and is_attribute_class(g, r)}
    return {r for r in ranges
            if not any(o != r and is_subclass_of(g, o, r) for o in ranges)}


def own_general_predicate(g: Graph, x: URIRef) -> Optional[URIRef]:
    """``x``'s own general predicate, or None when it has none (it inherits)."""
    x = URIRef(x)
    if x == ROOT_COMPONENT:
        return ROOT_PREDICATE
    cands = _general_candidates(g, x)
    if len(cands) <= 1:
        return next(iter(cands), None)
    ranged = sorted(p for p in cands if _range_categories(g, x, p))
    if len(ranged) == 1:
        return ranged[0]
    raise ScaffoldError(f"`{local_name(x)}` has several general attribute predicates: "
                        + ", ".join(f"`{local_name(p)}`" for p in sorted(cands)))


def own_category(g: Graph, x: URIRef) -> Optional[URIRef]:
    """``x``'s own category: the range of its own general predicate."""
    x = URIRef(x)
    if x == ROOT_COMPONENT:
        return ROOT_CATEGORY
    general = own_general_predicate(g, x)
    if general is None:
        return None
    cats = _range_categories(g, x, general)
    if len(cats) > 1:
        raise ScaffoldError(f"`{local_name(general)}` has several category ranges: "
                            + ", ".join(f"`{local_name(c)}`" for c in sorted(cats)))
    return next(iter(cats), None)


def general_predicate_of(g: Graph, x: URIRef) -> URIRef:
    """``x``'s general predicate, or its nearest ancestor's."""
    for c in _ancestor_order(g, x):
        p = own_general_predicate(g, c)
        if p is not None:
            return p
    return ROOT_PREDICATE


def category_of(g: Graph, x: URIRef) -> URIRef:
    """``x``'s category, or its nearest ancestor's."""
    for c in _ancestor_order(g, x):
        if own_general_predicate(g, c) is not None:
            cat = own_category(g, c)
            if cat is not None:
                return cat
    return ROOT_CATEGORY


def specific_predicates_of(g: Graph, x: URIRef) -> List[URIRef]:
    """``x``'s specific predicates: domain ``x``, strictly under its own general
    predicate."""
    x = URIRef(x)
    general = own_general_predicate(g, x)
    if general is None:
        return []
    return sorted({p for p in g.subjects(RDFS.domain, x)
                   if isinstance(p, URIRef) and p != general
                   and general in _strict_superproperties(g, p)})


def attributes_of(g: Graph, x: URIRef) -> List[URIRef]:
    """The attributes linked to ``x``: the ranges of its specific predicates."""
    return sorted({r for p in specific_predicates_of(g, x)
                   for r in g.objects(p, RDFS.range) if isinstance(r, URIRef)})


def link_predicates(g: Graph, x: URIRef, attribute: URIRef) -> List[URIRef]:
    """``x``'s specific predicates whose range is ``attribute``."""
    return [p for p in specific_predicates_of(g, x) if (p, RDFS.range, URIRef(attribute)) in g]


def link_predicate(g: Graph, x: URIRef, attribute: URIRef) -> Optional[URIRef]:
    """The declared predicate linking an ``x`` to ``attribute``: ``x``'s own, or
    the nearest ancestor's (an attribute of ``Turbine`` is one of every
    ``WindTurbine``). None when no class on the way links it."""
    for c in _ancestor_order(g, x):
        found = link_predicates(g, c, attribute)
        if len(found) > 1:
            raise ScaffoldError(f"`{local_name(c)}` links `{local_name(attribute)}` through "
                                "several predicates: "
                                + ", ".join(f"`{local_name(p)}`" for p in found))
        if found:
            return found[0]
    return None


def categories(g: Graph) -> Dict[URIRef, URIRef]:
    """``{category: component}`` for every component with a category of its own."""
    out: Dict[URIRef, URIRef] = {ROOT_CATEGORY: ROOT_COMPONENT}
    for c in component_classes(g):
        cat = own_category(g, c)
        if cat is not None:
            out[cat] = c
    return out


def category_members(g: Graph, x: URIRef) -> List[URIRef]:
    """The attribute classes under ``x``'s OWN category (``rdfs:subClassOf+``),
    other categories left out. Empty when ``x`` has no category of its own."""
    cat = own_category(g, x)
    if cat is None:
        return []
    cats = set(categories(g))
    return sorted(c for c in g.transitive_subjects(RDFS.subClassOf, cat)
                  if isinstance(c, URIRef) and c != cat and c not in cats)


def category_members_by_component(g: Graph) -> Dict[URIRef, List[URIRef]]:
    """``{component: category_members(g, component)}`` for every component
    class (an empty list when it has no category of its own)."""
    cats = categories(g)
    out: Dict[URIRef, List[URIRef]] = {}
    for comp in sorted(component_classes(g)):
        cat = own_category(g, comp)
        out[comp] = [] if cat is None else sorted(
            c for c in g.transitive_subjects(RDFS.subClassOf, cat)
            if isinstance(c, URIRef) and c != cat and c not in cats)
    return out


# -- writing ------------------------------------------------------------------

def _declared(g: Graph, term: URIRef) -> bool:
    return (term, None, None) in g


def _set_only_super(write: Graph, term: URIRef, rel: URIRef, target: URIRef) -> None:
    """Make ``target`` the only stated super of ``term`` in ``write``."""
    for old in list(write.objects(term, rel)):
        if old != target:
            write.remove((term, rel, old))
    write.add((term, rel, target))


def ensure_scaffold(view: Graph, write: Graph, x: URIRef) -> Tuple[URIRef, URIRef]:
    """Give ``x`` (and first every ancestor that lacks one) its own general
    predicate and category, placed under its parent's, and return them.

    ``view`` is what is read (core + extension); ``write`` is the graph that
    takes the new triples (the extension, or the core in core mode). An
    existing term is adopted, never duplicated; a term the pattern would mint
    that is already something else is a :class:`ScaffoldError`. Attribute
    ranges an older Ontology Manager put on the general predicate are removed
    from ``write``: the range is the category only."""
    x = URIRef(x)
    if x == ROOT_COMPONENT:
        return ROOT_PREDICATE, ROOT_CATEGORY
    parents = component_parents(view, x)
    if len(parents) != 1:
        raise ScaffoldError(f"`{local_name(x)}` must sit under exactly one component class "
                            f"(found {len(parents)})")
    parent_general, parent_category = ensure_scaffold(view, write, parents[0])
    name = local_name(x)

    general = own_general_predicate(view, x)
    if general is None:
        general = DICI[f"has{name}Attribute"]
        if _declared(view, general) and \
                not set(view.objects(general, RDFS.domain)) <= {x}:
            raise ScaffoldError(f"`{local_name(general)}` already exists for another class")
        write.add((general, RDF.type, OWL.ObjectProperty))
        write.add((general, RDFS.domain, x))
    if (general, RDFS.subPropertyOf, parent_general) not in view:
        _set_only_super(write, general, RDFS.subPropertyOf, parent_general)

    category = own_category(view, x)
    if category is None:
        category = DICI[f"{name}Attribute"]
        if _declared(view, category):
            if category in _not_category(view) or is_component_class(view, category) \
                    or any(view.objects(category, RDF.type)) and \
                    (category, RDF.type, OWL.Class) not in view:
                raise ScaffoldError(f"`{local_name(category)}` already exists and is not "
                                    "an attribute category")
            other = [p for p in view.subjects(RDFS.range, category) if p != general
                     and any(view.objects(p, RDFS.domain))]
            if other:
                raise ScaffoldError(f"`{local_name(category)}` is already the category of "
                                    f"`{local_name(other[0])}`")
        else:
            write.add((category, RDF.type, OWL.Class))
            write.add((category, RDFS.label, Literal(f"{name} Attribute")))
        write.add((general, RDFS.range, category))
    if (category, RDFS.subClassOf, parent_category) not in view:
        _set_only_super(write, category, RDFS.subClassOf, parent_category)

    for r in list(write.objects(general, RDFS.range)):
        if r != category:
            write.remove((general, RDFS.range, r))
    return general, category


# -- the invariant ------------------------------------------------------------

def _undeclared_supers(g: Graph, p: URIRef) -> List[URIRef]:
    return sorted(q for q in g.objects(p, RDFS.subPropertyOf)
                  if isinstance(q, URIRef) and q != p
                  and not any((q, RDF.type, t) in g for t in _PROPERTY_TYPES))


def check_pattern(g: Graph, components: Optional[Iterable[URIRef]] = None) -> List[str]:
    """Every way ``g`` (core + extension) breaks the pattern, as sentences.

    Checked for each component class (all of them, or ``components``):
    exactly one category, its own or inherited; its own category ⊑ its
    parent's category and its own general predicate ⊑ its parent's; the
    general predicate's only range is its category; no predicate with its
    domain points at an undeclared super-property; each linked attribute
    through exactly one specific predicate. And over the whole graph: every
    class under ``ComponentAttribute`` without a value kind is some
    component's category."""
    problems: List[str] = []
    comps = sorted(component_classes(g) if components is None else map(URIRef, components))
    for c in comps:
        name = local_name(c)
        for p in sorted(p for p in g.subjects(RDFS.domain, c) if isinstance(p, URIRef)):
            missing = _undeclared_supers(g, p)
            if missing:
                problems.append(f"`{local_name(p)}` (domain `{name}`) is under undeclared "
                                + ", ".join(f"`{local_name(q)}`" for q in missing))
        try:
            candidates = _general_candidates(g, c)
            if len(candidates) > 1:
                problems.append(f"`{name}` has {len(candidates)} general attribute predicates: "
                                + ", ".join(f"`{local_name(p)}`" for p in sorted(candidates)))
            general = own_general_predicate(g, c)
            category = own_category(g, c)
            parents = component_parents(g, c)
            if len(parents) != 1:
                problems.append(f"`{name}` sits under {len(parents)} component classes")
                continue
            parent = parents[0]
            if general is None:
                continue                                  # inherits its parent's
            if category is None:
                problems.append(f"`{local_name(general)}` (`{name}`) has no category range")
                continue
            extra = sorted(r for r in g.objects(general, RDFS.range) if r != category)
            if extra:
                problems.append(f"`{local_name(general)}` has ranges besides its category "
                                f"`{local_name(category)}`: "
                                + ", ".join(f"`{local_name(r)}`" for r in extra))
            if not is_subclass_of(g, category, category_of(g, parent)):
                problems.append(f"`{local_name(category)}` is not under "
                                f"`{local_name(category_of(g, parent))}`")
            if not is_subproperty_of(g, general, general_predicate_of(g, parent)):
                problems.append(f"`{local_name(general)}` is not under "
                                f"`{local_name(general_predicate_of(g, parent))}`")
            for attr in attributes_of(g, c):
                found = link_predicates(g, c, attr)
                if len(found) > 1:
                    problems.append(f"`{name}` links `{local_name(attr)}` through "
                                    f"{len(found)} predicates")
        except ScaffoldError as e:
            problems.append(str(e))
    if components is None:
        try:
            cats = set(categories(g))
        except ScaffoldError as e:
            return problems + [str(e)]
        kinds = _value_kinds(g)
        for k in sorted(g.transitive_subjects(RDFS.subClassOf, ROOT_CATEGORY)):
            if not isinstance(k, URIRef) or k in cats:
                continue
            if any(is_subclass_of(g, k, kind) for kind in kinds):
                continue
            problems.append(f"`{local_name(k)}` sits under `ComponentAttribute` with no value "
                            "kind and is no component's category")
    return problems
