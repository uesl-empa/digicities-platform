# SPDX-License-Identifier: Apache-2.0

"""The scenario builder reads meaning from the ontology, never from spelling.

Each test feeds a name that the old string heuristics misread ("TimeSeries"
inside a key, "has...Attribute" around a predicate, a kind named by a subclass)
and checks the hierarchy of the real vendored core decides instead.
"""
from __future__ import annotations

import pandas as pd
import pytest
from rdflib import URIRef

from backend.ontology_kinds import DICI, AttributeKind
from backend.scenario_builder.semantics import (
    as_attribute_kind,
    has_time_series_data,
    is_time_series_key,
    is_time_series_reference_key,
    kind_of,
    names_scenario_class,
)


def test_attribute_kind_tags_old_and_new():
    assert as_attribute_kind("Dynamic") is AttributeKind.DYNAMIC
    assert as_attribute_kind("DynamicAttribute") is AttributeKind.DYNAMIC
    # A class under DynamicAttribute in the core: the old string compare saw
    # neither "DynamicAttribute" nor any other kind here.
    assert as_attribute_kind("ElectricityDemandProfile") is AttributeKind.DYNAMIC
    assert as_attribute_kind(AttributeKind.EVENT) is AttributeKind.EVENT
    for not_a_kind in ("system", "unknown", "annotation", "Some Label", None, 3):
        assert as_attribute_kind(not_a_kind) is None
    assert kind_of({"attribute_type": "CategoricalAttribute"}) is AttributeKind.CATEGORICAL
    assert kind_of("not a dict") is None


def test_time_series_keys_by_hierarchy():
    assert is_time_series_key("hasLiveTimeSeries")
    assert is_time_series_key("hasTimeSeries")
    assert not is_time_series_key("hasLiveTimeSeriesReference")
    assert is_time_series_reference_key("hasLiveTimeSeriesReference")
    assert is_time_series_reference_key("hasTimeSeriesReference")
    # Spelt with "TimeSeries" but no such property: the old substring test
    # took these as time series keys.
    for key in ("TimeSeriesNote", "hasLiveTimeSeries_unit", "time_series_reference"):
        assert not is_time_series_key(key)
        assert not is_time_series_reference_key(key)
    assert not has_time_series_data(["TimeSeriesNote", "unit", "value"])
    assert has_time_series_data(["unit", "hasHistoricTimeSeriesReference"])


def test_scenario_by_hierarchy():
    assert names_scenario_class("Scenario")
    assert not names_scenario_class("ScenarioPlanner")
    assert not names_scenario_class("WindTurbine")


def test_emitter_does_not_retype_on_a_spelling():
    """A nested key that merely contains "TimeSeries" no longer turns an
    attribute dynamic; a real time series reference still does."""
    from backend.scenario_builder.emitter import resolve_enhanced_attribute_value

    comp = {"type": "Pump", "uri": "https://x.org/Pump/p1",
            "attributes": {"Power": {"value": 5, "unit": "KiloW",
                                     "attribute_type": "PhysicalAttribute"}},
            "nested_properties": {"Power": {"TimeSeriesNote": "x"}}}
    _, _, data = resolve_enhanced_attribute_value(comp, "Power")
    assert kind_of(data) is AttributeKind.PHYSICAL

    comp["nested_properties"]["Power"] = {"hasLiveTimeSeriesReference": "p.csv"}
    _, _, data = resolve_enhanced_attribute_value(comp, "Power")
    assert data["attribute_type"] is AttributeKind.DYNAMIC


def test_reload_skips_attribute_nodes_by_type_not_predicate_name():
    """An attribute node linked by a predicate not spelt has...Attribute is
    still an attribute (it is typed under dici_onto:Attribute); the old
    predicate-name test listed it as a component."""
    from backend.scenario_builder.reload import draft_from_ttl

    ttl = """
    @prefix dici_onto: <https://digicities.info/ontology#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    <https://x.org/S> a dici_onto:Scenario ; rdfs:label "S" .
    <https://x.org/Pump/p1> a dici_onto:Pump ;
        dici_onto:ratedBy <https://x.org/Pump/p1/Power> ;
        dici_onto:usedInScenario <https://x.org/S> .
    <https://x.org/Pump/p1/Power> a dici_onto:Power, dici_onto:PhysicalAttribute ;
        dici_onto:usedInScenario <https://x.org/S> .
    """
    draft = draft_from_ttl(ttl)
    assert [c["uri"] for c in draft["components"]] == ["https://x.org/Pump/p1"]
    assert draft["components"][0]["type"] == "Pump"


