# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The Digital Replica Explorer's "view component hierarchy" option.

``get_component_hierarchy_edges``/``get_component_hierarchy_chain`` must
survive a MATERIALISED closure exactly like the provisioned store's — every
class carries a reflexive ``rdfs:subClassOf`` edge to itself and a direct
edge to every transitive ancestor, not just its immediate parent (see
``tests/test_instance_inspector.py`` for the same convention). That closure
is what broke a naive "collect (child, parent) edges and walk them" approach
during development: every class in the chain ends up with several
simultaneous "parent" candidates, with no syntactic way left to tell direct
from transitive. The fixture also includes ``rdfs:Resource``/``owl:Thing`` —
a real store's RDFS-Plus materialisation surfaces those as universal
"ancestors" of everything, which must never leak into the displayed chain.

Deterministic: an in-memory rdflib dataset stands in for the triplestore.
"""
from __future__ import annotations

import pandas as pd
import pytest

rdflib = pytest.importorskip("rdflib")

from backend.graphdb.graphs import (  # noqa: E402
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
)
from backend.graphdb.queries import get_component_hierarchy_edges  # noqa: E402
from backend.explorer import get_component_hierarchy_chain  # noqa: E402

ONTOLOGY = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# Materialised closure: every class also carries a reflexive edge to itself
# and a direct edge to EVERY transitive ancestor (Component, rdfs:Resource,
# owl:Thing) — exactly as RDFS-Plus inference leaves a provisioned store.
dici_onto:Component a owl:Class ;
    rdfs:subClassOf dici_onto:Component, rdfs:Resource, owl:Thing .

dici_onto:Converter a owl:Class ;
    rdfs:subClassOf dici_onto:Converter, dici_onto:Component, rdfs:Resource, owl:Thing .

dici_onto:EnergyConverter a owl:Class ; rdfs:label "Energy Converter" ;
    rdfs:subClassOf dici_onto:EnergyConverter, dici_onto:Converter, dici_onto:Component,
                     rdfs:Resource, owl:Thing .

dici_onto:Turbine a owl:Class ;
    rdfs:subClassOf dici_onto:Turbine, dici_onto:EnergyConverter, dici_onto:Converter,
                     dici_onto:Component, rdfs:Resource, owl:Thing .

dici_onto:WindTurbine a owl:Class ; rdfs:label "Wind Turbine" ;
    rdfs:subClassOf dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:EnergyConverter,
                     dici_onto:Converter, dici_onto:Component, rdfs:Resource, owl:Thing .

# A component one level under Component only — no intermediate class at all.
dici_onto:Building a owl:Class ;
    rdfs:subClassOf dici_onto:Building, dici_onto:Component, rdfs:Resource, owl:Thing .
"""


class _Client:
    def __init__(self):
        self.ds = rdflib.Dataset()
        self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH)).parse(data=ONTOLOGY, format="turtle")
        # The graph must EXIST even without instance data: rdflib dereferences
        # an unknown FROM graph over HTTP, which a real store never does.
        g = self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH))
        g.add((rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH),
               rdflib.RDFS.comment, rdflib.Literal("no instance data needed")))

    def sparql_api_query(self, query: str, out_format: str = "df"):
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def client() -> _Client:
    return _Client()


def test_chain_is_root_first_and_ends_with_the_type(client):
    assert get_component_hierarchy_chain(client, "Wind Turbine") == [
        "Converter", "Energy Converter", "Turbine", "Wind Turbine",
    ]


def test_chain_excludes_component_and_rdfs_owl_vocabulary(client):
    # Regression pin: a materialised closure gives Building direct subClassOf
    # edges to Component, rdfs:Resource AND owl:Thing — none of the three may
    # leak into the chain. Component is excluded everywhere (every chain
    # leads there; it isn't informative), so a class one level under it has
    # nothing else to show.
    chain = get_component_hierarchy_chain(client, "Building")
    assert chain == ["Building"]
    assert "Component" not in chain
    assert not any("w3.org" in c for c in chain)


def test_chain_resolves_by_local_name_when_no_label(client):
    # Converter/EnergyConverter/Turbine carry no rdfs:label in the fixture —
    # the same local-name fallback the explorer's type list itself uses.
    assert get_component_hierarchy_chain(client, "Converter") == ["Converter"]
    assert get_component_hierarchy_chain(client, "Turbine") == [
        "Converter", "Energy Converter", "Turbine",
    ]


def test_chain_falls_back_to_the_bare_label_for_an_unknown_type(client):
    assert get_component_hierarchy_chain(client, "NoSuchType") == ["NoSuchType"]


def test_edges_depth_is_monotonic_root_first(client):
    # The fake client stringifies every binding (see _Client), same as
    # tests/test_instance_inspector.py's — cast before comparing order.
    df = get_component_hierarchy_edges(client, "Wind Turbine")
    depths = [int(d) for d in df["depth"]]
    assert depths == sorted(depths)
    assert depths == [0, 1, 2, 3]
