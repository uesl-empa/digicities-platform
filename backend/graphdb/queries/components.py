# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Component / attribute discovery queries.

Pure SPARQL query functions for components, their instances, and attribute
values. UI-independent: each takes a client and returns a pandas DataFrame
(empty on error or no results). Graph scoping comes from
``backend.graphdb.graphs``.

These consolidate the queries previously embedded in the Streamlit components
(Digital Replica Explorer, Service Requirements Builder, Scenario Builder
component loader). The components now call these functions and handle display
only.
"""

from __future__ import annotations

import pandas as pd

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    from_clause,
)

# Common prefixes used across the queries.
_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX qudt: <http://qudt.org/schema/qudt/>\n"
    "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
    "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
    "PREFIX schema: <https://schema.org/>\n"
)

# A component instance is never the OBJECT of a hasAttribute-family edge. The
# dual-typing convention types a Categorical attribute node with its VALUE class;
# when that value class is also a component class (a SiteType whose value IS
# GlobalWindAtlasSite), a bare `?instance a <class>` picks the attribute node up
# as a phantom instance. Every instance-enumerating query below carries this
# guard, so the exclusion is uniform across ALL workspaces and modules.
NOT_ATTRIBUTE_NODE = (
    "  FILTER NOT EXISTS {\n"
    "    ?attrOwner ?attrEdge ?instance .\n"
    "    ?attrEdge rdfs:subPropertyOf* dici_onto:hasAttribute .\n"
    "  }\n"
)

# Empty-DataFrame columns per query, so callers always get a stable schema.
_EMPTY_COLS = {
    "types_with_instances": ["componentType", "componentName", "instanceCount"],
    "all_instances": ["instance", "type", "label"],
    "instance_attr_links": ["instance", "attribute"],
    "attribute_kinds": ["attribute", "kind"],
    "all_attr_values": ["instance", "attribute", "property", "value"],
    "all_direct_props": ["instance", "property", "value"],
    "instances": ["instance", "instanceLabel"],
    "comprehensive": ["instance", "attribute", "property", "value"],
    "basic": ["instance", "property", "value"],
    "classes": ["class", "label"],
    "subclasses": ["component"],
    "attr_subclasses": ["attribute", "label"],
    "types": ["type"],
    "type_instances": ["instance", "label"],
    "instance_attrs": ["attribute", "property", "value"],
    "instance_props": ["property", "value"],
    "object_props": ["component", "property", "attribute"],
    "sources": ["instance", "scope", "attributeName", "source", "sourceLabel",
                "sourceType", "sourceUrl", "sourceDate", "sourceComment"],
}


def _run(client, query: str, empty_key: str) -> pd.DataFrame:
    """Execute a query and return a DataFrame, never raising.

    Returns an empty DataFrame with the expected columns on any failure or
    empty result, so callers can rely on the column schema.
    """
    empty = pd.DataFrame(columns=_EMPTY_COLS[empty_key])
    if client is None:
        return empty
    try:
        result = client.sparql_api_query(query, out_format="df")
    except Exception as exc:  # network / SPARQL error — caller decides how to surface
        print(f"[graphdb.queries.components] query failed ({empty_key}): {exc}")
        return empty
    if result is None or result.empty:
        return empty
    return result


# ---------------------------------------------------------------------------
# Replica Builder "load existing instances" — semantic discovery
# ---------------------------------------------------------------------------

def get_all_component_instances(client) -> pd.DataFrame:
    """Every component instance with its most specific component type and label.

    Fully semantic: an instance qualifies because its type is
    ``rdfs:subClassOf* dici_onto:Component`` (the ontology hierarchy decides what
    is a Component — no reliance on class-name spelling). The ``FILTER NOT EXISTS``
    keeps only the leaf type, so an instance that also carries inferred supertypes
    (``a dici_onto:Component`` after RDFS materialisation) is reported under its
    authored type, not an abstract one. Columns: instance, type, label.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?type ?label
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance a ?type .
      ?type rdfs:subClassOf* dici_onto:Component .
      FILTER(?type != dici_onto:Component)
      FILTER NOT EXISTS {{
        ?instance a ?sub .
        ?sub rdfs:subClassOf+ ?type .
        FILTER(?sub != ?type)
      }}
{NOT_ATTRIBUTE_NODE}      OPTIONAL {{ ?instance rdfs:label ?label }}
    }}
    ORDER BY ?instance
    """
    return _run(client, query, "all_instances")


def get_all_instance_attribute_links(client) -> pd.DataFrame:
    """Instance → attribute-node links for every component instance.

    Semantic: any predicate that is ``rdfs:subPropertyOf* dici_onto:hasAttribute``
    counts, so typed predicates (``has<Type><Name>Attribute``) are followed as
    well as the plain ``hasAttribute`` — without matching on predicate spelling.
    Columns: instance, attribute.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?attribute
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance ?attrPredicate ?attribute .
      ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
    }}
    ORDER BY ?instance ?attribute
    """
    return _run(client, query, "instance_attr_links")


# The attribute-kind classes the Replica Builder editor understands. They are
# flat siblings in the ontology, so an attribute node resolves to exactly one via
# rdfs:subClassOf* — including custom subclasses (e.g. GroundFloorArea →
# PhysicalAttribute) that don't assert the kind directly.
ATTRIBUTE_KIND_CLASSES = (
    "PhysicalAttribute", "DynamicAttribute", "CategoricalAttribute",
    "EventAttribute", "CurveAttribute", "SimpleCostAttribute",
    "UnitBasedCostAttribute", "ResourceAttribute", "SimpleValueAttribute",
    "CustomPhysicalRatioAttribute", "GeospatialAttribute",
)


def get_attribute_kinds(client) -> pd.DataFrame:
    """Map each attribute node to its editor kind class via the ontology
    hierarchy (``rdfs:subClassOf*`` onto one of ATTRIBUTE_KIND_CLASSES).

    Semantic replacement for matching attribute class names by string. Columns:
    attribute, kind (the kind class IRI).
    """
    values = " ".join(f"dici_onto:{k}" for k in ATTRIBUTE_KIND_CLASSES)
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attribute ?kind
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?attribute a ?type .
      ?type rdfs:subClassOf* ?kind .
      VALUES ?kind {{ {values} }}
    }}
    """
    return _run(client, query, "attribute_kinds")


