# SPDX-License-Identifier: Apache-2.0

"""Where a component is, asked of the ontology's place predicates, not one name.

Core v0.6.0 gives ``locatedIn`` its own inverse, so ``hasLocation`` no longer
brings ``locatedIn`` with it. The direct place query used to ask for
``locatedIn`` only and found ``hasLocation`` links through that collapse; it now
names every core place predicate and says which one it found.
"""
from __future__ import annotations

import pandas as pd
import pytest

rdflib = pytest.importorskip("rdflib")

from backend.graphdb.graphs import (CLASSES_AND_ATTRIBUTES_GRAPH, ONTOLOGY_GRAPH,  # noqa: E402
                                    SYSTEM_DESCRIPTION_GRAPH)
from backend.graphdb.queries import system_description as sd  # noqa: E402
from backend.ontology_kinds import core_graph  # noqa: E402
from backend.scenario_builder.link_discovery import discover_component_links  # noqa: E402

D = rdflib.Namespace("https://digicities.info/ontology#")
P = "https://x.org/p/"

DATA = f"""
@prefix d: <https://digicities.info/ontology#> .
<{P}WindPark/A> a d:WindPark .
<{P}WindTurbine/T1> a d:WindTurbine ; d:hasLocation <{P}WindPark/A> .
<{P}WindTurbine/T2> a d:WindTurbine ; d:locatedIn <{P}WindPark/A> .
"""

EXTENSION = """
@prefix d: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
d:WindTurbine rdfs:subClassOf d:Turbine .
d:WindPark rdfs:subClassOf d:Location .
"""


class _Store:
    def __init__(self):
        self.ds = rdflib.Dataset()
        onto = self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH))
        onto += core_graph()
        onto.parse(data=EXTENSION, format="turtle")
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(data=DATA, format="turtle")
        self.ds.graph(rdflib.URIRef(SYSTEM_DESCRIPTION_GRAPH))

    def sparql_api_query(self, query: str, out_format: str = "df") -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame([[None if v is None else str(v) for v in row] for row in res],
                            columns=[str(v) for v in res.vars])


def test_the_place_query_finds_has_location_and_located_in():
    rows = sd.query_direct_located_in(_Store())
    found = {(r["source"], r["linkProperty"]) for _, r in rows.iterrows()}
    assert found == {(f"{P}WindTurbine/T1", str(D.hasLocation)),
                     (f"{P}WindTurbine/T2", str(D.locatedIn))}


def test_discovered_links_carry_the_predicate_they_were_found_by():
    links = discover_component_links(_Store())
    by_source = {lk["source_label"]: lk["link_property"] for lk in links}
    assert by_source == {"T1": "hasLocation", "T2": "locatedIn"}


def test_the_link_property_offer_is_the_cores_link_tree():
    from backend.replica_builder.model import DEFAULT_LINK_PROPERTIES
    assert {"locatedIn", "locationContains", "hasLocation", "partOf"} <= set(DEFAULT_LINK_PROPERTIES)
    assert "connectedTo" not in DEFAULT_LINK_PROPERTIES       # not a core term
