# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Instance Inspector: recommended SPARQL queries for one selected instance.

Given an instance URI (picked in the Digital Replica Explorer), build the
queries a user is most likely to want next — each one a ready-to-edit SPARQL
string for the Query Manager, with the instance as subject.

Every recommendation is derived from the CORE ONTOLOGY'S RULES, not from the
instance's class name: relationships are matched by walking
``rdfs:subPropertyOf*`` from the core anchor properties (``linksComponent``,
``hasAttribute``, ``derivedFromCatalogue``, ``prov:wasDerivedFrom``) and class
kinship by walking ``rdfs:subClassOf`` — so the same seven queries work for any
workspace extension class without this module knowing it exists.

The provisioned ontology graph materialises the RDFS closure, which makes
``rdfs:subClassOf`` transitively closed. "Direct parent" therefore cannot be
read off a single triple; the templates recover it with a no-intermediate
filter, and the instance's "own class" with a no-more-specific filter.

Each recommendation carries an ``ask`` twin — the same WHERE block under an
ASK — so a caller can pre-flight which recommendations would actually return
rows (``available_recommendations``) and hide the empty ones.
"""

from __future__ import annotations

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    from_clause,
)

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
    "PREFIX schema: <https://schema.org/>\n"
)

# The instance's own class, at its most specific: with a materialised closure the
# instance is typed with every ancestor too, so keep only classes that no other
# asserted type of the instance is a proper subclass of.
_OWN_CLASS = """  <{uri}> a ?class .
  ?class rdfs:subClassOf* dici_onto:Component .
  FILTER NOT EXISTS {{
    <{uri}> a ?moreSpecific .
    ?moreSpecific rdfs:subClassOf ?class .
    FILTER(?moreSpecific != ?class)
  }}"""

# A DIRECT subclass edge, recovered under a transitively-closed subClassOf:
# child -> parent with no distinct class strictly between them. @CHILD@/@PARENT@
# are plain replace-tokens so the SPARQL braces survive until the one .format call.
_DIRECT_EDGE = """  @CHILD@ rdfs:subClassOf @PARENT@ .
  FILTER(@CHILD@ != @PARENT@)
  FILTER NOT EXISTS {{
    @CHILD@ rdfs:subClassOf @MID@ .
    @MID@ rdfs:subClassOf @PARENT@ .
    FILTER(@MID@ != @CHILD@ && @MID@ != @PARENT@)
  }}"""


def _direct_edge(child: str, parent: str, mid: str) -> str:
    return (_DIRECT_EDGE.replace("@CHILD@", child).replace("@PARENT@", parent)
            .replace("@MID@", mid))


def _validate(instance_uri: str) -> str:
    uri = (instance_uri or "").strip()
    if not uri.startswith(("http://", "https://")) or any(ch in uri for ch in "<> \n\t\""):
        raise ValueError(f"not an absolute IRI: {instance_uri!r}")
    return uri


# (key, name, description, SELECT clause, WHERE block, ORDER BY clause).
# The WHERE block is shared verbatim between the SELECT and its ASK twin.
_RECOMMENDATIONS = [
    (
        "overview",
        "Everything about this instance",
        "Every statement the instance appears in, outgoing and incoming.",
        "?direction ?predicate ?value ?valueLabel",
        """  {{ BIND("outgoing →" AS ?direction) <{uri}> ?predicate ?value . }}
  UNION
  {{ BIND("← incoming" AS ?direction) ?value ?predicate <{uri}> . }}
  OPTIONAL {{ ?value rdfs:label ?valueLabel }}""",
        "DESC(?direction) ?predicate",
    ),
    (
        "attributes",
        "Attributes and their values",
        "The instance's attribute nodes with every recorded property (value, unit, "
        "data points), matched via the hasAttribute property hierarchy.",
        "?attribute ?attributeClass ?property ?value",
        """  <{uri}> ?attrPredicate ?attribute .
  ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
  ?attribute ?property ?value .
  OPTIONAL {{
    ?attribute a ?attributeClass .
    # only the most specific type of the attribute node
    FILTER NOT EXISTS {{
      ?attribute a ?moreSpecific .
      ?moreSpecific rdfs:subClassOf ?attributeClass .
      FILTER(?moreSpecific != ?attributeClass)
    }}
  }}
  FILTER(?property != rdf:type)""",
        "?attribute ?property",
    ),
    (
        "links",
        "Linked components",
        "Components connected to this instance in either direction, via any "
        "predicate under the core linksComponent hierarchy.",
        "?direction ?predicate ?component ?componentClass ?componentLabel",
        """  {{ BIND("outgoing →" AS ?direction) <{uri}> ?predicate ?component . }}
  UNION
  {{ BIND("← incoming" AS ?direction) ?component ?predicate <{uri}> . }}
  ?predicate rdfs:subPropertyOf* dici_onto:linksComponent .
  OPTIONAL {{
    ?component a ?componentClass .
    ?componentClass rdfs:subClassOf* dici_onto:Component .
    # only the most specific class of the neighbour
    FILTER NOT EXISTS {{
      ?component a ?moreSpecific .
      ?moreSpecific rdfs:subClassOf ?componentClass .
      FILTER(?moreSpecific != ?componentClass)
    }}
  }}
  OPTIONAL {{ ?component rdfs:label ?componentLabel }}""",
        "DESC(?direction) ?predicate ?component",
    ),
    (
        "same_class",
        "Instances of the same class",
        "Every other instance sharing this instance's (most specific) class.",
        "?class ?instance ?instanceLabel",
        _OWN_CLASS + """
  ?instance a ?class .
  FILTER(?instance != <{uri}>)
  OPTIONAL {{ ?instance rdfs:label ?instanceLabel }}""",
        "?class ?instance",
    ),
    (
        "cousins",
        "Instances of sibling (cousin) classes",
        "Instances of the other classes under this instance's direct parent in "
        "the class hierarchy — its nearest relatives.",
        "?parentClass ?cousinClass ?instance ?instanceLabel",
        _OWN_CLASS + "\n"
        + _direct_edge("?class", "?parentClass", "?mid1") + "\n"
        + _direct_edge("?cousinClass", "?parentClass", "?mid2") + """
  FILTER(?cousinClass != ?class)
  FILTER NOT EXISTS {{ <{uri}> a ?cousinClass }}
  ?instance a ?cousinClass .
  FILTER(?instance != <{uri}>)
  OPTIONAL {{ ?instance rdfs:label ?instanceLabel }}""",
        "?parentClass ?cousinClass ?instance",
    ),
    (
        "catalogue",
        "Catalogue derivation",
        "The catalogue entry this instance was specced from, and any instances "
        "specced from this one.",
        "?relation ?other ?otherLabel",
        """  {{
    BIND("specced from catalogue entry" AS ?relation)
    <{uri}> ?p ?other .
    ?p rdfs:subPropertyOf* dici_onto:derivedFromCatalogue .
  }}
  UNION
  {{
    BIND("instances specced from this entry" AS ?relation)
    ?other ?p <{uri}> .
    ?p rdfs:subPropertyOf* dici_onto:derivedFromCatalogue .
  }}
  OPTIONAL {{ ?other rdfs:label ?otherLabel }}""",
        "?relation ?other",
    ),
    (
        "sources",
        "Data sources (provenance)",
        "The Reference each value was read from — the record's own source and any "
        "per-attribute sources, via the prov:wasDerivedFrom property hierarchy.",
        "?scope ?attribute ?source ?sourceLabel ?sourceUrl",
        """  {{
    BIND("instance" AS ?scope)
    <{uri}> ?sourcePredicate ?source .
  }}
  UNION
  {{
    BIND("attribute" AS ?scope)
    <{uri}> ?attrPredicate ?attributeNode .
    ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
    ?attributeNode ?sourcePredicate ?source .
    BIND(REPLACE(STR(?attributeNode), "^.*/", "") AS ?attribute)
  }}
  ?sourcePredicate rdfs:subPropertyOf* prov:wasDerivedFrom .
  # a citable origin, not the catalogue link (which also sits under wasDerivedFrom)
  ?source a dici_onto:Reference .
  OPTIONAL {{ ?source rdfs:label ?sourceLabel }}
  OPTIONAL {{ ?source schema:url ?sourceUrl }}""",
        "?scope ?attribute",
    ),
]


def recommended_queries(instance_uri: str) -> list[dict]:
    """The recommended queries for one instance, ready for the Query Manager.

    Returns ``[{"key", "name", "description", "sparql", "ask"}, ...]`` in
    presentation order. Raises ``ValueError`` on anything that is not an
    absolute IRI, so a malformed value can never be spliced into a query.
    """
    uri = _validate(instance_uri)
    graphs = from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)
    out = []
    for key, name, description, select, where, order in _RECOMMENDATIONS:
        body = where.format(uri=uri)
        out.append({
            "key": key,
            "name": name,
            "description": description,
            "sparql": f"{_PREFIXES}SELECT DISTINCT {select}\n{graphs}WHERE {{\n"
                      f"{body}\n}}\nORDER BY {order}",
            "ask": f"{_PREFIXES}ASK\n{graphs}WHERE {{\n{body}\n}}",
        })
    return out


def available_recommendations(client, instance_uri: str) -> list[dict]:
    """``recommended_queries`` filtered to those that would return rows.

    Each candidate's ASK twin is executed first; a recommendation whose pattern
    matches nothing is dropped, so the UI never offers a query that comes back
    empty. Fails OPEN: if an ASK cannot be executed (transport error, a store
    without ASK support), the recommendation is kept — hiding must never lose a
    working query.
    """
    return [r for r in recommended_queries(instance_uri) if _ask(client, r["ask"])]


def _ask(client, query: str) -> bool:
    try:
        res = client.sparql_api_query(query, out_format="response")
        if hasattr(res, "json"):
            res = res.json()
        if isinstance(res, dict):
            return bool(res.get("boolean", True))
        return bool(res)
    except Exception as exc:
        print(f"[graphdb.queries.inspector] ASK pre-flight failed (keeping query): {exc}")
        return True