def get_all_attribute_values(client) -> pd.DataFrame:
    """Every (instance, attribute, property, value) for all component instances,
    in one query. Attribute nodes are reached via ``rdfs:subPropertyOf*
    dici_onto:hasAttribute`` (typed predicates included). The constant-query-count
    companion to the per-instance ``get_instance_attributes``; lets a loader pull
    the whole workspace's attribute values without N+1 round-trips.

    Columns: instance, attribute, property, value.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?attribute ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance ?attrPredicate ?attribute .
      ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?attribute ?property ?value .
    }}
    ORDER BY ?instance ?attribute ?property
    """
    return _run(client, query, "all_attr_values")


def get_all_instance_direct_properties(client) -> pd.DataFrame:
    """Direct (non-type, non-hasAttribute) properties of every component instance,
    in one query — for annotations like rdfs:comment/description. Restricted to
    subjects that are instances of a Component subclass so attribute nodes are
    excluded. Columns: instance, property, value.
    """
    query = f"""
    {_PREFIXES}
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?instance ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance a ?type .
      ?type rdfs:subClassOf* dici_onto:Component .
{NOT_ATTRIBUTE_NODE}      ?instance ?property ?value .
      FILTER(?property != dici_onto:hasAttribute)
      FILTER(!STRSTARTS(STR(?property), STR(dici_onto:has)))
      FILTER(?property != rdf:type)
    }}
    ORDER BY ?instance ?property
    """
    return _run(client, query, "all_direct_props")


# ---------------------------------------------------------------------------
# Digital Replica Explorer queries
# ---------------------------------------------------------------------------

def get_component_types_with_instances(client) -> pd.DataFrame:
    """Component types that actually have instances, with instance counts.

    Columns: componentType, componentName, instanceCount.
    """
    query = f"""
    {_PREFIXES}
    SELECT ?componentType ?componentName (COUNT(DISTINCT ?instance) as ?instanceCount)
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:subClassOf* dici_onto:Component .
      FILTER(?componentType != dici_onto:Component)
      ?instance a ?componentType .
{NOT_ATTRIBUTE_NODE}      OPTIONAL {{ ?componentType rdfs:label ?label }}
      BIND(COALESCE(
        ?label,
        IF(CONTAINS(STR(?componentType), "#"),
           STRAFTER(STR(?componentType), "#"),
           REPLACE(STR(?componentType), "^.*/([^/]+)$", "$1"))
      ) as ?componentName)
      FILTER(BOUND(?componentName) && STR(?componentName) != "")
    }}
    GROUP BY ?componentType ?componentName
    ORDER BY DESC(?instanceCount) ?componentName
    """
    return _run(client, query, "types_with_instances")


