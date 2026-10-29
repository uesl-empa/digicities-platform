# SPDX-License-Identifier: Apache-2.0

"""A contract field may name the unit its value must be in; the platform converts.

``CapMax: {ref: EnergyConverter.CapMax, unit: KiloW}`` sends the boiler's
capacity in kW whatever unit the replica holds it in; ``{ref: ..Price, unit:
KiloW-HR, currency: CHF}`` sends a price per kWh in CHF. What cannot be given
in the unit asked for (energy where power is asked, another currency, a series
file in another unit) is refused: validation reports it, the service never
receives it.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from backend.api_submission.ttl_converter import clean_placeholder_values, convert_scenario  # noqa: E402
from backend.api_submission.validation import validate_payload  # noqa: E402
from backend.service_requirements.contract import (  # noqa: E402
    parse_value_spec, refusal_reason, required_references,
)
from backend.unit_conversion import UnitRefused, convert, convert_cost  # noqa: E402

P = "https://digicities.info/proj/units/"
TTL = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix unit: <http://qudt.org/vocab/unit/> .
@prefix cur: <http://qudt.org/vocab/currency/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <{P}> .

ex:Baseline a dici_onto:Scenario ; rdfs:label "Baseline" .
ex:boiler a dici_onto:EnergyConverter ; rdfs:label "boiler" ;
    dici_onto:hasAttribute ex:boiler_cap, ex:boiler_eff, ex:boiler_heat, ex:boiler_limit .
ex:boiler_cap a dici_onto:CapMax, dici_onto:PhysicalAttribute ;
    qudt:value "0.1"^^xsd:decimal ; qudt:unit unit:MegaW .
ex:boiler_eff a dici_onto:Efficiency, dici_onto:PhysicalAttribute ;
    qudt:value "90"^^xsd:decimal ; qudt:unit unit:PERCENT .
ex:boiler_heat a dici_onto:AnnualHeat, dici_onto:PhysicalAttribute ;
    qudt:value "5"^^xsd:decimal ; qudt:unit unit:MegaW-HR .
ex:boiler_limit a dici_onto:CapMin, dici_onto:PhysicalAttribute ;
    qudt:value "INF"^^xsd:double ; qudt:unit unit:MegaW .
ex:gas_in a dici_onto:EnergyCarrierFlow ; rdfs:label "gas in" ;
    dici_onto:hasAttribute ex:gas_price, ex:gas_euro, ex:gas_demand .
ex:gas_price a dici_onto:Price, dici_onto:UnitBasedCostAttribute ;
    qudt:value "100"^^xsd:decimal ; qudt:unit unit:MegaW-HR ; dici_onto:currency cur:CHF .
ex:gas_euro a dici_onto:PriceEuro, dici_onto:UnitBasedCostAttribute ;
    qudt:value "0.1"^^xsd:decimal ; qudt:unit unit:KiloW-HR ; dici_onto:currency cur:EUR .
ex:gas_demand a dici_onto:Demand, dici_onto:DynamicAttribute ;
    dici_onto:hasHistoricTimeSeries ex:gas_demand_ts ;
    dici_onto:hasHistoricTimeSeriesReference "resources/gas_demand.csv"^^xsd:string .
ex:gas_demand_ts a dici_onto:TimeSeries ; qudt:unit unit:MegaW .
ex:CL_0 a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Baseline ;
    dici_onto:linksInputyEntityTo ex:boiler ; dici_onto:usedInScenario ex:Baseline .
ex:CL_1 a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Baseline ;
    dici_onto:linksInputyEntityTo ex:gas_in ; dici_onto:usedInScenario ex:Baseline .
"""


def template(**fields):
    boiler = {"uri": "EnergyConverter.URI"}
    flow = {"uri": "EnergyCarrierFlow.URI"}
    for name, spec in fields.items():
        ref = spec["ref"] if isinstance(spec, dict) else spec
        (boiler if ref.startswith("EnergyConverter") else flow)[name] = spec
    data = {"boilers": {"link": "CL.Scenario.EnergyConverter", "template": boiler}}
    if len(flow) > 1:
        data["flows"] = {"link": "CL.Scenario.EnergyCarrierFlow", "template": flow}
    return {"service_name": "units", "scenario_data": data}


