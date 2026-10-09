# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Canonical named-graph layout for a workspace dataset.

Single source of truth for the named graphs the platform uses, plus a helper to
build SPARQL ``FROM`` clauses. Every module — UI or backend — imports the graph
IRIs and ``from_clause`` from here instead of hard-coding strings, so the layout
is defined in exactly one place and queries stay portable across triple stores.

Why explicit ``FROM`` clauses matter
-------------------------------------
SPARQL 1.1 leaves the contents of the *default graph* implementation-defined when
a query carries no ``FROM``/dataset clause. The stores disagree:

- GraphDB / RDF4J union all named graphs into the default graph, so a clause-less
  query sees everything.
- Apache Jena Fuseki and Oxigraph read only the (separate, here empty) default
  graph, so a clause-less query sees nothing.

Naming the graphs explicitly with ``FROM`` makes the query's default graph the
union of exactly those named graphs, so it returns the same result on every
SPARQL 1.1 store while the workspace's data stays cleanly partitioned. The
partitioning is what lets a section be replaced independently: rewriting the
ontology is a single PUT to ``ONTOLOGY_GRAPH`` that leaves instances and links
untouched.

Layout inside each workspace's dataset
--------------------------------------
- ``ONTOLOGY_GRAPH``              core ontology + workspace extensions (schema)
- ``CLASSES_AND_ATTRIBUTES_GRAPH`` component instances + their attribute values
- ``SYSTEM_DESCRIPTION_GRAPH``     component-to-component links (replica-built)
- ``SCENARIOS_GRAPH``             scenario graphs
- ``COLLECTIONS_GRAPH``           DERIVED sets/statistics over attribute values
  (materialized by ``backend.collections``; wiped on every data reload — never
  authored, always recomputable)
- ``SERVICES_GRAPH``              registered services (``services/*.ttl``): their
  requirements and configuration profiles (``ServiceConfiguration`` with its
  ``ConfigurationAttribute`` parameters)

Asserted and inferred triples
-----------------------------
The graphs above hold exactly what was asserted. The platform's write-time
closure (``backend.workspace.inference``) goes to an INFERRED companion of each
closed graph (``INFERRED_OF``): ``locatedIn`` derived from an asserted
``hasLocation`` lives in ``http://inferred/classes_and_attributes``, never next
to the link the user chose. One companion per graph, so replacing a section
(the ontology manager's upload, the replica builder's) can recompute its own
inferences without touching the others.

Readers choose with ONE switch: ``from_clause(..., inferred=True)`` (the
default, unchanged behaviour) reads each named graph with its companion;
``inferred=False`` reads only what was asserted ("which link did the user
choose"). ``graph_union`` does the same for an explicit ``GRAPH`` pattern.
"""

from __future__ import annotations

from typing import Iterable

# The canonical named graphs inside each workspace dataset. Bare IRIs (no angle
# brackets) — wrap with ``<...>`` only where SPARQL/REST syntax requires it.
ONTOLOGY_GRAPH = "http://ontology_dici_onto"
CLASSES_AND_ATTRIBUTES_GRAPH = "http://classes_and_attributes"
SYSTEM_DESCRIPTION_GRAPH = "http://system_description"
SCENARIOS_GRAPH = "http://scenarios"
COLLECTIONS_GRAPH = "http://collections"
SERVICES_GRAPH = "http://services"

# Convenience groupings for common query scopes.
SCHEMA_GRAPHS = (ONTOLOGY_GRAPH,)
INSTANCE_GRAPHS = (CLASSES_AND_ATTRIBUTES_GRAPH, SYSTEM_DESCRIPTION_GRAPH)
# Schema + instances: the usual scope for component/attribute discovery queries
# (a component's type lives in the schema, its instances in the data graph).
SCHEMA_AND_INSTANCES = (ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)
ALL_GRAPHS = (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
    SCENARIOS_GRAPH,
    SERVICES_GRAPH,
)

# The inferred companion of each graph the platform closes at write time.
# Scenarios, collections and the replica builder's link graph are not closed.
INFERRED_OF = {
    ONTOLOGY_GRAPH: "http://inferred/ontology_dici_onto",
    CLASSES_AND_ATTRIBUTES_GRAPH: "http://inferred/classes_and_attributes",
    SERVICES_GRAPH: "http://inferred/services",
}
INFERRED_GRAPHS = tuple(INFERRED_OF.values())


def _bare(iri: str) -> str:
    """Strip surrounding angle brackets/whitespace so callers may pass either
    ``http://g`` or ``<http://g>``."""
    iri = iri.strip()
    if iri.startswith("<") and iri.endswith(">"):
        iri = iri[1:-1]
    return iri


def read_scope(*graphs: str, inferred: bool = True) -> list[str]:
    """The named graphs a reader of ``graphs`` reads: each one, followed by its
    inferred companion when ``inferred`` (asserted only otherwise). Accepts an
    iterable or varargs, bare or angle-bracketed IRIs; order kept, no repeats."""
    if len(graphs) == 1 and not isinstance(graphs[0], str):
        candidates: Iterable[str] = graphs[0]  # a single iterable was passed
    else:
        candidates = graphs
    scope: list[str] = []
    for g in candidates:
        if not g:
            continue
        iri = _bare(g)
        for name in (iri, INFERRED_OF.get(iri) if inferred else None):
            if name and name not in scope:
                scope.append(name)
    return scope


def graph_union(graph: str, pattern: str, inferred: bool = True) -> str:
    """A ``GRAPH`` pattern over ``graph`` and, when ``inferred``, its companion.

    The pattern is matched in each graph separately and the matches are
    combined, so pass ONE triple pattern (or one property path) per call and
    join several calls outside: per-triple matching over two graphs is the
    same as matching against their union, and a property path stays correct
    because the companion holds the whole closure."""
    names = read_scope(graph, inferred=inferred)
    if len(names) == 1:
        return f"GRAPH <{names[0]}> {{ {pattern} }}"
    return " UNION ".join(f"{{ GRAPH <{n}> {{ {pattern} }} }}" for n in names)


def from_clause(*graphs: str, inferred: bool = True) -> str:
    """Build a SPARQL ``FROM <g>`` block for the given graph IRIs.

    Place the result between a query's ``SELECT``/``CONSTRUCT`` clause and its
    ``WHERE`` clause. The returned string ends in a newline (or is empty when no
    graphs are given), so it interpolates cleanly into an f-string:

        query = f'''
        SELECT ?x
        {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{ ... }}
        '''

    Querying with these clauses makes the union of the named graphs the query's
    default graph, which is portable across all SPARQL 1.1 stores regardless of
    their union-default behaviour.

    Each graph is read with its inferred companion (``read_scope``); pass
    ``inferred=False`` to read only what was asserted.

    Accepts either an iterable of IRIs or varargs; bare or angle-bracketed IRIs.
    """
    return "".join(f"FROM <{iri}>\n" for iri in read_scope(*graphs, inferred=inferred))
