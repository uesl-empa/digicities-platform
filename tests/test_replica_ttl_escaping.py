# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workbook text must never break the replica TTL.

Cell values were interpolated into Turtle unescaped: a double quote, a
backslash or a newline in a label, a path or a free-text value, a categorical
value with a space, or a row id with a space produced a file rdflib cannot
parse. The builder only printed a warning, and every loader (provisioning,
convert) then skipped the whole file — so every attribute in it went missing
downstream with no visible error.
"""
from __future__ import annotations

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from rdflib import URIRef  # noqa: E402

from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)
from backend.replica_builder.utils.ttl_attribute_helpers import (  # noqa: E402
    dici_term,
    escape_iri,
    escape_ttl_string,
)

PROJ = "https://x.org/p"
DICI = "https://digicities.info/ontology#"
QUDT = "http://qudt.org/schema/qudt/"

LABEL = 'He said "hi"\nsecond line\twith tab and a \\ backslash'
NOTE = 'quote " and backslash \\ end'
PATH = 'C:\\data\\input files\\file "1".csv'
IDENT = 'ID\\42 "x"'
# No carriage return here: an xlsx cell's CR is normalised to LF by the XML
# reader on some platforms (the workbook layer's behaviour, not the TTL
# escaping this file tests). CR escaping is checked on the helper directly.
TEXT_VALUE = 'n/a "unknown"\nsee notes\tend'
EVENT = 'sometime "soon"'
REF_DESC = 'Report "2024"\nvolume \\ 2'


def _workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    park = wb.create_sheet("Park")
    park.cell(row=1, column=1, value="id")
    park.cell(row=7, column=1, value="Park A")          # id with a space

    m = wb.create_sheet("Machine")
    cols = [
        ("id", None, None),
        ("label", "Annotation", None),
        ("Note", "Annotation", None),
        ("DataFile", "Resource", None),
        ("Code", "Identifier", None),
        ("Comment", "SimpleValue", None),
        ("Heating", "Categorical", None),
        ("Odd", "Categorical", None),
        ("Built", "Event", None),
        ("Status", "Physical", None),
        ("park", "ClassObject", "partOf"),
    ]
    for c, (name, atype, pred) in enumerate(cols, start=1):
        m.cell(row=1, column=c, value=name)
        if atype:
            m.cell(row=2, column=c, value=atype)
        if pred:
            m.cell(row=6, column=c, value=pred)
    row = ["M1", LABEL, NOTE, PATH, IDENT, TEXT_VALUE, "Electrically heated",
           'A/B <odd> "x"', EVENT, 'not a number "!"', "Park/Park A"]
    for c, v in enumerate(row, start=1):
        m.cell(row=7, column=c, value=v)

    ref = wb.create_sheet("Reference")
    ref.cell(row=1, column=1, value="id")
    ref.cell(row=1, column=2, value="description")
    ref.cell(row=7, column=1, value="ref 1")
    ref.cell(row=7, column=2, value=REF_DESC)

    wb.save(path)
    return path


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> rdflib.Graph:
    tmp = tmp_path_factory.mktemp("esc")
    xlsx = _workbook(tmp / "wb.xlsx")
    ttl = tmp / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(ttl))
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")          # the regression: this used to raise
    return g


M1 = URIRef(f"{PROJ}/Machine/M1")


def _one(g, s, p):
    (o,) = list(g.objects(s, URIRef(p)))
    return o


def test_annotation_literals_round_trip_exactly(graph):
    assert str(_one(graph, M1, "http://www.w3.org/2000/01/rdf-schema#label")) == LABEL
    assert str(_one(graph, M1, f"{PROJ}#Note")) == NOTE


def test_attribute_string_values_round_trip_exactly(graph):
    assert str(_one(graph, URIRef(f"{M1}/DataFile"), DICI + "hasDataPath")) == PATH
    assert str(_one(graph, URIRef(f"{M1}/Code"), DICI + "identifierValue")) == IDENT
    assert str(_one(graph, URIRef(f"{M1}/Comment"), DICI + "hasAttributeValue")) == TEXT_VALUE
    assert str(_one(graph, URIRef(f"{M1}/Built"), DICI + "hasTemporalValue")) == EVENT
    assert str(_one(graph, URIRef(f"{M1}/Status"), QUDT + "value")) == 'not a number "!"'


def test_reference_literals_round_trip_and_ids_are_encoded(graph):
    ref = URIRef(f"{PROJ}/Reference/ref%201")
    assert str(_one(graph, ref, "http://www.w3.org/2000/01/rdf-schema#label")) == REF_DESC


def test_categorical_values_become_valid_ontology_terms(graph):
    # Whitespace removed the way the Ontology Manager names individuals.
    assert _one(graph, URIRef(f"{M1}/Heating"), DICI + "hasCategoricalValue") \
        == URIRef(DICI + "Electricallyheated")
    odd = _one(graph, URIRef(f"{M1}/Odd"), DICI + "hasCategoricalValue")
    assert odd == URIRef(DICI + "A/B%3Codd%3E%22x%22")
    assert (URIRef(f"{M1}/Odd"), rdflib.RDF.type, odd) in graph


def test_row_id_with_space_and_link_to_it_agree(graph):
    target = URIRef(f"{PROJ}/Park/Park%20A")
    assert (target, rdflib.RDF.type, URIRef(DICI + "Park")) in graph
    assert (M1, URIRef(DICI + "partOf"), target) in graph


def test_plain_values_keep_their_usual_form():
    """Valid names are written exactly as before — no churn for normal data."""
    assert dici_term("ElectricallyHeated") == "dici_onto:ElectricallyHeated"
    assert escape_iri("https://x.org/p/Park/P1") == "https://x.org/p/Park/P1"
    assert escape_iri("a%20b") == "a%20b"                     # no double encoding
    assert escape_ttl_string("plain") == "plain"


# ── materialize: a broken replica file is skipped LOUDLY ─────────────────────
def test_materialize_reports_unparsable_replica_files(tmp_path, capsys):
    from backend.api_submission.materialize import materialize_against_workspace
    from backend.workspace.storage import WorkspaceStorage

    storage = WorkspaceStorage.local(str(tmp_path))
    storage.write_text("ingestion/output/good.ttl", f"""
