# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""SPARQL for the collections module: member selection, family detection,
attribute-type discovery, and reading back materialized collections.

All queries scope their graphs explicitly via ``backend.graphdb.graphs`` and
walk the ontology semantically (``rdfs:subClassOf*`` / ``rdfs:subPropertyOf*``)
— never by class-name spelling. Attribute nodes are recognised the same way the
platform's phantom-instance guard does: they are objects of a
``hasAttribute``-family edge.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
    COLLECTIONS_GRAPH,
    from_clause,
)
from backend.graphdb.queries._exec import run_df

DICI = "https://digicities.info/ontology#"

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX qudt: <http://qudt.org/schema/qudt/>\n"
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
)

# The value-bearing patterns an attribute instance may carry. Numeric replica
# values are ``qudt:value``; simple values are ``dici_onto:hasAttributeValue``;
# categorical values are the URI object of ``dici_onto:hasCategoricalValue``.
_VALUE_OPTIONALS = (
    "  OPTIONAL {{ {node} qudt:value {q} . }}\n"
    "  OPTIONAL {{ {node} dici_onto:hasAttributeValue {s} . }}\n"
    "  OPTIONAL {{ {node} dici_onto:hasCategoricalValue {c} .\n"
    "             OPTIONAL {{ {c} rdfs:label {cl} . }} }}\n"
)


def base_types_of(client, attribute_class_iri: str) -> List[str]:
    """Local names of every core base value-type the attribute class sits
    under (``rdfs:subClassOf*`` in the schema graph)."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?base
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
      <{attribute_class_iri}> rdfs:subClassOf* ?base .
      ?base rdfs:subClassOf* dici_onto:Attribute .
    }}
    """
    df = run_df(client, query, ["base"])
    return [str(b).split("#")[-1] for b in df["base"].tolist()]


def member_values(client, attribute_class_iri: str,
                  dataset_iri: Optional[str] = None) -> pd.DataFrame:
    """Every attribute instance of the given type attached to a component,
    with its raw value(s). Columns: attr, numValue, simpleValue, catValue,
    catLabel."""
    ds = f"  ?comp dici_onto:hasDataSource <{dataset_iri}> .\n" if dataset_iri else ""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attr ?numValue ?simpleValue ?catValue ?catLabel
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?comp ?edge ?attr .
      ?edge rdfs:subPropertyOf* dici_onto:hasAttribute .
{ds}      ?attr a ?t .
      ?t rdfs:subClassOf* <{attribute_class_iri}> .
{_VALUE_OPTIONALS.format(node="?attr", q="?numValue", s="?simpleValue",
                         c="?catValue", cl="?catLabel")}
    }}
    """
    return run_df(client, query,
                  ["attr", "numValue", "simpleValue", "catValue", "catLabel"])


def grouped_member_values(client, target_class_iri: str, grouping_class_iri: str,
                          dataset_iri: Optional[str] = None) -> pd.DataFrame:
    """Target-attribute values paired with the grouping-attribute value on the
    SAME component. Columns: attr, numValue, simpleValue, catValue, catLabel,
    gNumValue, gSimpleValue, gCatValue, gCatLabel."""
    ds = f"  ?comp dici_onto:hasDataSource <{dataset_iri}> .\n" if dataset_iri else ""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attr ?numValue ?simpleValue ?catValue ?catLabel
                    ?gNumValue ?gSimpleValue ?gCatValue ?gCatLabel
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?comp ?edge ?attr .
      ?edge rdfs:subPropertyOf* dici_onto:hasAttribute .
{ds}      ?attr a ?t .
      ?t rdfs:subClassOf* <{target_class_iri}> .
{_VALUE_OPTIONALS.format(node="?attr", q="?numValue", s="?simpleValue",
                         c="?catValue", cl="?catLabel")}
      ?comp ?gedge ?gattr .
      ?gedge rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?gattr a ?gt .
      ?gt rdfs:subClassOf* <{grouping_class_iri}> .
{_VALUE_OPTIONALS.format(node="?gattr", q="?gNumValue", s="?gSimpleValue",
                         c="?gCatValue", cl="?gCatLabel")}
    }}
    """
    return run_df(client, query,
                  ["attr", "numValue", "simpleValue", "catValue", "catLabel",
                   "gNumValue", "gSimpleValue", "gCatValue", "gCatLabel"])


def is_component_class(client, class_iri: str) -> bool:
    """Whether the class sits under dici_onto:Component in the schema graph."""
    query = f"""
    {_PREFIXES}
    SELECT (COUNT(*) AS ?n)
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
      <{class_iri}> rdfs:subClassOf* dici_onto:Component .
    }}
    """
    df = run_df(client, query, ["n"])
    try:
        return not df.empty and int(df["n"].iloc[0]) > 0
    except (TypeError, ValueError, KeyError, IndexError):
        return False


