# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Curves must survive the whole path: workbook -> replica TTL -> payload.

Two bugs made every curve reach payloads as an unparsed string: the workbook
parser only understood ``(x,y)`` with no spaces, no signs and no exponents (so
``(3, 0)`` or ``(0,-1.5)`` silently produced zero points), and the writer put
one ``[x, y]`` per line with no commas between them, which is not JSON, so the
converter's ``json.loads`` failed and passed the raw literal through.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from backend.api_submission.ttl_converter import convert_scenario  # noqa: E402
from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)
from backend.replica_builder.utils.ttl_attribute_helpers import (  # noqa: E402
    curve_points_literal,
    parse_curve_points,
    process_curve_data_string,
)

PROJ = "https://x.org/p"
DICI = "https://digicities.info/ontology#"

# id -> (cell value, expected points)
CURVES = {
    "M1": ("[(3,0);(4,5)]", [[3.0, 0.0], [4.0, 5.0]]),
    "M2": ("[(3, 0); (4, 5); (5, 12.5)]", [[3.0, 0.0], [4.0, 5.0], [5.0, 12.5]]),
    "M3": ("(0,-1.5);(2e3, 4.5E-1)", [[0.0, -1.5], [2000.0, 0.45]]),
    "M4": ("[[3,0],[4,5]]", [[3.0, 0.0], [4.0, 5.0]]),
    "M5": ("[(1,1)]", [[1.0, 1.0]]),
}

LEGACY_LITERAL = "[\n    [     3.0,        0.0]\n    [     4.0,       50.5]\n    ]"


# ── the parser ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value,expected", [v for v in CURVES.values()])
def test_parse_curve_points_accepts_authoring_shapes(value, expected):
    assert parse_curve_points(value) == (expected, 0)


def test_parse_curve_points_accepts_python_lists_and_tuples():
    assert parse_curve_points([[3, 0], (4, 5)]) == ([[3.0, 0.0], [4.0, 5.0]], 0)
    assert parse_curve_points("[(3, 0), (4, 5)]") == ([[3.0, 0.0], [4.0, 5.0]], 0)


def test_parse_curve_points_reads_the_legacy_comma_less_literal():
    assert parse_curve_points(LEGACY_LITERAL) == ([[3.0, 0.0], [4.0, 50.5]], 0)


def test_parse_curve_points_counts_what_it_cannot_read():
    points, dropped = parse_curve_points("[(3,0);(4,x);(5,6)]")
    assert points == [[3.0, 0.0], [5.0, 6.0]] and dropped == 1


def test_written_literal_is_json():
    pts = [[3.0, 0.0], [-1.5, 2000.0], [1e-5, 4.0]]
    assert json.loads(curve_points_literal(pts)) == pts
    assert json.loads(curve_points_literal([])) == []


def test_ui_curve_formatter_uses_the_same_parser():
    assert len(process_curve_data_string("[(3, 0); (0,-1.5)]")) == 2


