# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Unit tests for backend.assumptions.thin_scenario_ttl — the thin-scenario serialiser.

Guards the highest-churn contract of the assumptions rework: generated scenarios
must be *thin* (override nodes with dici_onto:supersedesAttribute, anchors via
usedInScenario, ComponentLinks in the historical linksInputyEntityTo spelling)
and must materialize back into a complete scenario via
materialize_scenario_graphs, with unchanged attributes inherited from the
replica and QUDT unit codes round-tripping unmangled.
"""
from __future__ import annotations

import rdflib
from rdflib import RDF, URIRef

from backend.assumptions.thin_scenario_ttl import build_thin_scenario_ttl
from backend.graphdb.queries.scenarios import materialize_scenario_graphs

NS = "https://digicities.info/ontology#"
QUDT = "http://qudt.org/schema/qudt/"
UNIT = "http://qudt.org/vocab/unit/"
PROJ = "https://digicities.info/proj/ws1"
BASELINE = f"{PROJ}/Baseline"
BUILDING = f"{PROJ}/Building/B1"


def _dici(local: str) -> URIRef:
    return URIRef(NS + local)


def _scenario_data() -> dict:
    """A minimal assumptions-engine result: one building, one modified physical
    attribute (with a QUDT unit code), one unmodified attribute, one modified
    categorical, plus a baseline-rooted component link."""
    return {
        "scenario_name": "HP Retrofit",
        "namespace": PROJ,
        "based_on": BASELINE,
        "workspace": "ws1",
        "service": "demo_service",
        "type": "single",
        "modified_count": 1,
        "assumption": {"name": "Heat pump swap"},
        "components": [
            {
                "uri": BUILDING,
                "derived_from": BUILDING,
                "attributes": {
                    "URI": BUILDING,
                    "label": "B1",
                    "HeatingPower": {
                        "uri": f"{BUILDING}/HeatingPower_override",
                        "original_uri": f"{BUILDING}/HeatingPower",
                        "is_modified": True,
                        "attribute_type": "PhysicalAttribute",
                        "attr_class": "HeatingPower",
                        "value": 20,
                        "unit": "KiloW",
                    },
                    "GroundFloorArea": {
                        "uri": f"{BUILDING}/GroundFloorArea",
                        "is_modified": False,
                        "attribute_type": "PhysicalAttribute",
                        "value": 50,
                        "unit": "M2",
                    },
                    "HeatingSupply": {
                        "uri": f"{BUILDING}/HeatingSupply_override",
                        "original_uri": f"{BUILDING}/HeatingSupply",
                        "is_modified": True,
                        "attribute_type": "CategoricalAttribute",
                        "attr_class": "HeatingSupply",
                        "category_value": "HeatPump",
                    },
                },
            },
        ],
        "component_links": [
            {"properties": {"hasInputEntity": BASELINE,
                            "linksInputyEntityTo": BUILDING}},
        ],
    }


def _build():
    ttl = build_thin_scenario_ttl(_scenario_data())
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return ttl, g


SCN = URIRef(f"{PROJ}/HP_Retrofit")


def test_parses_and_declares_scenario():
    _ttl, g = _build()
    assert (SCN, RDF.type, _dici("Scenario")) in g
    assert (SCN, _dici("basedOn"), URIRef(BASELINE)) in g
    assert (SCN, _dici("assumptionApplied"), rdflib.Literal("Heat pump swap")) in g
    counts = list(g.objects(SCN, _dici("modifiedComponents")))
    assert counts and int(counts[0]) == 1


def test_component_anchored_once():
    _ttl, g = _build()
    anchored = {s for s in g.subjects(_dici("usedInScenario"), SCN)
                if "/ComponentLink_" not in str(s) and "_override" not in str(s)}
    assert anchored == {URIRef(BUILDING)}


def test_physical_override_shape():
    _ttl, g = _build()
    ov = URIRef(f"{BUILDING}/HeatingPower_override")
    assert (ov, RDF.type, _dici("HeatingPower")) in g
    assert (ov, RDF.type, _dici("PhysicalAttribute")) in g
    assert (ov, _dici("supersedesAttribute"), URIRef(f"{BUILDING}/HeatingPower")) in g
    assert (ov, _dici("usedInScenario"), SCN) in g
    vals = list(g.objects(ov, URIRef(QUDT + "value")))
    assert vals and float(vals[0]) == 20.0
    # The QUDT unit code must survive as the full vocab IRI (the UNITLESS /
    # display-abbreviation regression this module was built to avoid).
    assert (ov, URIRef(QUDT + "unit"), URIRef(UNIT + "KiloW")) in g
    assert (ov, _dici("hasUnitLabel"), rdflib.Literal("KiloW", datatype=rdflib.XSD.string)) in g


def test_categorical_override_typed_by_value_class():
    _ttl, g = _build()
    ov = URIRef(f"{BUILDING}/HeatingSupply_override")
    types = set(g.objects(ov, RDF.type))
    assert {_dici("HeatingSupply"), _dici("CategoricalAttribute"), _dici("HeatPump")} <= types
    assert not list(g.objects(ov, URIRef(QUDT + "value")))


def test_unmodified_attribute_not_emitted():
    ttl, _g = _build()
    assert "GroundFloorArea" not in ttl  # inherits from the replica


def test_links_use_historical_spelling_and_reanchor_baseline():
    _ttl, g = _build()
    links = list(g.subjects(RDF.type, _dici("ComponentLink")))
    assert len(links) == 1
    ln = links[0]
    # The baseline-rooted endpoint is re-pointed at THIS scenario.
    assert (ln, _dici("hasInputEntity"), SCN) in g
    # Readers match only the historical misspelling; the canonical name is
    # bridged in the ontology via rdfs:subPropertyOf.
    assert (ln, _dici("linksInputyEntityTo"), URIRef(BUILDING)) in g
    assert not list(g.objects(ln, _dici("linksInputEntityTo")))


def test_materializes_against_replica_with_inheritance():
    """Round-trip: thin scenario + replica -> complete scenario. The overridden
    attribute is swapped in; the untouched one is inherited verbatim."""
    ttl, _g = _build()
    scn_graph = rdflib.Graph()
    scn_graph.parse(data=ttl, format="turtle")

    replica = rdflib.Graph()
    replica.parse(data=f"""
        @prefix dici_onto: <{NS}> .
        @prefix qudt: <{QUDT}> .
        @prefix unit: <{UNIT}> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <{BUILDING}> a dici_onto:Building ;
            dici_onto:hasAttribute <{BUILDING}/HeatingPower>, <{BUILDING}/GroundFloorArea> .
        <{BUILDING}/HeatingPower> a dici_onto:HeatingPower, dici_onto:PhysicalAttribute ;
            qudt:value "10.0"^^xsd:decimal ; qudt:unit unit:KiloW .
        <{BUILDING}/GroundFloorArea> a dici_onto:GroundFloorArea, dici_onto:PhysicalAttribute ;
            qudt:value "50.0"^^xsd:decimal ; qudt:unit unit:M2 .
    """, format="turtle")

    out_ttl = materialize_scenario_graphs(scn_graph, replica, str(SCN))
    assert out_ttl
    out = rdflib.Graph()
    out.parse(data=out_ttl, format="turtle")

    # Component now points at the override, not the superseded original.
    attrs = set(out.objects(URIRef(BUILDING), _dici("hasAttribute")))
    assert URIRef(f"{BUILDING}/HeatingPower_override") in attrs
    assert URIRef(f"{BUILDING}/HeatingPower") not in attrs
    # Override carries the new value; the inherited attribute keeps the replica's.
    assert float(next(out.objects(URIRef(f"{BUILDING}/HeatingPower_override"),
                                  URIRef(QUDT + "value")))) == 20.0
    assert float(next(out.objects(URIRef(f"{BUILDING}/GroundFloorArea"),
                                  URIRef(QUDT + "value")))) == 50.0
    assert (URIRef(f"{BUILDING}/GroundFloorArea"),
            URIRef(QUDT + "unit"), URIRef(UNIT + "M2")) in out