def run(**fields):
    t = template(**fields)
    raw = convert_scenario(t, TTL, clean=False)
    return raw, validate_payload(raw, t), clean_placeholder_values(raw, t)


def field(payload, name):
    items = [i[0] for i in payload["scenario_data"].values() if i]
    return next((i[name] for i in items if name in i), None)


# -- the arithmetic, from QUDT's factors ---------------------------------------

def test_power_energy_and_temperature_convert():
    assert convert(0.1, "unit:MegaW", "KiloW") == pytest.approx(100)
    assert convert(5000, "http://qudt.org/vocab/unit/KiloW-HR", "MegaW-HR") == pytest.approx(5)
    assert convert(20, "unit:DEG_C", "K") == pytest.approx(293.15)
    assert convert(32, "unit:DEG_F", "DEG_C") == pytest.approx(0, abs=1e-9)
    assert convert(90, "unit:PERCENT", "UNITLESS") == pytest.approx(0.9)


def test_a_different_kind_of_quantity_is_refused():
    with pytest.raises(UnitRefused, match="different kind of quantity"):
        convert(5, "unit:MegaW-HR", "KiloW")
    with pytest.raises(UnitRefused, match="not a QUDT unit"):
        convert(5, "unit:Wombat", "KiloW")


def test_a_value_already_in_the_unit_asked_for_passes_even_when_qudt_does_not_know_it():
    assert convert(60, "unit:KiloW-HR-PER-YR", "KiloW-HR-PER-YR") == 60
    assert convert_cost(0.1, "unit:Widget", "http://qudt.org/vocab/currency/CHF", "Widget", "CHF") == 0.1
    with pytest.raises(UnitRefused, match="not a QUDT unit"):
        convert(60, "unit:KiloW-HR-PER-YR", "KiloW-HR")


def test_a_value_with_no_unit_is_only_a_plain_number():
    assert convert(0.9, None, "UNITLESS") == 0.9
    with pytest.raises(UnitRefused, match="states no unit"):
        convert(100, "unit:None", "KiloW")
    with pytest.raises(UnitRefused, match="states no unit"):
        convert(0.9, None, "PERCENT")          # 0.9 or 90? the value does not say


def test_a_cost_converts_by_what_it_is_per_never_by_currency():
    assert convert_cost(100, "unit:MegaW-HR", "http://qudt.org/vocab/currency/CHF",
                        "KiloW-HR", "CHF") == pytest.approx(0.1)
    with pytest.raises(UnitRefused, match="no exchange rates"):
        convert_cost(0.1, "unit:KiloW-HR", "http://qudt.org/vocab/currency/EUR", "KiloW-HR", "CHF")


# -- the contract ---------------------------------------------------------------

def test_a_value_spec_is_a_required_reference_like_any_other():
    spec = parse_value_spec({"ref": "EnergyConverter.CapMax", "unit": "KiloW"})
    assert spec.ref.text == "EnergyConverter.CapMax" and spec.unit == "KiloW"
    assert parse_value_spec({"ref": "EnergyConverter.CapMax"}) is None        # names no unit
    assert parse_value_spec({"ref": "x", "unit": "KiloW"}) is None            # not a reference
    refs = required_references(template(CapMax={"ref": "EnergyConverter.CapMax", "unit": "KiloW"}))
    assert [r.text for r in refs] == ["EnergyConverter.URI", "EnergyConverter.CapMax"]


# -- the payload -----------------------------------------------------------------