def get_component_instances(client, component_type_label: str) -> pd.DataFrame:
    """All instances of a component type (by label). Columns: instance, instanceLabel."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?instanceLabel
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
{NOT_ATTRIBUTE_NODE}      OPTIONAL {{ ?instance rdfs:label ?instanceLabel }}
    }}
    ORDER BY ?instance
    """
    return _run(client, query, "instances")


def get_component_attributes_comprehensive(client, component_type_label: str) -> pd.DataFrame:
    """Attribute values for every instance of a component type (by label).

    Uses a ``rdfs:subPropertyOf* dici_onto:hasAttribute`` property path so typed
    attribute predicates (e.g. ``hasWindTurbineHubHeightAttribute``) are picked
    up alongside direct ``hasAttribute`` uses, without relying on backend
    subproperty inference. Columns: instance, attribute, property, value.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?attribute ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
      ?instance ?attrPredicate ?attribute .
      ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?attribute ?property ?value .
    }}
    ORDER BY ?instance ?attribute ?property
    """
    return _run(client, query, "comprehensive")


def get_component_sources(client, component_type_label: str) -> pd.DataFrame:
    """Where each instance of a component type came from.

    Provenance is recorded at two granularities and both are returned, tagged by
    ``scope``:

    * ``instance`` — the whole record came from here (``dici_onto:hasSource``)
    * ``attribute`` — one value came from somewhere else than the record did, e.g.
      a specification copied down from a catalogue entry in another file
      (the ``<attr>_datasource`` column, emitted since long before ``hasSource``)

    The query matches on ``prov:wasDerivedFrom`` rather than on ``hasSource``, so it
    is deliberately agnostic about which mechanism wrote the triple: a hand-authored
    workbook that only ever used the Reference sheet lights up the same as an
    onboarded folder, and a future source kind needs no change here. What KIND of
    source it is comes from the Reference's own ``hasReferenceType``, not from the
    predicate. Columns: instance, scope, attributeName, source, sourceLabel,
    sourceType, sourceUrl, sourceDate, sourceComment.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?scope ?attributeName ?source ?sourceLabel
                    ?sourceType ?sourceUrl ?sourceDate ?sourceComment
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
{NOT_ATTRIBUTE_NODE}      {{
        ?instance ?sourcePredicate ?source .
        ?sourcePredicate rdfs:subPropertyOf* prov:wasDerivedFrom .
        BIND("instance" AS ?scope)
      }} UNION {{
        ?instance ?attrPredicate ?attribute .
        ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
        ?attribute ?sourcePredicate ?source .
        ?sourcePredicate rdfs:subPropertyOf* prov:wasDerivedFrom .
        BIND("attribute" AS ?scope)
        BIND(REPLACE(STR(?attribute), "^.*/", "") AS ?attributeName)
      }}
      # A citable origin, not any derivation. `derivedFromCatalogue` is also a
      # wasDerivedFrom subproperty but points at another COMPONENT, which belongs in
      # the model, not in "where did this data come from".
      ?source a dici_onto:Reference .
      OPTIONAL {{ ?source rdfs:label ?sourceLabel }}
      OPTIONAL {{ ?source dici_onto:hasReferenceType ?sourceTypeUri
                 BIND(REPLACE(STR(?sourceTypeUri), "^.*[#/]", "") AS ?sourceType) }}
      OPTIONAL {{ ?source schema:url ?sourceUrl }}
      OPTIONAL {{ ?source dcterms:dateAccessed ?sourceDate }}
      OPTIONAL {{ ?source rdfs:comment ?sourceComment }}
    }}
    ORDER BY ?instance ?scope ?attributeName
    """
    return _run(client, query, "sources")


def get_component_basic_properties(client, component_type_label: str) -> pd.DataFrame:
    """Non-attribute direct properties of a component type's instances (by label).

    Columns: instance, property, value.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
{NOT_ATTRIBUTE_NODE}      ?instance ?property ?value .
      FILTER(?property != dici_onto:hasAttribute)
      FILTER(!STRSTARTS(STR(?property), STR(dici_onto:has)))
      FILTER(?property != rdf:type)
    }}
    ORDER BY ?instance ?property
    """
    return _run(client, query, "basic")


# ---------------------------------------------------------------------------
# Service Requirements Builder queries (schema-level discovery)
# ---------------------------------------------------------------------------

