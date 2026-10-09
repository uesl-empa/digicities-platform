# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Collections module: statistics registry + materializer triple shapes.

The registry tests are pure. The materializer tests run against an in-memory
fake client (recorded SPARQL updates + canned SELECT results), so the triple
shapes and the surgical-replace updates are pinned without a triplestore.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest
import rdflib
from rdflib import Namespace, RDF

from backend.collections import (
    BOOLEAN, CATEGORICAL, NUMERIC,
    CollectionError, MixedFamilyError, compute_stats, sniff_family,
)
from backend.collections import materializer
from backend.graphdb.graphs import COLLECTIONS_GRAPH

D = Namespace("https://digicities.info/ontology#")


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def test_numeric_stats():
    stats, bins = compute_stats(NUMERIC, ["31.5", "37.5"])
    assert stats["count"] == 2
    assert stats["mean"] == pytest.approx(34.5)
    assert stats["minValue"] == 31.5 and stats["maxValue"] == 37.5
    assert stats["sum"] == pytest.approx(69.0)
    assert stats["median"] == pytest.approx(34.5)
    assert stats["standardDeviation"] == pytest.approx(4.2426, rel=1e-3)
    assert sum(b["frequency"] for b in bins) == 2


def test_numeric_single_value_omits_stdev():
    stats, bins = compute_stats(NUMERIC, ["5.0"])
    assert "standardDeviation" not in stats      # absent, never null
    assert bins == [{"label": "5", "lower": 5.0, "upper": 5.0, "frequency": 1}]


def test_mixed_family_fails_loudly():
    with pytest.raises(MixedFamilyError):
        compute_stats(NUMERIC, ["31.5", "north"])


def test_empty_set_fails_loudly():
    with pytest.raises(CollectionError):
        compute_stats(NUMERIC, [])


def test_categorical_stats_and_frequency_bins():
    stats, bins = compute_stats(CATEGORICAL, ["a", "b", "a", "c"])
    assert stats["count"] == 4 and stats["distinctCount"] == 3
    assert stats["mode"] == ["a"]
    assert bins[0] == {"label": "a", "frequency": 2}


def test_categorical_mode_ties_all_reported():
    stats, _ = compute_stats(CATEGORICAL, ["a", "b"])
    assert stats["mode"] == ["a", "b"]


def test_boolean_family_sniff_and_stats():
    assert sniff_family(["true", "false", "true"]) == BOOLEAN
    stats, bins = compute_stats(BOOLEAN, ["true", "false", "true"])
    assert stats["count"] == 3
    assert {b["label"]: b["frequency"] for b in bins} == {"true": 2, "false": 1}


def test_sniff_numeric_vs_categorical():
    assert sniff_family(["1.5", "2"]) == NUMERIC
    assert sniff_family(["8600", "8610"]) == NUMERIC   # numeric-looking codes
    assert sniff_family(["north", "south"]) == CATEGORICAL


# ---------------------------------------------------------------------------
# materializer (fake client)
# ---------------------------------------------------------------------------

class FakeClient:
    """Records sparql_update calls; serves canned SELECT DataFrames."""

    def __init__(self, frames):
        self.frames = frames          # substring → DataFrame
        self.updates = []

    def sparql_api_query(self, query, out_format="df", **kw):
        for key, df in self.frames.items():
            if key in query:
                return df
        return pd.DataFrame()

    def sparql_update(self, statement):
        self.updates.append(statement)


def _inserted_graph(client) -> rdflib.Graph:
    """Parse the INSERT DATA payload back into a graph."""
    inserts = [u for u in client.updates if u.startswith("INSERT DATA")]
    assert len(inserts) == 1
    body = re.search(r"GRAPH <[^>]+> \{\n(.*)\n\}", inserts[0], re.S).group(1)
    g = rdflib.Graph()
    g.parse(data=body, format="nt")
    return g


