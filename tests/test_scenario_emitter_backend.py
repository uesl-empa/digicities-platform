# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The backend scenario emitter, driven by an explicit ScenarioDraft.

Counterpart to ``tests/test_characterize_scenario_emitter.py``: the same
fixture data, but fed through ``backend.scenario_builder`` with no Streamlit
session state anywhere — and checked against the SAME golden
(``tests/goldens/scenario_emitter_full.ttl``). Passing both suites proves the
Streamlit path (session state -> shim -> emitter) and the headless path
(ScenarioDraft -> emitter) emit identical scenario graphs.

The fixture dicts are duplicated from the characterization test on purpose:
that file must stay importable-only-with-streamlit and byte-identical, this
one must run without streamlit installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from backend.scenario_builder import emitter  # noqa: E402
from backend.scenario_builder.draft import ScenarioDraft  # noqa: E402
from backend.scenario_builder.publish import save_scenario_to_workspace  # noqa: E402

from tests.golden import assert_ttl_golden  # noqa: E402

WT_URI = "https://digicities.info/proj/ws_golden/WindTurbine/WT1"
EDP_URI = "https://digicities.info/proj/ws_golden/ElectricityDemandProfile/EDP1"

REQUIRED_ATTRIBUTES = {
    "WindTurbine": ["hubHeight", "manufacturer", "isOffshore",
                    "commissioningDate", "turbineClass"],
    "ElectricityDemandProfile": ["Power.hasHistoricTimeSeriesReference"],
}


def _wind_turbine():
    return {
        "uri": WT_URI,
        "type": "WindTurbine",
        "label": "Turbine One",
        "source": "ttl_use_case",
        "workspace_id": "ws_golden",
        "attributes": {
            "hubHeight": {"value": 120, "unit": "m",
                          "attribute_type": "PhysicalAttribute"},
            "manufacturer": {"value": "Vestas", "unit": "text",
                             "attribute_type": "PhysicalAttribute"},
            "isOffshore": {"value": True, "unit": "dimensionless",
                           "attribute_type": "PhysicalAttribute"},
            "commissioningDate": {"value": "2020-05",
                                  "temporal_value": "2020-05",
                                  "temporal_precision": "YearMonth",
                                  "unit": "temporal",
                                  "attribute_type": "EventAttribute"},
            "turbineClass": {"value": "IEC Class II",
                             "category_value": "IEC Class II",
                             "unit": "category",
                             "attribute_type": "CategoricalAttribute"},
        },
    }


def _demand_profile():
    return {
        "uri": EDP_URI,
        "type": "ElectricityDemandProfile",
        "label": "Demand Profile One",
        "source": "data_products",
        "source_catalog": "catalog_a",
        "attributes": {
            "Power": {"value": "timeseries", "unit": "kW"},
        },
        "nested_properties": {
            "Power": {
                "hasHistoricTimeSeriesReference": "resources/demand.csv",
                "hasHistoricTimeSeries":
                    "https://digicities.info/proj/ws_golden/ts/demand",
                "unit": "kW",
            },
        },
    }


def _links():
    return [
        {"source": "scenario", "target": WT_URI,
         "link_type": "scenario_automatic"},
        {"source": EDP_URI, "target": WT_URI, "link_type": "feeds"},
    ]


def _draft() -> ScenarioDraft:
    return ScenarioDraft(
        scenario_name="Golden Scenario",
        workspace_id="ws_golden",
        workspace_name="Golden Workspace",
        service_name="golden_service",
        ttl_specificity="High",
        required_attributes=REQUIRED_ATTRIBUTES,
        components=[_wind_turbine(), _demand_profile()],
        links=_links(),
    )


def test_backend_emitter_matches_streamlit_golden():
    """The headless draft path reproduces the exact graph the Streamlit
    session-state path pinned — same golden, RDF-isomorphic."""
    ttl = emitter.generate_full_ttl(_draft())
    assert_ttl_golden(ttl, "scenario_emitter_full.ttl")


def test_draft_dict_round_trip():
    draft = _draft()
    data = draft.to_dict()
    assert ScenarioDraft.from_dict(data) == draft
    assert ScenarioDraft.from_dict(data).to_dict() == data


def test_from_session_state_reads_the_session_shapes():
    """A plain dict with the Scenario Builder's session keys maps onto the
    draft exactly (workspace id/name, service from selected_requirements)."""
    state = {
        "scenario_name": "Golden Scenario",
        "current_workspace": {"id": "ws_golden", "name": "Golden Workspace"},
        "selected_requirements": {"service_name": "golden_service",
                                  "component_links": []},
        "ttl_specificity": "High",
        "required_attributes": REQUIRED_ATTRIBUTES,
        "scenario_components": [_wind_turbine(), _demand_profile()],
        "scenario_links": _links(),
    }
    draft = ScenarioDraft.from_session_state(state)
    assert draft == _draft()
    # And no workspace selected falls back exactly like the old code did.
    bare = ScenarioDraft.from_session_state({"scenario_name": "S"})
    assert bare.workspace_id == "default_workspace"
    assert bare.workspace_name == "Default Workspace"
    assert bare.ttl_specificity == "High"


def test_from_request_normalizes_and_requires_type():
    draft = ScenarioDraft.from_request(
        "Golden Scenario", "ws_golden",
        components=[{"uri": WT_URI, "type": "WindTurbine", "source": None,
                     "attributes": None, "nested_properties": None}],
        links=[{"source": "scenario", "target": WT_URI, "link_type": None}],
    )
    # None fields dropped so the emitter's .get(...) defaults fire; label
    # defaults to the URI fragment; workspace_name falls back to the id.
    assert draft.components == [{"uri": WT_URI, "type": "WindTurbine", "label": "WT1"}]
    assert draft.links == [{"source": "scenario", "target": WT_URI}]
    assert draft.workspace_name == "ws_golden"

    with pytest.raises(ValueError, match="needs a 'type'"):
        ScenarioDraft.from_request("S", "ws", components=[{"uri": WT_URI}])


def test_backend_filters_keep_truthiness_quirk():
    """Same pinned behavior as the characterization test, explicit-args form:
    a 0-valued required attribute drops the component, and links follow."""
    components = [_wind_turbine(), _demand_profile()]
    kept = emitter.get_filtered_components_for_ttl(components, REQUIRED_ATTRIBUTES)
    assert [c["label"] for c in kept] == ["Turbine One", "Demand Profile One"]

    components[0]["attributes"]["hubHeight"]["value"] = 0
    kept = emitter.get_filtered_components_for_ttl(components, REQUIRED_ATTRIBUTES)
    assert [c["label"] for c in kept] == ["Demand Profile One"]

    links = emitter.get_filtered_links_for_ttl(_links(), kept)
    assert links == []  # both links touch the dropped WindTurbine


def test_save_scenario_to_workspace_writes_via_storage():
    written = {}

    class _Storage:
        def write_text(self, rel, content):
            written[rel] = content

    rel = save_scenario_to_workspace(_Storage(), "# ttl", "My_Scenario.ttl")
    assert rel == "scenarios/My_Scenario.ttl"
    assert written == {"scenarios/My_Scenario.ttl": "# ttl"}
