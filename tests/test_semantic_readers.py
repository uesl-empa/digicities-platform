# SPDX-License-Identifier: Apache-2.0

"""Graph readers decide what a thing is from the ontology, never from its name.

Each case below is spelt so that the old name rules would get it wrong: a link
predicate not spelt has..., an attribute predicate with no "Attribute" in it,
an undeclared typed predicate, category values that are classes or
individuals, a materialised closure that types a class as an attribute, a
Scenario subclass, and IRIs that do not follow the path convention. The
SPARQL runs for real over an in-memory dataset with the same named graphs the
platform uses, against the REAL vendored core.
"""
from __future__ import annotations

import pandas as pd
import pytest
import rdflib
from rdflib import RDF, Graph, URIRef

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH, ONTOLOGY_GRAPH, SYSTEM_DESCRIPTION_GRAPH,
)
from backend.ontology_kinds import core_graph

D = "https://digicities.info/ontology#"
P = "https://digicities.info/proj/ws"

ONTOLOGY = f"""
@prefix dici_onto: <{D}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

dici_onto:Building rdfs:subClassOf dici_onto:Component ; rdfs:label "Building" .
dici_onto:Site rdfs:subClassOf dici_onto:Component ; rdfs:label "Site" .
dici_onto:Roof rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:CategoricalAttribute .
dici_onto:Rooftop a owl:NamedIndividual, dici_onto:Roof .
dici_onto:Use rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:CategoricalAttribute .
dici_onto:Office rdfs:subClassOf dici_onto:Use .
dici_onto:Area rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:PhysicalAttribute .
dici_onto:standsOn a owl:ObjectProperty ; rdfs:subPropertyOf dici_onto:linksComponent .
dici_onto:carries a owl:ObjectProperty ; rdfs:subPropertyOf dici_onto:hasAttribute .
dici_onto:sameSiteAs a owl:ObjectProperty .
dici_onto:fromCatalogue a owl:ObjectProperty ; rdfs:subPropertyOf prov:wasDerivedFrom .
"""

REPLICA = f"""
@prefix dici_onto: <{D}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .

<{P}/b1> a dici_onto:Building ; rdfs:label "B1" ; rdfs:comment "kept" ;
    dici_onto:carries <{P}/x/area> , <{P}/x/roof> , <{P}/x/use> , <{P}/x/stated> ;
    dici_onto:hasBuildingLegacyAttribute <{P}/x/legacy> ;
    dici_onto:standsOn <{P}/s1> ;
    dici_onto:sameSiteAs <{P}/b2> ;
    dici_onto:fromCatalogue <{P}/b2> .
<{P}/b2> a dici_onto:Building ; rdfs:label "B2" .
<{P}/s1> a dici_onto:Site ; rdfs:label "S1" .
<{P}/x/area> a dici_onto:Area ; qudt:value 5 .
<{P}/x/legacy> a dici_onto:Area ; qudt:value 7 .
<{P}/x/roof> a dici_onto:Roof, dici_onto:CategoricalAttribute, dici_onto:Rooftop .
<{P}/x/use> a dici_onto:Use, dici_onto:CategoricalAttribute, dici_onto:Office .
<{P}/x/stated> a dici_onto:Use, dici_onto:CategoricalAttribute, dici_onto:Office ;
    dici_onto:hasCategoricalValue dici_onto:Office .
"""