# ── workbook -> TTL -> payload ───────────────────────────────────────────────
def _workbook(path: Path, rows: dict[str, str]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sh = wb.create_sheet("Machine")
    sh.cell(row=1, column=1, value="id")
    sh.cell(row=1, column=2, value="PerformanceCurve")
    sh.cell(row=2, column=2, value="Curve")
    sh.cell(row=3, column=2, value="M-PER-SEC")
    sh.cell(row=4, column=2, value="KiloW")
    for r, (mid, cell) in enumerate(rows.items(), start=7):
        sh.cell(row=r, column=1, value=mid)
        sh.cell(row=r, column=2, value=cell)
    wb.save(path)
    return path


def _scenario(ids) -> str:
    lines = [f"@prefix dici_onto: <{DICI}> .",
             f"<{PROJ}/Scenario/S1> a dici_onto:Scenario ."]
    for i, mid in enumerate(ids):
        lines.append(f"<{PROJ}/CL/{i}> a dici_onto:ComponentLink ; "
                     f"dici_onto:hasInputEntity <{PROJ}/Scenario/S1> ; "
                     f"dici_onto:linksInputyEntityTo <{PROJ}/Machine/{mid}> .")
    return "\n".join(lines) + "\n"


TEMPLATE = {"service_name": "svc",
            "scenario_data": {"machine": {"uri": "Machine.URI",
                                          "curve": "Machine.PerformanceCurve"}}}


@pytest.fixture(scope="module")
def replica_ttl(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("curves")
    xlsx = _workbook(tmp / "wb.xlsx", {k: v[0] for k, v in CURVES.items()})
    out = tmp / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(out))
    return out.read_text(encoding="utf-8")


def test_replica_curve_literals_are_valid_json(replica_ttl):
    g = rdflib.Graph()
    g.parse(data=replica_ttl, format="turtle")
    literals = {str(s): str(o) for s, _, o in
                g.triples((None, rdflib.URIRef(DICI + "hasDataPoints"), None))}
    assert len(literals) == len(CURVES)
    for mid, (_cell, expected) in CURVES.items():
        assert json.loads(literals[f"{PROJ}/Machine/{mid}/PerformanceCurve"]) == expected


def test_converter_returns_structured_curves(replica_ttl):
    payload = convert_scenario(TEMPLATE, replica_ttl + "\n" + _scenario(CURVES))
    by_uri = {m["uri"]: m["curve"] for m in payload["scenario_data"]["machine"]}
    for mid, (_cell, expected) in CURVES.items():
        curve = by_uri[f"{PROJ}/Machine/{mid}"]
        assert curve["points"] == expected
        assert curve["x_unit"] == "M-PER-SEC" and curve["y_unit"] == "KiloW"


def test_unparseable_points_are_reported_not_silently_dropped(tmp_path, capsys):
    xlsx = _workbook(tmp_path / "wb.xlsx", {"M1": "[(3,0);(4,oops);(5,6)]"})
    out = tmp_path / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(out))
    printed = capsys.readouterr().out
    assert "Machine.M1.PerformanceCurve" in printed and "1 point(s)" in printed
    g = rdflib.Graph()
    g.parse(out, format="turtle")
    (lit,) = [str(o) for o in g.objects(None, rdflib.URIRef(DICI + "hasDataPoints"))]
    assert json.loads(lit) == [[3.0, 0.0], [5.0, 6.0]]


def test_legacy_comma_less_literal_converts_to_structured_points():
    """Replicas written before the fix hold the comma-less literal; they must
    convert to structured curves without being rebuilt."""
    replica = f"""
    @prefix dici_onto: <{DICI}> .
    <{PROJ}/Machine/M1> a dici_onto:Machine ;
        dici_onto:hasMachinePerformanceCurveAttribute <{PROJ}/Machine/M1/PerformanceCurve> .
    <{PROJ}/Machine/M1/PerformanceCurve> a dici_onto:PerformanceCurve ;
        a dici_onto:CurveAttribute ;
        dici_onto:hasDataPoints \"\"\"{LEGACY_LITERAL}\"\"\" .
    """
    payload = convert_scenario(TEMPLATE, replica + _scenario(["M1"]))
    (machine,) = payload["scenario_data"]["machine"]
    assert machine["curve"] == {"points": [[3.0, 0.0], [4.0, 50.5]]}


def test_file_reference_curve_passes_through_as_string():
    replica = f"""
    @prefix dici_onto: <{DICI}> .
    <{PROJ}/Machine/M1> a dici_onto:Machine ;
        dici_onto:hasMachinePerformanceCurveAttribute <{PROJ}/Machine/M1/PerformanceCurve> .
    <{PROJ}/Machine/M1/PerformanceCurve> a dici_onto:PerformanceCurve ;
        a dici_onto:CurveAttribute ;
        dici_onto:hasDataPoints "resources/curve.csv" .
    """
    payload = convert_scenario(TEMPLATE, replica + _scenario(["M1"]))
    assert payload["scenario_data"]["machine"][0]["curve"] == "resources/curve.csv"