def test_thin_override_for_a_kind_named_by_subclass():
    """attribute_type ElectricityDemandProfile is a dynamic attribute: the
    override is written with the DynamicAttribute kind class. The old code
    emitted no override at all for it."""
    from backend.assumptions.thin_scenario_ttl import _override_lines

    lines = _override_lines("Demand", {
        "uri": "https://x.org/S/Demand", "original_uri": "https://x.org/B/b1/Demand",
        "attribute_type": "ElectricityDemandProfile", "value": 3, "unit": "KiloW",
    }, "https://x.org/S")
    assert lines and "dici_onto:DynamicAttribute" in lines[0]
    assert any("qudt:value" in line for line in lines)


def test_component_loader_reads_properties_by_iri():
    pytest.importorskip("streamlit")
    from components.scenario_builder.graphdb_component_loader import GraphDBComponentLoader

    loader = GraphDBComponentLoader.__new__(GraphDBComponentLoader)
    attr = "https://x.org/B/b1/Kind"
    rows = pd.DataFrame([
        {"attribute": attr, "property": str(DICI.hasLiveTimeSeriesReference), "value": "k.csv"},
        {"attribute": attr, "property": str(DICI.hasLiveTimeSeries), "value": "https://x.org/ts"},
        # Spelt like a time series link, but it is no such property.
        {"attribute": attr, "property": "https://x.org/ext#hasTimeSeriesNote", "value": "n"},
        {"attribute": attr, "property": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
         "value": str(DICI.CategoricalAttribute)},
    ])
    out = loader._process_attribute_data(rows, None, str(DICI.Detached))
    assert out["attribute_type"] is AttributeKind.CATEGORICAL
    assert out["category_value"] == "Detached"
    assert out["time_series_type"] == "live"
    assert loader._extract_nested_properties(rows) == {"hasLiveTimeSeries": "https://x.org/ts"}


def test_component_loader_kind_precedence():
    pytest.importorskip("streamlit")
    from components.scenario_builder import graphdb_component_loader as gcl

    class FakeQueries:
        @staticmethod
        def get_attribute_kinds(client):
            return pd.DataFrame([
                {"attribute": "a1", "kind": str(DICI.PhysicalAttribute)},
                {"attribute": "a1", "kind": str(DICI.DynamicAttribute)},
                {"attribute": "a2", "kind": str(URIRef(DICI.TurbineAttribute))},
            ])

    loader = gcl.GraphDBComponentLoader.__new__(gcl.GraphDBComponentLoader)
    loader.client = object()
    loader._attr_kind_cache = None
    real = gcl.gdb_queries
    gcl.gdb_queries = FakeQueries
    try:
        kinds = loader._get_attribute_kind_map()
    finally:
        gcl.gdb_queries = real
    assert kinds == {"a1": AttributeKind.DYNAMIC}


def test_reload_takes_types_from_the_graph_never_the_iri():
    """A bare reference has no rdf:type in a thin scenario. Its type comes from
    the workspace graph; without it the type is None and a warning says so.
    The old fallback read "WindTurbine" off the IRI path."""
    from backend.scenario_builder import build_scenario_ttl
    from backend.scenario_builder.reload import draft_from_ttl

    wt = "https://x.org/proj/ws/WindTurbine/T1"
    ttl = build_scenario_ttl("S", "ws", [wt], [])
    draft = draft_from_ttl(ttl)
    assert draft["components"][0]["type"] is None
    assert draft["warnings"] and wt in draft["warnings"][0]

    draft = draft_from_ttl(ttl, instance_types={wt: "Turbine"})
    assert draft["components"][0]["type"] == "Turbine" and not draft["warnings"]


def test_temporal_precision_by_individual():
    """Precisions are the core's TemporalPrecision individuals. A name that is
    none of them ("DayPrecision") is no precision: it gets no datatype of its
    own and is not written as dici_onto:hasTemporalPrecision; the old code
    wrote any string other than "Unknown"."""
    from backend.scenario_builder.emitter import (
        generate_enhanced_attribute_declaration,
        get_xsd_datatype_for_temporal_precision as xsd,
    )

    assert xsd("YearMonth", "2020-01") == "xsd:gYearMonth"
    assert xsd("Year", "nonsense") == "xsd:gYear"
    assert xsd("DayPrecision", "2019-06-01") == "xsd:date"   # from the value
    assert xsd("Unknown", "free text") == "xsd:string"

    def lines(precision):
        out = []
        generate_enhanced_attribute_declaration(
            out, "https://x.org/b/Built", "Built",
            {"attribute_type": "Event", "temporal_value": "2019-06-01",
             "temporal_precision": precision},
            "2019-06-01", "temporal", "https://x.org/S", "test")
        return "\n".join(out)

    assert "dici_onto:hasTemporalPrecision dici_onto:Date ;" in lines("Date")
    assert "hasTemporalPrecision" not in lines("DayPrecision")
    assert "hasTemporalPrecision" not in lines("Unknown")
