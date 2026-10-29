# SPDX-License-Identifier: Apache-2.0

"""Values a tool writes that a plain number cell does not cover reach the replica
as valid RDF.

Found 2026-10-20: infinity, a tool's "no
limit" (Calliope `.inf`), was written as `"inf"^^xsd:decimal`, which is not a
valid xsd:decimal.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from rdflib.namespace import XSD  # noqa: E402

from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)
from workbook_schema import declare_workbook  # noqa: E402

PROJ = "https://x.org/p"
QUDT_VALUE = rdflib.URIRef("http://qudt.org/schema/qudt/value")


def _workbook(path: Path, header: list, meta: dict, rows: list) -> Path:
    """One sheet `Pump`; ``meta`` maps a header row (2-6) to its cells."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sh = wb.create_sheet("Pump")
    for c, name in enumerate(["id", *header], start=1):
        sh.cell(row=1, column=c, value=name)
    for r, cells in meta.items():
        for c, v in enumerate(cells, start=2):
            sh.cell(row=r, column=c, value=v)
    for r, row in enumerate(rows, start=7):
        for c, v in enumerate(row, start=1):
            sh.cell(row=r, column=c, value=v)
    wb.save(path)
    return path


def _replica(tmp_path, header, meta, rows) -> rdflib.Graph:
    xlsx = _workbook(tmp_path / "wb.xlsx", header, meta, rows)
    out = tmp_path / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(out),
                         ontology=declare_workbook(xlsx, tmp_path / "ws"))
    g = rdflib.Graph()
    g.parse(out, format="turtle")
    return g


HAS_VALUE = rdflib.URIRef("https://digicities.info/ontology#hasAttributeValue")


def test_infinity_is_a_valid_double(tmp_path):
    # A workbook carries infinity as text: Excel has no infinite number, and
    # openpyxl writes float('inf') as an empty cell.
    g = _replica(tmp_path, ["MaxFlow", "Rating"],
                 {2: ["Physical", "SimpleValue"], 3: ["KiloW", None]},
                 [["P1", "inf", "inf"], ["P2", 40, "-inf"]])
    values = {str(s).rsplit("/", 2)[-2] + "." + str(s).rsplit("/", 1)[-1]: o
              for p in (QUDT_VALUE, HAS_VALUE) for s, _, o in g.triples((None, p, None))}
    for key in ("P1.MaxFlow", "P1.Rating", "P2.Rating"):
        lit = values[key]
        assert lit.datatype == XSD.double, (key, lit.n3())
        assert math.isinf(lit.toPython())
    assert values["P2.Rating"].toPython() < 0
    assert values["P2.MaxFlow"].datatype == XSD.decimal
    assert float(values["P2.MaxFlow"]) == 40.0


def test_infinity_reaches_the_payload_as_text_not_invalid_json(tmp_path):
    """A workbook's "inf" (no limit) reaches the payload as the text "inf":
    strict JSON has no number for it, and leaving it out told a service the
    last finite limit held (decided 2026-10-26)."""
    import json

    from backend.api_submission.ttl_converter import convert_scenario

    xlsx = _workbook(tmp_path / "wb.xlsx", ["MaxFlow"], {2: ["Physical"], 3: ["KiloW"]},
                     [["P1", "inf"], ["P2", 40]])
    out = tmp_path / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(out),
                         ontology=declare_workbook(xlsx, tmp_path / "ws"))
    dici = "https://digicities.info/ontology#"
    scenario = (f"@prefix dici_onto: <{dici}> .\n<{PROJ}/Scenario/S1> a dici_onto:Scenario .\n"
                + "".join(f"<{PROJ}/CL/{i}> a dici_onto:ComponentLink ; "
                          f"dici_onto:hasInputEntity <{PROJ}/Scenario/S1> ; "
                          f"dici_onto:linksInputyEntityTo <{PROJ}/Pump/{m}> .\n"
                          for i, m in enumerate(["P1", "P2"])))
    template = {"service_name": "svc",
                "scenario_data": {"pump": {"uri": "Pump.URI", "max": "Pump.MaxFlow"}}}
    payload = convert_scenario(template, out.read_text(encoding="utf-8") + "\n" + scenario)
    json.dumps(payload, allow_nan=False)          # strict JSON, as the API and submit use
    by_uri = {p["uri"].rsplit("/", 1)[-1]: p.get("max") for p in payload["scenario_data"]["pump"]}
    assert by_uri == {"P1": "inf", "P2": 40.0}


def test_a_price_series_keeps_its_currency(tmp_path):
    dici = rdflib.Namespace("https://digicities.info/ontology#")
    g = _replica(tmp_path, ["Tariff", "Load"],
                 {2: ["Historic", "Historic"], 3: ["KiloW-HR", "KiloW"], 5: ["GBP", None]},
                 [["P1", "resources/Pump_P1_Tariff.csv", "resources/Pump_P1_Load.csv"]])
    series = {str(s).split("/Pump/P1/")[1].split("/")[0].removesuffix("_historic"): s
              for s in g.subjects(rdflib.RDF.type, dici.TimeSeries)}
    assert set(series) == {"Tariff", "Load"}
    assert str(g.value(series["Tariff"], dici.currency)) == "http://qudt.org/vocab/currency/GBP"
    assert g.value(series["Load"], dici.currency) is None
    assert g.value(series["Tariff"], rdflib.URIRef("http://qudt.org/schema/qudt/unit")) is not None
