# SPDX-License-Identifier: Apache-2.0

"""A materialised scenario carries the scenario and the derived values its
service template asks for, never the collections' own bookkeeping.

Provisioning builds a population collection for every linked population (the
Collections view shows all of them), so the collections graph holds sets,
groups, statistics and an ``aggregatedIn`` edge on every member attribute.
None of that is part of a scenario: only a projected value the template names
(``Tree.WeightMean``) joins the scenario, on the scenario's own components.
"""
from __future__ import annotations

import rdflib
from rdflib import Dataset, Graph, Namespace, URIRef

from backend.api_submission import materialize as M
from backend.api_submission.ttl_converter import convert_scenario
from backend.graphdb.graphs import COLLECTIONS_GRAPH
from backend.graphdb.queries import graph_io
from backend.workspace.storage import WorkspaceStorage

DICI = Namespace("https://digicities.info/ontology#")
PROJ = "https://digicities.info/proj/orchard"
COL = f"{PROJ}/collections"
BOOKKEEPING = {DICI.aggregatedIn, DICI.aggregateOf, DICI.hasMember, DICI.hasGroup,
               DICI.groupComponent, DICI.hasDescriptiveStatistics}

REPLICA = f"""
@prefix dici_onto: <{DICI}> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{PROJ}/Tree/T1> a dici_onto:Tree ; rdfs:label "T1" .
<{PROJ}/Tree/T2> a dici_onto:Tree ; rdfs:label "T2" .
<{PROJ}/Apple/A1> a dici_onto:Apple ; dici_onto:partOf <{PROJ}/Tree/T1> ;
    dici_onto:hasAttribute <{PROJ}/Apple/A1/Weight> .
<{PROJ}/Apple/A1/Weight> a dici_onto:Weight, dici_onto:PhysicalAttribute ; qudt:value 150.0 .
"""

SCENARIO = f"""
@prefix dici_onto: <{DICI}> .
<urn:s> a dici_onto:Scenario .
<urn:cl1> a dici_onto:ComponentLink ; dici_onto:usedInScenario <urn:s> ;
    dici_onto:hasInputEntity <urn:s> ; dici_onto:linksInputyEntityTo <{PROJ}/Tree/T1> .
<urn:cl2> a dici_onto:ComponentLink ; dici_onto:usedInScenario <urn:s> ;
    dici_onto:hasInputEntity <{PROJ}/Tree/T1> ; dici_onto:linksInputyEntityTo <{PROJ}/Apple/A1> .
<{PROJ}/Tree/T1> dici_onto:usedInScenario <urn:s> .
<{PROJ}/Apple/A1> dici_onto:usedInScenario <urn:s> .
"""

# The collections graph as provisioning and a service template leave it: the
# Weight-per-Tree collection, membership on the apple's Weight, and two
# projected statistics per tree (only WeightMean is asked for below).
COLLECTIONS = f"""
@prefix dici_onto: <{DICI}> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<{COL}/WeightByTree> a dici_onto:GroupedSet ;
    dici_onto:hasGroup <{COL}/WeightByTree/group/T1> .
<{COL}/WeightByTree/group/T1> a dici_onto:Set ;
    dici_onto:groupComponent <{PROJ}/Tree/T1> ;
    dici_onto:hasDescriptiveStatistics <{COL}/WeightByTree/group/T1/stats> .
<{PROJ}/Apple/A1/Weight> dici_onto:aggregatedIn <{COL}/WeightByTree/group/T1> .
<{PROJ}/Tree/T1> dici_onto:hasAttribute <{PROJ}/Tree/T1/WeightMean>,
        <{PROJ}/Tree/T1/WeightStandardDeviation> ;
    dici_onto:hasTreeWeightMeanAttribute <{PROJ}/Tree/T1/WeightMean> .
<{PROJ}/Tree/T1/WeightMean> a dici_onto:WeightMean, dici_onto:AggregateAttribute,
        dici_onto:PhysicalAttribute ;
    qudt:value "150.0"^^xsd:double ;
    dici_onto:aggregateOf <{COL}/WeightByTree/group/T1> ;
    dici_onto:statisticUsed "mean" .
<{PROJ}/Tree/T1/WeightStandardDeviation> a dici_onto:WeightStandardDeviation,
        dici_onto:AggregateAttribute, dici_onto:PhysicalAttribute ;
    qudt:value "0.0"^^xsd:double .
<{PROJ}/Tree/T2> dici_onto:hasAttribute <{PROJ}/Tree/T2/WeightMean> .
<{PROJ}/Tree/T2/WeightMean> a dici_onto:WeightMean, dici_onto:AggregateAttribute ;
    qudt:value "90.0"^^xsd:double .
"""


