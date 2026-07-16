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
)
from backend.graphdb.queries._exec import run_df

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
)
_SYS = f"<{SYSTEM_DESCRIPTION_GRAPH}>"
_CA = f"<{CLASSES_AND_ATTRIBUTES_GRAPH}>"
_ONT = f"<{ONTOLOGY_GRAPH}>"


def query_direct_located_in(client) -> pd.DataFrame:
    """Direct locatedIn links between components. Columns: source, sourceType, target, targetType."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?target ?targetType
    WHERE {{
        {{ GRAPH {_SYS} {{ ?source dici_onto:locatedIn ?target . }} }}
        UNION
        {{ GRAPH {_CA} {{ ?source dici_onto:locatedIn ?target . }} }}

        GRAPH {_CA} {{
            ?source a ?sourceType .
            ?target a ?targetType .
        }}
        GRAPH {_ONT} {{
            ?sourceType rdfs:subClassOf* dici_onto:Component .
            ?targetType rdfs:subClassOf* dici_onto:Component .
        }}
        FILTER(?sourceType != dici_onto:Component)
        FILTER(?targetType != dici_onto:Component)
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "target", "targetType"])


def query_links_with_subproperty(client) -> pd.DataFrame:
    """Links via any linksComponent subproperty.

    Columns: source, sourceType, linkProperty, target, targetType.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?linkProperty ?target ?targetType
    WHERE {{
        {{ GRAPH {_SYS} {{ ?source ?linkProperty ?target . }} }}
        UNION
        {{ GRAPH {_CA} {{ ?source ?linkProperty ?target . FILTER(isIRI(?target)) }} }}

        GRAPH {_ONT} {{
            ?linkProperty rdfs:subPropertyOf* dici_onto:linksComponent .
        }}
        GRAPH {_CA} {{
            ?source a ?sourceType .
            ?target a ?targetType .
        }}
        GRAPH {_ONT} {{
            ?sourceType rdfs:subClassOf* dici_onto:Component .
            ?targetType rdfs:subClassOf* dici_onto:Component .
        }}
        FILTER(?sourceType != dici_onto:Component)
        FILTER(?targetType != dici_onto:Component)
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "linkProperty", "target", "targetType"])


def query_all_component_relationships(client) -> pd.DataFrame:
    """Broad fallback: any dici_onto predicate linking two components.

    Columns: source, sourceType, linkProperty, target, targetType.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?source ?sourceType ?linkProperty ?target ?targetType
    WHERE {{
        {{ GRAPH {_SYS} {{ ?source ?linkProperty ?target . FILTER(isIRI(?target)) }} }}
        UNION
        {{ GRAPH {_CA} {{
            ?source ?linkProperty ?target .
            FILTER(isIRI(?target))
            FILTER(?linkProperty != rdf:type)
            FILTER(?linkProperty != dici_onto:hasAttribute)
        }} }}

        GRAPH {_CA} {{
            ?source a ?sourceType .
            ?target a ?targetType .
        }}
        GRAPH {_ONT} {{
            ?sourceType rdfs:subClassOf* dici_onto:Component .
            ?targetType rdfs:subClassOf* dici_onto:Component .
        }}
        FILTER(?sourceType != dici_onto:Component)
        FILTER(?targetType != dici_onto:Component)
        FILTER(STRSTARTS(str(?linkProperty), "https://digicities.info/ontology#"))
    }}
    ORDER BY ?source ?target
    """
    return run_df(client, query, ["source", "sourceType", "linkProperty", "target", "targetType"])
