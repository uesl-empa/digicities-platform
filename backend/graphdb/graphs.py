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
"""

from __future__ import annotations

from typing import Iterable

# The canonical named graphs inside each workspace dataset. Bare IRIs (no angle
# brackets) — wrap with ``<...>`` only where SPARQL/REST syntax requires it.
ONTOLOGY_GRAPH = "http://ontology_dici_onto"
CLASSES_AND_ATTRIBUTES_GRAPH = "http://classes_and_attributes"
SYSTEM_DESCRIPTION_GRAPH = "http://system_description"
SCENARIOS_GRAPH = "http://scenarios"

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
)


def _bare(iri: str) -> str:
    """Strip surrounding angle brackets/whitespace so callers may pass either
    ``http://g`` or ``<http://g>``."""
    iri = iri.strip()
    if iri.startswith("<") and iri.endswith(">"):
        iri = iri[1:-1]
    return iri


def from_clause(*graphs: str) -> str:
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

    Accepts either an iterable of IRIs or varargs; bare or angle-bracketed IRIs.
    """
    if len(graphs) == 1 and not isinstance(graphs[0], str):
        candidates: Iterable[str] = graphs[0]  # a single iterable was passed
    else:
        candidates = graphs

    iris = [_bare(g) for g in candidates if g]
    if not iris:
        return ""
    return "".join(f"FROM <{iri}>\n" for iri in iris)
