# SPDX-License-Identifier: Apache-2.0
"""A top-level block reached through a component link.

A running service may expect two blocks side by side (``site`` and ``units``
at the top level) while it still needs to know that the units belong to the
site. The only link syntax the template had was nesting, so the link vanished
from the contract. A ROOT entry with a ``link_pattern`` is now written as
``link: CL.Site.Unit`` + ``template`` at the top level: the contract states the
link, the payload shape stays flat, and only linked instances are sent.
"""
from __future__ import annotations

import yaml

from backend.api_submission.ttl_converter import convert_scenario
from backend.scenario_builder import build_scenario_ttl
from backend.scenario_builder.requirements import extract_component_links
from backend.service_requirements.template import (build_service_template,
                                                   entries_from_path_tree,
                                                   entries_from_type_tree,
                                                   parse_yaml_to_components)

P = "https://digicities.info/proj/ws"


def _template(**kw):
    entries = entries_from_type_tree(
        [("Site", None, ["Capacity"]), ("Unit", None, ["Area"])],
        links_from={"Unit": "Site"})
    return build_service_template("Svc", entries, **kw)


def test_a_root_reached_through_a_link_is_written_top_level_with_its_link():
    sd = _template()["scenario_data"]
    assert sd["site"] == {"name": "Site.label", "uri": "Site.URI", "Capacity": "Site.Capacity"}
    assert sd["unit"] == {"link": "CL.Site.Unit",
                          "template": {"name": "Unit.label", "uri": "Unit.URI",
                                       "Area": "Unit.Area"}}


def test_custom_block_and_id_names_apply_inside_the_template():
    sd = _template(custom_field_names={"unit|__path__": "units", "unit|Area|Static": "area_m2",
                                       "unit|label|Static": "unit_id"})["scenario_data"]
    assert sd["units"]["link"] == "CL.Site.Unit"
    assert sd["units"]["template"]["area_m2"] == "Unit.Area"
    assert sd["units"]["template"]["unit_id"] == "Unit.label"


def test_round_trip_keeps_the_link():
    first = _template()
    name, entries = parse_yaml_to_components(yaml.safe_dump(first, sort_keys=False))
    unit = next(e for e in entries if e.component_type == "Unit")
    assert unit.level == 1 and unit.link_pattern == "CL.Site.Unit" and unit.parent_path == ""
    assert build_service_template(name, entries) == first


def test_path_tree_links_from():
    entries = entries_from_path_tree(
        [("Site", "site", None, ["Capacity"]), ("Unit", "units", None, ["Area"])],
        links_from={"units": "Site"})
    sd = build_service_template("Svc", entries)["scenario_data"]
    assert sd["units"]["link"] == "CL.Site.Unit"


def test_the_scenario_builder_requires_the_link():
    assert "CL.Site.Unit" in extract_component_links(_template())


def _scenario(links, parts):
    sc = f"{P}/scenarios/s"
    sites = [f"{P}/Site/S1", f"{P}/Site/S2"]
    ttl = build_scenario_ttl(scenario_name="s", workspace_id="ws", components=sites + parts,
                             links=[(sc, s) for s in sites] + links, service_name=None,
                             description=None, scenario_uri=sc)
    typed = "\n".join(
        f"<{u}> a <https://digicities.info/ontology#{u.rsplit('/', 2)[-2]}> ; "
        f"<http://www.w3.org/2000/01/rdf-schema#label> \"{u.rsplit('/', 1)[-1]}\" ."
        for u in sites + parts)
    return ttl + "\n" + typed + "\n"


def test_convert_sends_the_linked_units_flat_and_leaves_out_an_unlinked_one():
    units = [f"{P}/Unit/{i}" for i in ("u1", "u2", "u3", "stray")]
    ttl = _scenario([(f"{P}/Site/S1", units[0]), (f"{P}/Site/S1", units[1]),
                     (f"{P}/Site/S2", units[2])], units)
    tmpl = {"scenario_data": {"site": {"name": "Site.label", "uri": "Site.URI"},
                              "units": {"link": "CL.Site.Unit",
                                        "template": {"name": "Unit.label"}}}}
    out = convert_scenario(tmpl, ttl)["scenario_data"]
    assert [u["name"] for u in out["units"]] == ["u1", "u2", "u3"]    # flat, stray left out
    assert "units" not in out["site"][0]                               # not nested
