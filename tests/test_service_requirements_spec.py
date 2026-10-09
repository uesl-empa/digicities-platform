# SPDX-License-Identifier: Apache-2.0

"""docs/SERVICE_REQUIREMENTS_SPEC.md is checked against the platform.

Every YAML example in the spec carries a marker (valid / rejected / not caught /
fragment) and is run through the platform's own parser. The behaviour the spec
states for the running wind and orchard examples is checked by converting them
against a small scenario: lists for blocks, links followed both ways, the live
reference of the weather component, what is copied into the payload and what
validation reports.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from backend.api_submission.connection import resolve_connection, submit_via_connection
from backend.api_submission.ttl_converter import convert_scenario
from backend.api_submission.validation import validate_payload
from backend.scenario_builder.requirements import parse_service_requirements
from backend.service_requirements.template import parse_service_template

SPEC = Path(__file__).resolve().parents[1] / "docs" / "SERVICE_REQUIREMENTS_SPEC.md"
_BLOCK = re.compile(r"```yaml\n(.*?)```", re.S)
_MARKER = re.compile(r"^# example: (valid|rejected|not caught|fragment)\s*$")


def _examples():
    out = []
    for i, body in enumerate(_BLOCK.findall(SPEC.read_text(encoding="utf-8"))):
        first = body.splitlines()[0] if body.strip() else ""
        m = _MARKER.match(first)
        out.append(pytest.param(m.group(1) if m else None, body, id=f"example{i + 1}"))
    return out


def _example(service_name: str) -> dict:
    for _, body in (p.values for p in _examples()):
        doc = yaml.safe_load(body)
        if isinstance(doc, dict) and doc.get("service_name") == service_name:
            return doc
    raise AssertionError(f"no example with service_name {service_name}")


@pytest.mark.parametrize("marker, body", _examples())
def test_every_example_does_what_its_marker_says(marker, body):
    assert marker is not None, "every yaml example starts with an '# example: ...' marker"
    assert yaml.safe_load(body) is not None
    if marker == "fragment":
        return
    if marker == "rejected":
        with pytest.raises(ValueError):
            parse_service_template(body)
        return
    service_name, entries, _, connection = parse_service_template(body)
    assert service_name
    if marker == "valid":
        assert entries
        parse_service_requirements(yaml.safe_load(body))
        resolve_connection(connection)


P = "https://example.org/ws"
SCENARIO = f"""
@prefix d: <https://digicities.info/ontology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{P}/scn> a d:Scenario ; rdfs:label "Baseline" .
<{P}/l1> a d:ComponentLink ; d:hasInputEntity <{P}/scn> ;
    d:linksInputyEntityTo <{P}/WindPark/Alkmaar> .
<{P}/l2> a d:ComponentLink ; d:hasInputEntity <{P}/WindPark/Alkmaar> ;
    d:linksInputyEntityTo <{P}/WindTurbine/T1> .
<{P}/l3> a d:ComponentLink ; d:hasInputEntity <{P}/WindTurbine/T2> ;
    d:linksInputyEntityTo <{P}/WindPark/Alkmaar> .
<{P}/l4> a d:ComponentLink ; d:hasInputEntity <{P}/WindPark/Alkmaar> ;
    d:linksInputyEntityTo <{P}/Weather/W> .
<{P}/WindPark/Alkmaar> a d:WindPark ; rdfs:label "WindparkAlkmaar" ;
    d:hasAttribute <{P}/WindPark/Alkmaar/Roughness> .
<{P}/WindPark/Alkmaar/Roughness> a d:Roughness, d:PhysicalAttribute ; qudt:value 0.1 .
<{P}/WindTurbine/T1> a d:WindTurbine ; d:hasAttribute <{P}/WindTurbine/T1/HubHeight> .
<{P}/WindTurbine/T1/HubHeight> a d:HubHeight, d:PhysicalAttribute ; qudt:value 80.0 .
<{P}/WindTurbine/T2> a d:WindTurbine .
<{P}/Weather/W> a d:Weather ; d:hasAttribute <{P}/Weather/W/WindspeedForecast> .
<{P}/Weather/W/WindspeedForecast> a d:WindspeedForecast, d:DynamicAttribute ;
    d:hasLiveTimeSeriesReference "weather.forecasts.openmeteo.Alkmaar" .
