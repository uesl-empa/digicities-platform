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
    SCENARIOS_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
)
from backend.graphdb.queries import (  # noqa: E402
    available_recommendations,
    available_workspace_queries,
    recommended_queries,
    workspace_queries,
)

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

# The [] is an ANONYMOUS class typing, as the pre-hygiene inference closure
# used to mint from owl:Restriction superclasses — older graphs still carry
# them, and the class queries must never surface a blank node as a class.
<{T1}/HubHeight> a dici_onto:HubHeight, dici_onto:PhysicalAttribute, [] ;
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


# A link that lives ONLY in the system-description graph (the replica-built
# path) — the link queries must see it too.
SYSTEM_DESCRIPTION = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
<{PROJ}/TidalTurbine/TT1> dici_onto:locatedIn <{PROJ}/Location/Site1> .
"""

SCENARIOS = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{PROJ}/scenario/Baseline> a dici_onto:Scenario ; rdfs:label "Baseline" .
"""


class _Client:
    def __init__(self, scenarios: str = SCENARIOS):
        self.ds = rdflib.Dataset()
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(
            data=REPLICA, format="turtle")
        self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH)).parse(data=ONTOLOGY, format="turtle")
        self.ds.graph(rdflib.URIRef(SYSTEM_DESCRIPTION_GRAPH)).parse(
            data=SYSTEM_DESCRIPTION, format="turtle")
        # The graph must EXIST even when it holds no scenarios: rdflib
        # dereferences a FROM graph it does not know over HTTP, which a real
        # store never does. A graph only registers once it holds a triple, so
        # "no scenarios yet" is a graph with one unmatchable marker triple.
        g = self.ds.graph(rdflib.URIRef(SCENARIOS_GRAPH))
        if scenarios:
            g.parse(data=scenarios, format="turtle")
        else:
            g.add((rdflib.URIRef(SCENARIOS_GRAPH),
                   rdflib.RDFS.comment, rdflib.Literal("no scenarios yet")))

    def run(self, query: str) -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])

    def sparql_api_query(self, query: str, out_format: str = "df"):
        res = self.ds.query(query)
        if res.type == "ASK":
            return {"boolean": bool(res.askAnswer)}
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
        # the ASK twin shares the pattern, scoped to the same graphs
        assert r["ask"].count("FROM") == r["sparql"].count("FROM")
        assert "ASK" in r["ask"] and T1 in r["ask"]


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
    # and from the site's perspective the links are incoming — including the one
    # recorded only in the system-description graph
    back = client.run(_q("links", f"{PROJ}/Location/Site1"))
    inc = back[back["direction"] == "← incoming"]
    assert set(inc["component"]) == {
        T1, f"{PROJ}/WindTurbine/T2", f"{PROJ}/TidalTurbine/TT1"}


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


def test_ask_preflight_hides_only_the_empty_recommendations(client):
    # T1 has links, attributes, a catalogue entry, sources and peers: all seven.
    assert [r["key"] for r in available_recommendations(client, T1)] == [
        "overview", "attributes", "links", "same_class", "cousins", "catalogue", "sources"]
    # The pump has none of that: no attributes, no links, no catalogue, no
    # sources, no same-class peers. Its overview (it exists) and its cousins
    # (Turbine and Location instances beside Pump under Component) remain.
    pump = available_recommendations(client, f"{PROJ}/Pump/P1")
    assert [r["key"] for r in pump] == ["overview", "cousins"]


def test_ask_preflight_fails_open_when_ask_cannot_run(client):
    class _Broken:
        def sparql_api_query(self, query, out_format="df"):
            raise RuntimeError("no ASK support")
    # Hiding must never lose a working query: with ASK unavailable, everything stays.
    assert len(available_recommendations(_Broken(), T1)) == 7


def test_sources_are_references_never_the_catalogue_link(client):
    df = client.run(_q("sources"))
    by_scope = {s: set(g["source"]) for s, g in df.groupby("scope")}
    assert by_scope["instance"] == {f"{PROJ}/Reference/park_yaml"}
    assert by_scope["attribute"] == {f"{PROJ}/Reference/types_yaml"}
    assert not any(df["source"].str.contains("Cat1"))


# ── the workspace-level landing set ───────────────────────────────────────────

def _wq(key: str) -> str:
    return next(r["sparql"] for r in workspace_queries() if r["key"] == key)


def test_workspace_queries_named_scoped_and_askable():
    recs = workspace_queries()
    assert [r["key"] for r in recs] == [
        "all_components", "class_counts", "component_links", "attribute_values",
        "scenarios", "data_sources", "catalogue_instances"]
    for r in recs:
        assert r["name"] and r["description"]
        assert "FROM" in r["sparql"] and "ASK" in r["ask"]


def test_all_components_reports_most_specific_classes(client):
    df = client.run(_wq("all_components"))
    by_class = {c.rsplit("#", 1)[-1]: set(g["instance"]) for c, g in df.groupby("class")}
    assert set(by_class) == {"WindTurbine", "TidalTurbine", "Pump", "Location"}
    assert by_class["WindTurbine"] == {T1, f"{PROJ}/WindTurbine/T2", f"{PROJ}/WindTurbine/Cat1"}


def test_class_counts_add_up(client):
    df = client.run(_wq("class_counts"))
    counts = {c.rsplit("#", 1)[-1]: int(n) for c, n in zip(df["class"], df["instances"])}
    assert counts == {"WindTurbine": 3, "TidalTurbine": 1, "Pump": 1, "Location": 1}


def test_component_links_span_both_data_graphs(client):
    df = client.run(_wq("component_links"))
    assert set(df["subject"]) == {T1, f"{PROJ}/WindTurbine/T2", f"{PROJ}/TidalTurbine/TT1"}


def test_scenarios_and_data_sources(client):
    assert list(client.run(_wq("scenarios"))["scenario"]) == [f"{PROJ}/scenario/Baseline"]
    src = client.run(_wq("data_sources"))
    counts = {s: int(n) for s, n in zip(src["source"], src["derivedCount"])}
    assert counts[f"{PROJ}/Reference/park_yaml"] == 1     # T1's record
    assert counts[f"{PROJ}/Reference/types_yaml"] == 1    # the copied-down curve


def test_catalogue_instances_pair_entry_with_derived(client):
    df = client.run(_wq("catalogue_instances"))
    assert set(df["entry"]) == {f"{PROJ}/WindTurbine/Cat1"}
    assert set(df["derivedInstance"]) == {T1, f"{PROJ}/WindTurbine/T2"}


def test_workspace_ask_preflight_hides_missing_sections():
    # No scenarios graph -> the scenarios recommendation disappears; the rest stay.
    bare = _Client(scenarios="")
    keys = [r["key"] for r in available_workspace_queries(bare)]
    assert "scenarios" not in keys
    assert "all_components" in keys and "catalogue_instances" in keys
