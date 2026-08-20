# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The replica must contain only the instances the workbook defines.

A ClassObject cell is written as ``Sheet/instanceId`` and, in default URI mode, was
turned into ``<project_uri/Sheet/instanceId>`` with no check that the target exists.
A typo therefore emitted a link to a URI no row defines. That looks harmless in the
TTL — until the closure is materialized: the ontology gives these predicates an
``rdfs:range``, RDFS rule rdfs3 types the dangling URI, and the replica gains an
"instance" that is in no spreadsheet row, has no attributes and no source, yet is
counted by every instance query. One real onboarding produced 7 turbine types for 3
catalogue entries that way, the extra 4 being nothing but broken links.

So an unresolvable link is dropped and reported. The rule is deliberately narrow —
these guards exist to stop it quietly widening into "drops links people rely on".
"""
from __future__ import annotations

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)

PROJ = "https://x.org/p"


def _workbook(path: Path, *, seven_row: bool = False):
    """Two sheets plus a Reference sheet, exercising every reference shape."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    park = wb.create_sheet("WindPark")
    for c, name in enumerate(["id", "label"], start=1):
        park.cell(row=1, column=c, value=name)
    park.cell(row=2, column=2, value="Annotation")
    if seven_row:
        park.cell(row=7, column=1, value="LinkedClassObjectType")
    start = 8 if seven_row else 7
    park.cell(row=start, column=1, value="ParkA")
    park.cell(row=start, column=2, value="Park A")

    turb = wb.create_sheet("WindTurbine")
    cols = [
        ("id", None, None, None),
        ("good", "ClassObject", "partOf", None),              # -> WindPark/ParkA
        ("typo", "ClassObject", "partOf", None),              # sheet exists, row doesn't
        ("bare", "ClassObject", "partOf", None),              # no "/" at all
        ("cited", "ClassObject", "hasSource", None),          # -> Reference/ref1
        ("elsewhere", "ClassObject", "partOf", None),         # a sheet we don't have
        ("external", "ClassObject", "sameAs", "https://vocab.example.org/"),
    ]
    for c, (name, atype, pred, linked) in enumerate(cols, start=1):
        turb.cell(row=1, column=c, value=name)
        turb.cell(row=2, column=c, value=atype)
        turb.cell(row=6, column=c, value=pred)
        if seven_row and linked:
            turb.cell(row=7, column=c, value=linked)
    if seven_row:
        turb.cell(row=7, column=1, value="LinkedClassObjectType")
    turb.cell(row=start, column=1, value="T1")
    turb.cell(row=start, column=2, value="WindPark/ParkA")
    turb.cell(row=start, column=3, value="WindPark/NOPE")
    turb.cell(row=start, column=4, value="WindPark_ParkA")
    turb.cell(row=start, column=5, value="Reference/ref1")
    turb.cell(row=start, column=6, value="SomeOtherSheet/X")
    turb.cell(row=start, column=7, value="ExternalThing")

    ref = wb.create_sheet("Reference")
    for c, name in enumerate(["id", "description"], start=1):
        ref.cell(row=1, column=c, value=name)
    if seven_row:
        ref.cell(row=7, column=1, value="LinkedClassObjectType")
    ref.cell(row=start, column=1, value="ref1")
    ref.cell(row=start, column=2, value="A cited source")

    wb.save(path)
    return path


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> rdflib.Graph:
    tmp = tmp_path_factory.mktemp("links")
    xlsx = _workbook(tmp / "wb.xlsx", seven_row=True)
    ttl = tmp / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(ttl))
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    return g


def _objects(graph: rdflib.Graph) -> set[str]:
    subject = rdflib.URIRef(f"{PROJ}/WindTurbine/T1")
    return {str(o) for _, _, o in graph.triples((subject, None, None))}


def test_a_valid_cross_sheet_link_is_kept(graph):
    assert f"{PROJ}/WindPark/ParkA" in _objects(graph)


def test_a_link_to_a_row_that_does_not_exist_is_dropped(graph):
    assert f"{PROJ}/WindPark/NOPE" not in _objects(graph)


def test_a_cell_that_cannot_address_an_instance_is_dropped(graph):
    # No "/" — this is the shape that produced the phantom turbine types.
    assert not any("WindPark_ParkA" in o for o in _objects(graph))


def test_a_citation_to_the_reference_sheet_is_kept(graph):
    assert f"{PROJ}/Reference/ref1" in _objects(graph)


def test_a_reference_into_a_sheet_this_workbook_lacks_is_left_alone(graph):
    # Not ours to judge: the target may be loaded into the project separately.
    assert f"{PROJ}/SomeOtherSheet/X" in _objects(graph)


def test_an_explicit_external_prefix_is_untouched(graph):
    # LinkedClassObjectType exists precisely to point outside the workbook.
    assert "https://vocab.example.org/ExternalThing" in _objects(graph)


def test_no_phantom_instance_survives_the_closure(tmp_path):
    """The end-to-end property: after materializing the closure, every instance of a
    class is one the workbook defines."""
    from backend.workspace.inference import materialize

    xlsx = _workbook(tmp_path / "wb.xlsx")
    ttl = tmp_path / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(ttl))

    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    g.parse(data="""
        @prefix dici_onto: <https://digicities.info/ontology#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        dici_onto:WindPark a owl:Class .
        dici_onto:partOf a owl:ObjectProperty ; rdfs:range dici_onto:WindPark .
    """, format="turtle")
    materialize(g)

    parks = {str(r[0]) for r in g.query(
        "PREFIX d: <https://digicities.info/ontology#> SELECT ?i WHERE { ?i a d:WindPark }")}
    # ParkA is the only WindPark row in the workbook. SomeOtherSheet/X is typed too —
    # it is a deliberate out-of-workbook reference, not a typo — but NOPE and
    # WindPark_ParkA must be nowhere.
    assert f"{PROJ}/WindPark/ParkA" in parks
    assert f"{PROJ}/WindPark/NOPE" not in parks
    assert not any("WindPark_ParkA" in p for p in parks)
