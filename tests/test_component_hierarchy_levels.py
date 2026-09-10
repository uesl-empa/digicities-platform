# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The explorer's "show parent classes" opt-out of the most-specific filter.

Provisioning materialises the RDFS closure, so every instance is typed with
its whole ancestor chain. ``MOST_SPECIFIC_TYPE`` (added in 218d153) hides all
but the leaf class, which is the right default — the same turbine listed under
Converter, Energy Converter, Turbine AND Wind Turbine reads as duplicates.
But it also removed the only way to SEE the modelled hierarchy from the
explorer, so both queries now take ``most_specific_only=False`` to restore the
pre-218d153 listing on demand.

The pair matters: the type list is useless if picking an ancestor level then
shows an empty table, so the instance query has to honour the same flag.

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
from backend.graphdb.queries import (  # noqa: E402
    get_component_instances,
    get_component_types_with_instances,
)

PROJ = "https://digicities.info/proj/t"

# Materialised closure, exactly as a provisioned store holds it: reflexive
# edges plus a direct edge to every transitive ancestor. Every class carries
# an rdfs:label, as the real core ontology does — the instance query resolves
# a type by label, so a label-less class would list but never open.
ONTOLOGY = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

dici_onto:Component a owl:Class ; rdfs:label "Component" ;
    rdfs:subClassOf dici_onto:Component .
dici_onto:Converter a owl:Class ; rdfs:label "Converter" ;
    rdfs:subClassOf dici_onto:Converter, dici_onto:Component .
dici_onto:Turbine a owl:Class ; rdfs:label "Turbine" ;
    rdfs:subClassOf dici_onto:Turbine, dici_onto:Converter, dici_onto:Component .
dici_onto:WindTurbine a owl:Class ; rdfs:label "Wind Turbine" ;
    rdfs:subClassOf dici_onto:WindTurbine, dici_onto:Turbine, dici_onto:Converter,
                     dici_onto:Component .
dici_onto:Location a owl:Class ; rdfs:label "Location" ;
    rdfs:subClassOf dici_onto:Location, dici_onto:Component .
"""

REPLICA = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<{PROJ}/WindTurbine/T1> a dici_onto:WindTurbine, dici_onto:Turbine,
    dici_onto:Converter, dici_onto:Component ; rdfs:label "Turbine 1" .
<{PROJ}/WindTurbine/T2> a dici_onto:WindTurbine, dici_onto:Turbine,
    dici_onto:Converter, dici_onto:Component ; rdfs:label "Turbine 2" .
<{PROJ}/Location/Site1> a dici_onto:Location, dici_onto:Component ;
    rdfs:label "Site 1" .
"""


class _Client:
    def __init__(self):
        self.ds = rdflib.Dataset()
        self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH)).parse(data=ONTOLOGY, format="turtle")
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(
            data=REPLICA, format="turtle")

    def sparql_api_query(self, query: str, out_format: str = "df"):
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def client() -> _Client:
    return _Client()


def _counts(df) -> dict[str, int]:
    return {str(r.componentName): int(r.instanceCount) for r in df.itertuples()}


def test_default_lists_leaf_classes_only(client):
    # James's 218d153 behaviour, unchanged: the turbines answer as Wind
    # Turbine and nothing else.
    counts = _counts(get_component_types_with_instances(client))
    assert counts == {"Wind Turbine": 2, "Location": 1}


def test_opt_out_lists_every_ancestor_level(client):
    counts = _counts(get_component_types_with_instances(client, most_specific_only=False))
    # Same two turbines counted at each level they belong to — overlapping by
    # design, which is the point of the view.
    assert counts == {
        "Converter": 2, "Turbine": 2, "Wind Turbine": 2, "Location": 1,
    }
    # Core Component stays out of the list either way.
    assert "Component" not in counts


def test_ancestor_pick_returns_its_descendants_instances(client):
    # Without the flag an ancestor level is a dead end — which is exactly why
    # the toggle has to reach this query too, not just the type list.
    assert get_component_instances(client, "Turbine").empty
    rows = get_component_instances(client, "Turbine", most_specific_only=False)
    assert sorted(rows["instance"]) == [
        f"{PROJ}/WindTurbine/T1", f"{PROJ}/WindTurbine/T2",
    ]


def test_leaf_pick_is_unaffected_by_the_flag(client):
    both = [get_component_instances(client, "Wind Turbine", most_specific_only=m)
            for m in (True, False)]
    assert sorted(both[0]["instance"]) == sorted(both[1]["instance"])
    assert len(both[0]) == 2