def test_values_arrive_in_the_unit_the_field_names():
    raw, check, payload = run(
        CapMax={"ref": "EnergyConverter.CapMax", "unit": "KiloW"},
        Efficiency={"ref": "EnergyConverter.Efficiency", "unit": "UNITLESS"},
        Price={"ref": "EnergyCarrierFlow.Price", "unit": "KiloW-HR", "currency": "CHF"},
        CapMin={"ref": "EnergyConverter.CapMin", "unit": "KiloW"})
    assert check.is_valid, check.errors
    assert field(payload, "CapMax") == 100
    assert field(payload, "Efficiency") == pytest.approx(0.9)
    assert field(payload, "Price") == pytest.approx(0.1)
    assert field(payload, "CapMin") == "inf"                 # no limit stays no limit


def test_a_field_without_a_unit_sends_the_value_as_held():
    _, check, payload = run(CapMax="EnergyConverter.CapMax")
    assert check.is_valid and field(payload, "CapMax") == 0.1


def test_energy_where_power_is_asked_is_refused_and_not_sent():
    raw, check, payload = run(AnnualHeat={"ref": "EnergyConverter.AnnualHeat", "unit": "KiloW"})
    assert "different kind of quantity" in refusal_reason(field(raw, "AnnualHeat"))
    assert not check.is_valid
    assert any("not in the unit asked for" in e and "boilers[1].AnnualHeat" in e for e in check.errors)
    assert field(payload, "AnnualHeat") is None


def test_another_currency_is_refused():
    _, check, _ = run(PriceEuro={"ref": "EnergyCarrierFlow.PriceEuro", "unit": "KiloW-HR", "currency": "CHF"})
    assert any("no exchange rates" in e for e in check.errors)


def test_a_currency_on_something_that_is_not_a_cost_is_refused():
    _, check, _ = run(CapMax={"ref": "EnergyConverter.CapMax", "unit": "KiloW", "currency": "CHF"})
    assert any("not a cost" in e for e in check.errors)


def test_a_series_must_already_be_in_the_unit_asked_for():
    ref = "EnergyCarrierFlow.Demand.hasHistoricTimeSeriesReference"
    _, check, payload = run(Demand={"ref": ref, "unit": "MegaW"})
    assert check.is_valid and field(payload, "Demand") == "resources/gas_demand.csv"
    _, check, payload = run(Demand={"ref": ref, "unit": "KiloW"})
    assert any("does not rewrite files" in e for e in check.errors)
    assert field(payload, "Demand") is None
    _, check, _ = run(Demand={"ref": ref, "unit": "KiloW-HR"})
    assert any("different kind of quantity" in e for e in check.errors)


def test_an_optional_field_refused_for_its_unit_is_a_warning():
    t = template(AnnualHeat={"ref": "EnergyConverter.AnnualHeat", "unit": "KiloW"})
    t["optional_attributes"] = ["EnergyConverter.AnnualHeat"]
    raw = convert_scenario(t, TTL, clean=False)
    check = validate_payload(raw, t)
    assert check.is_valid and any("not in the unit asked for" in w for w in check.warnings)


def test_a_materialized_scenario_keeps_its_series_units():
    """API Submission converts a scenario materialized against the replica: the
    series node (which holds the unit) must come along, or every series field
    that names a unit is refused."""
    from rdflib import Graph

    from backend.graphdb.queries.scenarios import materialize_scenario_graphs

    scenario = Graph().parse(data=f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix ex: <{P}> .
ex:Baseline a dici_onto:Scenario .
ex:gas_in dici_onto:usedInScenario ex:Baseline .
ex:CL_1 a dici_onto:ComponentLink ; dici_onto:hasInputEntity ex:Baseline ;
    dici_onto:linksInputyEntityTo ex:gas_in ; dici_onto:usedInScenario ex:Baseline .
""", format="turtle")
    replica = Graph().parse(data=TTL, format="turtle")
    ttl = materialize_scenario_graphs(scenario, replica, P + "Baseline")
    t = template(Demand={"ref": "EnergyCarrierFlow.Demand.hasHistoricTimeSeriesReference", "unit": "MegaW"})
    del t["scenario_data"]["boilers"]
    raw = convert_scenario(t, ttl, clean=False)
    check = validate_payload(raw, t)
    assert check.is_valid, check.errors
    assert raw["scenario_data"]["flows"][0]["Demand"] == "resources/gas_demand.csv"