def _frames_numeric():
    schema = pd.DataFrame({"base": [
        "https://digicities.info/ontology#RotorDiameter",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})
    members = pd.DataFrame({
        "attr": ["https://digicities.info/proj/ws/WindTurbine/T1/RotorDiameter",
                 "https://digicities.info/proj/ws/WindTurbine/T2/RotorDiameter"],
        "numValue": ["31.5", "37.5"],
        "simpleValue": [None, None],
        "catValue": [None, None],
        "catLabel": [None, None],
    })
    return {"rdfs:subClassOf* ?base": schema, "?comp ?edge ?attr": members}


def test_materialize_set_triples():
    client = FakeClient(_frames_numeric())
    iri = materializer.materialize_set(
        client, "ws", "https://digicities.info/ontology#RotorDiameter")

    assert iri == "https://digicities.info/proj/ws/collections/RotorDiameterSet"
    g = _inserted_graph(client)
    set_ref = rdflib.URIRef(iri)
    assert (set_ref, RDF.type, D.Set) in g
    assert (set_ref, D.ofAttributeType, D.RotorDiameter) in g
    # membership asserted from the attribute side only (aggregatedIn)
    members = list(g.subjects(D.aggregatedIn, set_ref))
    assert len(members) == 2
    assert not list(g.objects(set_ref, D.hasMember))
    # statistics node with the numeric family values
    stats = g.value(set_ref, D.hasDescriptiveStatistics)
    assert float(g.value(stats, D.mean)) == pytest.approx(34.5)
    assert int(g.value(stats, D["count"])) == 2
    # provenance
    assert g.value(set_ref, D.computedAt) is not None
    assert str(g.value(set_ref, D.computedBy)) == materializer.COMPUTED_BY
    # no dataset filter → no derivedFromDataSet
    assert g.value(set_ref, D.derivedFromDataSet) is None


def test_materialize_set_surgical_delete_targets_own_subtree_only():
    client = FakeClient(_frames_numeric())
    iri = materializer.materialize_set(
        client, "ws", "https://digicities.info/ontology#RotorDiameter")
    deletes = [u for u in client.updates if u.startswith("DELETE")]
    # aggregate-edges + aggregate-nodes + the collection's own nodes
    assert len(deletes) == 3
    for d in deletes:
        assert COLLECTIONS_GRAPH in d
        assert f"<{iri}>" in d
        assert "STRSTARTS" not in d and "STR(" not in d   # links, never IRI text


class _StoreClient:
    """Runs the materializer's SPARQL updates against an in-memory dataset."""

    def __init__(self, ds):
        self.ds = ds

    def sparql_update(self, statement):
        self.ds.update(statement)


def test_replace_collection_follows_links_not_iri_prefixes():
    """The delete finds a collection's nodes by its own structure links. A
    sibling whose IRI merely starts with the root's (RotorDiameterSet2), and a
    node under the root's IRI that the collection does not link to, survive;
    every node the collection links to goes, wherever its IRI is."""
    P = "https://digicities.info/proj/ws/collections/"
    ds = rdflib.Dataset()
    g = ds.graph(rdflib.URIRef(COLLECTIONS_GRAPH))
    root, sibling = rdflib.URIRef(P + "RotorDiameterSet"), rdflib.URIRef(P + "RotorDiameterSet2")
    group = rdflib.URIRef("https://example.org/elsewhere/group-a")   # IRI not under root
    stats, gstats = rdflib.URIRef(P + "RotorDiameterSet/stats"), rdflib.URIRef("https://example.org/s")
    dist, bin0 = rdflib.URIRef(P + "RotorDiameterSet/distribution"), rdflib.URIRef("https://example.org/b0")
    unlinked = rdflib.URIRef(P + "RotorDiameterSet/not-part-of-it")
    member = rdflib.URIRef("https://digicities.info/proj/ws/WindTurbine/T1/RotorDiameter")
    dataset = rdflib.URIRef("https://example.org/dataset")
    container = rdflib.URIRef("https://digicities.info/proj/ws/WindPark/P1")
    agg = rdflib.URIRef(str(container) + "/RotorDiameterMean")
    for t in [
        (root, RDF.type, D.GroupedSet), (root, D.hasGroup, group),
        (root, D.hasDescriptiveStatistics, stats), (stats, D.mean, rdflib.Literal(1.0)),
        (root, D.hasDistribution, dist), (dist, D.hasBin, bin0),
        (bin0, D.binLabel, rdflib.Literal("x")),
        (group, RDF.type, D.Set), (group, D.hasDescriptiveStatistics, gstats),
        (gstats, D.mean, rdflib.Literal(2.0)),
        (member, D.aggregatedIn, group), (dataset, D.hasSet, root),
        (container, D.hasAttribute, agg), (agg, D.aggregateOf, group),
        (agg, RDF.type, D.AggregateAttribute),
        (sibling, RDF.type, D.Set), (member, D.aggregatedIn, sibling),
        (unlinked, RDF.type, D.Set),
    ]:
        g.add(t)

    materializer._replace_collection(_StoreClient(ds), str(root), rdflib.Graph())

    left = set(g)
    gone = {root, group, stats, gstats, dist, bin0, agg}
    assert not [t for t in left if t[0] in gone or t[2] in gone]
    assert (sibling, RDF.type, D.Set) in left
    assert (member, D.aggregatedIn, sibling) in left
    assert (unlinked, RDF.type, D.Set) in left


def test_materialize_grouped_set():
    schema_target = pd.DataFrame({"base": [
        "https://digicities.info/ontology#FloorArea",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})
    schema_group = pd.DataFrame({"base": [
        "https://digicities.info/ontology#SiteType",
        "https://digicities.info/ontology#CategoricalAttribute",
        "https://digicities.info/ontology#Attribute"]})

    def schema_router(query):
        return schema_target if "FloorArea" in query else schema_group

    grouped = pd.DataFrame({
        "attr": ["https://p/B1/FloorArea", "https://p/B2/FloorArea"],
        "numValue": ["412.0", "185.0"],
        "simpleValue": [None, None], "catValue": [None, None], "catLabel": [None, None],
        "gNumValue": [None, None], "gSimpleValue": [None, None],
        "gCatValue": ["https://digicities.info/ontology#Urban",
                      "https://digicities.info/ontology#Rural"],
        "gCatLabel": ["Urban", "Rural"],
    })

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* ?base" in query:
                return schema_router(query)
            return grouped

    client = Router({})
    iri = materializer.materialize_grouped_set(
        client, "ws",
        "https://digicities.info/ontology#FloorArea",
        "https://digicities.info/ontology#SiteType")

    g = _inserted_graph(client)
    gset = rdflib.URIRef(iri)
    assert (gset, RDF.type, D.GroupedSet) in g
    assert (gset, D.groupedBy, D.SiteType) in g
    groups = list(g.objects(gset, D.hasGroup))
    assert len(groups) == 2
    # every group Set: key + own stats + membership
    for member_set in groups:
        key = str(g.value(member_set, D.groupKey))
        assert key in ("Urban", "Rural")
        stats = g.value(member_set, D.hasDescriptiveStatistics)
        assert int(g.value(stats, D["count"])) == 1
        assert len(list(g.subjects(D.aggregatedIn, member_set))) == 1


def test_group_by_continuous_rejected():
    schema_numeric = pd.DataFrame({"base": [
        "https://digicities.info/ontology#FloorArea",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* ?base" in query:
                return schema_numeric        # BOTH attributes numeric
            return pd.DataFrame({
                "attr": ["https://p/B1/FloorArea"], "numValue": ["412.0"],
                "simpleValue": [None], "catValue": [None], "catLabel": [None],
                "gNumValue": ["98.0"], "gSimpleValue": [None],
                "gCatValue": [None], "gCatLabel": [None],
            })

    with pytest.raises(CollectionError, match="continuous"):
        materializer.materialize_grouped_set(
            Router({}), "ws",
            "https://digicities.info/ontology#FloorArea",
            "https://digicities.info/ontology#HubHeight")


def test_materialize_component_grouped_set():
    schema_target = pd.DataFrame({"base": [
        "https://digicities.info/ontology#HubHeight",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})
    is_component = pd.DataFrame({"n": [1]})
    grouped = pd.DataFrame({
        "attr": ["https://p/T1/HubHeight", "https://p/T2/HubHeight",
                 "https://p/T3/HubHeight"],
        "numValue": ["85.0", "85.0", "98.0"],
        "simpleValue": [None] * 3, "catValue": [None] * 3, "catLabel": [None] * 3,
        "container": ["https://p/WindPark/North", "https://p/WindPark/North",
                      "https://p/WindPark/South"],
        "containerLabel": ["North Park", "North Park", "South Park"],
    })

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* dici_onto:Component" in query:
                return is_component
            if "rdfs:subClassOf* ?base" in query:
                return schema_target
            return grouped

    client = Router({})
    iri = materializer.materialize_grouped_set(          # semantic dispatch
        client, "ws",
        "https://digicities.info/ontology#HubHeight",
        "https://digicities.info/ontology#WindPark")

    assert iri.endswith("/collections/HubHeightByWindPark")
    g = _inserted_graph(client)
    gset = rdflib.URIRef(iri)
    assert (gset, RDF.type, D.GroupedSet) in g
    assert (gset, D.groupedBy, D.WindPark) in g
    groups = list(g.objects(gset, D.hasGroup))
    assert len(groups) == 2
    by_key = {str(g.value(s, D.groupKey)): s for s in groups}
    assert set(by_key) == {"North Park", "South Park"}
    # groups keyed by the container INSTANCE, recorded via groupComponent
    north = by_key["North Park"]
    assert g.value(north, D.groupComponent) == rdflib.URIRef(
        "https://p/WindPark/North")
    stats = g.value(north, D.hasDescriptiveStatistics)
    assert int(g.value(stats, D["count"])) == 2
    assert float(g.value(stats, D.mean)) == pytest.approx(85.0)
    assert len(list(g.subjects(D.aggregatedIn, north))) == 2


def test_component_grouping_projects_mean_as_attribute():
    """The projected aggregate takes the exact authored-attribute shape, so
    Component.attribute service requests (District.FloorAreaMean) resolve
    through the ordinary converter patterns."""
    schema_target = pd.DataFrame({"base": [
        "https://digicities.info/ontology#FloorArea",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})
    grouped = pd.DataFrame({
        "attr": ["https://p/B1/FloorArea", "https://p/B2/FloorArea"],
        "numValue": ["100.0", "200.0"],
        "simpleValue": [None] * 2, "catValue": [None] * 2, "catLabel": [None] * 2,
        "unit": ["http://qudt.org/vocab/unit/M2"] * 2,
        "unitLabel": ["M2"] * 2,
        "container": ["https://p/District/DNorth"] * 2,
        "containerLabel": ["North district"] * 2,
    })

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* dici_onto:Component" in query:
                return pd.DataFrame({"n": [1]})
            if "rdfs:subClassOf* ?base" in query:
                return schema_target
            return grouped

    client = Router({})
    materializer.materialize_grouped_set(
        client, "ws",
        "https://digicities.info/ontology#FloorArea",
        "https://digicities.info/ontology#District")

    g = _inserted_graph(client)
    QUDT = Namespace("http://qudt.org/schema/qudt/")
    container = rdflib.URIRef("https://p/District/DNorth")
    node = rdflib.URIRef("https://p/District/DNorth/FloorAreaMean")
    # authored-attribute shape: both edge styles + dual typing + qudt value/unit
    assert (container, D.hasAttribute, node) in g
    assert (container, D.hasDistrictFloorAreaMeanAttribute, node) in g
    assert (node, RDF.type, D.FloorAreaMean) in g
    assert (node, RDF.type, D.AggregateAttribute) in g
    assert (node, RDF.type, D.PhysicalAttribute) in g
    val = g.value(node, QUDT.value)
    assert float(val) == pytest.approx(150.0)
    # xsd:double, never xsd:decimal: decimal literals bound by DELETE templates
    # don't reliably match their stored form on Fuseki/TDB, which strands
    # undeletable orphan values on recompute/delete.
    assert val.datatype == rdflib.XSD.double, val.datatype
    assert g.value(node, QUDT.unit) == rdflib.URIRef("http://qudt.org/vocab/unit/M2")
    # provenance back to the group Set + which statistic
    agg_set = g.value(node, D.aggregateOf)
    assert agg_set is not None and (agg_set, RDF.type, D.Set) in g
    assert str(g.value(node, D.statisticUsed)) == "mean"
    # the aggregate class is declared (in the collections graph)
    assert (D.FloorAreaMean, rdflib.RDFS.subClassOf, D.AggregateAttribute) in g


def test_template_aggregates_of_one_attribute_are_projected_together():
    """A service asking for the mean AND the standard deviation (and the count)
    of one attribute per container gets all three. Ensuring them one by one
    replaced the shared collection each time, so only the last one survived
    and the others converted to null."""
    schema_target = pd.DataFrame({"base": [
        "https://digicities.info/ontology#Weight",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})
    grouped = pd.DataFrame({
        "attr": ["https://p/Apple/1/Weight", "https://p/Apple/2/Weight",
                 "https://p/Apple/3/Weight"],
        "numValue": ["100.0", "140.0", "180.0"],
        "simpleValue": [None] * 3, "catValue": [None] * 3, "catLabel": [None] * 3,
        "unit": ["http://qudt.org/vocab/unit/GM"] * 3,
        "unitLabel": ["GM"] * 3,
        "container": ["https://p/Tree/T01"] * 3,
        "containerLabel": ["T01"] * 3,
    })

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* dici_onto:Component" in query:
                return pd.DataFrame({"n": [1]})
            if "rdfs:subClassOf* ?base" in query:
                return schema_target
            return grouped

    client = Router({})
    template = {"scenario_data": {"tree": {
        "uri": "Tree.URI",
        "WeightMean": "Tree.WeightMean",
        "WeightStandardDeviation": "Tree.WeightStandardDeviation",
        "WeightCount": "Tree.WeightCount"}}}
    ensured = materializer.ensure_template_aggregates(client, "ws", template)

    assert len(ensured) == 1                       # one collection, one pass
    g = _inserted_graph(client)                    # exactly one INSERT
    QUDT = Namespace("http://qudt.org/schema/qudt/")
    tree = "https://p/Tree/T01"
    values = {s: float(g.value(rdflib.URIRef(f"{tree}/Weight{s}"), QUDT.value))
              for s in ("Mean", "StandardDeviation", "Count")}
    assert values == pytest.approx({"Mean": 140.0, "StandardDeviation": 40.0, "Count": 3})
    gm = rdflib.URIRef("http://qudt.org/vocab/unit/GM")
    assert g.value(rdflib.URIRef(f"{tree}/WeightMean"), QUDT.unit) == gm
    assert g.value(rdflib.URIRef(f"{tree}/WeightStandardDeviation"), QUDT.unit) == gm
    # a count is a number of apples, not grams
    assert g.value(rdflib.URIRef(f"{tree}/WeightCount"), QUDT.unit) is None


def _population_client(existing=()):
    """A workspace with two linked populations on `Tree`: apple Weight and
    apple Diameter. ``existing`` are collection IRIs already materialized."""
    # per (attribute type, container): how many linked components carry it
    groups = pd.DataFrame({
        "attrType": [f"{D}Diameter", f"{D}Weight", f"{D}Weight"],
        "container": ["https://p/Tree/T01", "https://p/Tree/T01", "https://p/Tree/T02"],
        "n": ["3", "3", "1"]})
    types = pd.DataFrame({"container": ["https://p/Tree/T01", "https://p/Tree/T02"],
                          "containerType": [f"{D}Tree", f"{D}Tree"]})

    def grouped(attr):
        return pd.DataFrame({
            "attr": [f"https://p/Apple/{i}/{attr}" for i in (1, 2, 3)],
            "numValue": ["60.0", "70.0", "80.0"],
            "simpleValue": [None] * 3, "catValue": [None] * 3, "catLabel": [None] * 3,
            "unit": ["http://qudt.org/vocab/unit/MilliM"] * 3, "unitLabel": ["MilliM"] * 3,
            "container": ["https://p/Tree/T01"] * 3, "containerLabel": ["T01"] * 3})

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "COUNT(DISTINCT ?owner)" in query:
                return groups
            if "VALUES ?container" in query:
                return types
            if "FILTER(?kind IN" in query:
                return pd.DataFrame({"collection": list(existing)})
            if "rdfs:subClassOf* dici_onto:Component" in query:
                return pd.DataFrame({"n": [1]})
            if "rdfs:subClassOf* ?base" in query:
                return pd.DataFrame({"base": [f"{D}PhysicalAttribute", f"{D}Attribute"]})
            return grouped("Diameter" if "#Diameter>" in query else "Weight")

    return Router({})


def test_every_linked_population_is_materialized_without_projection():
    """Collections shows the distribution of every attribute over the
    components linked to each container, whether or not a service asks for a
    statistic of it. Nothing is projected onto the container: that is what a
    service template requests."""
    client = _population_client()
    made = materializer.materialize_populations(client, "ws")
    base = materializer._collections_base("ws")
    assert made == [f"{base}/DiameterByTree", f"{base}/WeightByTree"]
    inserts = [u for u in client.updates if u.startswith("INSERT DATA")]
    assert len(inserts) == 2
    assert all("hasAttribute" not in u and "aggregateOf" not in u for u in inserts)


def test_a_container_with_one_linked_component_is_no_population():
    """One turbine per site, one location per tree: nothing to distribute."""
    from backend.collections.queries import linked_populations

    class OneEach(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "COUNT(DISTINCT ?owner)" in query:
                return pd.DataFrame({"attrType": [f"{D}Latitude"] * 2,
                                     "container": ["https://p/Tree/T01", "https://p/Tree/T02"],
                                     "n": ["1", "1"]})
            return pd.DataFrame({"container": ["https://p/Tree/T01", "https://p/Tree/T02"],
                                 "containerType": [f"{D}Tree"] * 2})
    assert linked_populations(OneEach({})).empty


def test_a_collection_a_service_made_is_not_replaced_by_its_bare_population():
    base = materializer._collections_base("ws")
    client = _population_client(existing=[f"{base}/WeightByTree"])
    made = materializer.materialize_populations(client, "ws")
    assert made == [f"{base}/DiameterByTree"]
    assert not any("WeightByTree" in u for u in client.updates)


def test_population_discovery_failing_never_raises():
    class Broken(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            raise RuntimeError("triplestore down")
    assert materializer.materialize_populations(Broken({}), "ws") == []


def test_provisioning_materializes_populations_once_per_replica_version(tmp_path, monkeypatch):
    """On the first provisioning of a replica version the linked populations are
    materialized and the version is stamped; reopening the same version does
    not rebuild them (a population the user deleted stays deleted)."""
    from backend.workspace import WorkspaceContext, graphdb_provisioning as gp
    from backend.workspace.storage import WorkspaceStorage

    marks: dict = {}
    runs: list = []

    class _Backend:
        def dataset_exists(self, repo):
            return True

    monkeypatch.setattr(gp, "get_backend", lambda: _Backend())
    monkeypatch.setattr(gp, "_publish_local_working_copy", lambda ctx: None)
    monkeypatch.setattr(gp, "clear_default_graph", lambda repo: True)
    monkeypatch.setattr(gp, "upload_ttl_to_graph", lambda repo, g, ttl, replace=True: True)
    monkeypatch.setattr(gp, "clear_graph", lambda repo, g: marks.clear() or True)
    monkeypatch.setattr(gp, "_collections_fingerprint",
                        lambda repo, pred=gp._COLLECTIONS_META_PRED: marks.get(pred))
    monkeypatch.setattr(gp, "_stamp_collections_fingerprint",
                        lambda repo, fp, pred=gp._COLLECTIONS_META_PRED: marks.__setitem__(pred, fp))
    monkeypatch.setattr(gp, "_materialize_populations", lambda ctx, repo, url: runs.append(repo))
    import backend.workspace.deletion as deletion
    monkeypatch.setattr(deletion, "touch_workspace_activity", lambda storage: None)

    out = tmp_path / "ingestion" / "output"
    out.mkdir(parents=True)
    (out / "replica.ttl").write_text("", encoding="utf-8")
    ctx = WorkspaceContext(id="ws", name="ws", storage=WorkspaceStorage.local(str(tmp_path)),
                           graphdb_repository="ws")
    assert gp.ensure_workspace_repo(ctx)
    assert runs == ["ws"]
    assert gp.ensure_workspace_repo(ctx)                 # same replica: not again
    assert runs == ["ws"]
    (out / "replica.ttl").write_text("# edited", encoding="utf-8")
    assert gp.ensure_workspace_repo(ctx)                 # changed: cleared, rebuilt
    assert runs == ["ws", "ws"]


def test_component_grouping_with_no_links_fails_loudly():
    schema_target = pd.DataFrame({"base": [
        "https://digicities.info/ontology#HubHeight",
        "https://digicities.info/ontology#PhysicalAttribute",
        "https://digicities.info/ontology#Attribute"]})

    class Router(FakeClient):
        def sparql_api_query(self, query, out_format="df", **kw):
            if "rdfs:subClassOf* dici_onto:Component" in query:
                return pd.DataFrame({"n": [1]})
            if "rdfs:subClassOf* ?base" in query:
                return schema_target
            return pd.DataFrame()          # no linked containers

    with pytest.raises(CollectionError, match="nothing to group"):
        materializer.materialize_component_grouped_set(
            Router({}), "ws",
            "https://digicities.info/ontology#HubHeight",
            "https://digicities.info/ontology#WindPark")


def test_unsupported_base_type_rejected():
    schema = pd.DataFrame({"base": [
        "https://digicities.info/ontology#PowerCurve",
        "https://digicities.info/ontology#CurveAttribute",
        "https://digicities.info/ontology#Attribute"]})
    client = FakeClient({"rdfs:subClassOf* ?base": schema})
    with pytest.raises(CollectionError, match="not scalar"):
        materializer.materialize_set(
            client, "ws", "https://digicities.info/ontology#PowerCurve")


def test_stats_table_keeps_plain_set_rows():
    """A plain Set's stats rows have no groupKey (NaN); pivot_table silently
    drops NaN index keys, which rendered every full-dataset table empty in
    the UI. The pivot must keep them (and normalize Fuseki's '160.0e0')."""
    st_mod = pytest.importorskip("streamlit")  # noqa: F841 — UI module import
    from components.collections_explorer import _stats_table

    stats = pd.DataFrame([
        {"set": "https://p/collections/FloorAreaSet", "groupKey": None,
         "statistic": "https://digicities.info/ontology#mean", "value": "160.0e0"},
        {"set": "https://p/collections/FloorAreaSet", "groupKey": None,
         "statistic": "https://digicities.info/ontology#count", "value": "5"},
    ])
    wide = _stats_table(stats)
    assert len(wide) == 1, "plain-Set row was dropped by the pivot"
    assert wide.iloc[0]["mean"] == "160.0" or float(wide.iloc[0]["mean"]) == 160.0
    assert int(float(wide.iloc[0]["count"])) == 5


def test_core_ontology_declares_collections_tbox():
    from backend.ontology_manager.functions import OntologyFunctions
    import os
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    g = rdflib.Graph()
    g.parse(str(repo_root / "data" / "ontology" / "dici_onto_core.ttl"),
            format="turtle")
    assert (D.Set, rdflib.RDFS.subClassOf, D.Collection) in g
    assert (D.GroupedSet, rdflib.RDFS.subClassOf, D.Collection) in g
    assert (D.aggregatedIn, rdflib.RDFS.range, D.Set) in g
    assert (D.hasMember, rdflib.OWL.inverseOf, D.aggregatedIn) in g
