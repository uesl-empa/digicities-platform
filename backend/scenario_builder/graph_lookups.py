# SPDX-License-Identifier: Apache-2.0

"""Workspace-graph lookups the scenario builder makes on top of the shared
component queries in ``backend.graphdb.queries``.
"""
from __future__ import annotations

from typing import Dict

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
    from_clause,
)


def categorical_values(client) -> Dict[str, str]:
    """``{attribute IRI: category value IRI}`` for every categorical attribute.

    The value is the attribute's ``dici_onto:hasCategoricalValue`` (an IRI: a
    named individual of the attribute's class). Data written before that
    property was stated typed the node with the chosen value instead; for such
    a node the value is the type that is a named individual of its attribute
    class. That fallback goes away once the workspace is rebuilt. Query errors
    propagate to the caller.
    """
    query = f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?attribute ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?attribute a ?attrClass .
      ?attrClass rdfs:subClassOf* dici_onto:CategoricalAttribute .
      {{ ?attribute dici_onto:hasCategoricalValue ?value . }}
      UNION
      {{ FILTER NOT EXISTS {{ ?attribute dici_onto:hasCategoricalValue ?stated . }}
         ?value a ?attrClass .
         ?attribute a ?value . }}
    }}
    """
    df = client.sparql_api_query(query, out_format="df")
    if df is None or df.empty:
        return {}
    return {str(row["attribute"]): str(row["value"]) for _, row in df.iterrows()}


def category_labels(client) -> Dict[str, str]:
    """``{value IRI: label}`` for every declared categorical value: what a person
    reads for a value (its rdfs:label, else the last segment of its IRI). The
    value itself stays its IRI wherever it is carried."""
    from backend.graphdb.queries.ontology import get_named_individuals
    from backend.ontology_kinds import namespace_of

    df = get_named_individuals(client)
    out: Dict[str, str] = {}
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        iri, label = str(row["individual"]), row.get("label")
        if label is not None and str(label) not in ("", "nan"):
            out[iri] = str(label)
        else:
            out.setdefault(iri, iri[len(namespace_of(iri) or ""):])
    return out


def instance_types(client) -> Dict[str, str]:
    """``{instance IRI: class local name}`` for every component instance in the
    workspace graph (its most specific class under dici_onto:Component), the
    type a thin scenario's bare instance reference stands for."""
    from backend.graphdb.queries.components import get_all_component_instances
    from backend.scenario_builder.display_utils import get_uri_fragment

    df = get_all_component_instances(client)
    if df is None or df.empty:
        return {}
    return {str(row["instance"]): get_uri_fragment(str(row["type"])) for _, row in df.iterrows()}


def workspace_extensions(storage):
    """Every extension TTL of a workspace (``ontology/extensions/*.ttl``) in one
    rdflib graph: the classes and properties its instances are typed with,
    placed under the core hierarchy. Parse errors propagate."""
    from rdflib import Graph

    g = Graph()
    for rel in sorted(storage.glob("ontology/extensions/*.ttl")):
        g.parse(data=storage.read_text(rel), format="turtle")
    return g
