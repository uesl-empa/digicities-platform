# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Scenario TTL → editable draft round trip, and link-suggestion matching."""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from backend.scenario_builder import build_scenario_ttl, scenario_uri_for
from backend.scenario_builder.link_discovery import match_links_to_requirements
from backend.scenario_builder.reload import draft_from_ttl

WT = "https://x/proj/ws1/WindTurbine/WT1"
SITE = "https://x/proj/ws1/GlobalWindAtlasSite/S1"


def _build():
    sc = scenario_uri_for("ws1", "My Windpark")
    return build_scenario_ttl(
        "My Windpark", "ws1",
        [{"uri": WT, "type": "WindTurbine", "label": "WT1"},
         {"uri": SITE, "type": "GlobalWindAtlasSite", "label": "Site 1"}],
        [{"source": sc, "target": SITE, "link_type": "scenario_automatic"},
         {"source": SITE, "target": WT, "link_type": "manual"}],
        service_name="WindParkForecaster",
    )


def test_draft_round_trips_thin_scenario():
    draft = draft_from_ttl(_build())
    assert draft["scenario_name"] == "My Windpark"
    assert draft["service_name"] == "WindParkForecaster"
    comps = {c["uri"]: c for c in draft["components"]}
    assert set(comps) == {WT, SITE}
    assert comps[WT]["type"] == "WindTurbine" and comps[WT]["label"] == "WT1"

    links = {(l["source"], l["target"]): l for l in draft["links"]}
    # The scenario IRI comes back as the 'scenario' pseudo-source.
    auto = links[("scenario", SITE)]
    assert auto["link_type"] == "scenario_automatic"
    assert auto["pattern"] == "CL.Scenario.GlobalWindAtlasSite"
    manual = links[(SITE, WT)]
    assert manual["pattern"] == "CL.GlobalWindAtlasSite.WindTurbine"


def test_match_orients_reversed_located_in():
    """locatedIn runs child→parent; the suggestion must come back oriented
    to the CL.Parent.Child requirement."""
    discovered = [{
        "source_uri": "https://x/Building/B1", "source_type": "Building",
        "link_property": "locatedIn",
        "target_uri": "https://x/Location/L1", "target_type": "Location",
        "source_label": "B1", "target_label": "L1",
    }]
    matched = match_links_to_requirements(discovered, ["CL.Location.Building", "CL.PV.Grid"])
    assert set(matched) == {"CL.Location.Building"}
    m = matched["CL.Location.Building"][0]
    assert m["suggested_source"] == "https://x/Location/L1"
    assert m["suggested_target"] == "https://x/Building/B1"


def test_match_keeps_forward_direction_when_it_fits():
    discovered = [{
        "source_uri": "https://x/Location/L1", "source_type": "Location",
        "link_property": "feeds",
        "target_uri": "https://x/Building/B1", "target_type": "Building",
        "source_label": "L1", "target_label": "B1",
    }]
    m = match_links_to_requirements(discovered, ["CL.Location.Building"])["CL.Location.Building"][0]
    assert m["suggested_source"] == "https://x/Location/L1"
    assert m["suggested_target"] == "https://x/Building/B1"


def test_full_emitter_multiline_curve_value_stays_parseable():
    """Curve data points are multi-line strings; the emitter used to wrap them
    in bare quotes (invalid Turtle), so an emitted scenario could not be
    re-parsed (draft reload, strict consumers). Triple-quoted now."""
    from backend.scenario_builder.draft import ScenarioDraft
    from backend.scenario_builder.emitter import generate_full_ttl

    wt = "https://x/proj/ws1/WindTurbine/WT1"
    draft = ScenarioDraft.from_request(
        "Curvy", "ws1",
        [{"uri": wt, "type": "WindTurbine", "label": "WT1",
          "attributes": {"PowerCurve": {
              "value": "[\n [1.0, 0.0]\n [2.0, 3.0]\n]",
              "attribute_type": "CurveAttribute"}}}],
        [],
        required_attributes={"WindTurbine": ["PowerCurve"]},
    )
    ttl = generate_full_ttl(draft)
    parsed = draft_from_ttl(ttl)  # must not raise on re-parse
    assert parsed["components"][0]["uri"] == wt
