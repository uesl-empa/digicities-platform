# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Tests for ``backend.data_products.ttl_parser.TTLParser``.

Drives the same entry points the data-products processor calls
(``parse_ttl_content`` → ``extract_components_from_graph`` →
``get_component_summary``) over the shared fixture
``tests/fixtures/use_case_data_product.ttl``, which carries one of each
attribute flavor: physical + QUDT unit, unit-based and simple costs
(currency), a new-style categorical, a dynamic attribute with a live time
series, a curve, and a temporal event. Attribute discovery here runs on the
platform's path-style URI convention (``<component>/<AttributeName>``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from backend.data_products.ttl_parser import TTLParser, get_component_summary  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "use_case_data_product.ttl"


@pytest.fixture(scope="module")
def components():
    parser = TTLParser()
    graph = parser.parse_ttl_content(FIXTURE.read_text(encoding="utf-8"))
    assert graph is not None
    return parser.extract_components_from_graph(graph)


def _one(components, comp_type):
    assert comp_type in components
    assert len(components[comp_type]) == 1
    return components[comp_type][0]


# ── parsing ──────────────────────────────────────────────────────────────────
def test_parse_ttl_content_invalid_returns_none():
    assert TTLParser().parse_ttl_content("this is not turtle @@@") is None


def test_component_vs_attribute_separation(components):
    """Only the two real components surface; attribute instances (typed
    PhysicalAttribute, CategoricalAttribute, ...) never appear as components."""
    assert set(components) == {"Battery", "Building"}
    battery = _one(components, "Battery")
    assert battery["label"] == "Home Battery 1"
    assert battery["uri"].endswith("/Battery/HomeBattery1")
    building = _one(components, "Building")
    assert building["label"] == "Main Office"


# ── attribute flavor extraction (Battery) ────────────────────────────────────
def test_physical_attribute_value_and_unit(components):
    attr = _one(components, "Battery")["attributes"]["StorageCapacity"]
    assert attr["attribute_type"] == "PhysicalAttribute"
    assert attr["category"] == "physical"
    assert attr["value"] == 13.5  # xsd:decimal → float
    assert attr["unit"] == "KiloW-HR"


def test_unit_based_cost_attribute(components):
    attr = _one(components, "Battery")["attributes"]["InvestmentCost"]
    assert attr["attribute_type"] == "UnitBasedCostAttribute"
    assert attr["category"] == "cost"
    assert attr["value"] == 650.0
    assert attr["currency"] == "CHF"
    assert attr["unit"] == "KiloW-HR"


def test_categorical_attribute_reads_category_type(components):
    """New-style categorical: typed CategoricalAttribute + its own attribute
    class (matching the URI fragment) + the category value. The value is the
    category class, not the attribute class."""
    attr = _one(components, "Battery")["attributes"]["ChemistryType"]
    assert attr["attribute_type"] == "CategoricalAttribute"
    assert attr["value"] == "LithiumIon"
    assert attr["category_value"] == "LithiumIon"
    assert attr["unit"] == "category"
    assert attr["specific_attribute_type"] == "ChemistryType"


def test_curve_attribute_data_points_and_axis_units(components):
    attr = _one(components, "Battery")["attributes"]["ChargeEfficiencyCurve"]
    assert attr["attribute_type"] == "CurveAttribute"
    assert attr["data_points"].startswith("[[0.0, 0.9]")
    assert attr["x_unit"] == "PERCENT"
    assert attr["y_unit"] == ""  # unit:None is a missing unit, not the word "None"


# ── attribute flavor extraction (Building) ───────────────────────────────────
def test_simple_cost_attribute_falls_back_to_currency_unit(components):
    attr = _one(components, "Building")["attributes"]["AnnualMaintenanceCost"]
    assert attr["attribute_type"] == "SimpleCostAttribute"
    assert attr["value"] == 18000  # xsd:integer → int
    assert attr["currency"] == "EUR"
    assert attr["unit"] == "EUR"  # no qudt:unit → currency stands in


def test_dynamic_attribute_live_time_series_and_resource(components):
    attr = _one(components, "Building")["attributes"]["ElectricityDemand"]
    assert attr["attribute_type"] == "DynamicAttribute"
    assert attr["unit"] == "kW"
    assert attr["time_series_type"] == "live"
    assert attr["time_series_reference"] == "timeseries/main_office_demand.csv"
    # a .csv reference is tracked as a component resource
    assert attr["resource_reference"] == "timeseries/main_office_demand.csv"
    resources = _one(components, "Building")["resources"]
    assert resources["ElectricityDemand"] == "timeseries/main_office_demand.csv"


def test_event_attribute_temporal_value_and_precision(components):
    attr = _one(components, "Building")["attributes"]["CommissioningDate"]
    assert attr["attribute_type"] == "EventAttribute"
    assert attr["value"] == "2019-06-01"
    assert attr["temporal_value"] == "2019-06-01"
    assert attr["temporal_precision"] == "DayPrecision"
    assert attr["unit"] == "temporal"


def test_physical_attribute_on_building(components):
    attr = _one(components, "Building")["attributes"]["GrossFloorArea"]
    assert attr["value"] == 1250.0
    assert attr["unit"] == "M2"


# ── summary ──────────────────────────────────────────────────────────────────
def test_component_summary_counts(components):
    summary = get_component_summary(components)
    assert summary["total_components"] == 2
    assert {t["type"]: t["count"] for t in summary["component_types"]} == {
        "Battery": 1, "Building": 1}
    assert summary["total_attributes"] == 8
    assert summary["components_with_resources"] == 1
    assert summary["attribute_categories"]["physical"] == 2
    assert summary["attribute_categories"]["cost"] == 2
