# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Characterization tests for the Component Explorer attribute pipeline.

``components.component_explorer`` is headed for extraction to ``backend/``;
these tests pin what it does today. The pipeline under test is pure data
transformation: ``get_component_data_unified`` shapes SPARQL SELECT rows into
binding dicts (``{'instance': {'value': ...}, 'attribute': ..., 'property':
..., 'value': ...}``), and ``process_enhanced_component_data`` +
``AttributeProcessor`` turn those into the display DataFrame. The fixture here
is built in exactly that binding-dict shape, so no triplestore, network, or
Streamlit runtime is involved.

The processed frame is pinned as golden JSON; pandas NaN cells (an attribute
one instance has and another lacks) are normalized to null first, because
NaN != NaN would make the golden compare to itself as unequal.
"""
from __future__ import annotations

import math

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("streamlit")

from components import component_explorer as ce  # noqa: E402

from tests.golden import assert_json_golden  # noqa: E402

DICI = "https://digicities.info/ontology#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
QUDT = "http://qudt.org/schema/qudt/"
UNIT = "http://qudt.org/vocab/unit/"

PV1 = "https://digicities.info/proj/ws_golden/PV/PV1"
PV2 = "https://digicities.info/proj/ws_golden/PV/PV2"


def _binding(instance, attribute, prop, value):
    return {
        "instance": {"value": instance},
        "attribute": {"value": attribute},
        "property": {"value": prop},
        "value": {"value": value},
    }


def _instances():
    # PV1 carries a label; PV2 does not, so its label falls back to the URI
    # fragment — both paths pinned.
    return [
        {"instance": {"value": PV1}, "instanceLabel": {"value": "Rooftop PV One"}},
        {"instance": {"value": PV2}},
    ]


def _attributes():
    """Attribute rows in the shape get_component_attributes_comprehensive
    emits: numeric with QUDT unit, unit-based cost with currency, a curve with
    inline points, a categorical value carried as an rdf:type, and a historic
    time-series reference."""
    rows = []

    # PV1: PhysicalAttribute ratedPower = 21.5 MW.
    a = f"{PV1}/ratedPower"
    rows += [
        _binding(PV1, a, RDF_TYPE, f"{DICI}ratedPower"),
        _binding(PV1, a, RDF_TYPE, f"{DICI}PhysicalAttribute"),
        _binding(PV1, a, f"{QUDT}value", "21.5"),
        _binding(PV1, a, f"{QUDT}unit", f"{UNIT}MegaW"),
    ]

    # PV1: UnitBasedCostAttribute investmentCost = 1200 CHF/kW.
    a = f"{PV1}/investmentCost"
    rows += [
        _binding(PV1, a, RDF_TYPE, f"{DICI}investmentCost"),
        _binding(PV1, a, RDF_TYPE, f"{DICI}UnitBasedCostAttribute"),
        _binding(PV1, a, f"{QUDT}value", "1200"),
        _binding(PV1, a, f"{QUDT}unit", f"{UNIT}KiloW"),
        _binding(PV1, a, f"{DICI}currency", "http://qudt.org/vocab/currency/CHF"),
    ]

    # PV1: CurveAttribute powerCurve, semicolon-separated authoring format.
    a = f"{PV1}/powerCurve"
    rows += [
        _binding(PV1, a, RDF_TYPE, f"{DICI}powerCurve"),
        _binding(PV1, a, RDF_TYPE, f"{DICI}CurveAttribute"),
        _binding(PV1, a, f"{DICI}hasDataPoints", "[(0, 0); (5, 120.5); (10, 250)]"),
        # The Excel ingestion writes IRIs and string labels; labels win.
        _binding(PV1, a, f"{DICI}xUnit", f"{UNIT}M-PER-SEC"),
        _binding(PV1, a, f"{DICI}xUnitLabel", "m/s"),
        _binding(PV1, a, f"{DICI}yUnit", f"{UNIT}KiloW"),
        _binding(PV1, a, f"{DICI}yUnitLabel", "kW"),
    ]

    # PV2: CategoricalAttribute MountingType = Rooftop. The value is an
    # rdf:type; structural types, the attribute's own class, and non-dici
    # types (rdfs:Resource, once inference materializes) must all be ignored.
    a = f"{PV2}/MountingType"
    rows += [
        _binding(PV2, a, RDF_TYPE, f"{DICI}MountingType"),
        _binding(PV2, a, RDF_TYPE, f"{DICI}CategoricalAttribute"),
        _binding(PV2, a, RDF_TYPE, f"{DICI}Rooftop"),
        _binding(PV2, a, RDF_TYPE, "http://www.w3.org/2000/01/rdf-schema#Resource"),
    ]

    # PV2: DynamicAttribute generation with a historic time-series reference.
    a = f"{PV2}/generation"
    rows += [
        _binding(PV2, a, RDF_TYPE, f"{DICI}generation"),
        _binding(PV2, a, RDF_TYPE, f"{DICI}DynamicAttribute"),
        _binding(PV2, a, f"{DICI}hasHistoricTimeSeriesReference",
                 "resources/pv_generation.csv"),
        _binding(PV2, a, f"{QUDT}unit", f"{UNIT}KiloW"),
    ]

    return rows


def _scrub(obj):
    """NaN -> None, tuples -> lists, so the structure is golden-comparable."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    return obj


