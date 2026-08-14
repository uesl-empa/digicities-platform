# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The Instance Inspector's recommended queries, executed against a real graph.

Every recommendation must be derived from the core ontology's rules — property
hierarchies (``rdfs:subPropertyOf*``) and class kinship (``rdfs:subClassOf``) —
never from hardcoded class names. The fixture deliberately mirrors what the
provisioned store actually contains: a MATERIALISED closure, where every
instance is typed with all its ancestor classes and ``subClassOf`` is
transitively closed (plus reflexive edges). That is what makes "the instance's
class" and "direct parent" non-trivial, and what these tests pin:

* the same-class query returns peers of the MOST SPECIFIC class only;
* the cousin query finds siblings under the DIRECT parent (TidalTurbine under
  Turbine) and does not leak uncle-level classes (Pump under Component), even
  though the closure says WindTurbine subClassOf Component too;
* links are matched via the linksComponent hierarchy, so derivedFromCatalogue
  (not a link) stays out; sources via wasDerivedFrom, restricted to References,
  so the catalogue link stays out of provenance;
* a malformed instance URI can never be spliced into a query.

Deterministic: an in-memory rdflib dataset stands in for the triplestore.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

rdflib = pytest.importorskip("rdflib")

from backend.graphdb.graphs import (  # noqa: E402
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
)
from backend.graphdb.queries import recommended_queries  # noqa: E402

PROJ = "https://digicities.info/proj/t"
T1 = f"{PROJ}/WindTurbine/T1"

ONTOLOGY = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

# Class hierarchy WITH the materialised closure: transitive and reflexive edges
# included, exactly as the provisioned ontology graph has them.
dici_onto:Component a owl:Class ; rdfs:subClassOf dici_onto:Component .
dici_onto:Turbine a owl:Class ;
    rdfs:subClassOf dici_onto:Turbine, dici_onto:Component .
dici_onto:WindTurbine a owl:Class ;
    rdfs:subClassOf dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:Component .
dici_onto:TidalTurbine a owl:Class ;
    rdfs:subClassOf dici_onto:TidalTurbine, dici_onto:Turbine, dici_onto:Component .
dici_onto:Pump a owl:Class ;
    rdfs:subClassOf dici_onto:Pump, dici_onto:Component .
dici_onto:Location a owl:Class ;
    rdfs:subClassOf dici_onto:Location, dici_onto:Component .

dici_onto:PhysicalAttribute a owl:Class .
dici_onto:HubHeight a owl:Class ;
    rdfs:subClassOf dici_onto:HubHeight, dici_onto:PhysicalAttribute .

# Property hierarchies — the "rules" the recommendations traverse.
dici_onto:locatedIn a owl:ObjectProperty ;
    rdfs:subPropertyOf dici_onto:linksComponent .
dici_onto:hasHubHeightAttribute a owl:ObjectProperty ;
    rdfs:subPropertyOf dici_onto:hasAttribute .
dici_onto:hasSource a owl:ObjectProperty ;
    rdfs:subPropertyOf prov:wasDerivedFrom .
dici_onto:derivedFromCatalogue a owl:ObjectProperty ;
    rdfs:subPropertyOf prov:wasDerivedFrom .
"""

REPLICA = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix schema: <https://schema.org/> .

<{T1}> a dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:Component ;
    rdfs:label "Turbine 1" ;
    dici_onto:locatedIn <{PROJ}/Location/Site1> ;
    dici_onto:hasHubHeightAttribute <{T1}/HubHeight> ;
    dici_onto:derivedFromCatalogue <{PROJ}/WindTurbine/Cat1> ;
    dici_onto:hasSource <{PROJ}/Reference/park_yaml> .

<{T1}/HubHeight> a dici_onto:HubHeight, dici_onto:PhysicalAttribute ;
    dici_onto:hasValue "85.0" ;
    prov:wasDerivedFrom <{PROJ}/Reference/types_yaml> .

<{PROJ}/WindTurbine/T2> a dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:Component ;
    rdfs:label "Turbine 2" ;
    dici_onto:locatedIn <{PROJ}/Location/Site1> ;
    dici_onto:derivedFromCatalogue <{PROJ}/WindTurbine/Cat1> .

<{PROJ}/WindTurbine/Cat1> a dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:Component ;
    rdfs:label "Catalogue 2.3MW" .

<{PROJ}/TidalTurbine/TT1> a dici_onto:TidalTurbine, dici_onto:Turbine, dici_onto:Component ;
    rdfs:label "Tidal 1" .

<{PROJ}/Pump/P1> a dici_onto:Pump, dici_onto:Component ; rdfs:label "Pump 1" .

<{PROJ}/Location/Site1> a dici_onto:Location, dici_onto:Component ;
    rdfs:label "Site 1" .

<{PROJ}/Reference/park_yaml> a dici_onto:Reference ;
    rdfs:label "park_alkmaar.yaml" ;
    schema:url "default-configs/park_alkmaar.yaml" .
<{PROJ}/Reference/types_yaml> a dici_onto:Reference ;
    rdfs:label "turbinetypes.yaml" .
"""