def component_grouped_member_values(client, target_class_iri: str,
                                    grouping_component_class_iri: str,
                                    dataset_iri: Optional[str] = None) -> pd.DataFrame:
    """Target-attribute values paired with the component instance of the
    grouping class that their OWNER component is linked to — in either link
    direction, via any ``linksComponent``-family edge (system topology only:
    bookkeeping predicates like ``derivedFromCatalogue`` are subproperties of
    ``prov:wasDerivedFrom``, not ``linksComponent``, so they never group).
    Columns: attr, numValue, simpleValue, catValue, catLabel, container,
    containerLabel."""
    ds = f"  ?owner dici_onto:hasDataSource <{dataset_iri}> .\n" if dataset_iri else ""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attr ?numValue ?simpleValue ?catValue ?catLabel
                    ?container ?containerLabel
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH,
                 SYSTEM_DESCRIPTION_GRAPH)}WHERE {{
      ?owner ?edge ?attr .
      ?edge rdfs:subPropertyOf* dici_onto:hasAttribute .
{ds}      ?attr a ?t .
      ?t rdfs:subClassOf* <{target_class_iri}> .
{_VALUE_OPTIONALS.format(node="?attr", q="?numValue", s="?simpleValue",
                         c="?catValue", cl="?catLabel")}
      {{
        ?owner ?link ?container .
        ?link rdfs:subPropertyOf* dici_onto:linksComponent .
      }}
      UNION
      {{
        ?container ?link ?owner .
        ?link rdfs:subPropertyOf* dici_onto:linksComponent .
      }}
      ?container a ?ct .
      ?ct rdfs:subClassOf* <{grouping_component_class_iri}> .
      FILTER(?container != ?owner)
      OPTIONAL {{ ?container rdfs:label ?containerLabel . }}
    }}
    """
    return run_df(client, query,
                  ["attr", "numValue", "simpleValue", "catValue", "catLabel",
                   "container", "containerLabel"])


def workspace_component_types(client) -> pd.DataFrame:
    """Component classes with instances in this workspace — the component-
    grouping options for the Collections builder. Only classes whose instances
    actually take part in a component link are offered (grouping by an
    unlinked class would always yield nothing). Columns: componentType, label,
    instanceCount."""
    query = f"""
    {_PREFIXES}
    SELECT ?componentType ?label (COUNT(DISTINCT ?inst) AS ?instanceCount)
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH,
                 SYSTEM_DESCRIPTION_GRAPH)}WHERE {{
      ?inst a ?componentType .
      ?componentType rdfs:subClassOf+ dici_onto:Component .
      {{ ?inst ?link ?other . ?link rdfs:subPropertyOf* dici_onto:linksComponent . }}
      UNION
      {{ ?other ?link ?inst . ?link rdfs:subPropertyOf* dici_onto:linksComponent . }}
      FILTER(?other != ?inst)
      OPTIONAL {{ ?componentType rdfs:label ?label . }}
      FILTER NOT EXISTS {{
        ?inst a ?moreSpecific .
        ?moreSpecific rdfs:subClassOf+ ?componentType .
        FILTER(?moreSpecific != ?componentType)   # closure has reflexive subClassOf
      }}
      FILTER NOT EXISTS {{
        ?attrOwner ?attrEdge ?inst .
        ?attrEdge rdfs:subPropertyOf* dici_onto:hasAttribute .
      }}
    }}
    GROUP BY ?componentType ?label
    ORDER BY ?componentType
    """
    return run_df(client, query, ["componentType", "label", "instanceCount"])


def workspace_attribute_types(client) -> pd.DataFrame:
    """The attribute classes that actually occur on this workspace's attribute
    nodes, with instance counts — the options for the Collections builder.

    Keeps only each node's most specific Attribute class (closure also types
    every node with its base value-type, which would otherwise flood the list).
    Columns: attrType, label, instanceCount.
    """
    query = f"""
    {_PREFIXES}
    SELECT ?attrType ?label (COUNT(DISTINCT ?attr) AS ?instanceCount)
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?comp ?edge ?attr .
      ?edge rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?attr a ?attrType .
      ?attrType rdfs:subClassOf+ dici_onto:Attribute .
      OPTIONAL {{ ?attrType rdfs:label ?label . }}
      FILTER NOT EXISTS {{
        ?attr a ?moreSpecific .
        ?moreSpecific rdfs:subClassOf+ ?attrType .
        ?moreSpecific rdfs:subClassOf+ dici_onto:Attribute .
        FILTER(?moreSpecific != ?attrType)   # closure has reflexive subClassOf
      }}
    }}
    GROUP BY ?attrType ?label
    ORDER BY ?attrType
    """
    return run_df(client, query, ["attrType", "label", "instanceCount"])


def workspace_datasets(client) -> pd.DataFrame:
    """The data sources (References) components cite via hasDataSource, for the
    optional dataset filter. Columns: dataset, label, componentCount."""
    query = f"""
    {_PREFIXES}
    SELECT ?dataset ?label (COUNT(DISTINCT ?comp) AS ?componentCount)
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?comp dici_onto:hasDataSource ?dataset .
      OPTIONAL {{ ?dataset rdfs:label ?label . }}
    }}
    GROUP BY ?dataset ?label
    ORDER BY ?dataset
    """
    return run_df(client, query, ["dataset", "label", "componentCount"])


def list_collections(client) -> pd.DataFrame:
    """Top-level collections in the workspace (group-member Sets excluded).
    Columns: collection, kind, attrType, groupedBy, dataset, computedAt."""
    query = f"""
    {_PREFIXES}
    SELECT ?collection ?kind ?attrType ?groupedBy ?dataset ?computedAt
    {from_clause(COLLECTIONS_GRAPH)}WHERE {{
      ?collection a ?kind .
      FILTER(?kind IN (dici_onto:Set, dici_onto:GroupedSet))
      ?collection dici_onto:ofAttributeType ?attrType .
      OPTIONAL {{ ?collection dici_onto:groupedBy ?groupedBy . }}
      OPTIONAL {{ ?collection dici_onto:derivedFromDataSet ?dataset . }}
      OPTIONAL {{ ?collection dici_onto:computedAt ?computedAt . }}
      FILTER NOT EXISTS {{ ?parent dici_onto:hasGroup ?collection . }}
    }}
    ORDER BY ?collection
    """
    return run_df(client, query,
                  ["collection", "kind", "attrType", "groupedBy", "dataset",
                   "computedAt"])


def set_statistics(client, collection_iri: str) -> pd.DataFrame:
    """All statistics of a Set — or of every group member when the IRI is a
    GroupedSet. Columns: set, groupKey, statistic, value."""
    query = f"""
    {_PREFIXES}
    SELECT ?set ?groupKey ?statistic ?value
    {from_clause(COLLECTIONS_GRAPH)}WHERE {{
      {{ BIND(<{collection_iri}> AS ?set) }}
      UNION
      {{ <{collection_iri}> dici_onto:hasGroup ?set . }}
      ?set dici_onto:hasDescriptiveStatistics ?stats .
      ?stats ?statistic ?value .
      FILTER(?statistic != rdf:type)
      OPTIONAL {{ ?set dici_onto:groupKey ?groupKey . }}
    }}
    ORDER BY ?set ?statistic
    """
    return run_df(client, query, ["set", "groupKey", "statistic", "value"])


def set_bins(client, collection_iri: str) -> pd.DataFrame:
    """Distribution bins of a Set (or of all group members of a GroupedSet).
    Columns: set, groupKey, binLabel, lower, upper, frequency."""
    query = f"""
    {_PREFIXES}
    SELECT ?set ?groupKey ?binLabel ?lower ?upper ?frequency
    {from_clause(COLLECTIONS_GRAPH)}WHERE {{
      {{ BIND(<{collection_iri}> AS ?set) }}
      UNION
      {{ <{collection_iri}> dici_onto:hasGroup ?set . }}
      ?set dici_onto:hasDistribution ?dist .
      ?dist dici_onto:hasBin ?bin .
      ?bin dici_onto:binLabel ?binLabel ;
           dici_onto:binFrequency ?frequency .
      OPTIONAL {{ ?bin dici_onto:binLowerBound ?lower . }}
      OPTIONAL {{ ?bin dici_onto:binUpperBound ?upper . }}
      OPTIONAL {{ ?set dici_onto:groupKey ?groupKey . }}
    }}
    ORDER BY ?set ?lower ?binLabel
    """
    return run_df(client, query,
                  ["set", "groupKey", "binLabel", "lower", "upper", "frequency"])


def member_count(client, set_iri: str) -> int:
    """How many attribute instances are aggregated in the Set."""
    query = f"""
    {_PREFIXES}
    SELECT (COUNT(?attr) AS ?n)
    {from_clause(COLLECTIONS_GRAPH)}WHERE {{
      ?attr dici_onto:aggregatedIn <{set_iri}> .
    }}
    """
    df = run_df(client, query, ["n"])
    try:
        return int(df["n"].iloc[0]) if not df.empty else 0
    except (TypeError, ValueError):
        return 0
