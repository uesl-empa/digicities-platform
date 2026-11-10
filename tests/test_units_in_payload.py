# SPDX-License-Identifier: Apache-2.0

"""The payload carries the unit of every value the data states one for.

The values keep the tool's own shape and stay plain numbers and strings; a
top-level ``units`` block of the same shape gives each one's unit (a QUDT code;
for a cost what it is per and its currency). What the service does with them is
up to the service. A field that names its unit is sent in it, and the block says
so. ``units_in_payload: false`` leaves the block out.
"""
from __future__ import annotations

import json

import pytest
import yaml

pytest.importorskip("rdflib")

from backend.api_submission.ttl_converter import (  # noqa: E402
    convert_scenario, finish_payload, split_units,
)
from backend.api_submission.validation import validate_payload  # noqa: E402

from tests.test_units_in_contract import TTL, template  # noqa: E402

SERIES = "EnergyCarrierFlow.Demand.hasHistoricTimeSeriesReference"


def payload(t):
    return convert_scenario(t, TTL)


def test_every_value_comes_with_the_unit_the_data_states():
    p = payload(template(CapMax="EnergyConverter.CapMax", Efficiency="EnergyConverter.Efficiency",
                         Price="EnergyCarrierFlow.Price", Demand=SERIES))
    data = p["scenario_data"]
    assert data["boilers"][0]["CapMax"] == 0.1 and type(data["boilers"][0]["CapMax"]) is float
    assert data["flows"][0]["Demand"] == "resources/gas_demand.csv"
    assert type(data["flows"][0]["Demand"]) is str
    units = p["units"]["scenario_data"]
    assert units["boilers"] == [{"CapMax": "MegaW", "Efficiency": "PERCENT"}]
    assert units["flows"] == [{"Price": {"per": "MegaW-HR", "currency": "CHF"}, "Demand": "MegaW"}]


def test_a_field_that_names_its_unit_says_the_unit_it_was_sent_in():
    p = payload(template(CapMax={"ref": "EnergyConverter.CapMax", "unit": "KiloW"},
                         Price={"ref": "EnergyCarrierFlow.Price", "unit": "KiloW-HR", "currency": "CHF"},
                         CapMin={"ref": "EnergyConverter.CapMin", "unit": "KiloW"}))
    assert p["scenario_data"]["boilers"][0]["CapMax"] == 100
    assert p["scenario_data"]["boilers"][0]["CapMin"] == "inf"
    assert p["units"]["scenario_data"]["boilers"] == [{"CapMax": "KiloW", "CapMin": "KiloW"}]
    assert p["units"]["scenario_data"]["flows"] == [{"Price": {"per": "KiloW-HR", "currency": "CHF"}}]


def test_identities_and_values_without_a_unit_have_none():
    p = payload(template(CapMax="EnergyConverter.CapMax"))
    assert "uri" in p["scenario_data"]["boilers"][0]
    assert p["units"]["scenario_data"]["boilers"] == [{"CapMax": "MegaW"}]
    p = payload({"service_name": "units", "scenario_data": {
        "boilers": {"link": "CL.Scenario.EnergyConverter", "template": {"uri": "EnergyConverter.URI"}}}})
    assert "units" not in p


def test_a_value_refused_for_its_unit_has_no_unit_either():
    p = payload(template(CapMax="EnergyConverter.CapMax",
                         AnnualHeat={"ref": "EnergyConverter.AnnualHeat", "unit": "KiloW"}))
    assert "AnnualHeat" not in p["scenario_data"]["boilers"][0]
    assert p["units"]["scenario_data"]["boilers"] == [{"CapMax": "MegaW"}]


def test_a_registration_can_leave_the_units_out():
    t = template(CapMax="EnergyConverter.CapMax")
    t["units_in_payload"] = False
    p = payload(t)
    assert "units" not in p and "units_in_payload" not in p
    assert p["scenario_data"]["boilers"][0]["CapMax"] == 0.1


def test_a_tools_own_units_key_is_never_overwritten():
    t = template(CapMax="EnergyConverter.CapMax")
    t["units"] = "SI"
    assert payload(t)["units"] == "SI"


def test_validation_reads_the_raw_payload_as_before_and_the_api_path_gives_the_same_payload():
    t = template(CapMax="EnergyConverter.CapMax", Demand=SERIES)
    raw = convert_scenario(t, TTL, clean=False)
    assert validate_payload(raw, t).is_valid
    assert finish_payload(raw, t) == payload(t)
    # The raw output dumps as plain JSON and YAML (the Convert tab shows it).
    assert json.loads(json.dumps(raw))["scenario_data"]["boilers"][0]["CapMax"] == 0.1
    assert "CapMax: 0.1" in yaml.dump(raw) and "resources/gas_demand.csv" in yaml.dump(raw)
    assert yaml.safe_dump(json.loads(json.dumps(raw)))


def test_a_list_keeps_its_positions():
    from backend.api_submission.ttl_converter import _with_unit
    values, units = split_units({"a": [1.0, _with_unit(2.0, "KiloW")], "b": "x"})
    assert values == {"a": [1.0, 2.0], "b": "x"} and type(values["a"][1]) is float
    assert units == {"a": [None, "KiloW"]}