def get_component_classes(client) -> pd.DataFrame:
    """All component classes (subclasses of Component). Columns: class, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?class ?label
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
        ?class rdfs:subClassOf* dici_onto:Component .
        OPTIONAL {{ ?class rdfs:label ?label }}
    }}
    ORDER BY ?class
    """
    return _run(client, query, "classes")


def get_attribute_classes(client) -> pd.DataFrame:
    """All attribute classes (subclasses of Attribute). Columns: class, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?class ?label
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
        ?class rdfs:subClassOf* dici_onto:Attribute .
        OPTIONAL {{ ?class rdfs:label ?label }}
    }}
    ORDER BY ?class
    """
    return _run(client, query, "classes")


def get_component_subclasses(client) -> pd.DataFrame:
    """Component subclasses excluding Component itself. Columns: component."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?component
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
        ?component rdfs:subClassOf* dici_onto:Component .
        FILTER(?component != dici_onto:Component)
    }}
    ORDER BY ?component
    """
    return _run(client, query, "subclasses")


def get_attribute_subclasses_for(client, attribute_class_name: str) -> pd.DataFrame:
    """Attribute subclasses of a named attribute class (by local name), excluding
    the class itself. Columns: attribute, label.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attribute ?label
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
        ?attribute rdfs:subClassOf* dici_onto:{attribute_class_name} .
        FILTER(?attribute != dici_onto:{attribute_class_name})
        OPTIONAL {{ ?attribute rdfs:label ?label }}
    }}
    ORDER BY ?attribute
    """
    return _run(client, query, "attr_subclasses")


def get_component_attribute_object_properties(client) -> pd.DataFrame:
    """Object-property based component->attribute mappings (fallback discovery
    used when the naming-convention method finds nothing).

    Columns: component, property, attribute.
    """
    query = f"""
    {_PREFIXES}
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?component ?property ?attribute
    {from_clause(ONTOLOGY_GRAPH)}WHERE {{
      ?property a owl:ObjectProperty ;
                rdfs:domain ?component ;
                rdfs:range ?attribute .
      ?component rdfs:subClassOf* dici_onto:Component .
      {{ ?attribute rdfs:subClassOf* dici_onto:StaticAttribute . }}
      UNION
      {{ ?attribute rdfs:subClassOf* dici_onto:DynamicAttribute . }}
      FILTER(CONTAINS(STR(?property), "Attribute"))
    }}
    ORDER BY ?component ?property ?attribute
    """
    return _run(client, query, "object_props")


# ---------------------------------------------------------------------------
# Scenario Builder component-loader queries
# ---------------------------------------------------------------------------

def get_leaf_component_types(client) -> pd.DataFrame:
    """Leaf component types that have instances (no instantiated subtype).

    Columns: type.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?type
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
        ?instance a ?type .
        ?type rdfs:subClassOf* dici_onto:Component .
        FILTER(?type != dici_onto:Component)
{NOT_ATTRIBUTE_NODE}
        FILTER NOT EXISTS {{
            ?type rdfs:subClassOf ?parent .
            ?parent rdfs:subClassOf* dici_onto:Component .
            ?instance a ?parent .
            FILTER(?parent != ?type && ?parent != dici_onto:Component)
        }}
    }}
    ORDER BY ?type
    """
    return _run(client, query, "types")


def get_instances_of_type(client, component_type: str) -> pd.DataFrame:
    """Instances of a component type by local name (``a dici_onto:<type>``).

    Columns: instance, label.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?instance ?label
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
        ?instance a dici_onto:{component_type} .
{NOT_ATTRIBUTE_NODE}        OPTIONAL {{ ?instance rdfs:label ?label }}
    }}
    ORDER BY ?instance
    """
    return _run(client, query, "type_instances")


def get_instance_attributes(client, instance_uri: str) -> pd.DataFrame:
    """Attribute values for a specific instance URI. Columns: attribute, property, value."""
    query = f"""
    {_PREFIXES}
    PREFIX dcterms: <http://purl.org/dc/terms/>
    SELECT DISTINCT ?attribute ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
        <{instance_uri}> ?attrPredicate ?attribute .
        ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
        ?attribute ?property ?value .
    }}
    ORDER BY ?attribute ?property
    """
    return _run(client, query, "instance_attrs")


def get_instance_direct_properties(client, instance_uri: str) -> pd.DataFrame:
    """Direct (non-type, non-hasAttribute) properties of an instance.

    Columns: property, value.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
        <{instance_uri}> ?property ?value .
        FILTER(?property != rdf:type && ?property != dici_onto:hasAttribute)
    }}
    """
    return _run(client, query, "instance_props")