class _Client:
    def __init__(self):
        self.ds = rdflib.Dataset()
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(
            data=REPLICA, format="turtle")
        self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH)).parse(data=ONTOLOGY, format="turtle")

    def run(self, query: str) -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def client() -> _Client:
    return _Client()


def _q(key: str, uri: str = T1) -> str:
    return next(r["sparql"] for r in recommended_queries(uri) if r["key"] == key)


# ── the recommendation set itself ─────────────────────────────────────────────

def test_seven_recommendations_each_named_and_scoped():
    recs = recommended_queries(T1)
    assert [r["key"] for r in recs] == [
        "overview", "attributes", "links", "same_class", "cousins", "catalogue", "sources"]
    for r in recs:
        assert r["name"] and r["description"]
        assert T1 in r["sparql"] and "FROM" in r["sparql"]


def test_queries_are_ontology_driven_not_name_matched():
    # No recommendation may mention any concrete class name — kinship and
    # relationships must come from subClassOf / subPropertyOf traversal.
    for r in recommended_queries(T1):
        body = r["sparql"].replace(T1, "")
        for name in ("WindTurbine", "Turbine", "Pump", "HubHeight"):
            assert name not in body, f"{r['key']} hardcodes {name}"
        if r["key"] != "overview":      # the raw triple dump traverses nothing
            assert "subClassOf" in r["sparql"] or "subPropertyOf" in r["sparql"]


@pytest.mark.parametrize("bad", ["", "not a uri", "urn:x", "https://x/> . ?s ?p ?o"])
def test_a_malformed_uri_is_rejected_not_spliced(bad):
    with pytest.raises(ValueError):
        recommended_queries(bad)


# ── each query, executed ──────────────────────────────────────────────────────

def test_overview_returns_both_directions(client):
    df = client.run(_q("overview"))
    out = df[df["direction"] == "outgoing →"]
    assert any(out["value"].str.endswith("/Site1"))          # locatedIn
    inc = client.run(_q("overview", f"{PROJ}/WindTurbine/Cat1"))
    inc = inc[inc["direction"] == "← incoming"]
    assert set(inc["value"]) == {T1, f"{PROJ}/WindTurbine/T2"}


def test_attributes_come_with_values_and_most_specific_class(client):
    df = client.run(_q("attributes"))
    assert set(df["attribute"]) == {f"{T1}/HubHeight"}
    values = df[df["property"].str.endswith("hasValue")]
    assert list(values["value"]) == ["85.0"]
    # dual-typed attribute node -> only the most specific class is reported
    assert set(df["attributeClass"].dropna()) == {"https://digicities.info/ontology#HubHeight"}


def test_links_follow_the_linkscomponent_hierarchy_only(client):
    df = client.run(_q("links"))
    assert set(df["component"]) == {f"{PROJ}/Location/Site1"}     # not Cat1, not the Reference
    assert set(df["componentClass"].dropna()) == {"https://digicities.info/ontology#Location"}
    # and from the site's perspective the same link is incoming
    back = client.run(_q("links", f"{PROJ}/Location/Site1"))
    inc = back[back["direction"] == "← incoming"]
    assert set(inc["component"]) == {T1, f"{PROJ}/WindTurbine/T2"}


def test_same_class_means_the_most_specific_class(client):
    df = client.run(_q("same_class"))
    assert set(df["class"]) == {"https://digicities.info/ontology#WindTurbine"}
    assert set(df["instance"]) == {f"{PROJ}/WindTurbine/T2", f"{PROJ}/WindTurbine/Cat1"}


def test_cousins_are_siblings_under_the_direct_parent_only(client):
    df = client.run(_q("cousins"))
    # TidalTurbine sits beside WindTurbine under Turbine; Pump sits under
    # Component and must NOT leak in via the materialised closure edge.
    assert set(df["cousinClass"]) == {"https://digicities.info/ontology#TidalTurbine"}
    assert set(df["parentClass"]) == {"https://digicities.info/ontology#Turbine"}
    assert set(df["instance"]) == {f"{PROJ}/TidalTurbine/TT1"}


def test_catalogue_derivation_both_ways(client):
    df = client.run(_q("catalogue"))
    assert set(df["other"]) == {f"{PROJ}/WindTurbine/Cat1"}
    entry = client.run(_q("catalogue", f"{PROJ}/WindTurbine/Cat1"))
    derived = entry[entry["relation"] == "instances specced from this entry"]
    assert set(derived["other"]) == {T1, f"{PROJ}/WindTurbine/T2"}


def test_sources_are_references_never_the_catalogue_link(client):
    df = client.run(_q("sources"))
    by_scope = {s: set(g["source"]) for s, g in df.groupby("scope")}
    assert by_scope["instance"] == {f"{PROJ}/Reference/park_yaml"}
    assert by_scope["attribute"] == {f"{PROJ}/Reference/types_yaml"}
    assert not any(df["source"].str.contains("Cat1"))
