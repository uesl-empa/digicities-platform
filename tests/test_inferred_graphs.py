# SPDX-License-Identifier: Apache-2.0

"""Inferred triples live in their own graph; one switch decides what a query reads.

A wind-shaped workspace on the REAL vendored core: the user links each turbine
to its park with ``hasLocation``. The closure adds ``locatedIn`` /
``locationOf`` / ``linksComponent`` / ``a Component`` / ``hasAttribute``; those
must land in the inferred companion, never next to the link the user chose,
while every reader that relied on them still finds them.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import rdflib
import pytest

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH,
    INFERRED_OF,
    ONTOLOGY_GRAPH,
    SERVICES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
    from_clause,
    graph_union,
    read_scope,
)

CORE = Path(__file__).resolve().parents[1] / "data" / "ontology" / "dici_onto_core.ttl"
D = rdflib.Namespace("https://digicities.info/ontology#")
P = "https://digicities.info/proj/ws"
CA_INF = INFERRED_OF[CLASSES_AND_ATTRIBUTES_GRAPH]

EXTENSION = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:WindTurbine a owl:Class ; rdfs:subClassOf dici_onto:Turbine .
dici_onto:WindPark a owl:Class ; rdfs:subClassOf dici_onto:Location .
dici_onto:HubHeight a owl:Class ; rdfs:subClassOf dici_onto:TurbineAttribute .
dici_onto:hasWindTurbineHubHeightAttribute a owl:ObjectProperty ;
    rdfs:subPropertyOf dici_onto:hasTurbineAttribute ;
    rdfs:domain dici_onto:WindTurbine ; rdfs:range dici_onto:HubHeight .
"""

REPLICA = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{P}/WindPark/Alkmaar> a dici_onto:WindPark .
""" + "".join(f"""
<{P}/WindTurbine/T{i}> a dici_onto:WindTurbine ;
    dici_onto:hasLocation <{P}/WindPark/Alkmaar> ;
    dici_onto:hasWindTurbineHubHeightAttribute <{P}/WindTurbine/T{i}/HubHeight> .
<{P}/WindTurbine/T{i}/HubHeight> a dici_onto:HubHeight, dici_onto:PhysicalAttribute ;
    qudt:value {80 + i}.0 .
