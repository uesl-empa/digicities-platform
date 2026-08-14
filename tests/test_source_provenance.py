# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Regression guards for instance provenance in the Digital Replica Explorer.

A replica can record where each instance came from: the record as a whole
(``dici_onto:hasSource``) and, where it differs, an individual value (the
``<attr>_datasource`` column, which has emitted ``prov:wasDerivedFrom`` since long
before ``hasSource`` existed). The Explorer reads BOTH by matching the
``prov:wasDerivedFrom`` superproperty, so it works for a hand-authored workbook
citing its Reference sheet as well as for an onboarded folder.

What must hold, and is easy to break:

* both granularities come back, tagged by scope;
* ``derivedFromCatalogue`` is ALSO a wasDerivedFrom subproperty but points at
  another component — it must not show up as a data source;
* a replica with no provenance is untouched, so existing workspaces look the same;
* an unbound OPTIONAL (NaN, which is truthy) never reaches the UI as "nan".

Deterministic: an in-memory rdflib dataset stands in for the triplestore, no
network and no Streamlit rendering.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "streamlit"))

rdflib = pytest.importorskip("rdflib")

from backend.graphdb.graphs import (  # noqa: E402
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
)
from backend.graphdb.queries import get_component_sources  # noqa: E402

PROJ = "https://digicities.info/proj/t"

ONTOLOGY = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

dici_onto:WindTurbine a owl:Class ; rdfs:label "Wind Turbine" .
dici_onto:PowerCurve a owl:Class ; rdfs:label "Power Curve" .
dici_onto:hasPowerCurveAttribute a owl:ObjectProperty ;
    rdfs:subPropertyOf dici_onto:hasAttribute .

dici_onto:hasSource a owl:ObjectProperty ;
    rdfs:subPropertyOf prov:wasDerivedFrom ;
    rdfs:range dici_onto:Reference .

# Also a wasDerivedFrom subproperty, but it points at a COMPONENT, not a citation.
dici_onto:derivedFromCatalogue a owl:ObjectProperty ;
    rdfs:subPropertyOf prov:wasDerivedFrom .
"""

REPLICA = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix schema: <https://schema.org/> .

<{PROJ}/Reference/park_yaml> a dici_onto:Reference ;
    rdfs:label "park_alkmaar.yaml" ;
    dici_onto:hasReferenceType dici_onto:OnboardedFile ;
    schema:url "default-configs/park_alkmaar.yaml"^^<http://www.w3.org/2001/XMLSchema#anyURI> ;
    dcterms:dateAccessed "2026-08-13"^^<http://www.w3.org/2001/XMLSchema#date> .

# Deliberately bare: no type, no url, no date — the unbound-OPTIONAL case.
<{PROJ}/Reference/types_yaml> a dici_onto:Reference .

<{PROJ}/WindTurbine/T1> a dici_onto:WindTurbine ;
    rdfs:label "Turbine 1" ;
    dici_onto:hasSource <{PROJ}/Reference/park_yaml> ;
    dici_onto:derivedFromCatalogue <{PROJ}/WindTurbine/CatalogueEntry> ;
    dici_onto:hasPowerCurveAttribute <{PROJ}/WindTurbine/T1/PowerCurve> .

<{PROJ}/WindTurbine/T1/PowerCurve> a dici_onto:PowerCurve ;
    prov:wasDerivedFrom <{PROJ}/Reference/types_yaml> .

# No provenance at all.
<{PROJ}/WindTurbine/T2> a dici_onto:WindTurbine ; rdfs:label "Turbine 2" .
"""


class _Client:
    """Minimal stand-in for the triplestore client: same query contract."""

    def __init__(self, replica: str = REPLICA, ontology: str = ONTOLOGY):
        self.ds = rdflib.Dataset()
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(
            data=replica, format="turtle")
        self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH)).parse(data=ontology, format="turtle")

    def sparql_api_query(self, query: str, out_format: str = "df") -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame(
            [[None if v is None else str(v) for v in row] for row in res],
            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def sources() -> pd.DataFrame:
    return get_component_sources(_Client(), "Wind Turbine")


def test_record_level_source_is_found(sources):
    inst = sources[sources.scope == "instance"]
    assert len(inst) == 1
    row = inst.iloc[0]
    assert row["instance"].endswith("/T1")
    assert row["sourceLabel"] == "park_alkmaar.yaml"
    assert row["sourceType"] == "OnboardedFile"       # local name, not the full IRI
    assert row["sourceUrl"] == "default-configs/park_alkmaar.yaml"
    assert row["sourceDate"] == "2026-08-13"


def test_value_level_source_is_found_and_names_its_attribute(sources):
    attr = sources[sources.scope == "attribute"]
    assert len(attr) == 1
    assert attr.iloc[0]["attributeName"] == "PowerCurve"
    assert attr.iloc[0]["source"].endswith("/Reference/types_yaml")


def test_catalogue_derivation_is_not_reported_as_a_source(sources):
    # derivedFromCatalogue is a wasDerivedFrom subproperty pointing at a component.
    # It belongs to the model, not to "where did this data come from".
    assert not any("CatalogueEntry" in str(v) for v in sources["source"])


def test_instance_without_provenance_is_absent(sources):
    assert not any(str(i).endswith("/T2") for i in sources["instance"])


# ── the Explorer's shaping of that query ─────────────────────────────────────
def test_explorer_shapes_sources_and_hides_them_until_asked():
    from components.component_explorer import (
        SOURCE_COLUMN, SOURCE_META_COLUMN, attach_sources, get_component_sources
        as explorer_sources, get_visible_columns, summarize_sources)

    src = explorer_sources(_Client(), "Wind Turbine")
    t1 = f"{PROJ}/WindTurbine/T1"
    assert [r["label"] for r in src[t1]["instance"]] == ["park_alkmaar.yaml"]
    assert list(src[t1]["attributes"]) == ["PowerCurve"]

    # A Reference with no label falls back to its id rather than showing blank.
    assert src[t1]["attributes"]["PowerCurve"][0]["label"] == "types_yaml"
    # An unbound OPTIONAL is NaN, which is truthy — it must never reach the UI.
    assert src[t1]["attributes"]["PowerCurve"][0]["type"] == ""

    df = pd.DataFrame([{"URI": t1, "instance_id": "T1"},
                       {"URI": f"{PROJ}/WindTurbine/T2", "instance_id": "T2"}])
    out = attach_sources(df, src)
    # The extra file is NAMED — a bare "+1" told the reader nothing. The
    # derivedFromCatalogue link in the table names the catalogue instance; this
    # column names the files.
    assert out.loc[0, SOURCE_COLUMN] == "park_alkmaar.yaml (+ types_yaml for some values)"
    # 3+ extra files fall back to a count so the cell stays readable.
    many = {"instance": [{"label": "a.yaml"}],
            "attributes": {f"Attr{i}": [{"label": f"f{i}.yaml"}] for i in range(3)}}
    assert summarize_sources(many) == "a.yaml (+3 files for some values)"
    assert out.loc[1, SOURCE_COLUMN] == ""                    # no provenance, no noise
    # The metadata rides hidden, so neither the table nor the CSV export changes.
    assert SOURCE_META_COLUMN in out.columns
    assert SOURCE_META_COLUMN not in get_visible_columns(out)
    assert summarize_sources(None) == ""


def test_replica_without_any_provenance_is_untouched():
    from components.component_explorer import attach_sources
    df = pd.DataFrame([{"URI": "x", "instance_id": "T1"}])
    assert attach_sources(df, {}).equals(df)