def test_processed_component_frame_golden():
    """The full pipeline output for the fixture, pinned as golden JSON: one
    record per instance with the human-readable attribute summaries, plus the
    hidden _curve__ column carrying the parsed points and axis units."""
    df = ce.process_enhanced_component_data(_instances(), _attributes())
    records = _scrub(df.to_dict(orient="records"))
    assert_json_golden(records, "component_explorer_processed.json")


def test_empty_instances_give_empty_frame():
    assert ce.process_enhanced_component_data([], _attributes()).empty


def test_curve_meta_rides_in_hidden_column():
    df = ce.process_enhanced_component_data(_instances(), _attributes())
    col = f"{ce.CURVE_META_PREFIX}powerCurve"
    assert col in df.columns
    meta = df.loc[df["URI"] == PV1, col].iloc[0]
    assert meta["points"] == [(0.0, 0.0), (5.0, 120.5), (10.0, 250.0)]
    assert meta["x_unit"] == "m/s"
    assert meta["y_unit"] == "kW"
    assert meta["reference"] is None


@pytest.mark.parametrize("uri, expected", [
    # Full QUDT URI -> display symbol.
    (f"{UNIT}MegaW", "MW"),
    (f"{UNIT}KiloW", "kW"),
    # ONE is mapped to the empty string (dimensionless).
    (f"{UNIT}ONE", ""),
    # unit: CURIE resolves through the endswith scan.
    ("unit:KiloW", "kW"),
    # Custom ratio without a scheme passes through untouched.
    ("KiloGM/KiloW", "KiloGM/KiloW"),
    # Full -PER- URIs go through the mapping table; the old shortcut fired on
    # the whole URI and leaked the scheme into the display
    # ("http://qudt.org/vocab/unit/KM/HR"). Bare codes keep the slash rewrite.
    (f"{UNIT}KiloGM-PER-KiloW", "kg/kW"),
    (f"{UNIT}M-PER-SEC", "m/s"),
    ("KiloW-PER-M2", "KiloW/M2"),
    # Unknown URI falls back to the local name (with -PER- slashed), never
    # the raw URI; empty stays empty.
    (f"{UNIT}PERCENT", "%"),
    (f"{UNIT}FT-PER-SEC", "FT/SEC"),
    ("", ""),
])
def test_map_unit_uri_to_string(uri, expected):
    assert ce.map_unit_uri_to_string(uri) == expected


@pytest.mark.parametrize("uri, expected", [
    ("http://qudt.org/vocab/currency/CHF", "CHF"),
    ("cur:EUR", "EUR"),
    # Legacy spellings still readable.
    ("http://example.org/currency/EUR", "EUR"),
    ("iso4217:USD", "USD"),
    # Unknown -> URI fragment; empty stays empty.
    ("http://qudt.org/vocab/currency/GBP", "GBP"),
    ("", ""),
])
def test_map_currency_uri_to_string(uri, expected):
    assert ce.map_currency_uri_to_string(uri) == expected


@pytest.mark.parametrize("raw, expected", [
    # JSON list-of-lists (Replica Builder UI).
    ("[[0, 1], [2, 3.5]]", [(0.0, 1.0), (2.0, 3.5)]),
    # Python tuples (hand-authored / tutorial data).
    ("[(0.10, 2.5), (0.25, 3.5)]", [(0.10, 2.5), (0.25, 3.5)]),
    # Newline-separated brackets with no commas between pairs (Excel->TTL).
    ("[  0.0,  1.0]\n[  1.0,  2.0]", [(0.0, 1.0), (1.0, 2.0)]),
    # Semicolon-separated authoring format.
    ("[(0,0);(1,10)]", [(0.0, 0.0), (1.0, 10.0)]),
    # Scientific notation and signs.
    ("[[-1.5e2, +0.5]]", [(-150.0, 0.5)]),
    # One bad pair is dropped, the rest survive.
    ('[[0, 1], [2, "x"]]', [(0.0, 1.0)]),
    # Non-finite values are dropped.
    ("[[0, NaN], [1, 2]]", [(1.0, 2.0)]),
    # Nothing parseable.
    ("", []),
    ("[]", []),
    ("no points here", []),
])
def test_parse_curve_data(raw, expected):
    assert ce.parse_curve_data(raw) == expected


def test_curve_reference_detection():
    assert ce.curve_data_is_reference("resources/pv_generation.csv")
    assert not ce.curve_data_is_reference("[(0,0);(1,10)]")
    assert not ce.curve_data_is_reference("")
