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


FLOWS = f"""
@prefix d: <https://digicities.info/ontology#> .
<{P}Location/H1> a d:Location .
<{P}Junction/H1_gas> a d:Junction ; d:locatedAt <{P}Location/H1> .
<{P}EnergyCarrier/gas> a d:EnergyCarrier .
<{P}Network/supply> a d:Network .
<{P}EnergyCarrierFlow/buy> a d:EnergyCarrierFlow ;
    d:hasSource <{P}Network/supply> ; d:hasDestination <{P}Junction/H1_gas> ;
    d:linksComponent <{P}EnergyCarrier/gas> .
"""


def _flow_store():
    store = _Store()
    ca = store.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH))
    ca.remove((None, None, None))
    ca.parse(data=FLOWS, format="turtle")
    return store


def test_place_links_do_not_hide_a_flows_ends_and_carrier():
    """A workspace with sites has place links; the flows' own links used to be
    read only when there were none, so the Scenario Builder never offered them."""
    found = {(lk["source_label"], lk["link_property"], lk["target_label"])
             for lk in discover_component_links(_flow_store())}
    assert {("H1_gas", "locatedAt", "H1"), ("buy", "hasSource", "supply"),
            ("buy", "hasDestination", "H1_gas"), ("buy", "linksComponent", "gas")} <= found


def test_a_flow_requirement_is_offered_once_per_pair():
    from backend.scenario_builder.link_discovery import match_links_to_requirements
    matched = match_links_to_requirements(
        discover_component_links(_flow_store()),
        ["CL.EnergyCarrierFlow.Network", "CL.EnergyCarrierFlow.Junction",
         "CL.EnergyCarrierFlow.EnergyCarrier", "CL.Junction.Location"])
    pairs = {pat: [(m["suggested_source"].rsplit("/", 1)[-1], m["suggested_target"].rsplit("/", 1)[-1],
                    m["link_property"]) for m in ms] for pat, ms in matched.items()}
    assert pairs["CL.EnergyCarrierFlow.Network"] == [("buy", "supply", "hasSource")]
    assert pairs["CL.EnergyCarrierFlow.Junction"] == [("buy", "H1_gas", "hasDestination")]
    assert pairs["CL.EnergyCarrierFlow.EnergyCarrier"] == [("buy", "gas", "linksComponent")]
    assert [p[:2] for p in pairs["CL.Junction.Location"]] == [("H1_gas", "H1")]
