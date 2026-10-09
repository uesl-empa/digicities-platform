# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Component-link discovery across the system-description / instance graphs.

Pure, UI-independent queries that find component-to-component links
(dici_onto:linksComponent subproperties, e.g. locatedIn) by joining the
``<system_description>`` and ``<classes_and_attributes>`` instance graphs against
the ``<ontology_dici_onto>`` schema graph. Each returns a pandas DataFrame; the
Scenario Builder shapes the rows into link dicts.

Graph IRIs come from ``backend.graphdb.graphs`` (single source of truth).
"""

from __future__ import annotations

import pandas as pd

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
    graph_union,
)
from backend.graphdb.queries._exec import run_df

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
    "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
)


def _sys(pattern: str) -> str:
    return graph_union(SYSTEM_DESCRIPTION_GRAPH, pattern)


def _ca(pattern: str) -> str:
    # The instance graph with its inferred companion: a link or a type the
    # platform inferred (``locationOf`` from ``hasLocation``) still counts here.
    return graph_union(CLASSES_AND_ATTRIBUTES_GRAPH, pattern)


def _ont(pattern: str) -> str:
    return graph_union(ONTOLOGY_GRAPH, pattern)


def _component_types() -> str:
    """Source and target typed under Component (one triple per graph union)."""
    return f"""
        {_ca("?source a ?sourceType .")}
        {_ca("?target a ?targetType .")}
        {_ont("?sourceType rdfs:subClassOf* dici_onto:Component .")}
        {_ont("?targetType rdfs:subClassOf* dici_onto:Component .")}
        FILTER(?sourceType != dici_onto:Component)
        FILTER(?targetType != dici_onto:Component)"""


# The core place predicates: the subject is located in / at the object. Their
# meaning is distinct in core v0.6.0 (each has its own inverse), so a query for
# "where is this component" names all of them, never just one.
LOCATION_PREDICATES = ("locatedIn", "hasLocation", "locatedAt")


def query_direct_located_in(client) -> pd.DataFrame:
    """Direct place links between components: the source is located in or at the
    target (any of ``LOCATION_PREDICATES``). Columns: source, sourceType,
    linkProperty, target, targetType."""
    values = " ".join(f"dici_onto:{p}" for p in LOCATION_PREDICATES)
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?linkProperty ?target ?targetType
    WHERE {{
        VALUES ?linkProperty {{ {values} }}
        {{ {_sys("?source ?linkProperty ?target .")} }}
        UNION
        {{ {_ca("?source ?linkProperty ?target .")} }}
        {_component_types()}
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "linkProperty", "target", "targetType"])


def query_links_with_subproperty(client) -> pd.DataFrame:
    """Links via any linksComponent subproperty.

    Columns: source, sourceType, linkProperty, target, targetType.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?linkProperty ?target ?targetType
    WHERE {{
        {{ {_sys("?source ?linkProperty ?target .")} }}
        UNION
        {{ {_ca("?source ?linkProperty ?target .")} FILTER(isIRI(?target)) }}
        {_ont("?linkProperty rdfs:subPropertyOf* dici_onto:linksComponent .")}
        {_component_types()}
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "linkProperty", "target", "targetType"])


def query_all_component_relationships(client) -> pd.DataFrame:
    """Broad fallback: any object property the workspace schema declares that
    links two components, other than an attribute edge or provenance (a
    catalogue or data-source reference never fulfils a link requirement).

    Columns: source, sourceType, linkProperty, target, targetType.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?linkProperty ?target ?targetType
    WHERE {{
        {{ {_sys("?source ?linkProperty ?target .")} FILTER(isIRI(?target)) }}
        UNION
        {{
            {_ca("?source ?linkProperty ?target .")}
            FILTER(isIRI(?target))
            FILTER(?linkProperty != rdf:type)
            FILTER(?linkProperty != dici_onto:hasAttribute)
        }}
        {_component_types()}
        {_ont("?linkProperty a owl:ObjectProperty .")}
        FILTER NOT EXISTS {{ {_ont("?linkProperty rdfs:subPropertyOf* dici_onto:hasAttribute .")} }}
        FILTER NOT EXISTS {{ {_ont("?linkProperty rdfs:subPropertyOf* prov:wasDerivedFrom .")} }}
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "linkProperty", "target", "targetType"])