""" for i in (1, 2))

T1, PARK = rdflib.URIRef(f"{P}/WindTurbine/T1"), rdflib.URIRef(f"{P}/WindPark/Alkmaar")


def _raw():
    schema = rdflib.Graph().parse(source=str(CORE), format="turtle")
    schema.parse(data=EXTENSION, format="turtle")
    return schema, rdflib.Graph().parse(data=REPLICA, format="turtle"), rdflib.Graph()


@pytest.fixture(scope="module")
def sections():
    from backend.workspace.graphdb_provisioning import closed_sections
    return closed_sections(*_raw())


class _Store:
    """A dataset holding the provisioned sections, queried like the platform client."""

    def __init__(self, sections):
        self.ds = rdflib.Dataset()
        for iri, graph in sections.items():
            self.ds.graph(rdflib.URIRef(iri)).__iadd__(graph)

    def sparql_api_query(self, query: str, out_format: str = "df") -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame([[None if v is None else str(v) for v in row] for row in res],
                            columns=[str(v) for v in res.vars])


def test_one_switch_decides_the_scope():
    assert read_scope(CLASSES_AND_ATTRIBUTES_GRAPH) == [CLASSES_AND_ATTRIBUTES_GRAPH, CA_INF]
    assert read_scope(CLASSES_AND_ATTRIBUTES_GRAPH, inferred=False) == [CLASSES_AND_ATTRIBUTES_GRAPH]
    # a graph the platform never closes has no companion
    assert read_scope(SYSTEM_DESCRIPTION_GRAPH) == [SYSTEM_DESCRIPTION_GRAPH]
    assert from_clause(f"<{ONTOLOGY_GRAPH}>").count("FROM <") == 2
    assert from_clause(ONTOLOGY_GRAPH, inferred=False) == f"FROM <{ONTOLOGY_GRAPH}>\n"
    assert "UNION" in graph_union(SERVICES_GRAPH, "?s ?p ?o")
    assert "UNION" not in graph_union(SERVICES_GRAPH, "?s ?p ?o", inferred=False)


def test_the_link_the_user_chose_stays_alone(sections):
    asserted, inferred = sections[CLASSES_AND_ATTRIBUTES_GRAPH], sections[CA_INF]
    assert (T1, D.hasLocation, PARK) in asserted
    for triple in ((T1, D.locatedIn, PARK), (PARK, D.locationOf, T1),
                   (T1, D.linksComponent, PARK), (T1, rdflib.RDF.type, D.Component)):
        assert triple not in asserted
        assert triple in inferred
    # what was asserted is not repeated in the companion, and no schema leaks in
    assert (T1, D.hasLocation, PARK) not in inferred
    assert (D.WindTurbine, rdflib.RDFS.subClassOf, D.Turbine) not in asserted
    assert len(sections[ONTOLOGY_GRAPH] & sections[INFERRED_OF[ONTOLOGY_GRAPH]]) == 0


def test_readers_see_inference_by_default_and_assertions_on_request(sections):
    store = _Store(sections)
    ask = (f"PREFIX d: <{D}>\nSELECT ?p {{scope}}WHERE {{{{ <{T1}> ?p <{PARK}> }}}}")
    both = set(store.sparql_api_query(ask.format(scope=from_clause(CLASSES_AND_ATTRIBUTES_GRAPH)))["p"])
    mine = set(store.sparql_api_query(ask.format(
        scope=from_clause(CLASSES_AND_ATTRIBUTES_GRAPH, inferred=False)))["p"])
    assert mine == {str(D.hasLocation)}
    assert {str(D.hasLocation), str(D.locatedIn), str(D.linksComponent)} <= both

    from backend.graphdb.queries.system_description import query_links_with_subproperty
    links = query_links_with_subproperty(store)
    t1 = links[(links["source"] == str(T1)) & (links["target"] == str(PARK))]
    assert set(t1["linkProperty"]) >= {str(D.hasLocation), str(D.locatedIn)}
    assert str(D.WindTurbine) in set(t1["sourceType"])


def test_populations_are_still_found_on_split_graphs(sections):
    from backend.collections.queries import linked_populations
    found = linked_populations(_Store(sections))
    pairs = {(r["attrType"], r["containerType"]) for _, r in found.iterrows()}
    assert (str(D.HubHeight), str(D.WindPark)) in pairs


def test_refresh_recomputes_only_the_companions(sections, monkeypatch):
    import backend.graphdb.queries.graph_io as graph_io
    import backend.workspace.graphdb_provisioning as gp

    asserted = {g: sections[g] for g in INFERRED_OF}
    monkeypatch.setattr(graph_io, "construct_named_graph",
                        lambda client, g, inferred=True: asserted[g])
    written = {}
    monkeypatch.setattr(gp, "upload_ttl_to_graph",
                        lambda repo, g, ttl, replace=True: written.__setitem__(g, ttl) or True)

    class _Client:
        repository = "ws"

    assert gp.refresh_inferred(_Client())
    assert set(written) == set(INFERRED_OF.values())
    again = rdflib.Graph().parse(data=written[CA_INF], format="turtle")
    assert (T1, D.locatedIn, PARK) in again and (T1, D.hasLocation, PARK) not in again


def test_provisioning_writes_asserted_and_inferred_apart(tmp_path, monkeypatch):
    from backend.workspace import WorkspaceContext, graphdb_provisioning as gp
    from backend.workspace.storage import WorkspaceStorage

    (tmp_path / "ontology" / "extensions").mkdir(parents=True)
    (tmp_path / "ontology" / "extensions" / "ext.ttl").write_text(EXTENSION, encoding="utf-8")
    (tmp_path / "ingestion" / "output").mkdir(parents=True)
    (tmp_path / "ingestion" / "output" / "replica.ttl").write_text(REPLICA, encoding="utf-8")

    uploads: dict = {}

    class _Backend:
        def dataset_exists(self, repo):
            return True

    monkeypatch.setattr(gp, "get_backend", lambda: _Backend())
    monkeypatch.setattr(gp, "_publish_local_working_copy", lambda ctx: None)
    monkeypatch.setattr(gp, "clear_default_graph", lambda repo: True)
    monkeypatch.setattr(gp, "upload_ttl_to_graph",
                        lambda repo, g, ttl, replace=True: uploads.__setitem__(g, ttl) or True)
    monkeypatch.setattr(gp, "_collections_fingerprint", lambda repo, *pred: None)
    monkeypatch.setattr(gp, "_stamp_collections_fingerprint", lambda repo, fp, *pred: None)
    monkeypatch.setattr(gp, "_materialize_populations", lambda ctx, repo, url: None)
    monkeypatch.setattr(gp, "clear_graph", lambda repo, g: True)
    import backend.workspace.deletion as deletion
    monkeypatch.setattr(deletion, "touch_workspace_activity", lambda storage: None)

    ctx = WorkspaceContext(id="ws", name="ws", storage=WorkspaceStorage.local(str(tmp_path)),
                           graphdb_repository="ws")
    assert gp.ensure_workspace_repo(ctx)
    # every closed section and its companion is replaced (a stale companion never survives)
    assert set(INFERRED_OF) | set(INFERRED_OF.values()) <= set(uploads)
    data = rdflib.Graph().parse(data=uploads[CLASSES_AND_ATTRIBUTES_GRAPH], format="turtle")
    inferred = rdflib.Graph().parse(data=uploads[CA_INF], format="turtle")
    assert (T1, D.hasLocation, PARK) in data and (T1, D.locatedIn, PARK) not in data
    assert (T1, D.locatedIn, PARK) in inferred
