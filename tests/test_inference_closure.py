# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Hygiene of the write-time inference closure.

The OWL-RL closure is logically correct but noisy: the eq-ref rule asserts
``x owl:sameAs x`` for every term, and owl:Restriction superclasses type every
instance with anonymous (blank-node) classes — which then DANGLE, because
provisioning splits the closure across named graphs and blank-node identity
does not survive the split. Both showed up verbatim in the Query Manager as
``b0…b4`` classes and sameAs self-loops on every curve attribute.

``materialize`` must keep the useful closure (subClassOf/subPropertyOf
transitivity, instance typing with named ancestors) and strip the noise.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

rdflib = pytest.importorskip("rdflib")
pytest.importorskip("owlrl")

from backend.workspace.inference import materialize  # noqa: E402

ONTO = "https://digicities.info/ontology#"

DATA = f"""
@prefix dici_onto: <{ONTO}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .

dici_onto:Component a owl:Class .
dici_onto:Turbine a owl:Class ; rdfs:subClassOf dici_onto:Component .
dici_onto:WindTurbine a owl:Class ; rdfs:subClassOf dici_onto:Turbine .

# The CurveAttribute pattern that minted the b0…b4 noise: a class with
# owl:Restriction anonymous superclasses.
dici_onto:CurveAttribute a owl:Class ;
    rdfs:subClassOf [ a owl:Restriction ;
                      owl:onProperty dici_onto:xUnit ;
                      owl:someValuesFrom qudt:Unit ] ,
                    [ a owl:Restriction ;
                      owl:onProperty dici_onto:yUnit ;
                      owl:someValuesFrom qudt:Unit ] .

<https://digicities.info/proj/t/WindTurbine/T1> a dici_onto:WindTurbine .
<https://digicities.info/proj/t/WindTurbine/T1/PowerCurve> a dici_onto:CurveAttribute .
"""


@pytest.fixture(scope="module")
def closed() -> "rdflib.Graph":
    g = rdflib.Graph()
    g.parse(data=DATA, format="turtle")
    materialize(g, profile="rdfs-plus")
    return g


def test_useful_closure_is_present(closed):
    t1 = rdflib.URIRef("https://digicities.info/proj/t/WindTurbine/T1")
    component = rdflib.URIRef(f"{ONTO}Component")
    # instance typing with named ancestors — the reason the closure exists
    assert (t1, rdflib.RDF.type, component) in closed


def test_no_reflexive_sameas_survives(closed):
    loops = [t for t in closed if t[1] == rdflib.OWL.sameAs and t[0] == t[2]]
    assert loops == []


def test_no_instance_is_typed_with_an_anonymous_class(closed):
    anon = [t for t in closed
            if t[1] == rdflib.RDF.type and isinstance(t[2], rdflib.BNode)]
    assert anon == []
    # while the restriction AXIOMS themselves (blank-node subjects) survive
    restriction = rdflib.OWL.Restriction
    assert any(t[2] == restriction for t in closed)