@prefix dici_onto: <{DICI}> .
@prefix qudt: <{QUDT}> .
<{PROJ}/Machine/M1> a dici_onto:Machine ;
    dici_onto:hasAttribute <{PROJ}/Machine/M1/RatedPower> .
<{PROJ}/Machine/M1/RatedPower> a dici_onto:RatedPower ; qudt:value 5.0 .
""")
    storage.write_text("ingestion/output/broken.ttl",
                       f'<{PROJ}/Machine/M2> <{DICI}label> "unterminated .\n')
    scenario = f"""
@prefix dici_onto: <{DICI}> .
<urn:s> a dici_onto:Scenario .
<urn:cl> a dici_onto:ComponentLink ; dici_onto:usedInScenario <urn:s> ;
    dici_onto:hasInputEntity <urn:s> ; dici_onto:linksInputyEntityTo <{PROJ}/Machine/M1> .
<{PROJ}/Machine/M1> dici_onto:usedInScenario <urn:s> .
"""
    skipped: list = []
    merged = materialize_against_workspace(storage, scenario, skipped=skipped)

    assert [s["file"] for s in skipped] == ["ingestion/output/broken.ttl"]
    assert "broken.ttl" in capsys.readouterr().out
    assert "RatedPower" in merged                         # the good file still merged

    # Backward compatible: no list passed, same text back.
    assert materialize_against_workspace(storage, scenario) == merged


def test_carriage_return_is_escaped_and_parses_back():
    import rdflib

    from backend.replica_builder.utils.ttl_attribute_helpers import escape_ttl_string
    raw = 'a\r\nb\rc "q"'
    g = rdflib.Graph().parse(data=f'<urn:s> <urn:p> "{escape_ttl_string(raw)}" .',
                             format="turtle")
    assert str(next(g.objects())) == raw