def _store():
    ds = Dataset(default_union=False)
    ds.graph(URIRef(COLLECTIONS_GRAPH)).parse(data=COLLECTIONS, format="turtle")
    return ds


def _answer_from(ds, monkeypatch, calls):
    """construct_ttl answered by an in-memory store whose default graph is
    empty (as on Fuseki): the query must name the collections graph itself."""
    def construct_ttl(client, query, timeout=60):
        calls.append(query)
        return ds.query(query).graph.serialize(format="turtle")
    monkeypatch.setattr(graph_io, "construct_ttl", construct_ttl)


def _storage(tmp_path):
    storage = WorkspaceStorage.local(str(tmp_path))
    storage.write_text("ingestion/output/replica.ttl", REPLICA)
    return storage


def _triples(ttl):
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g


def test_a_template_without_derived_values_reads_no_collection_data(tmp_path, monkeypatch):
    calls: list = []
    _answer_from(_store(), monkeypatch, calls)
    template = {"tree": {"uri": "Tree.URI", "apples": {
        "link": "CL.Tree.Apple", "template": {"weight": "Apple.Weight"}}}}
    merged = M.materialize_against_workspace(
        _storage(tmp_path), SCENARIO, client=object(), template=template)
    g = _triples(merged)
    assert not [t for t in g if t[1] in BOOKKEEPING]
    assert (URIRef(f"{PROJ}/Apple/A1/Weight"), None, None) in g     # the scenario's own data
    assert not [s for s in g.subjects() if str(s).startswith(COL)]
    # No template: nothing is fetched at all.
    calls.clear()
    M.materialize_against_workspace(_storage(tmp_path), SCENARIO, client=object())
    assert calls == [] or not any("WeightMean" in q for q in calls)


def test_only_the_derived_value_the_template_asks_for_joins_the_scenario(tmp_path, monkeypatch):
    calls: list = []
    _answer_from(_store(), monkeypatch, calls)
    template = {"tree": {"uri": "Tree.URI", "weightMean": "Tree.WeightMean"}}
    merged = M.materialize_against_workspace(
        _storage(tmp_path), SCENARIO, client=object(), template=template)
    g = _triples(merged)
    mean = URIRef(f"{PROJ}/Tree/T1/WeightMean")
    assert (URIRef(f"{PROJ}/Tree/T1"), DICI.hasAttribute, mean) in g
    assert (mean, rdflib.URIRef("http://qudt.org/schema/qudt/value"), None) in g
    assert not [t for t in g if t[1] in BOOKKEEPING]
    assert (URIRef(f"{PROJ}/Tree/T1/WeightStandardDeviation"), None, None) not in g
    assert (URIRef(f"{PROJ}/Tree/T2/WeightMean"), None, None) not in g   # not in the scenario
    payload = convert_scenario(template, merged)
    trees = payload["tree"] if isinstance(payload["tree"], list) else [payload["tree"]]
    assert [t["weightMean"] for t in trees] == [150.0]


def test_a_failed_read_is_reported_not_hidden(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(graph_io, "construct_ttl", lambda client, query, timeout=60: None)
    skipped: list = []
    merged = M.materialize_against_workspace(
        _storage(tmp_path), SCENARIO, client=object(), skipped=skipped,
        template={"tree": {"weightMean": "Tree.WeightMean"}})
    assert [s["file"] for s in skipped] == ["collections"]
    assert "could not be read" in capsys.readouterr().out
    assert "Weight" in merged                      # the replica still merged


def test_with_derived_values_only_touches_the_scenarios_components(monkeypatch):
    calls: list = []
    _answer_from(_store(), monkeypatch, calls)
    scenario = f"""
@prefix dici_onto: <{DICI}> .
<urn:s> a dici_onto:Scenario .
<{PROJ}/Tree/T1> a dici_onto:Tree ; dici_onto:usedInScenario <urn:s> .
"""
    out = _triples(M.with_derived_values(
        scenario, object(), {"tree": {"weightMean": "Tree.WeightMean"}}))
    assert (URIRef(f"{PROJ}/Tree/T1"), DICI.hasAttribute,
            URIRef(f"{PROJ}/Tree/T1/WeightMean")) in out
    assert (URIRef(f"{PROJ}/Tree/T2/WeightMean"), None, None) not in out
    assert not [t for t in out if t[1] in BOOKKEEPING]
    # Nothing asked for: the text comes back unchanged.
    assert M.with_derived_values(scenario, object(), {"tree": {"uri": "Tree.URI"}}) == scenario