class _Client:
    def __init__(self):
        self.ds = rdflib.Dataset()
        onto = self.ds.graph(URIRef(ONTOLOGY_GRAPH))
        for t in core_graph():
            onto.add(t)
        onto.parse(data=ONTOLOGY, format="turtle")
        self.ds.graph(URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(data=REPLICA, format="turtle")
        self.ds.graph(URIRef(SYSTEM_DESCRIPTION_GRAPH))

    def sparql_api_query(self, query: str, out_format: str = "df"):
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def client():
    return _Client()


def test_direct_properties_leave_out_attributes_links_and_provenance(client):
    from backend.graphdb.queries.components import get_all_instance_direct_properties
    df = get_all_instance_direct_properties(client)
    props = set(df[df["instance"] == f"{P}/b1"]["property"])
    # partOf-style links, typed attribute links (declared or not), provenance
    # and links to other components all go; free text stays.
    assert props == {"http://www.w3.org/2000/01/rdf-schema#label",
                     "http://www.w3.org/2000/01/rdf-schema#comment"}


def test_categorical_value_is_derived_from_the_schema(client):
    from backend.graphdb.queries.components import get_component_attributes_comprehensive
    df = get_component_attributes_comprehensive(client, "Building")
    cat = df[df["property"] == f"{D}hasCategoricalValue"]
    values = dict(zip(cat["attribute"], cat["value"]))
    assert values == {
        f"{P}/x/roof": f"{D}Rooftop",     # an individual of the attribute class
        f"{P}/x/use": f"{D}Office",       # a subclass of the attribute class
        f"{P}/x/stated": f"{D}Office",    # stated, not derived twice
    }
    assert len(cat[cat["attribute"] == f"{P}/x/stated"]) == 1


def test_a_class_typed_as_an_attribute_is_never_a_category():
    """A materialised OWL closure can type a CLASS as an instance of an
    attribute class; that class is not a category value."""
    from backend.graphdb.queries.components import get_component_attributes_comprehensive
    c = _Client()
    c.ds.graph(URIRef(ONTOLOGY_GRAPH)).parse(data=f"""
        @prefix dici_onto: <{D}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        dici_onto:Area a owl:Class, owl:NamedIndividual, dici_onto:Roof .
    """, format="turtle")
    c.ds.graph(URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).add(
        (URIRef(f"{P}/x/roof"), RDF.type, URIRef(f"{D}Area")))
    df = get_component_attributes_comprehensive(c, "Building")
    cat = df[(df["property"] == f"{D}hasCategoricalValue") & (df["attribute"] == f"{P}/x/roof")]
    assert list(cat["value"]) == [f"{D}Rooftop"]


def test_type_label_falls_back_to_local_name(client):
    from backend.graphdb.queries.components import get_component_types_with_instances
    c = _Client()
    c.ds.graph(URIRef(ONTOLOGY_GRAPH)).remove(
        (URIRef(f"{D}Site"), rdflib.RDFS.label, None))
    df = get_component_types_with_instances(c)
    assert dict(zip(df["componentName"], df["instanceCount"])) == {"Building": 2, "Site": 1}


def test_broad_link_fallback_skips_provenance_and_attributes(client):
    from backend.graphdb.queries.system_description import query_all_component_relationships
    df = query_all_component_relationships(client)
    links = set(zip(df["source"], df["linkProperty"], df["target"]))
    assert (f"{P}/b1", f"{D}standsOn", f"{P}/s1") in links
    assert (f"{P}/b1", f"{D}sameSiteAs", f"{P}/b2") in links
    assert not [l for l in links if l[1] == f"{D}fromCatalogue"]


def test_scenario_materialisation_redirects_attribute_edges_by_meaning():
    """An override replaces an attribute reached through a predicate with no
    "Attribute" in its name (declared in the extension) and through an
    undeclared predicate whose object is a core-typed attribute node."""
    from backend.graphdb.queries.scenarios import materialize_scenario_graphs
    onto = Graph().parse(data=ONTOLOGY, format="turtle")
    rep = Graph().parse(data=f"""
        @prefix dici_onto: <{D}> .
        @prefix qudt: <http://qudt.org/schema/qudt/> .
        <{P}/b1> a dici_onto:Building ; dici_onto:carries <{P}/b1/Area> ;
            dici_onto:holds <{P}/b1/Height> .
        <{P}/b1/Area> a dici_onto:Area, dici_onto:PhysicalAttribute ; qudt:value 5 .
        <{P}/b1/Height> a dici_onto:PhysicalAttribute ; qudt:value 9 .
    """, format="turtle")
    scn = Graph().parse(data=f"""
        @prefix dici_onto: <{D}> .
        @prefix qudt: <http://qudt.org/schema/qudt/> .
        <{P}/scn> a dici_onto:Scenario .
        <{P}/b1> dici_onto:usedInScenario <{P}/scn> .
        <{P}/b1/Area_new> a dici_onto:Area, dici_onto:PhysicalAttribute ; qudt:value 6 ;
            dici_onto:supersedesAttribute <{P}/b1/Area> ; dici_onto:usedInScenario <{P}/scn> .
        <{P}/b1/Height_new> a dici_onto:PhysicalAttribute ; qudt:value 10 ;
            dici_onto:supersedesAttribute <{P}/b1/Height> ; dici_onto:usedInScenario <{P}/scn> .
    """, format="turtle")
    out = Graph().parse(data=materialize_scenario_graphs(scn, rep, f"{P}/scn",
                                                         ontology_graph=onto), format="turtle")
    b1 = URIRef(f"{P}/b1")
    assert (b1, URIRef(f"{D}carries"), URIRef(f"{P}/b1/Area_new")) in out
    assert (b1, URIRef(f"{D}holds"), URIRef(f"{P}/b1/Height_new")) in out
    assert not list(out.triples((b1, None, URIRef(f"{P}/b1/Area"))))


def test_collection_kind_comes_from_the_type_iri():
    from backend.collections import CollectionKind, collection_kind
    assert collection_kind(f"{D}Set") is CollectionKind.SET
    assert collection_kind(URIRef(f"{D}GroupedSet")) is CollectionKind.GROUPED_SET
    with pytest.raises(KeyError):
        collection_kind(f"https://example.org/other#Set")


def test_explorer_categorical_reads_the_value_row_and_never_guesses():
    from backend.explorer.attributes import AttributeProcessor
    proc = AttributeProcessor()
    stated = {'properties': {'hasCategoricalValue': f"{D}Rooftop"},
              'type_uris': {f"{D}Roof", f"{D}CategoricalAttribute", f"{D}Rooftop"}}
    assert proc._process_categorical_attribute(stated, "Roof") == "Rooftop"
    # Without the value row and without the schema the attribute's own class and
    # the category look alike: no value is guessed from the node's name.
    bare = {'properties': {},
            'type_uris': {f"{D}Roof", f"{D}CategoricalAttribute", f"{D}Rooftop"}}
    assert proc._process_categorical_attribute(bare, "Roof") == "Unknown Category"


def test_converter_reads_scenario_and_category_from_the_ontology():
    """CL.Retrofit.Building resolves its source as the scenario because the
    schema says Retrofit is a Scenario; the categorical value is the node's
    hasCategoricalValue even though its IRI fits no naming convention."""
    from backend.api_submission.ttl_converter import convert_scenario
    onto = Graph().parse(data=f"""
        @prefix dici_onto: <{D}> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        dici_onto:Retrofit rdfs:subClassOf dici_onto:Scenario .
    """, format="turtle")
    ttl = f"""
        @prefix dici_onto: <{D}> .
        <{P}/scn> a dici_onto:Scenario .
        <{P}/link> a dici_onto:ComponentLink ;
            dici_onto:hasInputEntity <{P}/scn> ; dici_onto:linksInputyEntityTo <{P}/b1> .
        <{P}/b1> a dici_onto:Building ; dici_onto:hasBuildingRoofAttribute <{P}/n/42> .
        <{P}/n/42> a dici_onto:Roof, dici_onto:CategoricalAttribute, dici_onto:Rooftop ;
            dici_onto:hasCategoricalValue dici_onto:Rooftop .
    """
    template = {"service_name": "s", "scenario_data": {
        "buildings": {"link": "CL.Retrofit.Building", "template": {"roof": "Building.Roof"}}}}
    payload = convert_scenario(template, ttl, ontology_graph=onto)
    assert payload["scenario_data"]["buildings"] == [{"roof": "Rooftop"}]
