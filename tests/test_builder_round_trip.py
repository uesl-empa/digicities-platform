# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The Service Requirements Builder's load -> save: what it does not model is
kept, what it does model is the builder's."""
from __future__ import annotations

import copy

import yaml

from backend.service_requirements.template import (
    build_service_template,
    carry_over_unmodelled,
    parse_service_template,
    template_field_names,
)

TEMPLATE = """\
service_name: two_tools
connection: {transport: http, url: "http://tool/run", method: POST}
scenario_data:
  uri: Scenario.URI
  name: Scenario.label
  run_name: Scenario.RunName
  site:
    uri: Site.URI
    pc6: Site.label
    weather: Site.WeatherEPW
    flows:
      link: CL.Site.EnergyCarrierFlow
      template:
        uri: EnergyCarrierFlow.URI
        source: EnergyCarrierFlow.hasSource
        carrier: {link: CL.EnergyCarrierFlow.EnergyCarrier, template: EnergyCarrier.URI}
        p_nom: {ref: EnergyCarrierFlow.FlowCapacity, unit: KiloW}
        marginal_cost: {ref: EnergyCarrierFlow.Price.hasHistoricTimeSeriesReference, unit: KiloW-HR, currency: CHF}
        buses:
          link: CL.EnergyCarrierFlow.Junction
          template: {uri: Junction.URI, name: Junction.label}
optional_attributes:
  - EnergyCarrierFlow.Price
units_in_payload: false
outputs:
  - component: Site
    identified_by: pc6
    attributes: {demand: Site.Demand}
"""


def _load_and_save(text: str, edit=None) -> dict:
    """What a builder does: parse, maybe edit the component model, build, keep."""
    name, entries, description, connection = parse_service_template(text)
    if edit:
        edit(entries)
    doc = build_service_template(name, entries, description=description, connection=connection,
                                 custom_field_names=template_field_names(text))
    return carry_over_unmodelled(yaml.safe_load(text), doc)


def test_a_load_and_save_changes_nothing():
    before = yaml.safe_load(TEMPLATE)
    after = _load_and_save(TEMPLATE)
    assert after == before
    # Order too: the saved file reads like the loaded one.
    assert list(after["scenario_data"]["site"]) == list(before["scenario_data"]["site"])
    assert list(after) == list(before)


def test_the_fields_own_names_come_back_with_the_parse():
    names = template_field_names(TEMPLATE)
    assert names["flows|FlowCapacity|Static"] == "p_nom"
    assert names["flows|Price|Historic"] == "marginal_cost"
    assert names["site|label|Static"] == "pc6"
    assert names["site|WeatherEPW|Static"] == "weather"


def test_a_block_with_only_a_component_uri_is_a_component():
    _name, entries, _d, _c = parse_service_template(TEMPLATE)
    assert {e.path: e.component_type for e in entries} == {
        "site": "Site", "flows": "EnergyCarrierFlow", "buses": "Junction"}


def test_an_attribute_removed_in_the_builder_is_gone_with_its_unit():
    def drop_capacity(entries):
        flows = next(e for e in entries if e.path == "flows")
        del flows.configured_attributes["FlowCapacity"]

    template = _load_and_save(TEMPLATE, drop_capacity)["scenario_data"]["site"]["flows"]["template"]
    assert "p_nom" not in template
    assert template["marginal_cost"]["currency"] == "CHF"


def test_a_component_removed_in_the_builder_is_gone_with_what_it_held():
    def drop_flows(entries):
        entries[:] = [e for e in entries if e.path not in ("flows", "buses")]

    site = _load_and_save(TEMPLATE, drop_flows)["scenario_data"]["site"]
    assert "flows" not in site and site["weather"] == "Site.WeatherEPW"


def test_an_attribute_added_in_the_builder_is_written():
    def add_area(entries):
        next(e for e in entries if e.path == "site").configured_attributes["Area"] = ["Static"]

    assert _load_and_save(TEMPLATE, add_area)["scenario_data"]["site"]["Area"] == "Site.Area"


def test_nothing_to_keep_without_a_loaded_template():
    name, entries, _d, connection = parse_service_template(TEMPLATE)
    doc = build_service_template(name, entries, connection=connection)
    assert carry_over_unmodelled(None, copy.deepcopy(doc)) == doc