"""


def _wind():
    return _example("WindForecast")


def test_blocks_are_lists_and_links_are_followed_both_ways():
    payload = convert_scenario(_wind(), SCENARIO)
    data = payload["scenario_data"]
    assert data["uri"] == f"{P}/scn" and data["label"] == "Baseline"
    park = data["windPark"]
    assert isinstance(park, list) and len(park) == 1
    park = park[0]
    assert park["name"] == "WindparkAlkmaar" and park["Roughness"] == 0.1
    # T1 is linked park -> turbine, T2 turbine -> park: both are found (section 5.2)
    assert [t["uri"] for t in park["windTurbine"]] == [f"{P}/WindTurbine/T1", f"{P}/WindTurbine/T2"]
    # a missing value leaves the field out (section 9)
    assert park["windTurbine"][0]["HubHeight"] == 80.0 and "HubHeight" not in park["windTurbine"][1]


def test_the_stream_is_the_live_reference_of_the_weather_component():
    park = convert_scenario(_wind(), SCENARIO)["scenario_data"]["windPark"][0]
    assert park["weather"] == [{"uri": f"{P}/Weather/W",
                                "WindspeedForecast_live": "weather.forecasts.openmeteo.Alkmaar"}]


def test_connection_is_dropped_and_metadata_is_copied():
    template = dict(_wind(), optional_attributes=["WindTurbine.HubHeight"],
                    required_attributes=["Roughness"])
    payload = convert_scenario(template, SCENARIO)
    assert "connection" not in payload                                   # section 7
    assert payload["service_name"] == "WindForecast"                     # section 9, issue 3
    assert payload["optional_attributes"] == [] and payload["required_attributes"] == ["Roughness"]


def test_nested_paths_read_one_time_series_property_only():
    template = _wind()
    weather = template["scenario_data"]["windPark"]["weather"]["template"]
    weather["Extra"] = "Weather.WindspeedForecast.hasLiveTimeSeriesReference.foo.bar"
    weather["Generic"] = "Weather.WindspeedForecast.hasTimeSeriesReference"
    weather["NotSeries"] = "Weather.WindspeedForecast.hasUnitLabel"
    got = convert_scenario(template, SCENARIO)["scenario_data"]["windPark"][0]["weather"][0]
    assert got["Extra"] == got["Generic"] == "weather.forecasts.openmeteo.Alkmaar"  # 4.4, issue 4
    assert "NotSeries" not in got


def test_validation_guarantees_and_gaps():
    template = dict(_wind(), required_attributes=["HubHeight"])
    raw = convert_scenario(template, SCENARIO, clean=False)
    result = validate_payload(raw, template)
    # a required field that did not resolve is an error (section 6.2)
    assert not result.is_valid and any("HubHeight" in e for e in result.errors)

    plain = validate_payload(convert_scenario(_wind(), SCENARIO, clean=False), _wind())
    assert plain.is_valid and any("HubHeight" in w for w in plain.warnings)

    broken = _example("BrokenLink")
    report = validate_payload(convert_scenario(broken, SCENARIO, clean=False), broken)
    assert any("no components found for link 'CL.Site'" in e for e in report.errors)

    wrong = _example("WrongNestedProperty")
    wrong["scenario_data"]["park"] = {"name": "WindPark.label", "uri": "WindPark.URI",
                                      "RoughnessUnit": "WindPark.Roughness.hasUnitLabel"}
    report = validate_payload(convert_scenario(wrong, SCENARIO, clean=False), wrong)
    assert report.is_valid and any("RoughnessUnit" in w for w in report.warnings)


def test_a_root_block_with_no_linked_instance_yields_no_list():
    template = {"service_name": "S", "scenario_data": {
        "uri": "Scenario.URI", "site": {"name": "Site.label", "uri": "Site.URI"}}}
    payload = convert_scenario(template, SCENARIO)
    assert "site" not in payload["scenario_data"]


def test_optional_and_derived_leave_the_completeness_gate():
    required = parse_service_requirements(_example("OrchardYield"))["required_attributes"]
    assert set(required["Tree"]) == {"URI", "label"}


def test_a_redis_contract_without_request_stream_cannot_start_a_run():
    connection = _wind()["connection"]
    assert resolve_connection(connection)["redis"]["request_stream"] == ""
    result = submit_via_connection({"scenario_data": {}}, connection)
    assert not result.success
