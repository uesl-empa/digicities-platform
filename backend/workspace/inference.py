# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Write-time inference materialization for workspace provisioning.

Why this exists
---------------
Different triplestores expose different inference profiles by default:
- Apache Jena Fuseki TDB2: no inference unless an explicit reasoner is wired in
- Ontotext GraphDB Free: configurable rulesets (`empty`, `rdfs`, `owl-horst`, …)
- Eclipse RDF4J, Oxigraph, virtuoso, … : each has its own conventions

If application queries depend on inference being materialised (e.g. they query
`?inst a dici_onto:Component` and expect WindTurbine instances to show up),
they work on one backend and silently fail on another.

The platform's answer: **materialize an RDFS-Plus closure at write time**,
in the workspace provisioning step. Queries can then use the natural
semantic forms they expect — the inferred triples are physically present
in every backend's dataset.

What gets materialized (RDFS-Plus subset, via the `owlrl` library)
-------------------------------------------------------------------
- `rdfs:subClassOf` transitive closure
- `rdfs:subPropertyOf` transitive closure
- `owl:equivalentClass` and `owl:equivalentProperty` propagation
- `owl:inverseOf` propagation
- `owl:sameAs` reasoning (non-reflexive)
- `owl:TransitiveProperty` and `owl:SymmetricProperty` handling

Deliberately NOT materialized: `rdfs:domain` / `rdfs:range` propagation. In OWL
those are typing rules, not constraints — "domain Location" retypes whatever
uses the predicate as a Location instead of rejecting it. Every replica
instance is explicitly typed by the converter, so the propagation only mints
surprise types (a turbine linked via locatedIn became a Location; everything
touched by hasSource became a Flow). The declarations remain in the stored
schema as queryable metadata; they are hidden from the reasoner.

What's *not* materialized (out of scope for v0.3)
-------------------------------------------------
- OWL-DL cardinality restrictions
- Complex class restrictions (`owl:Restriction` with `owl:hasValue`, `owl:someValuesFrom`)
- Consistency checking
- Classification (placing un-typed individuals into classes)

For those, configure GraphDB with `owl-horst` or `owl-max` ruleset
(via docker-compose.graphdb.yml) or wire in a separate reasoner.

Performance
-----------
RDFS-Plus closure on a Digicities workspace typically multiplies the triple
count by ~2-4x. Small enough not to matter for workspaces under ~100k
authored triples. For huge workspaces, switch to backend-native materialised
inference (configure GraphDB ruleset).
"""

from __future__ import annotations

from typing import Optional

import rdflib


def materialize(graph: rdflib.Graph, profile: str = "rdfs-plus") -> int:
    """Apply RDFS-Plus closure to `graph` in place. Returns the number of
    triples added (size after - size before).

    profile values:
      - "rdfs"      — pure RDFS (subClassOf/subPropertyOf/domain/range only)
      - "rdfs-plus" — RDFS + practical OWL bits (inverseOf, sameAs, transitive)
      - "owl-rl"    — full OWL 2 RL (largest closure, slowest, rarely needed)
      - "none"      — no-op, returned 0
    """
    if profile == "none":
        return 0

    try:
        import owlrl
    except ImportError as exc:
        # owlrl is in requirements.txt; this branch is reached only when the
        # image was built before the dep landed. Skip silently — queries will
        # still work via property paths.
        print(f"[inference] owlrl not installed, skipping materialisation: {exc}")
        return 0

    before = len(graph)

    # rdfs:domain / rdfs:range are set aside BEFORE reasoning and restored after,
    # so they never fire as inference. In OWL they are not constraints but typing
    # rules — "domain Location" means "whatever uses this predicate IS a
    # Location", so a WindTurbine linked via locatedIn was silently retyped as a
    # Location (and, earlier, everything touched by hasSource became a Flow).
    # Nothing in this platform needs the types they infer — every replica
    # instance is explicitly typed by the converter. The declarations stay in
    # the stored schema as queryable metadata (the SRB/Ontology Manager read
    # them; the onboarding agent shows them as guidance): USING a link must
    # never change what a thing is.
    dr = [t for t in graph if t[1] in (rdflib.RDFS.domain, rdflib.RDFS.range)]
    for t in dr:
        graph.remove(t)

    if profile == "rdfs":
        owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(graph)
    elif profile == "owl-rl":
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(graph)
    else:  # "rdfs-plus" (default)
        # Combined RDFS + the small OWL-RL slice useful for semantic web work
        # without DL complexity. This is what 90% of practical RDF apps want.
        owlrl.DeductiveClosure(owlrl.RDFS_OWLRL_Semantics).expand(graph)

    for t in dr:
        graph.add(t)
    if dr:
        print(f"[inference] {len(dr)} domain/range declaration(s) kept as metadata, "
              f"excluded from reasoning")

    # owlrl can produce edge-case triples with literal subjects (e.g. from
    # sameAs over equivalent literals). These violate RDF 1.1 and are
    # rejected by strict Turtle parsers (Fuseki: HTTP 400 "Subject is not
    # a URI or blank node"). Strip them so the serialized output is always
    # valid. Same for any predicate that isn't a URI.
    invalid = [
        t for t in graph
        if not isinstance(t[0], (rdflib.URIRef, rdflib.BNode))
        or not isinstance(t[1], rdflib.URIRef)
    ]
    for t in invalid:
        graph.remove(t)
    if invalid:
        print(f"[inference] stripped {len(invalid)} non-RDF-1.1-compliant triple(s) from closure")

    # owl:Nothing is the empty class — by definition a subclass of every class,
    # so the OWL-RL closure adds `owl:Nothing rdfs:subClassOf <everything>`.
    # That is logically correct but useless here, and it leaks into the UI as a
    # phantom "Nothing" component/attribute in any `subClassOf*` enumeration.
    # Strip every triple that mentions owl:Nothing as subject or object.
    nothing = rdflib.OWL.Nothing
    junk = [t for t in graph if t[0] == nothing or t[2] == nothing]
    for t in junk:
        graph.remove(t)
    if junk:
        print(f"[inference] stripped {len(junk)} owl:Nothing triple(s) from closure")

    # The eq-ref rule asserts `x owl:sameAs x` for every term the closure sees.
    # Logically true of everything, informative about nothing — and it surfaces
    # as a sameAs self-loop on every instance and attribute in the UI. Strip the
    # reflexive loops; a MEANINGFUL sameAs (between two distinct terms, and
    # whatever the closure derived from it) stays.
    same_as = rdflib.OWL.sameAs
    loops = [t for t in graph if t[1] == same_as and t[0] == t[2]]
    for t in loops:
        graph.remove(t)
    if loops:
        print(f"[inference] stripped {len(loops)} reflexive owl:sameAs triple(s) from closure")

    # The closure also types instances with ANONYMOUS superclasses — e.g. every
    # curve attribute becomes `a _:b0 … _:b4`, one per owl:Restriction on
    # CurveAttribute. A blank-node class cannot be referenced by any follow-up
    # query, and provisioning splits the closure across named graphs, which
    # severs blank-node identity — the types dangle. Nothing in this platform
    # authors `instance a [anonymous class]`, so strip every rdf:type whose
    # object is a blank node. (The axioms themselves — bnode SUBJECTS like
    # `_:b0 a owl:Restriction` — are untouched.)
    anon_types = [t for t in graph
                  if t[1] == rdflib.RDF.type and isinstance(t[2], rdflib.BNode)]
    for t in anon_types:
        graph.remove(t)
    if anon_types:
        print(f"[inference] stripped {len(anon_types)} anonymous-class rdf:type triple(s) from closure")

    added = len(graph) - before
    return added
