# SPDX-License-Identifier: Apache-2.0

"""hasLocation and locatedIn stay apart under the write-time inference closure.

Core 0.5.0 made ``locationOf`` the inverse of both ``hasLocation`` and
``locatedIn``, so a turbine linked to its park with ``hasLocation`` also came
out ``locatedIn`` the park after inference: the user's choice between the two
predicates was invisible. Since 0.6.0 ``locatedIn`` has its own inverse,
``locationContains``. Checked here against the REAL vendored core.
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
pytest.importorskip("owlrl")

from backend.ontology_kinds import DICI, core_graph  # noqa: E402
from backend.workspace.inference import materialize  # noqa: E402

PROJ = rdflib.Namespace("https://digicities.info/proj/t/")
TURBINE = PROJ["WindTurbine/Alkmaar_1"]
PARK = PROJ["WindPark/WindparkAlkmaar"]
REGION = PROJ["Region/NorthHolland"]


def _closure(*triples) -> rdflib.Graph:
    g = rdflib.Graph()
    for t in core_graph():
        g.add(t)
    g.add((TURBINE, rdflib.RDF.type, DICI.Turbine))
    g.add((PARK, rdflib.RDF.type, DICI.Location))
    g.add((REGION, rdflib.RDF.type, DICI.Location))
    for t in triples:
        g.add(t)
    materialize(g, profile="rdfs-plus")
    return g


def test_has_location_does_not_imply_located_in():
    g = _closure((TURBINE, DICI.hasLocation, PARK))
    assert (PARK, DICI.locationOf, TURBINE) in g
    assert (TURBINE, DICI.locatedIn, PARK) not in g
    assert (PARK, DICI.locationContains, TURBINE) not in g


def test_located_in_does_not_imply_has_location():
    g = _closure((PARK, DICI.locatedIn, REGION))
    assert (REGION, DICI.locationContains, PARK) in g
    assert (PARK, DICI.hasLocation, REGION) not in g
    assert (REGION, DICI.locationOf, PARK) not in g
